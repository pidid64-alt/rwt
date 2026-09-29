"""Карта уставок: применение адаптера терминала, округление, ПОВТОРНАЯ проверка после округления, статусы.

Порядок (ТЗ, разд. 12, 38, 40):
    расчётная уставка (PFM) → адаптер терминала (диапазон, шаг, единица, ближайшее допустимое значение)
    → принятая уставка → обратный пересчёт в универсальные единицы → повторная проверка чувствительности,
    устойчивости, селективности → статус строки: 🟢 / 🟡 / 🔴 (УСТАВКА НЕ ДОПУСТИМА / ВНЕ ДИАПАЗОНА ТЕРМИНАЛА).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .calc import functions as F
from .calc.context import CalcContext, TerminalContext
from .calc.results import Check, FunctionResult
from .errors import Status, worst
from .pfm import PFM, split_key
from .terminals.adapter import AdaptContext, Row, make_adapter
from .terminals.profile import TerminalProfile


@dataclass
class Card:
    profile: TerminalProfile
    variant: str
    functions: list
    rows: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)          # функция → повторные проверки
    warnings: list = field(default_factory=list)
    policy: str = "nearest"

    @property
    def status(self) -> Status:
        sts = [r.status for r in self.rows if r.supported and not (r.fixed and r.status == Status.OK)]
        sts += [c.status for cs in self.checks.values() for c in cs]
        return worst(sts) if sts else Status.NA

    def to_dict(self) -> dict:
        return {"terminal_id": self.profile.id, "label": self.profile.label, "profile_status": self.profile.status,
                "profile_status_label": self.profile.summary()["status_label"], "variant": self.variant, "functions": self.functions,
                "status": self.status.value, "icon": self.status.icon, "status_label": self.status.label, "policy": self.policy,
                "rows": [r.to_dict() for r in self.rows],
                "checks": {fid: [c.to_dict() for c in cs] for fid, cs in self.checks.items()}, "warnings": self.warnings,
                "source": [dict(s) for s in self.profile.data.get("sources", [])]}


def terminal_context(profile: TerminalProfile, extra: dict | None = None) -> TerminalContext:
    default, by = profile.reset_ratios()
    return TerminalContext(profile.id, profile.label, default, by, profile.tolerances(), extra or {})


def apply_terminal(ctx: CalcContext, results: dict[str, FunctionResult], profile: TerminalProfile, variant: str = "", functions: list | None = None,
                   policy: str | None = None) -> Card:
    policy = policy or ctx.a.rounding_policy
    fns = functions or [f for f in results if profile.supports(f) or True]
    sub = {fid: fr for fid, fr in results.items() if fid in fns}
    x = AdaptContext(ctx, sub, profile, variant)
    adapter = make_adapter(profile, x)
    rows, accepted = adapter.apply(sub, policy, ctx.p.overrides)
    card = Card(profile, variant, list(fns), rows, {}, [], policy)
    term = terminal_context(profile, {"u_set": dict(x.u_set_dev)})
    # повторная проверка — только для функций, поддерживаемых терминалом, с полным набором принятых значений
    for fid, fr in sub.items():
        if not profile.supports(fid):
            continue
        acc = {k: v for k, v in accepted.items() if PFM.get(split_key(k)[0]) and PFM[split_key(k)[0]].function == fid}
        if not acc:
            continue
        if fid == "87T":
            need = ("87T.IdiffPickup", "87T.Slope1", "87T.Slope2")
            if not all(k in acc for k in need):
                card.warnings.append("Дифференциальная защита: у терминала нет всех параметров характеристики (I_диф>, наклоны) — повторная проверка 87T не выполнена")
                continue
            acc.setdefault("87T.BasePoint1", ctx.a.bp1_pu)
            acc.setdefault("87T.BasePoint2", ctx.a.x_lin_pu)
        try:
            card.checks[fid] = F.get(fid).recheck(ctx, acc, term)
        except Exception as e:  # noqa
            card.warnings.append(f"Повторная проверка {fid} не выполнена: {e}")
    # статусы строк = наихудший из статуса округления и повторных проверок, привязанных к параметру
    by_param: dict[str, list[Check]] = {}
    for cs in card.checks.values():
        for c in cs:
            if c.param_key:
                by_param.setdefault(c.param_key, []).append(c)
    for r in rows:
        cs = by_param.get(r.pfm_key, [])
        fails = [c for c in cs if c.status == Status.FAIL]
        if fails and r.supported:
            r.status = Status.OUT_OF_RANGE if r.range_state != "in" else Status.FAIL
            msg = "УСТАВКА НЕ ДОПУСТИМА: после округления критерий не выполняется — " + fails[0].reason
            r.reason = (msg if not r.reason else msg + " | " + r.reason)
            if r.alt_safe is not None:
                r.reason += f" | Предложение: округление в безопасную сторону → {r.alt_safe:g} {r.unit}"
        elif cs and r.supported:
            r.status = worst([r.status] + [c.status for c in cs])
    return card


def statuses(issues, results: dict[str, FunctionResult], cards: dict[str, Card]) -> list[dict]:
    """Статусы проекта (ТЗ, разд. 39)."""
    out = []
    errs = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    miss = [m for fr in results.values() for m in fr.missing]
    calc_done = bool(results) and not errs
    out.append({"code": "calc_done", "ok": calc_done, "color": "green" if calc_done else "red", "label": "РАСЧЁТ ВЫПОЛНЕН" if calc_done else "РАСЧЁТ НЕ ВЫПОЛНЕН (ошибки исходных данных)"})
    if miss or errs:
        out.append({"code": "missing", "ok": False, "color": "orange", "label": "НЕ ХВАТАЕТ ИСХОДНЫХ ДАННЫХ", "detail": (miss + [i.message for i in errs])[:6]})
    sens = [c for fr in results.values() for c in fr.checks if c.kind == "sensitivity"]
    for cs in (cd for card in cards.values() for cd in card.checks.values()):
        sens += [c for c in cs if c.kind == "sensitivity"]
    if sens:
        bad = [c for c in sens if c.status in (Status.FAIL,)]
        chk = [c for c in sens if c.status == Status.CHECK]
        out.append({"code": "sens", "ok": not bad, "color": "green" if not bad and not chk else ("yellow" if not bad else "red"),
                    "label": "ЧУВСТВИТЕЛЬНОСТЬ ВЫПОЛНЕНА" if not bad and not chk else ("ЧУВСТВИТЕЛЬНОСТЬ: ТРЕБУЕТСЯ ПРОВЕРКА" if not bad else "КРИТЕРИЙ НЕ ВЫПОЛНЕН (чувствительность)"),
                    "detail": [c.reason for c in (bad or chk)][:6]})
    sel = [c for fr in results.values() for c in fr.checks if c.kind in ("selectivity", "coordination")]
    for cs in (cd for card in cards.values() for cd in card.checks.values()):
        sel += [c for c in cs if c.kind in ("selectivity", "coordination")]
    if sel:
        bad = [c for c in sel if c.status == Status.FAIL]
        out.append({"code": "sel", "ok": not bad, "color": "green" if not bad else "red", "label": "СЕЛЕКТИВНОСТЬ ВЫПОЛНЕНА" if not bad else "КРИТЕРИЙ НЕ ВЫПОЛНЕН (селективность)",
                    "detail": [c.reason for c in bad][:6]})
    stab = [c for fr in results.values() for c in fr.checks if c.kind == "stability"]
    for cs in (cd for card in cards.values() for cd in card.checks.values()):
        stab += [c for c in cs if c.kind == "stability"]
    if stab:
        bad = [c for c in stab if c.status == Status.FAIL]
        out.append({"code": "stab", "ok": not bad, "color": "green" if not bad else "red", "label": "УСТОЙЧИВОСТЬ ВЫПОЛНЕНА" if not bad else "КРИТЕРИЙ НЕ ВЫПОЛНЕН (устойчивость)"})
    oor = [r for card in cards.values() for r in card.rows if r.status == Status.OUT_OF_RANGE]
    if oor:
        out.append({"code": "range", "ok": False, "color": "red", "label": "УСТАВКА ВНЕ ДИАПАЗОНА ТЕРМИНАЛА", "detail": [f"{r.title}: {r.reason[:120]}" for r in oor][:6]})
    fails = [r for card in cards.values() for r in card.rows if r.status == Status.FAIL]
    if fails:
        out.append({"code": "fail", "ok": False, "color": "red", "label": "КРИТЕРИЙ НЕ ВЫПОЛНЕН (после округления)", "detail": [f"{r.title}" for r in fails][:6]})
    fr_fail = [(fid, p) for fid, fr in results.items() for p in fr.params if p.status == Status.FAIL and not p.fixed]
    if fr_fail:
        out.append({"code": "criteria", "ok": False, "color": "red", "label": "КРИТЕРИЙ НЕ ВЫПОЛНЕН (универсальный расчёт)", "detail": [f"{p.title}: {p.reason[:100]}" for _, p in fr_fail][:6]})
    check = warns or [r for card in cards.values() for r in card.rows if r.status == Status.CHECK] or [c for fr in results.values() for c in fr.checks if c.status == Status.CHECK]
    unverified = [c.profile.label for c in cards.values() if c.profile.status != "verified"]
    if check or unverified:
        det = [i.message for i in warns][:4] + ([f"Профиль терминала не верифицирован: {', '.join(unverified)}"] if unverified else [])
        out.append({"code": "review", "ok": False, "color": "yellow", "label": "ТРЕБУЕТСЯ ПРОВЕРКА", "detail": det})
    return out
