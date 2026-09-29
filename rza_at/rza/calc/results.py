"""Структуры результатов расчёта защит: параметры PFM, критерии, проверки."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import Status, worst
from ..trace import Trace


@dataclass
class Criterion:
    id: str
    kind: str                     # lower | upper | target | fixed
    value: float | None
    title: str
    ref: str = ""                 # нормативное основание (документ, пункт)
    formula_id: str = ""
    note: str = ""

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "value": self.value, "title": self.title, "ref": self.ref,
                "formula_id": self.formula_id, "note": self.note}


@dataclass
class ParamResult:
    pfm_id: str
    instance: str = ""
    title: str = ""
    unit: str = ""
    kind: str = "float"           # float | bool | enum | time
    calc: Any = None              # расчётная уставка (универсальные единицы PFM)
    lower: float | None = None    # минимально допустимое значение по критериям
    upper: float | None = None    # максимально допустимое значение по критериям
    criteria: list = field(default_factory=list)
    trace: Trace | None = None
    status: Status = Status.OK
    reason: str = ""
    notes: list = field(default_factory=list)
    rounding_dir: str = "nearest"  # up | down | nearest — безопасное направление округления
    fixed: bool = False           # инженерный выбор (не вычисляется по данным сети)
    side: str = ""
    group: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.pfm_id}@{self.instance}" if self.instance else self.pfm_id

    def to_dict(self):
        return {"key": self.key, "pfm_id": self.pfm_id, "instance": self.instance, "title": self.title, "unit": self.unit,
                "kind": self.kind, "calc": self.calc, "lower": self.lower, "upper": self.upper,
                "criteria": [c.to_dict() for c in self.criteria], "trace": self.trace.to_dict() if self.trace else None,
                "status": self.status.value, "status_label": self.status.label, "icon": self.status.icon, "reason": self.reason,
                "notes": self.notes, "rounding_dir": self.rounding_dir, "fixed": self.fixed, "side": self.side, "group": self.group,
                "meta": self.meta}


@dataclass
class Check:
    id: str
    function: str
    title: str
    kind: str                     # sensitivity | stability | selectivity | coordination | ct | requirement | data
    status: Status = Status.OK
    value: float | None = None
    threshold: float | None = None
    unit: str = ""
    cmp: str = "≥"
    reason: str = ""
    trace: Trace | None = None
    worst: dict = field(default_factory=dict)      # наихудший случай: режим, положение РПН, вид КЗ, точка
    details: list = field(default_factory=list)    # таблица случаев
    refs: list = field(default_factory=list)
    param_key: str = ""

    def to_dict(self):
        return {"id": self.id, "function": self.function, "title": self.title, "kind": self.kind, "status": self.status.value,
                "status_label": self.status.label, "icon": self.status.icon, "value": self.value, "threshold": self.threshold,
                "unit": self.unit, "cmp": self.cmp, "reason": self.reason, "trace": self.trace.to_dict() if self.trace else None,
                "worst": self.worst, "details": self.details, "refs": self.refs, "param_key": self.param_key}


@dataclass
class FunctionResult:
    function_id: str
    title: str
    params: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    supported: bool = True

    @property
    def status(self) -> Status:
        sts = [p.status for p in self.params if not p.fixed] + [c.status for c in self.checks]
        if self.missing:
            sts.append(Status.MISSING)
        return worst(sts) if sts else Status.NA

    def param(self, key: str) -> ParamResult | None:
        for p in self.params:
            if p.key == key:
                return p
        return None

    def to_dict(self):
        return {"function_id": self.function_id, "title": self.title, "status": self.status.value, "icon": self.status.icon,
                "status_label": self.status.label, "params": [p.to_dict() for p in self.params],
                "checks": [c.to_dict() for c in self.checks], "warnings": self.warnings, "missing": self.missing,
                "meta": self.meta}
