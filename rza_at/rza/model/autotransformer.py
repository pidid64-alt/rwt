"""Паспорт автотрансформатора / трансформатора и РПН как отдельный объект расчёта.

Поддерживаются: двухобмоточные и трёхобмоточные трансформаторы, автотрансформаторы (с третичной
обмоткой НН или без неё), однофазные группы АТ (данные одной фазы + признак группы),
варианты с регулировочной обмоткой / линейным регулировочным трансформатором.

Соглашения:
  * стороны: HV (ВН), MV (СН), LV (НН);
  * номера положений РПН: 1 … N; номер 1 — минимальное напряжение регулируемой стороны;
    U(положение) = U_ном·(1 + (номер − номинальное)·ступень/100);
  * u_к даётся для пар обмоток на трёх положениях (min / nom / max), промежуточные — интерполяцией.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .base import Model

SQRT3 = math.sqrt(3.0)
SIDES = ("HV", "MV", "LV")
PAIRS = ("HV_MV", "HV_LV", "MV_LV")
SIDE_RU = {"HV": "ВН", "MV": "СН", "LV": "НН"}


def rated_current_a(s_mva: float, u_kv: float) -> float:
    """Номинальный ток, А, по мощности (МВА) и междуфазному напряжению (кВ)."""
    return s_mva * 1000.0 / (SQRT3 * u_kv)


@dataclass
class Winding(Model):
    role: str = "HV"                 # HV | MV | LV
    u_nom_kv: float = 230.0          # номинальное междуфазное напряжение обмотки (среднее ответвление), кВ
    s_nom_mva: float | None = None   # номинальная мощность обмотки (None → S_ном трансформатора)
    connection: str = "YN"           # YN | Y | D | Z
    clock: int = 0                   # группа соединения (часы) относительно обмотки ВН, 0…11
    neutral: str = "solid"           # solid | impedance | isolated
    neutral_z_ohm: float = 0.0       # сопротивление в нейтрали, Ом


@dataclass
class UkPair(Model):
    nom: float = 10.0                # u_к, % на среднем ответвлении
    min: float | None = None         # u_к, % в положении «min» (None → как nom)
    max: float | None = None
    s_ref_mva: float | None = None   # мощность, к которой отнесено u_к (None → S_ном)
    source: str = ""                 # источник данных (паспорт, таблица 8.1 Вып. 13Б, протокол испытаний…)


@dataclass
class TapChanger(Model):
    present: bool = True
    side: str = "MV"                 # сторона, напряжение которой регулируется: HV | MV | LV
    location: str = "line"           # line (в линии) | neutral (в нейтрали) | winding | separate (ЛРТ)
    n_steps_plus: int = 6
    n_steps_minus: int = 6
    step_pct: float = 2.0
    nominal_position: int = 7
    used_min_position: int | None = None   # реально используемые положения (Вып. 13Б п. 1.4)
    used_max_position: int | None = None
    description: str = ""

    @property
    def n_positions(self) -> int:
        return self.n_steps_plus + self.n_steps_minus + 1 if self.present else 1

    def delta(self, position: int) -> float:
        """Относительное изменение напряжения регулируемой стороны в положении (доли)."""
        if not self.present:
            return 0.0
        return (position - self.nominal_position) * self.step_pct / 100.0

    def pos_min(self) -> int:
        return self.used_min_position or 1

    def pos_max(self) -> int:
        return self.used_max_position or self.n_positions

    def key_position(self, key) -> int:
        if isinstance(key, int):
            return key
        if key == "min":
            return self.pos_min()
        if key == "max":
            return self.pos_max()
        if key == "nom":
            return self.nominal_position
        if isinstance(key, str) and key.startswith("p"):
            return int(key[1:])
        raise ValueError(f"Неизвестный ключ положения РПН: {key}")

    def table(self) -> list[dict]:
        """Таблица положений: номер, отклонение напряжения, %."""
        return [{"number": n, "delta_pct": round(self.delta(n) * 100, 4),
                 "is_min": n == self.pos_min(), "is_nom": n == self.nominal_position, "is_max": n == self.pos_max()}
                for n in range(1, self.n_positions + 1)]


@dataclass
class Thermal(Model):
    k_factor: float | None = 1.05            # допустимый длительный ток / номинальный (из паспорта/ГОСТ 14209)
    tau_min: float | None = None             # тепловая постоянная времени, мин (данные завода)
    overload_curve: list[dict] = field(default_factory=list)  # [{"multiple": 1.3, "minutes": 120}, …] допустимая длительность
    curve_source: str = ""
    cooling: str = "ONAN"


@dataclass
class Transformer(Model):
    kind: str = "auto"               # auto | two_winding | three_winding | auto_group_1ph
    manufacturer: str = ""
    type_name: str = ""
    serial_number: str = ""
    year: int | None = None
    frequency_hz: float = 50.0
    s_nom_mva: float = 200.0         # номинальная (проходная) мощность, МВА
    s_typ_mva: float | None = None   # типовая мощность (АТ); None → S_ном·(1 − U_СН/U_ВН)
    windings: dict[str, Winding] = field(default_factory=dict)
    uk: dict[str, UkPair] = field(default_factory=dict)
    pk_kw: dict[str, float] = field(default_factory=dict)
    p0_kw: float | None = None
    i0_pct: float | None = None
    x0_over_x1: float = 1.0          # отношение X0/X1 ветвей схемы замещения нулевой последовательности
    oltc: TapChanger = field(default_factory=TapChanger)
    regulating_winding: bool = False # наличие регулировочной обмотки (однофазные группы АТ)
    series_z_ohm: dict[str, float] = field(default_factory=dict)  # последовательный элемент (ЛРТ/реактор) между выводом и шинами, Ом (на напряжении стороны)
    thermal: Thermal = field(default_factory=Thermal)
    builtin_protections: list[str] = field(default_factory=lambda: ["Газовая защита", "Реле давления", "Термосигнализаторы"])
    grounding_scheme: str = "Нейтраль ВН/СН глухо заземлена (общая нейтраль АТ)"

    # ── удобные свойства ──
    def sides(self) -> list[str]:
        return [s for s in SIDES if s in self.windings]

    def w(self, side: str) -> Winding:
        return self.windings[side]

    def is_auto(self) -> bool:
        return self.kind in ("auto", "auto_group_1ph")

    def u_nom(self, side: str) -> float:
        return self.windings[side].u_nom_kv

    def group_label(self) -> str:
        """Условное обозначение группы соединения, например YNa0d11."""
        parts = []
        for s in self.sides():
            w = self.windings[s]
            if self.is_auto() and s == "MV":
                continue
            c = w.connection
            if self.is_auto() and s == "HV":
                parts.append(f"{c}a0" if c.upper().startswith("Y") else c)
            else:
                parts.append((c.lower() if s != "HV" else c) + (str(w.clock) if s != "HV" else ""))
        return "".join(parts)

    def alpha(self) -> float:
        """Коэффициент выгодности АТ α = 1 − U_СН/U_ВН."""
        if self.is_auto() and "MV" in self.windings:
            return 1.0 - self.u_nom("MV") / self.u_nom("HV")
        return 1.0

    def s_typ(self) -> float:
        return self.s_typ_mva if self.s_typ_mva else self.s_nom_mva * self.alpha()

    def s_winding(self, side: str) -> float:
        w = self.windings[side]
        return w.s_nom_mva if w.s_nom_mva else self.s_nom_mva

    def i_nom(self, side: str, s_mva: float | None = None, u_kv: float | None = None) -> float:
        """Номинальный ток стороны (А) при мощности S (по умолчанию S_ном — проходная) и напряжении U (по умолчанию номинальном)."""
        return rated_current_a(s_mva if s_mva else self.s_nom_mva, u_kv if u_kv else self.u_nom(side))

    def rated_table(self) -> list[dict]:
        rows = []
        for s in self.sides():
            w = self.windings[s]
            rows.append({"side": s, "side_ru": SIDE_RU[s], "u_nom_kv": w.u_nom_kv, "s_winding_mva": self.s_winding(s),
                         "i_nom_through_a": self.i_nom(s), "i_nom_winding_a": self.i_nom(s, self.s_winding(s)),
                         "connection": w.connection, "clock": w.clock})
        return rows

    # ── положения РПН ──
    def u_side_at(self, side: str, position: int) -> float:
        """Номинальное напряжение стороны в положении РПН, кВ."""
        u = self.u_nom(side)
        if self.oltc.present and self.oltc.side == side:
            u *= 1.0 + self.oltc.delta(position)
        return u

    def uk_at(self, pair: str, position: int) -> float | None:
        """u_к пары обмоток, %, в положении РПН (интерполяция по min/nom/max, при наличии)."""
        uk = self.uk.get(pair)
        if uk is None:
            return None
        if not self.oltc.present or (uk.min is None and uk.max is None):
            return uk.nom
        pmin, pnom, pmax = self.oltc.pos_min(), self.oltc.nominal_position, self.oltc.pos_max()
        umin = uk.min if uk.min is not None else uk.nom
        umax = uk.max if uk.max is not None else uk.nom
        if position <= pmin:
            return umin
        if position >= pmax:
            return umax
        if position == pnom:
            return uk.nom
        if position < pnom:
            return umin + (uk.nom - umin) * (position - pmin) / max(pnom - pmin, 1)
        return uk.nom + (umax - uk.nom) * (position - pnom) / max(pmax - pnom, 1)

    def star_x_ohm(self, position: int) -> dict[str, float]:
        """Индуктивные сопротивления лучей схемы замещения (Ом), приведённые к стороне ВН на текущем ответвлении.

        Для трёхобмоточных трансформаторов и АТ: луч = ½(u_ab + u_ac − u_bc). Для двухобмоточных:
        весь u_к в луче ВН, луч НН — нулевой.
        """
        uH = self.u_side_at("HV", position)
        sb = self.s_nom_mva
        def u(pair):
            v = self.uk_at(pair, position)
            if v is None:
                return None
            ref = self.uk[pair].s_ref_mva or sb
            return v * sb / ref
        sides = self.sides()
        if len(sides) == 2:
            other = [s for s in sides if s != "HV"][0]
            pair = f"HV_{other}"
            up = u(pair)
            x = up / 100.0 * uH * uH / sb
            return {"H": x, other[0]: 1e-6}
        u_hm, u_hl, u_ml = u("HV_MV"), u("HV_LV"), u("MV_LV")
        if None in (u_hm, u_hl, u_ml):
            raise ValueError("Для трёхобмоточного трансформатора необходимы u_к всех трёх пар обмоток")
        uh = 0.5 * (u_hm + u_hl - u_ml)
        um = 0.5 * (u_hm + u_ml - u_hl)
        ul = 0.5 * (u_hl + u_ml - u_hm)
        f = uH * uH / sb / 100.0
        return {"H": uh * f, "M": um * f, "L": ul * f}


def tap_keys(tr: Transformer) -> list:
    """Положения РПН для обязательного расчёта: min → nom → max (Вып. 13Б п. 1.4; ТЗ п. 6, 28)."""
    if not tr.oltc.present:
        return ["nom"]
    keys = ["min", "nom", "max"]
    # если min/max совпадают с номинальным, оставляем уникальные
    seen, out = set(), []
    for k in keys:
        p = tr.oltc.key_position(k)
        if p not in seen:
            seen.add(p)
            out.append(k)
    return out


@dataclass
class TapState:
    key: str
    position: int
    delta: float
    u_kv: dict          # номинальные напряжения сторон в положении, кВ
    x_ohm: dict         # лучи схемы замещения (Ом, приведённые к ВН)
    uk_pct: dict        # u_к пар, %

    def label(self) -> str:
        names = {"min": "РПН min", "nom": "РПН номинальное", "max": "РПН max"}
        return f"{names.get(self.key, 'РПН ' + str(self.key))} (№{self.position}, {self.delta * 100:+.1f} %)"

    def to_dict(self):
        return {"key": self.key, "position": self.position, "delta_pct": self.delta * 100, "u_kv": self.u_kv,
                "x_ohm": self.x_ohm, "uk_pct": self.uk_pct, "label": self.label()}


def tap_state(tr: Transformer, key) -> TapState:
    pos = tr.oltc.key_position(key) if tr.oltc.present else tr.oltc.nominal_position
    keyname = key if isinstance(key, str) else f"p{key}"
    u = {s: tr.u_side_at(s, pos) for s in tr.sides()}
    uk = {p: tr.uk_at(p, pos) for p in PAIRS if p in tr.uk}
    return TapState(keyname, pos, tr.oltc.delta(pos), u, tr.star_x_ohm(pos), uk)


def tap_states(tr: Transformer, keys=None) -> list[TapState]:
    return [tap_state(tr, k) for k in (keys or tap_keys(tr))]
