"""Уровень 2 — адаптеры терминалов: «Protection Function Model → параметры устройства».

Адаптер получает расчётные значения PFM (универсальные единицы) и профиль терминала и определяет:
допустимый диапазон, шаг, единицу, ближайшую допустимую уставку (по политике округления), отклонение;
затем формируется набор принятых значений в универсальных единицах для ПОВТОРНОЙ проверки чувствительности,
устойчивости и селективности (rza.setpoints).

GenericAdapter — управляется данными профиля (виды преобразований: identity, slope_conv, bp_conv, i_rel_side, …).
Специальные адаптеры (например Siemens7UT6Adapter) наследуют его и добавляют особенности устройства.
Для нового устройства ядро не изменяется: достаточно профиля (и, при необходимости, адаптера-наследника).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..calc.context import CalcContext
from ..calc.results import FunctionResult, ParamResult
from ..calc.selectivity import IEC, time_dial
from ..errors import Status, worst
from ..pfm import PFM, split_key
from .profile import TerminalProfile

SQRT3 = math.sqrt(3.0)


def decimals(step: float | None) -> int:
    if not step:
        return 4
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def snap(value: float, lo, hi, step, mode: str = "nearest") -> tuple[float, str]:
    """Ближайшее допустимое значение с учётом диапазона и шага. Возвращает (значение, состояние диапазона in|below|above)."""
    state = "in"
    v = value
    if lo is not None and v < lo - 1e-12:
        state, v = "below", lo
    if hi is not None and v > hi + 1e-12:
        state, v = "above", hi
    if step:
        base = lo if lo is not None else 0.0
        k = (v - base) / step
        if mode == "up":
            k = math.ceil(k - 1e-9)
        elif mode == "down":
            k = math.floor(k + 1e-9)
        else:
            k = math.floor(k + 0.5)
        v2 = base + k * step
        if hi is not None and v2 > hi + 1e-12:
            v2 = base + math.floor((hi - base) / step + 1e-9) * step
        if lo is not None and v2 < lo - 1e-12:
            v2 = lo
        v = v2
    return round(v, decimals(step) + 2), state


@dataclass
class Row:
    function: str
    pfm_key: str
    pfm_id: str
    instance: str
    title: str
    group: str = ""
    supported: bool = True
    param_key: str | None = None
    param_name: str | None = None
    calc: object = None
    calc_unit: str = ""
    dev_calc: object = None
    accepted: object = None
    unit: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list = field(default_factory=list)
    special: list = field(default_factory=list)
    accepted_univ: object = None
    deviation_abs: float | None = None
    deviation_rel: float | None = None
    range_state: str = "in"
    lower: float | None = None
    upper: float | None = None
    status: Status = Status.OK
    reason: str = ""
    basis: str = ""
    comment: str = ""
    source: dict = field(default_factory=dict)
    step_verified: bool | None = None
    policy: str = "nearest"
    rounding_dir: str = "nearest"
    alt_safe: object = None             # значение при безопасном направлении округления (предложение при нарушении критерия)
    override: dict | None = None
    kind: str = "float"
    fixed: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "status"}
        d["status"] = self.status.value
        d["icon"] = self.status.icon
        d["status_label"] = self.status.label
        return d


class AdaptContext:
    def __init__(self, ctx: CalcContext, results: dict[str, FunctionResult], profile: TerminalProfile, variant: str = ""):
        self.ctx, self.p, self.results, self.profile, self.variant = ctx, ctx.p, results, profile, variant
        self.tr = ctx.tr
        r87 = results.get("87T")
        b = (r87.meta.get("balancing") if r87 else None) or {}
        self.bal_calc = {"u_set": dict(b.get("u_set_kv") or {s: self.tr.u_nom(s) for s in self.tr.sides()}),
                         "s_ref": b.get("s_ref_mva") or max(self.tr.s_winding(s) for s in self.tr.sides())}
        self.u_set_dev = dict(self.bal_calc["u_set"])       # напряжения выравнивания, введённые в терминал (могут быть округлены)

    def s_ref(self) -> float:
        return self.bal_calc["s_ref"]

    def i_no(self, side: str) -> float:
        return self.s_ref() * 1000.0 / (SQRT3 * self.u_set_dev[side])

    def i_ns(self, side: str) -> float:
        return self.tr.s_winding(side) * 1000.0 / (SQRT3 * self.u_set_dev[side])

    def k_ct(self, side: str) -> float:
        ct = self.ctx.ct(side)
        return ct.ratio if ct else 1.0

    def side_of(self, instance: str) -> str:
        return instance.split(":")[0] if instance else "HV"


class GenericAdapter:
    name = "generic"

    def __init__(self, profile: TerminalProfile, actx: AdaptContext):
        self.profile, self.x = profile, actx
        self.accepted_prim: dict[str, float] = {}       # принятые токи в первичных амперах (для эквивалента зависимых характеристик)

    # ── доступность экземпляра ──
    def instance_available(self, pid: str, instance: str, m: dict | None) -> tuple[bool, str]:
        return True, ""

    # ── преобразование универсальное значение → единица устройства ──
    def to_device(self, pid: str, instance: str, v: float, p_dev: dict, m: dict) -> float:
        t = m.get("transform", "identity")
        side = self.x.side_of(instance)
        unit = p_dev.get("unit", "")
        if t == "identity":
            return v
        if t == "slope_conv":
            return v / self.profile.k_conv()
        if t == "bp_conv":
            return v * self.profile.k_conv()
        if t == "i_rel_side":
            if unit == "I/InS":
                return v / self.x.i_ns(side)
            if unit == "A":
                return v / self.x.k_ct(side) * self.ct_sec(side)
            return v
        if t == "i_rel_obj":
            return v / self.x.i_no(side)
        if t == "i_sec":
            return v / self.x.k_ct(side) * self.ct_sec(side)
        if t == "pct_from_pu":
            return v * 100.0
        if t == "pu_from_pct":
            return v / 100.0
        if t == "seconds_to_cycles":
            return v * self.x.tr.frequency_hz
        if t == "ms_from_s":
            return v * 1000.0
        return v

    def from_device(self, pid: str, instance: str, d: float, p_dev: dict, m: dict) -> float:
        t = m.get("transform", "identity")
        side = self.x.side_of(instance)
        unit = p_dev.get("unit", "")
        if t == "identity":
            return d
        if t == "slope_conv":
            return d * self.profile.k_conv()
        if t == "bp_conv":
            return d / self.profile.k_conv()
        if t == "i_rel_side":
            if unit == "I/InS":
                return d * self.x.i_ns(side)
            if unit == "A":
                return d * self.x.k_ct(side) / self.ct_sec(side)
            return d
        if t == "i_rel_obj":
            return d * self.x.i_no(side)
        if t == "i_sec":
            return d * self.x.k_ct(side) / self.ct_sec(side)
        if t == "pct_from_pu":
            return d / 100.0
        if t == "pu_from_pct":
            return d * 100.0
        if t == "seconds_to_cycles":
            return d / self.x.tr.frequency_hz
        if t == "ms_from_s":
            return d / 1000.0
        return d

    def ct_sec(self, side: str) -> float:
        ct = self.x.ctx.ct(side)
        return ct.i2_a if ct else 1.0

    # ── основной метод: строка карты уставок ──
    def convert(self, pr: ParamResult, policy: str, override: float | None = None) -> Row:
        pid, inst = pr.pfm_id, pr.instance
        fid = PFM[pid].function
        row = Row(function=fid, pfm_key=pr.key, pfm_id=pid, instance=inst, title=pr.title, group=pr.group, calc=pr.calc, calc_unit=pr.unit,
                  lower=pr.lower, upper=pr.upper, rounding_dir=pr.rounding_dir, policy=policy, kind=pr.kind, fixed=pr.fixed)
        row.basis = "; ".join(f"{c.title}" + (f" [{c.ref}]" if c.ref else "") for c in pr.criteria[:4])
        if not self.profile.supports(fid):
            f = self.profile.function(fid) or {}
            row.supported = False
            row.status = Status.NA
            row.reason = f"Функция {fid} не поддерживается терминалом: {f.get('note', 'нет данных в профиле')}"
            return row
        if pr.calc is None:
            row.status = Status.MISSING
            row.reason = pr.reason or "Нет расчётного значения (не хватает исходных данных)"
            return row
        dev_key, m = self.profile.mapped_key(pid, inst)
        if dev_key is None or m is None:
            row.supported = False
            row.status = Status.NA
            row.reason = "В профиле терминала нет параметра для этой уставки (нет соответствия PFM → параметр устройства)"
            return row
        ok, why = self.instance_available(pid, inst, m)
        if not ok:
            row.supported = False
            row.status = Status.NA
            row.reason = why
            return row
        p_dev = self.profile.param(dev_key)
        if p_dev is None:
            row.supported = False
            row.status = Status.NA
            row.reason = f"Параметр {dev_key} отсутствует в профиле"
            return row
        row.param_key, row.param_name = dev_key, f"{p_dev.get('address', dev_key)} {p_dev.get('name', '')}".strip()
        row.unit = p_dev.get("unit", "")
        row.min, row.max, row.step = p_dev.get("min"), p_dev.get("max"), p_dev.get("step")
        row.options, row.special = p_dev.get("options", []), p_dev.get("special", [])
        row.source = p_dev.get("source", {})
        row.step_verified = p_dev.get("step_verified")
        row.comment = p_dev.get("comment", "")
        # ── дискретные ──
        if p_dev.get("kind") == "enum" or pr.kind in ("bool", "enum"):
            return self._enum(row, pr, p_dev, m, override)
        # ── числовые ──
        idm = (m.get("idmt_stage") or {}).get(inst)
        if idm:
            return self._idmt(row, pr, p_dev, m, idm, policy, override)
        dev = self.to_device(pid, inst, float(pr.calc), p_dev, m)
        row.dev_calc = dev
        mode = policy if policy in ("nearest", "up", "down") else pr.rounding_dir
        acc, state = snap(dev, row.min, row.max, row.step, mode)
        row.range_state = state
        if override is not None:
            row.override = {"value": override}
            acc, _ = snap(float(override), row.min, row.max, row.step, "nearest")
        row.accepted = acc
        row.accepted_univ = self.from_device(pid, inst, acc, p_dev, m)
        row.deviation_abs = row.accepted_univ - float(pr.calc)
        row.deviation_rel = (row.deviation_abs / float(pr.calc)) if pr.calc else None
        # безопасный вариант округления
        safe_mode = pr.rounding_dir if pr.rounding_dir in ("up", "down") else "nearest"
        alt, _ = snap(dev, row.min, row.max, row.step, safe_mode)
        row.alt_safe = alt if abs(alt - acc) > 1e-12 else None
        if state != "in":
            row.status = Status.CHECK
            row.reason = (f"Расчётное значение {dev:.4g} {row.unit} {'ниже минимума' if state == 'below' else 'выше максимума'} диапазона терминала "
                          f"({row.min} … {row.max}); принято ближайшее допустимое {acc:g} — требуется подтверждение проверкой после округления")
        else:
            row.reason = f"Округление до шага {row.step:g}: {dev:.5g} → {acc:g} {row.unit}" if row.step else ""
        if pr.status in (Status.CHECK, Status.FAIL, Status.MISSING) and pr.fixed:
            row.status = worst([row.status, Status.CHECK])
        elif pr.status == Status.FAIL:
            row.status = worst([row.status, Status.FAIL])
            row.reason += ("; " if row.reason else "") + "критерии расчёта не совместимы: " + pr.reason
        self.accepted_prim_store(pr, row)
        return row

    def accepted_prim_store(self, pr: ParamResult, row: Row):
        if pr.unit == "А" and row.accepted_univ is not None:
            self.accepted_prim[pr.key] = row.accepted_univ

    def _enum(self, row: Row, pr: ParamResult, p_dev: dict, m: dict, override) -> Row:
        t = m.get("transform", "identity")
        v = pr.calc
        if t == "bool_onoff":
            dev = "ON" if bool(v) else "OFF"
        elif t == "enum_map":
            dev = (m.get("map") or {}).get(str(v), str(v))
        else:
            dev = str(v)
        row.dev_calc = dev
        opts = p_dev.get("options", [])
        if override is not None:
            dev = str(override)
            row.override = {"value": dev}
        if opts and dev not in opts:
            row.status = Status.OUT_OF_RANGE
            row.reason = f"Значение «{dev}» не входит в допустимые: {', '.join(opts)}"
            row.accepted = None
            return row
        row.accepted = dev
        inv = {b: a for a, b in (m.get("map") or {}).items()}
        row.accepted_univ = (dev == "ON") if t == "bool_onoff" else inv.get(dev, dev)
        row.status = pr.status if pr.fixed else Status.OK
        row.reason = "Значение принято из допустимого набора терминала"
        return row

    def _idmt(self, row: Row, pr: ParamResult, p_dev: dict, m: dict, idm: dict, policy: str, override) -> Row:
        """Ступень реализуется зависимой характеристикой: временной множитель, эквивалентный требуемой выдержке в расчётной точке."""
        pid, inst = pr.pfm_id, pr.instance
        pick_key = "51N.I0Pickup@" + inst if pid == "51N.Delay" else None
        i_set = self.accepted_prim.get(pick_key) if pick_key else None
        i_ref = None
        for r in self.x.results.get("50N/51N", FunctionResult("", "")).params:
            if r.key == pick_key:
                i_ref = (r.meta or {}).get("i_ref_a")
        if not i_set or not i_ref:
            row.status = Status.MISSING
            row.reason = "Для эквивалента зависимой характеристики нужны принятый ток срабатывания и расчётный ток КЗ"
            return row
        curve = idm.get("curve", "IEC_NI")
        c, alpha, cname = IEC[curve]
        multiple = max(i_ref / i_set, 1.05)
        td = time_dial(curve, float(pr.calc), multiple)
        row.dev_calc = td
        acc, state = snap(td, row.min, row.max, row.step, "nearest")
        if override is not None:
            row.override = {"value": override}
            acc, _ = snap(float(override), row.min, row.max, row.step, "nearest")
        row.accepted, row.range_state = acc, state
        t_eq = acc * c / (multiple ** alpha - 1.0)
        row.accepted_univ = t_eq
        row.deviation_abs = t_eq - float(pr.calc)
        row.deviation_rel = row.deviation_abs / float(pr.calc) if pr.calc else None
        row.status = Status.CHECK
        row.note = idm.get("note", "")
        row.reason = (f"Независимая выдержка недоступна: принята зависимая характеристика «{cname}» ({idm.get('curve_option', curve)}), временной множитель {acc:g} даёт {t_eq:.2f} с "
                      f"при {multiple:.2f}·I_ср (расчётный ток КЗ {i_ref:.0f} А). Требуется проверка времятоковой характеристики на всём диапазоне токов.")
        row.step_verified = p_dev.get("step_verified")
        return row

    # ── данные объекта (переопределяется адаптерами) ──
    def object_rows(self) -> list[Row]:
        return []

    # ── обработка всех результатов ──
    def apply(self, results: dict[str, FunctionResult], policy: str, overrides: dict) -> tuple[list[Row], dict]:
        rows: list[Row] = []
        pending = []
        for fid, fr in results.items():
            for pr in fr.params:
                pending.append(pr)
        pending.sort(key=lambda p: (0 if not p.pfm_id.endswith("Delay") else 1))
        by_key: dict[str, Row] = {}
        for pr in pending:
            ov = overrides.get(f"{self.profile.id}|{pr.key}")
            row = self.convert(pr, policy, ov.value if ov and ov.value is not None else None)
            if ov and row.override is not None:
                row.override.update({"reason": ov.reason, "author": ov.author, "ts": ov.ts})
            by_key[pr.key] = row
        order = {p.key: i for i, p in enumerate(p for fr in results.values() for p in fr.params)}
        rows = sorted(by_key.values(), key=lambda r: order[r.pfm_key])
        accepted = {r.pfm_key: r.accepted_univ for r in rows if r.accepted_univ is not None and r.supported}
        return rows, accepted


_ADAPTERS: dict[str, type] = {"generic": GenericAdapter}


def register_adapter(name: str):
    def deco(cls):
        _ADAPTERS[name] = cls
        cls.name = name
        return cls
    return deco


def make_adapter(profile: TerminalProfile, actx: AdaptContext) -> GenericAdapter:
    from . import adapters  # noqa: F401  (регистрация адаптеров)
    cls = _ADAPTERS.get(profile.data.get("adapter", "generic"), GenericAdapter)
    return cls(profile, actx)
