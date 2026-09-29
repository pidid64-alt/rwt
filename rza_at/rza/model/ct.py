"""Модуль трансформаторов тока и напряжения.

Для каждого ТТ: первичный/вторичный ток, коэффициент трансформации, класс точности и защиты,
номинальная и фактическая нагрузка, предельная кратность, сопротивления цепи и обмотки, схема соединения,
расположение (встроенные, выносные, ТТ выключателей, вводов, нейтрали, нулевой последовательности),
назначение и принадлежность защитам.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import Model

CT_LOCATIONS = {
    "built_in": "Встроенный (ввода)", "external": "Выносной", "breaker": "ТТ выключателя",
    "bushing": "ТТ ввода", "neutral": "ТТ в нейтрали", "zero_seq": "ТТ нулевой последовательности",
}


@dataclass
class CT(Model):
    id: str = "TA1"
    name: str = ""
    side: str = "HV"                 # HV | MV | LV | N (нейтраль)
    location: str = "breaker"
    purpose: str = "Защита"
    protections: list[str] = field(default_factory=lambda: ["87T", "50/51"])
    i1_a: float = 600.0              # первичный номинальный ток, А
    i2_a: float = 1.0                # вторичный номинальный ток, А (1 или 5)
    accuracy_class: str = "5P"       # класс точности (для защиты, напр. 5P, 10P, TPY)
    protection_class: str = "5P20"   # класс защиты с предельной кратностью
    alf: float = 20.0                # номинальная предельная кратность K_ном
    s_nom_va: float = 30.0           # номинальная нагрузка, ВА
    s_fact_va: float = 10.0          # фактическая нагрузка, ВА (провода + реле)
    r_winding_ohm: float = 3.0       # сопротивление вторичной обмотки, Ом
    r_circuit_ohm: float | None = None   # сопротивление вторичной цепи, Ом (если None — из s_fact_va)
    connection: str = "Y"            # схема соединения вторичных обмоток: Y | D
    polarity: str = "to_object"      # to_object | to_bus (начало Л1 в сторону …)

    @property
    def ratio(self) -> float:
        return self.i1_a / self.i2_a

    @property
    def k_sx(self) -> float:
        """Коэффициент схемы: √3 при соединении вторичных обмоток в треугольник (Вып. 13Б, табл. 2.1)."""
        return 3 ** 0.5 if self.connection.upper().startswith("D") else 1.0

    def burden_ohm(self) -> float:
        if self.r_circuit_ohm is not None:
            return self.r_circuit_ohm
        return self.s_fact_va / (self.i2_a ** 2)

    def alf_actual(self) -> float:
        """Действительная предельная кратность при фактической нагрузке:
        K_дейст = K_ном · (S_ном + I₂²·R_ct) / (S_факт + I₂²·R_ct)."""
        i2 = self.i2_a
        num = self.s_nom_va + i2 * i2 * self.r_winding_ohm
        r_b = self.burden_ohm()
        den = r_b * i2 * i2 + i2 * i2 * self.r_winding_ohm
        return self.alf * num / den if den > 0 else self.alf

    def i_no_saturation_a(self) -> float:
        """Наибольший первичный ток, при котором полная погрешность не превышает класс (по действительной кратности)."""
        return self.alf_actual() * self.i1_a


@dataclass
class VT(Model):
    id: str = "TV1"
    name: str = ""
    side: str = "HV"
    u1_kv: float = 220.0
    u2_v: float = 100.0              # междуфазное вторичное напряжение основной обмотки (100/√3 → 100 В при делителе)
    u2_delta_v: float = 100.0        # обмотка разомкнутого треугольника: 3U0 при металлическом замыкании (100 В)
    accuracy_class: str = "0.5/3P"
    connection: str = "Y/Y/Δ"

    @property
    def ratio(self) -> float:
        return self.u1_kv * 1000.0 / self.u2_v
