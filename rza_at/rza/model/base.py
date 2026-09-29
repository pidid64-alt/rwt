"""Базовая сериализация dataclass-моделей в JSON-совместимые словари."""
from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any, get_args, get_origin, Union

_UNIONS = (Union, types.UnionType)


def _build(tp, val):
    if val is None:
        return None
    origin = get_origin(tp)
    if origin in _UNIONS or (isinstance(tp, type) and tp is types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        return _build(args[0], val) if args else val
    if dataclasses.is_dataclass(tp) and isinstance(val, dict):
        return tp.from_dict(val)
    if origin in (list, typing.List):
        (a,) = get_args(tp) or (Any,)
        return [_build(a, v) for v in val]
    if origin in (dict, typing.Dict):
        args = get_args(tp)
        vt = args[1] if len(args) == 2 else Any
        return {k: _build(vt, v) for k, v in val.items()}
    return val


class Model:
    """Миксин: to_dict / from_dict для dataclass'ов (вложенные dataclass, list, dict, Optional)."""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict):
        hints = typing.get_type_hints(cls)
        kwargs = {}
        for f in dataclasses.fields(cls):  # type: ignore[arg-type]
            if f.name in data:
                kwargs[f.name] = _build(hints[f.name], data[f.name])
        return cls(**kwargs)
