"""Модуль нормативно-методической базы: источники, нормативные значения, библиотека формул."""
from __future__ import annotations

from pathlib import Path

from .sources import SourceRegistry, DEFAULT_PRIORITY
from .norms import NormRegistry, NormValue
from .formulas import FormulaLibrary, Formula

USER_DIR = Path(__file__).resolve().parents[2] / "user_data" / "formulas"

_singleton = None


def registry():
    """Единый экземпляр (источники, нормы, формулы) для приложения."""
    global _singleton
    if _singleton is None:
        src = SourceRegistry(USER_DIR)
        _singleton = type("Reg", (), {})()
        _singleton.sources = src
        _singleton.norms = NormRegistry(src, USER_DIR)
        _singleton.formulas = FormulaLibrary(src, USER_DIR)
    return _singleton


def reset_registry():
    global _singleton
    _singleton = None


__all__ = ["registry", "reset_registry", "SourceRegistry", "NormRegistry", "NormValue", "FormulaLibrary", "Formula", "DEFAULT_PRIORITY"]
