"""Базовый класс расчёта функции защиты (универсальный уровень)."""
from __future__ import annotations

from ..context import CalcContext, TerminalContext
from ..results import FunctionResult, Check


class FunctionCalc:
    """Расчёт одной универсальной функции РЗА.

    calculate() возвращает FunctionResult с параметрами PFM (расчётные значения и допустимые интервалы по критериям)
    и проверками; recheck() повторно вычисляет проверки для ПРИНЯТЫХ (округлённых до шага терминала) уставок.
    """

    id: str = ""
    title: str = ""

    def calculate(self, ctx: CalcContext) -> FunctionResult:  # pragma: no cover - интерфейс
        raise NotImplementedError

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        return []
