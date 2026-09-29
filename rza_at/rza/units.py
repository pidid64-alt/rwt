"""Единая система единиц.

Внутреннее расчётное ядро работает в строго определённых канонических единицах:

    ток — А;  напряжение (междуфазное) — кВ;  мощность — МВА (МВт, Мвар);
    сопротивление — Ом;  время — с;  частота — Гц;  угол — градусы;
    относительные величины — доли единицы (1.0 = 100 % = 1 о.е.).

Преобразование при отображении выполняется функцией :func:`convert` и не влияет
на расчётный результат (в результатах всегда хранятся канонические значения).
Относительные единицы, привязанные к базе (In, Un, I/InO, I/InS), требуют указания базы.
"""
from __future__ import annotations

import math

CANON = {
    "current": "А",
    "voltage": "кВ",
    "power": "МВА",
    "impedance": "Ом",
    "time": "с",
    "frequency": "Гц",
    "angle": "град",
    "ratio": "о.е.",
}

# единица -> (размерность, множитель к канонической единице)
_ABS = {
    "A": ("current", 1.0), "А": ("current", 1.0), "kA": ("current", 1e3), "кА": ("current", 1e3),
    "mA": ("current", 1e-3), "мА": ("current", 1e-3),
    "V": ("voltage", 1e-3), "В": ("voltage", 1e-3), "kV": ("voltage", 1.0), "кВ": ("voltage", 1.0),
    "VA": ("power", 1e-6), "kVA": ("power", 1e-3), "MVA": ("power", 1.0), "МВА": ("power", 1.0), "кВА": ("power", 1e-3),
    "W": ("power", 1e-6), "kW": ("power", 1e-3), "MW": ("power", 1.0), "МВт": ("power", 1.0), "кВт": ("power", 1e-3),
    "var": ("power", 1e-6), "kvar": ("power", 1e-3), "MVAr": ("power", 1.0), "Мвар": ("power", 1.0),
    "Ω": ("impedance", 1.0), "Ом": ("impedance", 1.0), "ohm": ("impedance", 1.0), "mΩ": ("impedance", 1e-3),
    "мОм": ("impedance", 1e-3), "kΩ": ("impedance", 1e3), "кОм": ("impedance", 1e3),
    "s": ("time", 1.0), "с": ("time", 1.0), "sec": ("time", 1.0), "ms": ("time", 1e-3), "мс": ("time", 1e-3),
    "min": ("time", 60.0), "мин": ("time", 60.0), "h": ("time", 3600.0), "ч": ("time", 3600.0),
    "Hz": ("frequency", 1.0), "Гц": ("frequency", 1.0),
    "deg": ("angle", 1.0), "°": ("angle", 1.0), "град": ("angle", 1.0), "rad": ("angle", 180.0 / math.pi),
    "%": ("ratio", 0.01), "p.u.": ("ratio", 1.0), "pu": ("ratio", 1.0), "о.е.": ("ratio", 1.0), "1": ("ratio", 1.0), "": ("ratio", 1.0),
}
# относительные единицы с базой: единица -> размерность базы
_REL = {
    "In": "current", "I/In": "current", "I/InO": "current", "I/InS": "current", "I/Inobj": "current", "I/Iном": "current",
    "Un": "voltage", "U/Un": "voltage", "U/Uном": "voltage",
    "Sn": "power", "S/Sn": "power",
    "Zb": "impedance",
}


class UnitError(ValueError):
    pass


def dimension(unit: str) -> str:
    u = unit.strip()
    if u in _ABS:
        return _ABS[u][0]
    if u in _REL:
        return "rel:" + _REL[u]
    raise UnitError(f"Неизвестная единица измерения: «{unit}»")


def convert(value: float, from_unit: str, to_unit: str, base: float | None = None, freq: float = 50.0) -> float:
    """Преобразование значения между единицами.

    base — база для относительных единиц (In → А, Un → кВ, Sn → МВА, Zb → Ом), в канонических единицах.
    """
    f, t = from_unit.strip(), to_unit.strip()
    if f == t:
        return value
    if f in ("cycle", "период", "цикл") or t in ("cycle", "период", "цикл"):
        per = 1.0 / freq
        sec = value * per if f in ("cycle", "период", "цикл") else value
        return sec if t in ("s", "с") else (sec / per if t in ("cycle", "период", "цикл") else convert(sec, "с", t))
    if f in _ABS and t in _ABS:
        (d1, k1), (d2, k2) = _ABS[f], _ABS[t]
        if d1 != d2:
            raise UnitError(f"Нельзя преобразовать {from_unit} ({d1}) в {to_unit} ({d2})")
        return value * k1 / k2
    if f in _REL or t in _REL:
        if f in _REL and t in _ABS:
            d, k = _ABS[t]
            if d != _REL[f]:
                raise UnitError(f"Несовместимые единицы: {from_unit} → {to_unit}")
            if base is None:
                raise UnitError(f"Для {from_unit} → {to_unit} требуется база (base)")
            return value * base / k
        if f in _ABS and t in _REL:
            d, k = _ABS[f]
            if d != _REL[t]:
                raise UnitError(f"Несовместимые единицы: {from_unit} → {to_unit}")
            if base is None:
                raise UnitError(f"Для {from_unit} → {to_unit} требуется база (base)")
            return value * k / base
        if f in _REL and t in _REL:
            return value
        # относительная <-> о.е./%
        if f in _REL and t in _ABS and _ABS[t][0] == "ratio":
            return value / _ABS[t][1]
        if t in _REL and f in _ABS and _ABS[f][0] == "ratio":
            return value * _ABS[f][1]
    raise UnitError(f"Не поддерживается преобразование {from_unit} → {to_unit}")


def to_canon(value: float, unit: str, base: float | None = None) -> float:
    d = dimension(unit)
    if d.startswith("rel:"):
        if base is None:
            raise UnitError(f"Для {unit} требуется база")
        return value * base
    return convert(value, unit, CANON[d])


def fmt_num(x, sig: int = 4) -> str:
    """Формат числа для трасс расчёта: русская десятичная запятая, sig значащих цифр."""
    if x is None:
        return "—"
    if isinstance(x, str):
        return x
    if isinstance(x, bool):
        return "да" if x else "нет"
    if isinstance(x, complex):
        return f"{fmt_num(abs(x), sig)}∠{fmt_num(math.degrees(math.atan2(x.imag, x.real)), 3)}°"
    if x == 0:
        return "0"
    if math.isinf(x):
        return "∞" if x > 0 else "−∞"
    if math.isnan(x):
        return "н/д"
    ax = abs(x)
    if ax >= 1e6 or ax < 1e-4:
        s = f"{x:.{max(sig - 1, 1)}e}"
        mant, exp = s.split("e")
        return f"{mant.replace('.', ',')}·10^{int(exp)}"
    digits = max(sig - int(math.floor(math.log10(ax))) - 1, 0)
    s = f"{x:.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def fmt_val(x, unit: str = "", sig: int = 4) -> str:
    u = f" {unit}" if unit and unit not in ("1", "") else ""
    return f"{fmt_num(x, sig)}{u}"
