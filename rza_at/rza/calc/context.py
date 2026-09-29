"""Контекст расчёта: проект, библиотека КЗ, нормы, формулы, вспомогательные величины."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..errors import DataError, Status
from ..model.autotransformer import SQRT3, SIDE_RU, rated_current_a, tap_states
from ..model.project import Project
from ..normative import registry
from ..trace import Trace, Var
from .shortcircuit import KZ, FaultResult


class PinnedLibrary:
    """Библиотека формул с закреплёнными версиями (проект может фиксировать версию формулы для воспроизводимости)."""

    def __init__(self, lib, pins: dict):
        self.lib, self.pins = lib, pins or {}

    def get(self, fid: str, version: int | None = None):
        return self.lib.get(fid, version or self.pins.get(fid))


@dataclass
class TerminalContext:
    """Свойства выбранного терминала, влияющие на повторную проверку (Уровень 2)."""
    profile_id: str = ""
    name: str = ""
    reset_ratio: float | None = None          # коэффициент возврата токовых органов (по умолчанию)
    reset_by_function: dict = field(default_factory=dict)   # {"49": 0.97, …}
    conv: dict = field(default_factory=dict)  # конвенции (тормозной ток и т.п.)
    tolerances: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)      # напр. {"u_set": {"HV": 230.0, "MV": 119.3, …}} — округлённые напряжения выравнивания терминала


class CalcContext:
    def __init__(self, project: Project):
        self.p = project
        self.reg = registry()
        self.kz = KZ(project)
        self.lib = PinnedLibrary(self.reg.formulas, project.assumptions.formula_pins)
        self.a = project.assumptions
        self.tr = project.transformer
        self.warnings: list[str] = []
        self._cache: dict = {}

    # ── нормы и трассы ──
    def norm(self, nid: str):
        return self.reg.norms.resolve(nid, self.a.norm_priority, self.a.norm_overrides)

    def norm_var(self, nid: str, name: str) -> tuple[Var, object]:
        n = self.norm(nid)
        v = Var(name, n.value, "", n.title, n.ref(self.reg.sources))
        return v, n

    def trace(self, title: str) -> Trace:
        return Trace(self.lib, title)

    def note_norm(self, tr: Trace, n, title: str | None = None):
        """Записать выбор нормативного значения (с альтернативами из других источников) в трассу."""
        opts = [{"source": n.source_id, "short": self.reg.sources.get(n.source_id).short, "clause": n.clause, "value": n.value, "chosen": True}]
        opts += [dict(a, chosen=False) for a in n.alternatives]
        tr.choice(title or n.title, n.value, "", opts, n.ref(self.reg.sources), n.note)

    # ── величины объекта ──
    def sides(self) -> list[str]:
        return self.tr.sides()

    def side_ru(self, s: str) -> str:
        return f"{SIDE_RU[s]} {self.tr.u_nom(s):g} кВ"

    def i_nom(self, side: str) -> float:
        return self.tr.i_nom(side)

    def i_nom_winding(self, side: str) -> float:
        return self.tr.i_nom(side, self.tr.s_winding(side))

    def i_load_max(self, side: str, roles=("load",)) -> tuple[float, str]:
        """Максимальный рабочий ток стороны, А, по режимам с ролью «load» (I_раб.макс = k_нагр·I_ном.обмотки)."""
        best, mid = 0.0, ""
        for m in self.p.modes:
            if any(r in m.roles for r in roles):
                i = m.load_factor * self.i_nom_winding(side)
                if i > best:
                    best, mid = i, m.id
        ov = self.a.load_i_max_pu.get(side)
        if ov:
            best, mid = ov * self.i_nom_winding(side), "проект"
        return best, mid

    def ct(self, side: str, fn: str | None = None, strict: bool = False):
        return self.p.ct_for(side, fn, strict)

    def fault_side(self, node: str) -> str:
        """Сторона (напряжение), к которой относится точка КЗ."""
        if node in ("HV", "MV", "LV"):
            return node
        if node.startswith("T_"):
            return node[2:]
        if node.startswith("E_"):
            lid = node[2:]
            for ln in self.p.network.lines:
                if ln.id == lid:
                    return ln.side
        return "HV"

    def mode_sees(self, mode, relay_side: str, node: str) -> bool:
        """Течёт ли ток КЗ через ТТ стороны защиты в данном режиме (есть ли подпитка):
        КЗ на другой стороне — нужен источник на стороне защиты; КЗ на своей стороне (шины, линии) — нужен источник на другой стороне."""
        fside = self.fault_side(node)
        srcs = self.p.network.sources
        on = lambda s: mode.sources.get(s.id, "max") != "off"
        if fside == relay_side:
            others = [s for s in srcs if s.side != relay_side]
            return any(on(s) for s in others) if others else True
        own = [s for s in srcs if s.side == relay_side]
        return any(on(s) for s in own) if own else True

    def scan_for(self, side: str, role: str, node: str, ftype: str, exclude_energization: bool = True, cascade: bool = False) -> list[FaultResult]:
        """Расчёты КЗ для проверки защиты стороны: только реально возможные режимы (есть подпитка через ТТ защиты), без опробования."""
        out = []
        for r in self.scan(role, node, ftype, cascade):
            m = self.p.mode(r.mode_id)
            if exclude_energization and "energization" in m.roles:
                continue
            if not self.mode_sees(m, side, node):
                continue
            out.append(r)
        return out

    def dt(self) -> tuple[float, str]:
        if self.a.dt_step_s:
            return self.a.dt_step_s, "проект"
        n = self.norm("DT.STEP")
        return n.value, n.ref(self.reg.sources)

    def k_reset(self, term: TerminalContext | None = None, fid: str | None = None) -> tuple[float, str]:
        """Коэффициент возврата: из профиля терминала (по функции), иначе по классу устройства (норма)."""
        if term is not None:
            if fid and term.reset_by_function.get(fid):
                return term.reset_by_function[fid], f"профиль терминала «{term.name}», функция {fid}"
            if term.reset_ratio:
                return term.reset_ratio, f"профиль терминала «{term.name}»"
        if self.a.device_class == "electromechanical":
            n = self.norm("K.V.EM")
        else:
            n = self.norm("K.V.DIGITAL")
        return n.value, n.ref(self.reg.sources)

    def taps(self):
        return tap_states(self.tr)

    def bus_node(self, side: str) -> str:
        return side

    def require(self, cond: bool, msg: str, missing: list):
        if not cond:
            missing.append(msg)
        return cond

    # ── срезы КЗ ──
    def scan(self, role: str, node: str, ftype: str, cascade: bool = False) -> list[FaultResult]:
        key = ("scan", role, node, ftype, cascade)
        if key not in self._cache:
            self._cache[key] = self.kz.scan(role, node, ftype, cascade)
        return self._cache[key]

    def worst_min(self, role: str, node: str, ftype: str, getter) -> tuple[float, FaultResult] | None:
        rs = self.scan(role, node, ftype)
        if not rs:
            return None
        vals = [(getter(r), r) for r in rs]
        return min(vals, key=lambda x: x[0])

    def worst_max(self, role: str, node: str, ftype: str, getter) -> tuple[float, FaultResult] | None:
        rs = self.scan(role, node, ftype)
        if not rs:
            return None
        vals = [(getter(r), r) for r in rs]
        return max(vals, key=lambda x: x[0])

    def case_label(self, r: FaultResult) -> dict:
        m = self.p.mode(r.mode_id)
        tap = self.kz.model(r.mode_id, r.tap_key, r.cascade).tap
        return {"mode_id": r.mode_id, "mode": m.name, "tap": tap.key, "tap_label": tap.label(), "node": r.node, "ftype": r.ftype}


def status_from_ratio(k: float, need: float, soft: float | None = None) -> Status:
    """🟢 если k ≥ need; 🟡 если k в пределах допуска (soft·need ≤ k < need); 🔴 иначе."""
    if k >= need:
        return Status.OK
    if soft is not None and k >= soft * need:
        return Status.CHECK
    return Status.FAIL
