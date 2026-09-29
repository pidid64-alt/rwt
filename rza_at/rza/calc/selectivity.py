"""Времятоковые характеристики и проверка селективности по току и по времени.

Характеристики: независимая (definite) и зависимые IEC (NI, VI, EI, LTI):  t = TMS · c / ((I/I_p)^α − 1).
Проверка пары «защита — смежная защита»: в каждой точке диапазона токов вычисляется разность времён; требуется
t_вышестоящей − t_собственной ≥ Δt (и t_собственной − t_нижестоящей ≥ Δt) во всех точках, где обе защиты пришли в действие.
Зона селективности — область токов, где запас по времени не менее Δt.
"""
from __future__ import annotations

import math

from ..model.network import Stage

IEC = {"IEC_NI": (0.14, 0.02, "Нормально инверсная"), "IEC_VI": (13.5, 1.0, "Сильно инверсная"),
       "IEC_EI": (80.0, 2.0, "Чрезвычайно инверсная"), "IEC_LTI": (120.0, 1.0, "Длительно инверсная")}
CURVE_NAMES = {"definite": "Независимая", **{k: v[2] for k, v in IEC.items()}}


def stage_time(st: Stage, i_a: float) -> float | None:
    """Время срабатывания ступени при токе I (А, первичный); None — ступень не пришла в действие."""
    if not st.i_a or i_a < st.i_a:
        return None
    if st.curve == "definite":
        return st.t_s
    c, alpha, _ = IEC[st.curve]
    m = i_a / st.i_a
    if m <= 1.0:
        return None
    return st.t_s * c / (m ** alpha - 1.0)


def curve_time(stages: list[Stage], i_a: float) -> float | None:
    """Время срабатывания защиты как комбинации ступеней: наименьшее из пришедших в действие."""
    ts = [t for t in (stage_time(s, i_a) for s in stages) if t is not None]
    return min(ts) if ts else None


def time_dial(curve: str, t_req: float, multiple: float) -> float:
    """Временной множитель TMS зависимой характеристики, дающий время t_req при кратности тока multiple."""
    c, alpha, _ = IEC[curve]
    return t_req * (multiple ** alpha - 1.0) / c


def log_grid(i_lo: float, i_hi: float, n: int = 80) -> list[float]:
    i_lo, i_hi = max(i_lo, 1e-3), max(i_hi, i_lo * 1.01)
    return [i_lo * (i_hi / i_lo) ** (k / (n - 1)) for k in range(n)]


def check_pair(own: list[Stage], other: list[Stage], role: str, dt: float, i_lo: float, i_hi: float, scale: float = 1.0, n: int = 120) -> dict:
    """Проверка селективности по времени пары «своя защита — смежная».

    role: 'upstream' — смежная защита вышестоящая (должна быть медленнее на Δt);
          'downstream' — нижестоящая (должна быть быстрее своей на Δt).
    scale — коэффициент пересчёта тока: I_смежной = I_своей·scale (приведение к ступени напряжения).
    """
    worst = None
    rows = []
    for i in log_grid(i_lo, i_hi, n):
        t_own = curve_time(own, i)
        t_oth = curve_time(other, i * scale)
        if t_own is None or t_oth is None:
            continue
        margin = (t_oth - t_own) if role == "upstream" else (t_own - t_oth)
        rows.append((i, t_own, t_oth, margin))
        if worst is None or margin < worst[3]:
            worst = (i, t_own, t_oth, margin)
    if worst is None:
        return {"ok": True, "margin": None, "at_a": None, "note": "смежная защита не приходит в действие в проверяемом диапазоне токов", "rows": rows}
    return {"ok": worst[3] >= dt - 1e-9, "margin": worst[3], "at_a": worst[0], "t_own": worst[1], "t_other": worst[2], "rows": rows}


def series(stages: list[Stage], i_lo: float, i_hi: float, scale: float = 1.0, n: int = 90) -> list[dict]:
    """Точки времятоковой характеристики для графика (ток в амперах собственной стороны)."""
    pts = []
    for i in log_grid(i_lo, i_hi, n):
        t = curve_time(stages, i * scale)
        pts.append({"i": i, "t": t})
    return pts
