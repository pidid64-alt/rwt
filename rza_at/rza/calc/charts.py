"""Данные для графиков: характеристика 87T с точками режимов; времятоковые характеристики и зона селективности."""
from __future__ import annotations

from ..model.network import Stage
from ..model.project import Project
from . import selectivity as sel
from .functions.f87t import char_value


def _accepted(card, key: str, default=None):
    if card is not None:
        for r in card.rows:
            if r.pfm_key == key and r.accepted_univ is not None and r.supported:
                return r.accepted_univ
    return default


def char87t(project: Project, run, terminal_id: str | None = None, universal: bool = True) -> dict:
    """Характеристика I_диф = f(I_торм) в универсальных координатах и точки расчётных случаев (внешние КЗ и КЗ в зоне)."""
    fr = run.results.get("87T")
    if not fr or not fr.params:
        return {"available": False}
    card = run.cards.get(terminal_id) if terminal_id else None
    keys = ["87T.IdiffPickup", "87T.Slope1", "87T.BasePoint1", "87T.Slope2", "87T.BasePoint2", "87T.HighSet"]
    vals = {}
    for k in keys:
        pr = fr.param(k)
        vals[k] = _accepted(card, k, pr.calc if pr else None)
    P, s1, b1, s2, b2, hs = (vals[k] for k in keys)
    if None in (P, s1, s2):
        return {"available": False}
    b1 = b1 if b1 is not None else 0.0
    b2 = b2 if b2 is not None else 0.0
    ext = int_ = []
    checks = (card.checks.get("87T") if card and "87T" in card.checks else fr.checks) or []
    ext = next((c.details for c in checks if c.id == "87T.stab"), [])
    int_ = next((c.details for c in checks if c.id == "87T.sens"), [])
    xmax = max([d["x_res"] for d in ext + int_] + [5.0]) * 1.1
    xs = [i * xmax / 200 for i in range(201)]
    curve = [[x, min(char_value(x, P, s1, b1, s2, b2), hs if hs else 1e9)] for x in xs]
    return {"available": True, "terminal": terminal_id, "params": {"P": P, "s1": s1, "b1": b1, "s2": s2, "b2": b2, "hs": hs},
            "curve": curve, "hs": hs, "x_max": xmax,
            "ext": [{"x": d["x_res"], "y": d["i_unb"], "label": f"{d['mode']}/{d['tap']}/{d['ftype']} на {d['node']}", "margin": d["margin"]} for d in ext],
            "int": [{"x": d["x_res"], "y": d["i_diff"], "label": f"{d['mode']}/{d['tap']}/{d['ftype']} на {d['node']}", "kch": d["kch"]} for d in int_]}


def tcc(project: Project, run, side: str, terminal_id: str | None = None) -> dict:
    """Времятоковые характеристики: собственная МТЗ стороны, вышестоящие и нижестоящие защиты, зона селективности."""
    fr = run.results.get("50/51")
    net = project.network
    base = net.base_kv
    card = run.cards.get(terminal_id) if terminal_id else None
    own = []
    if fr:
        pi, pt = fr.param(f"51.IPickup@{side}"), fr.param(f"51.Delay@{side}")
        i_set = _accepted(card, f"51.IPickup@{side}", pi.calc if pi else None)
        t_set = _accepted(card, f"51.Delay@{side}", pt.calc if pt else None)
        if i_set and t_set is not None:
            own = [Stage(i_a=i_set, t_s=t_set, curve="definite")]
    if not own:
        return {"available": False}
    dt, _ = run.ctx.dt() if run.ctx else (0.3, "")
    i_lo = own[0].i_a * 0.5
    imax = 0.0
    for r in run.ctx.scan("max_kz", side, "3ph") if run.ctx else []:
        imax = max(imax, r.side_i_max(side))
    for nd in project.transformer.sides():
        for r in (run.ctx.scan("max_kz", nd, "3ph") if run.ctx else []):
            imax = max(imax, max(abs(x) for x in r.sides[side].i_abc))
    i_hi = max(imax * 1.2, own[0].i_a * 5)
    series = [{"name": f"МТЗ {side} (собственная)", "role": "own", "points": sel.series(own, i_lo, i_hi)}]
    checks = []
    for te in net.tcc:
        if not te.stages:
            continue
        rel = te.role
        if rel == "upstream" and te.side == side:
            scale = base[side] / base[te.side]
        elif rel == "downstream":
            scale = base[side] / base[te.side]
        else:
            continue
        series.append({"name": te.name, "role": rel, "points": sel.series(te.stages, i_lo, i_hi, scale)})
        res = sel.check_pair(own, te.stages, rel, dt, own[0].i_a, i_hi, scale)
        checks.append({"name": te.name, "role": rel, "ok": res["ok"], "margin": res["margin"], "at_a": res.get("at_a")})
    # зона селективности: токи, где запас относительно всех смежных защит ≥ Δt
    zone = []
    for i in sel.log_grid(i_lo, i_hi, 120):
        t_own = sel.curve_time(own, i)
        if t_own is None:
            continue
        ok = True
        for te in net.tcc:
            if not te.stages or not ((te.role == "upstream" and te.side == side) or te.role == "downstream"):
                continue
            scale = base[side] / base[te.side]
            t_o = sel.curve_time(te.stages, i * scale)
            if t_o is None:
                continue
            m = (t_o - t_own) if te.role == "upstream" else (t_own - t_o)
            ok = ok and m >= dt - 1e-9
        zone.append({"i": i, "ok": ok, "t_own": t_own})
    return {"available": True, "side": side, "dt": dt, "series": series, "checks": checks, "zone": zone, "i_lo": i_lo, "i_hi": i_hi}
