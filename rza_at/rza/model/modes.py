"""Библиотека расчётных режимов. Каждый режим имеет идентификатор и роль в расчёте защит.

Роли режима (по ним функции защит выбирают режимы):
    max_kz      — максимальные токи КЗ (отстройка, устойчивость дифзащиты при внешних КЗ);
    min_kz      — минимальные токи КЗ (проверка чувствительности);
    load        — нагрузочный режим (I_раб.макс, отстройка от нагрузки, небаланс при РПН);
    post_accident — послеаварийный (перегрузка оставшегося в работе АТ);
    energization — опробование/включение АТ под напряжение (бросок намагничивающего тока).

Положения РПН min/nom/max перебираются автоматически для каждого режима (Вып. 13Б п. 1.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import Model

ROLES = ("max_kz", "min_kz", "load", "post_accident", "energization")


@dataclass
class Mode(Model):
    id: str = "MODE"
    name: str = ""
    kind: str = "custom"              # normal | max_load | min_load | min_kz | max_kz | repair | post_accident | energization | tap | source_off | custom
    roles: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)   # id источника → max | min | off
    parallel_at: bool = False         # параллельный АТ в работе
    tap: str | None = None            # None — перебор min/nom/max; либо 'min' | 'nom' | 'max' | 'p<номер>'
    load_factor: float = 1.0          # I_нагр / I_ном (для нагрузочных режимов)
    c_factor: float = 1.0             # коэффициент ЭДС источников (E = c·U_ср/√3)
    description: str = ""
    builtin: bool = True


def default_modes(source_ids: list[str], has_parallel: bool) -> list[Mode]:
    """Библиотека режимов по умолчанию для заданного набора источников."""
    allmax = {s: "max" for s in source_ids}
    allmin = {s: "min" for s in source_ids}
    modes = [
        Mode("NORM", "Нормальный режим", "normal", ["load"], allmax, has_parallel, None, 0.7, 1.0,
             "Нормальная схема, нагрузка 70 % номинальной."),
        Mode("MAXLOAD", "Максимальная нагрузка", "max_load", ["load"], allmax, has_parallel, None, 1.0, 1.0,
             "Максимальная длительная нагрузка АТ (I_раб.макс = I_ном)."),
        Mode("MINLOAD", "Минимальная нагрузка", "min_load", ["load"], allmin, has_parallel, None, 0.3, 1.0,
             "Минимальная нагрузка."),
        Mode("MAXKZ", "Максимальный КЗ", "max_kz", ["max_kz"], allmax, has_parallel, None, 1.0, 1.0,
             "Все источники в режиме максимальной мощности КЗ, параллельный АТ в работе."),
        Mode("MAXKZ1", "Максимальный КЗ (один АТ)", "max_kz", ["max_kz"], allmax, False, None, 1.0, 1.0,
             "Все источники — максимум, параллельный АТ отключён (наибольший ток через защищаемый АТ)."),
        Mode("MINKZ", "Минимальный КЗ", "min_kz", ["min_kz"], allmin, has_parallel, None, 1.0, 1.0,
             "Все источники в режиме минимальной мощности КЗ, параллельный АТ в работе (ток делится между АТ)."),
        Mode("MINKZ1", "Минимальный КЗ (один АТ)", "min_kz", ["min_kz"], allmin, False, None, 1.0, 1.0,
             "Минимум источников, параллельный АТ отключён (снижение подпитки от параллельного АТ)."),
        Mode("POSTACC", "Послеаварийный", "post_accident", ["load", "post_accident"], allmax, False, None, 1.4, 1.0,
             "Отключён параллельный АТ; оставшийся АТ несёт нагрузку обоих (перегрузка 1,4 I_ном)."),
    ]
    for sid in source_ids:
        srcs = dict(allmin)
        srcs[sid] = "off"
        modes.append(Mode(f"OFF_{sid}", f"Отключён источник {sid}", "source_off", ["min_kz"], srcs, has_parallel, None, 1.0, 1.0,
                          f"Ремонтный режим: источник {sid} отключён, остальные — минимум."))
    # опробование: питание с одной стороны (первым — с ВН), остальные источники отключены
    if source_ids:
        first = source_ids[0]
        srcs = {s: "off" for s in source_ids}
        srcs[first] = "min"
        modes.append(Mode("ENERG", "Опробование АТ со стороны первого источника", "energization", ["energization", "min_kz"], srcs, False,
                          None, 0.0, 1.0, "АТ включается под напряжение с одной стороны; остальные стороны без подпитки."))
    for key, label in (("min", "РПН min"), ("nom", "РПН номинальное"), ("max", "РПН max")):
        modes.append(Mode(f"TAP_{key.upper()}", f"{label} (максимальный КЗ)", "tap", ["max_kz"], allmax, has_parallel, key, 1.0, 1.0,
                          f"Расчёт при фиксированном положении РПН: {label}."))
    return modes
