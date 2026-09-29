"""Трасса расчёта («Показать расчёт»).

Каждый важный результат хранит цепочку:

    Исходные данные → Формула (из библиотеки, с версией и источником) → Подстановка
      → Результат → Принятая уставка → Проверка.

Формулы вычисляются ТОЛЬКО через библиотеку формул (rza.normative.formulas), поэтому «безымянных»
формул в расчётах нет: у каждого шага есть идентификатор формулы, версия, документ и пункт.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from .errors import FormulaError
from .units import fmt_num

# ─────────────────────────── безопасный вычислитель ───────────────────────────

_FUNCS = {
    "max": max, "min": min, "abs": abs, "sqrt": math.sqrt, "exp": math.exp, "ln": math.log, "log10": math.log10,
    "tan": math.tan, "atan": math.atan, "atan2": math.atan2, "sin": math.sin, "cos": math.cos, "acos": math.acos,
    "asin": math.asin, "radians": math.radians, "degrees": math.degrees, "hypot": math.hypot,
}
_CONST = {"pi": math.pi, "SQRT3": math.sqrt(3.0)}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a ** b}
_UN = {ast.USub: lambda a: -a, ast.UAdd: lambda a: +a}
_CMP = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b}


def _eval_node(node, names: dict):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, names)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        if node.id in _CONST:
            return _CONST[node.id]
        raise FormulaError(f"Неизвестная переменная в формуле: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval_node(node.left, names), _eval_node(node.right, names))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval_node(node.operand, names))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval_node(a, names) for a in node.args])
    if isinstance(node, ast.IfExp):
        return _eval_node(node.body, names) if _eval_node(node.test, names) else _eval_node(node.orelse, names)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
        return _CMP[type(node.ops[0])](_eval_node(node.left, names), _eval_node(node.comparators[0], names))
    raise FormulaError(f"Недопустимая конструкция в формуле: {ast.dump(node)[:60]}")


def evaluate(expression: str, names: dict[str, float]) -> float:
    """Безопасное вычисление арифметического выражения (без eval)."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:  # pragma: no cover
        raise FormulaError(f"Синтаксическая ошибка формулы «{expression}»: {e}") from e
    try:
        return float(_eval_node(tree, names))
    except ZeroDivisionError as e:
        raise FormulaError(f"Деление на ноль при вычислении «{expression}»") from e


_ident = re.compile(r"[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*")


def substitute(expression: str, names: dict[str, float], sig: int = 4) -> str:
    """Подстановка значений в выражение для отображения: «1,3 · 218,4»."""
    def rep(m):
        n = m.group(0)
        if n in names:
            v = names[n]
            s = fmt_num(v, sig)
            return f"({s})" if isinstance(v, (int, float)) and v < 0 else s
        if n in _CONST:
            return fmt_num(_CONST[n], sig) if n != "SQRT3" else "√3"
        return n
    s = _ident.sub(rep, expression)
    s = s.replace("**2", "²").replace("**3", "³").replace("**", "^").replace("*", " · ").replace("/", " / ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ─────────────────────────── структуры трассы ───────────────────────────


@dataclass
class Var:
    name: str
    value: Any
    unit: str = ""
    desc: str = ""
    src: str = ""

    def __float__(self):
        return float(self.value)

    def to_dict(self):
        v = self.value
        if isinstance(v, complex):
            v = {"re": v.real, "im": v.imag}
        return {"name": self.name, "value": v, "unit": self.unit, "desc": self.desc, "src": self.src}


@dataclass
class Step:
    kind: str                       # calc | input | choice | note | check | rounding
    title: str
    formula_id: str = ""
    formula_version: int = 0
    display: str = ""               # формула в математической записи
    inputs: list[Var] = field(default_factory=list)
    substituted: str = ""
    result: Var | None = None
    source: str = ""                # документ, пункт
    note: str = ""
    options: list[dict] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["inputs"] = [v.to_dict() for v in self.inputs]
        d["result"] = self.result.to_dict() if self.result else None
        return d


def _num(v):
    return float(v.value) if isinstance(v, Var) else float(v)


class Trace:
    """Последовательность шагов расчёта одного параметра / проверки."""

    def __init__(self, library, title: str = ""):
        self.library = library
        self.title = title
        self.steps: list[Step] = []
        self.terminal_source: dict | None = None    # источник параметров терминала
        self.rounding: dict | None = None
        self.recheck: list[dict] = []

    # входные данные (для отображения в начале)
    def input(self, name: str, value, unit: str = "", desc: str = "", src: str = "") -> Var:
        v = Var(name, value, unit, desc, src)
        self.steps.append(Step("input", f"Исходное данное: {desc or name}", inputs=[v], result=v, source=src))
        return v

    def note(self, title: str, text: str = "", source: str = "") -> None:
        self.steps.append(Step("note", title, note=text, source=source))

    def choice(self, title: str, value, unit: str, options: list[dict], source: str = "", note: str = "") -> Var:
        v = Var(title, value, unit)
        self.steps.append(Step("choice", title, result=v, source=source, options=options, note=note))
        return v

    def calc(self, formula_id: str, values: dict, title: str | None = None, result_name: str | None = None,
             unit: str | None = None, note: str = "", version: int | None = None) -> Var:
        """Вычислить по формуле из библиотеки; записать шаг с подстановкой и источником."""
        f = self.library.get(formula_id, version)
        names: dict[str, float] = {}
        inputs: list[Var] = []
        for k, v in values.items():
            names[k] = _num(v)
            meta = f.variables.get(k, {})
            if isinstance(v, Var):
                inputs.append(Var(k, v.value, v.unit or meta.get("unit", ""), meta.get("desc", v.desc), v.src))
            else:
                inputs.append(Var(k, v, meta.get("unit", ""), meta.get("desc", "")))
        missing = [k for k in f.variables if k not in names]
        if missing:
            raise FormulaError(f"Формула {formula_id}: не заданы переменные {missing}")
        res = evaluate(f.expression, names)
        rname = result_name or f.result.get("name", "результат")
        runit = unit if unit is not None else f.result.get("unit", "")
        sub = substitute(f.expression, names)
        rv = Var(rname, res, runit, f.result.get("desc", ""))
        self.steps.append(Step(
            kind="calc", title=title or f.name, formula_id=f.id, formula_version=f.version,
            display=f.display, inputs=inputs, substituted=f"{rname} = {sub} = {fmt_num(res)}{(' ' + runit) if runit not in ('', '1') else ''}",
            result=rv, source=f.source_ref(), note=note))
        return rv

    def rounding_step(self, calc_value, accepted, unit: str, rng: tuple, step, policy: str, deviation: float, terminal_src: dict | None) -> None:
        self.rounding = {"calc": calc_value, "accepted": accepted, "unit": unit, "min": rng[0], "max": rng[1],
                         "step": step, "policy": policy, "deviation": deviation}
        self.terminal_source = terminal_src

    def to_dict(self) -> dict:
        return {"title": self.title, "steps": [s.to_dict() for s in self.steps], "terminal_source": self.terminal_source,
                "rounding": self.rounding, "recheck": self.recheck}
