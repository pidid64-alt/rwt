"""Реестр расчётных модулей функций защит.

Добавление новой функции = новый модуль с классом-наследником FunctionCalc и декоратором @register;
ядро и терминалы не изменяются.
"""
from __future__ import annotations

REGISTRY: dict[str, type] = {}


def register(cls):
    REGISTRY[cls.id] = cls
    return cls


def get(fid: str):
    return REGISTRY[fid]()


def all_ids() -> list[str]:
    order = ["87T", "50/51", "46", "50N/51N", "21", "49"]
    return [i for i in order if i in REGISTRY] + [i for i in REGISTRY if i not in order]


from . import f87t, f5051, f46, f50n51n, f21, f49  # noqa: E402,F401  (регистрация)
