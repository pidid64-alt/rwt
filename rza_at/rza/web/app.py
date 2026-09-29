"""Веб-приложение РЗА-АТ: JSON API + статический интерфейс.

Расчётное ядро (rza.calc) не зависит от веб-слоя; API лишь вызывает его и хранит текущий проект в user_data/projects.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import APP_NAME, APP_VERSION, assistant, pfm
from ..calc import b13, charts, functions as F, selftest
from ..calc.engine import RunResult, run_all
from ..calc.shortcircuit import FAULT_TYPES, KZ
from ..calc.validation import validate
from ..compare import compare_matrix
from ..errors import DataError, FormulaError, ProfileError
from ..model.autotransformer import tap_states, tap_keys
from ..model.demo import blank_project, demo_project
from ..model.modes import default_modes
from ..model.project import Project, TerminalAssign
from ..normative import DEFAULT_PRIORITY, registry
from ..reports.model import KINDS, build_report, export_guard
from ..reports.render import RENDERERS
from ..terminals.registry import terminal_registry

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "user_data" / "projects"
STATIC = Path(__file__).parent / "static"


def _default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, complex):
        return {"re": o.real, "im": o.imag}
    if isinstance(o, Enum):
        return o.value
    if is_dataclass(o):
        return asdict(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, bytes):
        return None
    return str(o)


def _clean(o):
    """Замена inf/nan (недопустимы в JSON)."""
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.generic):
        return _clean(o.item())
    return o


class UJSON(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(_clean(content), ensure_ascii=False, default=_default, allow_nan=False).encode("utf-8")


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.project: Project | None = None
        self.run: RunResult | None = None
        self.stale = True
        PROJECTS.mkdir(parents=True, exist_ok=True)
        self.load()

    def path(self, pid: str) -> Path:
        return PROJECTS / f"{pid}.json"

    def load(self, pid: str | None = None):
        if pid is None:
            cur = PROJECTS / "_current.txt"
            pid = cur.read_text(encoding="utf-8").strip() if cur.exists() else None
        p = self.path(pid) if pid else None
        if p and p.exists():
            self.project = Project.from_json(p.read_text(encoding="utf-8"))
        else:
            self.project = demo_project()
            self.save()
        self.project.ensure_modes()
        self.run, self.stale = None, True

    def save(self):
        assert self.project
        self.path(self.project.meta.id).write_text(self.project.to_json(), encoding="utf-8")
        (PROJECTS / "_current.txt").write_text(self.project.meta.id, encoding="utf-8")

    def touch(self):
        self.save()
        self.stale = True

    def ensure_run(self) -> RunResult:
        if self.run is None or self.stale:
            self.run = run_all(self.project)
            self.stale = False
        return self.run


STORE = Store()
app = FastAPI(title=APP_NAME, version=APP_VERSION)


def P() -> Project:
    return STORE.project


def _body_user(body: dict) -> tuple[str, str]:
    return (body.get("user") or P().meta.author or "пользователь"), body.get("reason", "")


@app.exception_handler(PermissionError)
async def perm(_, exc):
    return UJSON({"detail": str(exc)}, status_code=403)


@app.exception_handler(ValueError)
async def valerr(_, exc):
    return UJSON({"detail": str(exc)}, status_code=400)


@app.exception_handler(ProfileError)
async def proferr(_, exc):
    return UJSON({"detail": str(exc)}, status_code=400)


@app.exception_handler(FormulaError)
async def formerr(_, exc):
    return UJSON({"detail": str(exc)}, status_code=400)


@app.exception_handler(DataError)
async def dataerr(_, exc):
    return UJSON({"detail": str(exc), "missing": exc.missing}, status_code=422)


# ───────────────────────── проект ─────────────────────────
def _derived(p: Project) -> dict:
    tr = p.transformer
    return {"rated": tr.rated_table(), "group": tr.group_label(), "alpha": tr.alpha(), "s_typ": tr.s_typ(), "oltc_table": tr.oltc.table() if tr.oltc.present else [],
            "taps": [t.to_dict() for t in tap_states(tr)], "sides": tr.sides(),
            "cts": [{"id": c.id, "ratio": c.ratio, "alf_actual": c.alf_actual(), "i_no_sat_a": c.i_no_saturation_a()} for c in p.cts]}


@app.get("/api/info")
def info():
    return UJSON({"app": APP_NAME, "version": APP_VERSION, "kinds": KINDS, "norm_levels": DEFAULT_PRIORITY})


@app.get("/api/project")
def get_project():
    p = P()
    d = p.to_dict()
    d.pop("history", None)
    d["history"] = [{"version": s.version, "date": s.date, "author": s.author, "reason": s.reason} for s in p.history]
    return UJSON({"project": d, "derived": _derived(p), "stale": STORE.stale, "editable": p.editable()})


@app.get("/api/projects")
def list_projects():
    out = []
    for f in sorted(PROJECTS.glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8")).get("meta", {})
            out.append({"id": m.get("id", f.stem), "name": m.get("name"), "version": m.get("version"), "status": m.get("status"), "substation": m.get("substation"), "current": m.get("id") == P().meta.id})
        except Exception:
            pass
    return UJSON(out)


@app.post("/api/projects/new")
async def new_project(request: Request):
    body = await request.json()
    kind = body.get("kind", "demo")
    p = demo_project() if kind == "demo" else blank_project()
    base = body.get("name")
    pid = body.get("id") or f"project-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    p.meta.id = pid
    if base:
        p.meta.name = base
    p.meta.author = body.get("author") or p.meta.author
    p.log("version", "meta", "created", None, p.meta.version, "Создание проекта", p.meta.author)
    with STORE.lock:
        STORE.project = p
        STORE.touch()
    return UJSON({"id": pid})


@app.post("/api/projects/open/{pid}")
def open_project(pid: str):
    with STORE.lock:
        if not STORE.path(pid).exists():
            raise HTTPException(404, "Проект не найден")
        STORE.load(pid)
        STORE.save()
    return UJSON({"ok": True})


@app.put("/api/project/section/{section}")
async def put_section(section: str, request: Request):
    body = await request.json()
    user, reason = _body_user(body)
    with STORE.lock:
        if section not in ("meta", "transformer", "cts", "vts", "network", "modes", "assumptions", "terminals"):
            raise HTTPException(400, "Неизвестный раздел")
        if section == "meta":
            P().assert_editable()
            old = P().meta.to_dict()
            for k in ("name", "substation", "description", "author", "reviewer", "approver"):
                if k in body["data"] and body["data"][k] != old.get(k):
                    P().log("edit", "meta", k, old.get(k), body["data"][k], reason, user)
                    setattr(P().meta, k, body["data"][k])
            n = 1
        else:
            n = P().replace_section(section, body["data"], user, reason)
        if section == "modes":
            pass
        STORE.touch()
    return UJSON({"changes": n})


@app.patch("/api/project/path")
async def patch_path(request: Request):
    body = await request.json()
    user, reason = _body_user(body)
    with STORE.lock:
        P().patch(body["path"], body["value"], user, reason)
        STORE.touch()
    return UJSON({"ok": True})


@app.post("/api/project/regen_modes")
async def regen_modes(request: Request):
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    user, reason = _body_user(body)
    with STORE.lock:
        p = P()
        p.assert_editable()
        old = [m.id for m in p.modes]
        keep_custom = [m for m in p.modes if not m.builtin]
        p.modes = default_modes([s.id for s in p.network.sources], p.network.parallel_at.present) + keep_custom
        p.log("edit", "modes", "regen", f"{len(old)} режимов", f"{len(p.modes)} режимов", reason or "Пересоздание библиотеки режимов по составу источников", user)
        STORE.touch()
    return UJSON({"modes": len(p.modes)})


@app.post("/api/project/new_version")
async def new_version(request: Request):
    body = await request.json()
    with STORE.lock:
        v = P().new_version(body.get("author") or P().meta.author, body.get("reason", ""))
        STORE.touch()
    return UJSON({"version": v})


@app.post("/api/project/status")
async def set_status(request: Request):
    body = await request.json()
    with STORE.lock:
        if body["status"] == "approved":
            g = export_guard(P(), STORE.ensure_run())
            if not g["final_allowed"] and not body.get("force"):
                return UJSON({"detail": "Полный контроль проекта не пройден — утверждение возможно только при устранении замечаний либо с явным подтверждением (force).", "reasons": g["reasons"][:20]}, status_code=409)
        P().set_status(body["status"], body.get("by") or P().meta.author)
        STORE.touch()
        STORE.stale = False if STORE.run else True
    return UJSON({"status": P().meta.status})


@app.post("/api/project/override")
async def set_override(request: Request):
    from ..model.project import Override, now_iso
    body = await request.json()
    user, reason = _body_user(body)
    key = f"{body['terminal_id']}|{body['key']}"
    with STORE.lock:
        p = P()
        p.assert_editable()
        old = p.overrides.get(key)
        if body.get("value") is None:
            if old:
                del p.overrides[key]
            p.log("edit", "overrides", key, old.value if old else None, None, reason or "Сброс ручной уставки", user)
        else:
            if not reason.strip():
                raise ValueError("Для ручного изменения принятой уставки требуется указать причину")
            p.overrides[key] = Override(body["value"], reason, user, now_iso())
            p.log("edit", "overrides", key, old.value if old else None, body["value"], reason, user)
        STORE.touch()
    return UJSON({"ok": True})


@app.get("/api/project/export.json")
def export_json():
    return Response(P().to_json(), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{P().meta.id}.json"'})


@app.post("/api/project/import")
async def import_project(request: Request):
    body = await request.json()
    p = Project.from_dict(body)
    p.ensure_modes()
    p.log("version", "meta", "import", None, p.meta.version, "Импорт проекта из JSON", p.meta.author)
    with STORE.lock:
        STORE.project = p
        STORE.touch()
    return UJSON({"id": p.meta.id})


@app.get("/api/changelog")
def changelog():
    return UJSON([c.to_dict() for c in reversed(P().changelog)])


@app.get("/api/history/{version}")
def history_version(version: str):
    for s in P().history:
        if s.version == version:
            return UJSON({"version": s.version, "date": s.date, "author": s.author, "reason": s.reason, "data": s.data})
    raise HTTPException(404, "Версия не найдена")


# ───────────────────────── расчёт ─────────────────────────
def _brief_fn(fr):
    d = fr.to_dict()
    for p in d["params"]:
        p.pop("trace", None)
    for c in d["checks"]:
        c.pop("trace", None)
        c["details"] = c["details"][:0] if len(c.get("details") or []) > 0 else []
        c["n_details"] = 0
    return d


@app.get("/api/validate")
def api_validate():
    return UJSON([i.to_dict() for i in validate(P())])


@app.post("/api/calc/run")
async def calc_run(request: Request):
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    with STORE.lock:
        if body.get("policy"):
            P().assumptions.rounding_policy = body["policy"]
        STORE.run = run_all(P(), body.get("terminals"), body.get("policy"))
        STORE.stale = False
        rr = STORE.run
        P().log("calc", "calc", "run", None, {"blocked": rr.blocked, "statuses": [s["label"] for s in rr.statuses]}, "", body.get("user", ""))
        STORE.save()
    return UJSON(_summary(rr))


def _summary(rr: RunResult) -> dict:
    return {"blocked": rr.blocked, "ts": rr.ts, "seconds": rr.seconds, "version": rr.version, "issues": [i.to_dict() for i in rr.issues], "statuses": rr.statuses,
            "functions": {fid: {"status": fr.status.value, "icon": fr.status.icon, "title": fr.title, "missing": fr.missing, "warnings": fr.warnings, "n_params": len(fr.params), "n_checks": len(fr.checks)} for fid, fr in rr.results.items()},
            "cards": {tid: {"label": c.profile.label, "status": c.status.value, "icon": c.status.icon, "profile_status": c.profile.status, "functions": c.functions, "n_rows": len(c.rows)} for tid, c in rr.cards.items()}}


@app.get("/api/calc/summary")
def calc_summary():
    return UJSON({"stale": STORE.stale, **_summary(STORE.ensure_run())})


@app.get("/api/results/{fid:path}")
def results(fid: str):
    rr = STORE.ensure_run()
    fr = rr.results.get(fid)
    if fr is None:
        raise HTTPException(404, "Функция не рассчитана")
    d = fr.to_dict()
    for p in d["params"]:
        p.pop("trace", None)
    for c in d["checks"]:
        c.pop("trace", None)
    return UJSON(d)


@app.get("/api/trace")
def trace(function: str, key: str, terminal: str | None = None):
    rr = STORE.ensure_run()
    fr = rr.results.get(function)
    pr = fr.param(key) if fr else None
    if pr is None:
        raise HTTPException(404, "Параметр не найден")
    out = {"key": key, "title": pr.title, "unit": pr.unit, "calc": pr.calc, "lower": pr.lower, "upper": pr.upper, "status": pr.status.value, "reason": pr.reason,
           "trace": pr.trace.to_dict() if pr.trace else None, "criteria": [c.to_dict() for c in pr.criteria], "meta": pr.meta, "row": None, "recheck": []}
    for tid in ([terminal] if terminal else list(rr.cards)):
        card = rr.cards.get(tid)
        if not card:
            continue
        row = next((r for r in card.rows if r.pfm_key == key and r.supported), None)
        if row:
            out["row"] = dict(row.to_dict(), terminal=card.profile.label, terminal_id=tid, profile_status=card.profile.status)
            out["recheck"] = [c.to_dict() for cs in card.checks.values() for c in cs if c.param_key == key]
            out["terminal_source"] = card.profile.data.get("sources", [])
            break
    fchecks = [c.to_dict() for c in fr.checks if c.param_key == key]
    out["calc_checks"] = fchecks
    return UJSON(out)


@app.get("/api/card/{terminal_id}")
def card(terminal_id: str):
    rr = STORE.ensure_run()
    c = rr.cards.get(terminal_id)
    if c is None:
        raise HTTPException(404, "Карта для терминала не сформирована (терминал не назначен проекту)")
    d = c.to_dict()
    for cs in d["checks"].values():
        for k in cs:
            k.pop("trace", None)
    return UJSON(d)


@app.get("/api/checks")
def all_checks():
    rr = STORE.ensure_run()
    out = []
    for fid, fr in rr.results.items():
        for c in fr.checks:
            d = c.to_dict(); d["scope"] = "calc"; d["fid"] = fid; d["terminal"] = None
            out.append(d)
    for tid, card in rr.cards.items():
        for fid, cs in card.checks.items():
            for c in cs:
                d = c.to_dict(); d["scope"] = "card"; d["fid"] = fid; d["terminal"] = tid; d["terminal_label"] = card.profile.label
                out.append(d)
    return UJSON(out)


@app.get("/api/check_trace")
def check_trace(cid: str, scope: str = "calc", terminal: str | None = None):
    rr = STORE.ensure_run()
    pools = [c for fr in rr.results.values() for c in fr.checks] if scope == "calc" else [c for cs in (rr.cards[terminal].checks.values() if terminal in rr.cards else []) for c in cs]
    for c in pools:
        if c.id == cid:
            return UJSON(c.to_dict())
    raise HTTPException(404, "Проверка не найдена")


@app.get("/api/kz/meta")
def kz_meta():
    p = P()
    kz = KZ(p)
    return UJSON({"modes": [{"id": m.id, "name": m.name, "roles": m.roles, "taps": [str(t) for t in kz.tap_keys_for(m)]} for m in p.modes], "nodes": kz.fault_nodes(),
                  "ftypes": FAULT_TYPES, "sides": p.transformer.sides(), "taps": [t.to_dict() for t in tap_states(p.transformer)]})


@app.get("/api/kz/table")
def kz_table(mode: str | None = None, nodes: str | None = None, ftypes: str | None = None):
    p = P()
    kz = KZ(p)
    rows = kz.table([mode] if mode else None, nodes.split(",") if nodes else None, ftypes.split(",") if ftypes else None)
    return UJSON(rows)


@app.get("/api/kz/detail")
def kz_detail(mode: str, tap: str, node: str, ftype: str):
    p = P()
    kz = KZ(p)
    r = kz.fault(mode, tap, node, ftype)
    def cx(z): return {"abs": abs(z), "deg": float(np.degrees(np.angle(z))) if abs(z) > 1e-12 else 0.0}
    return UJSON({"fault": [cx(z) for z in r.fault_abc], "seq": [cx(z) for z in r.fault_seq], "z": [cx(z) for z in r.z_seq], "neutral_3i0": cx(r.neutral_3i0),
                  "sides": {s: {"i": [cx(z) for z in d.i_abc], "u": [cx(z) for z in d.u_abc], "i1": cx(d.i1), "i2": cx(d.i2), "i0": cx(d.i0)} for s, d in r.sides.items()}, "flags": r.flags,
                  "tap": kz.model(mode, tap).tap.to_dict()})


@app.get("/api/chart/87t")
def chart_87t(terminal: str | None = None):
    return UJSON(charts.char87t(P(), STORE.ensure_run(), terminal))


@app.get("/api/chart/tcc")
def chart_tcc(side: str = "HV", terminal: str | None = None):
    return UJSON(charts.tcc(P(), STORE.ensure_run(), side, terminal))


# ───────────────────────── терминалы ─────────────────────────
@app.get("/api/pfm")
def get_pfm():
    return UJSON({"functions": pfm.FUNCTIONS, "implemented": pfm.IMPLEMENTED, "params": pfm.catalog()})


@app.get("/api/terminals")
def terminals():
    return UJSON([p.summary() for p in terminal_registry().list()])


@app.get("/api/terminals/{tid}")
def terminal_get(tid: str):
    p = terminal_registry().get(tid)
    d = dict(p.data)
    d["_origin"], d["_validation"] = p.origin, p.validate()
    return UJSON(d)


@app.post("/api/terminals/validate")
async def terminal_validate(request: Request):
    from ..terminals.profile import TerminalProfile
    body = await request.json()
    return UJSON(TerminalProfile(body).validate())


@app.post("/api/terminals")
async def terminal_add(request: Request):
    body = await request.json()
    prof = body.get("profile", body)
    with STORE.lock:
        pr = terminal_registry().add(prof, overwrite=bool(body.get("overwrite")))
        P().log("profile", "terminals", pr.id, None, pr.label, body.get("reason", "Добавление профиля терминала"), body.get("user", ""))
        STORE.touch()
    return UJSON({"id": pr.id, "issues": pr.validate()})


@app.delete("/api/terminals/{tid}")
def terminal_delete(tid: str):
    with STORE.lock:
        terminal_registry().remove(tid)
        P().log("profile", "terminals", tid, tid, None, "Удаление пользовательского профиля")
        STORE.touch()
    return UJSON({"ok": True})


@app.get("/api/terminals/{tid}/export.json")
def terminal_export(tid: str):
    p = terminal_registry().get(tid)
    return Response(json.dumps(p.data, ensure_ascii=False, indent=1), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{tid}.json"'})


@app.post("/api/compare")
async def compare(request: Request):
    body = await request.json()
    rr = STORE.ensure_run()
    if rr.blocked:
        raise HTTPException(409, "Расчёт заблокирован ошибками исходных данных")
    return UJSON(compare_matrix(P(), rr, body.get("terminal_ids", [])))


# ───────────────────────── нормативная база ─────────────────────────
@app.get("/api/norms")
def norms():
    r = registry()
    return UJSON({"sources": [s.to_dict() for s in r.sources.list()], "values": r.norms.list(), "priority": P().assumptions.norm_priority, "overrides": P().assumptions.norm_overrides,
                  "levels": DEFAULT_PRIORITY})


@app.get("/api/formulas")
def formulas(history: bool = False):
    lib = registry().formulas
    return UJSON([f.to_dict() for f in lib.list(history)])


@app.get("/api/formulas/{fid}")
def formula_get(fid: str):
    lib = registry().formulas
    return UJSON([f.to_dict() for f in lib.versions(fid)])


@app.post("/api/formulas/{fid}/version")
async def formula_version(fid: str, request: Request):
    body = await request.json()
    with STORE.lock:
        f = registry().formulas.new_version(fid, body.get("changes", {}), body.get("author") or P().meta.author, body.get("reason", ""))
        P().log("formula", "formulas", fid, f"v{f.version - 1}", f"v{f.version}", body.get("reason", ""), body.get("author", ""))
        STORE.touch()
    return UJSON(f.to_dict())


@app.get("/api/b13")
def api_b13():
    return UJSON(assistant.compare_13b(P(), STORE.ensure_run()))


@app.get("/api/tests")
def api_tests():
    rows = selftest.run_reference_tests()
    return UJSON({"rows": rows, "summary": selftest.summary(rows)})


# ───────────────────────── ассистент, отчёты ─────────────────────────
@app.get("/api/assistant/review")
def assistant_review():
    return UJSON(assistant.review_project(P(), STORE.ensure_run()))


@app.post("/api/assistant/explain")
async def assistant_explain(request: Request):
    body = await request.json()
    return UJSON(assistant.explain_param(STORE.ensure_run(), body["function"], body["key"], body.get("terminal")))


@app.get("/api/report/guard")
def report_guard(terminal: str | None = None):
    return UJSON(export_guard(P(), STORE.ensure_run(), terminal))


@app.get("/api/report/{kind}")
def report(kind: str, fmt: str = "pdf", terminal: str | None = None):
    if kind not in KINDS or fmt not in RENDERERS:
        raise HTTPException(404, "Неизвестный вид отчёта/формат")
    with STORE.lock:
        rr = STORE.ensure_run()
        if rr.blocked:
            raise HTTPException(409, "Расчёт заблокирован ошибками исходных данных — отчёт не может быть сформирован")
        doc = build_report(kind, P(), rr, terminal)
        data, mime = RENDERERS[fmt][0](doc), RENDERERS[fmt][1]
        P().log("export", "report", kind, None, f"{fmt}{' (предварительный)' if doc.draft else ''}", "", "")
        STORE.save()
    name = f"{P().meta.id}_{kind}_v{P().meta.version}.{fmt}"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Draft": "1" if doc.draft else "0"})


# ───────────────────────── статика ─────────────────────────
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
