"""Модель сети: эквивалентные источники (макс/мин), смежные линии с уставками их защит, шины, параллельный АТ.

Все сопротивления задаются в Омах на номинальном напряжении соответствующей стороны (base_kv);
расчётное ядро само приводит их к одной ступени напряжения.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .base import Model


@dataclass
class SourceZ(Model):
    r1: float = 0.0        # Ом (прямая = обратная последовательность)
    x1: float = 10.0
    r0: float = 0.0
    x0: float = 12.0

    @classmethod
    def from_sk(cls, u_kv: float, sk3_mva: float, x_r: float = 10.0, x0_x1: float = 1.2, r0_r1: float | None = None) -> "SourceZ":
        """Эквивалент по мощности трёхфазного КЗ S_к (МВА) на шинах напряжением U (кВ).

        |Z1| = U²/S_к;  X/R = x_r;  Z0: X0 = x0_x1·X1.
        """
        z = u_kv ** 2 / sk3_mva
        x1 = z * x_r / math.hypot(1.0, x_r)
        r1 = z / math.hypot(1.0, x_r)
        x0 = x1 * x0_x1
        r0 = r1 * (r0_r1 if r0_r1 is not None else x0_x1)
        return cls(round(r1, 5), round(x1, 5), round(r0, 5), round(x0, 5))

    def z1(self) -> complex:
        return complex(self.r1, self.x1)

    def z0(self) -> complex:
        return complex(self.r0, self.x0)


@dataclass
class Source(Model):
    id: str = "SYS_HV"
    name: str = "Система"
    side: str = "HV"                       # к шинам какой стороны подключён
    max: SourceZ = field(default_factory=SourceZ)   # режим максимальной мощности КЗ
    min: SourceZ = field(default_factory=lambda: SourceZ(0, 20, 0, 24))  # режим минимальной мощности КЗ
    notes: str = ""


@dataclass
class Stage(Model):
    i_a: float | None = None      # ток срабатывания, А первичные (для ТЗНП — 3I0; для обр. посл. — I2)
    t_s: float = 0.0
    z_ohm: float | None = None    # сопротивление срабатывания, Ом (первичные, на напряжении линии)
    curve: str = "definite"       # definite | IEC_NI | IEC_VI | IEC_EI | IEC_LTI
    note: str = ""


@dataclass
class AdjProt(Model):
    """Уставки защит смежного элемента, с которыми выполняется согласование."""
    dist: list[Stage] = field(default_factory=list)
    i0: list[Stage] = field(default_factory=list)
    mtz: list[Stage] = field(default_factory=list)
    neg: list[Stage] = field(default_factory=list)
    source: str = ""              # источник уставок (карта уставок, протокол, ТУ)


@dataclass
class Line(Model):
    id: str = "L1"
    name: str = "ВЛ"
    side: str = "HV"
    length_km: float = 50.0
    r1: float = 0.075             # Ом/км
    x1: float = 0.42
    r0: float = 0.25
    x0: float = 1.3
    remote_source: Source | None = None    # подпитка с противоположного конца (режимы макс/мин)
    prot: AdjProt = field(default_factory=AdjProt)

    def z1(self) -> complex:
        return complex(self.r1, self.x1) * self.length_km

    def z0(self) -> complex:
        return complex(self.r0, self.x0) * self.length_km


@dataclass
class TccEntry(Model):
    """Вышестоящая/нижестоящая защита для построения времятоковых характеристик и проверки селективности."""
    id: str = ""
    name: str = ""
    role: str = "upstream"        # upstream | downstream
    side: str = "HV"
    stages: list[Stage] = field(default_factory=list)
    source: str = ""


@dataclass
class ParallelAT(Model):
    present: bool = False         # на подстанции параллельно работает такой же АТ
    same_taps: bool = True


@dataclass
class Network(Model):
    base_kv: dict[str, float] = field(default_factory=lambda: {"HV": 230.0, "MV": 115.0, "LV": 10.5})
    sources: list[Source] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    tcc: list[TccEntry] = field(default_factory=list)
    parallel_at: ParallelAT = field(default_factory=ParallelAT)
    bus_protection: dict[str, bool] = field(default_factory=lambda: {"HV": True, "MV": True, "LV": False})

    def source(self, sid: str) -> Source:
        for s in self.sources:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def lines_of(self, side: str) -> list[Line]:
        return [l for l in self.lines if l.side == side]
