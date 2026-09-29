"""Исключения и перечисление статусов проверки."""
from __future__ import annotations

from enum import Enum


class RzaError(Exception):
    """Базовая ошибка расчётного ядра."""


class DataError(RzaError):
    """Недостаточные или некорректные исходные данные (расчёт не может быть выполнен)."""

    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = missing or []


class FormulaError(RzaError):
    pass


class ProfileError(RzaError):
    pass


class Status(str, Enum):
    """Статус результата проверки (соответствует индикации 🟢 🟡 🔴 🟠 ⚪ из ТЗ)."""

    OK = "ok"                    # 🟢 выполнено
    CHECK = "check"              # 🟡 требуется проверка
    FAIL = "fail"                # 🔴 не выполнено
    MISSING = "missing"          # 🟠 не хватает исходных данных
    OUT_OF_RANGE = "out_of_range"  # 🔴 уставка вне диапазона терминала
    NA = "na"                    # ⚪ не применимо / не поддерживается

    @property
    def icon(self) -> str:
        return {"ok": "🟢", "check": "🟡", "fail": "🔴", "missing": "🟠", "out_of_range": "🔴", "na": "⚪"}[self.value]

    @property
    def label(self) -> str:
        return {"ok": "Выполнено", "check": "Требуется проверка", "fail": "Не выполнено",
                "missing": "Не хватает исходных данных", "out_of_range": "Уставка вне диапазона терминала",
                "na": "Не применимо"}[self.value]

    @property
    def severity(self) -> int:
        return {"ok": 0, "na": 0, "check": 1, "missing": 2, "fail": 3, "out_of_range": 3}[self.value]


def worst(statuses) -> Status:
    """Наихудший из статусов (для агрегирования)."""
    st = [s for s in statuses if s is not None]
    if not st:
        return Status.NA
    return max(st, key=lambda s: s.severity)
