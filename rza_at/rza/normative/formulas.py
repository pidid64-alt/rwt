"""Библиотека инженерных формул.

Для каждой формулы: идентификатор, название, математическая запись, описание, единицы,
источник, пункт документа, область применения, версия, дата изменения.

Формулы НЕЛЬЗЯ изменять «на месте»: любое изменение создаёт новую версию (старые версии
остаются в библиотеке и доступны для аудита прошлых расчётов).
Встроенные формулы — в rza/normative/data/formulas.json (только чтение);
пользовательские версии — в user_data/formulas/user_formulas.json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

from ..errors import FormulaError
from ..trace import evaluate, _ident, _CONST, _FUNCS

DATA = Path(__file__).parent / "data"


@dataclass
class Formula:
    id: str
    version: int
    name: str
    display: str
    expression: str
    variables: dict
    result: dict
    description: str = ""
    source_id: str = ""
    clause: str = ""
    scope: str = ""
    date: str = ""
    status: str = "active"
    verified: bool = False
    author: str = "встроенная база"
    reason: str = ""
    _sources: object = None

    def source_ref(self) -> str:
        if self._sources is not None:
            s = self._sources.get(self.source_id)
            base = s.short
        else:
            base = self.source_id
        return f"{base}, {self.clause}".strip(", ")

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_sources", None)
        if self._sources is not None:
            s = self._sources.get(self.source_id)
            d["source_title"] = s.title
            d["source_verified"] = s.verified
        return d


def _names_in(expression: str) -> set[str]:
    return {n for n in _ident.findall(expression) if n not in _CONST and n not in _FUNCS}


class FormulaLibrary:
    def __init__(self, sources, user_dir: Path | None = None):
        self.sources = sources
        self.user_path = (user_dir / "user_formulas.json") if user_dir else None
        self._h: dict[str, list[Formula]] = {}
        for rec in json.loads((DATA / "formulas.json").read_text(encoding="utf-8")):
            self._add(rec, user=False)
        self._user_ids: list[dict] = []
        if self.user_path and self.user_path.exists():
            for rec in json.loads(self.user_path.read_text(encoding="utf-8")):
                self._add(rec, user=True)
                self._user_ids.append(rec)
        self._refresh_status()

    # ── загрузка ──
    def _add(self, rec: dict, user: bool):
        rec = dict(rec)
        f = Formula(**{k: v for k, v in rec.items() if k in Formula.__dataclass_fields__ and k != "_sources"})
        f._sources = self.sources
        self._h.setdefault(f.id, []).append(f)
        self._h[f.id].sort(key=lambda x: x.version)

    def _refresh_status(self):
        for lst in self._h.values():
            for i, f in enumerate(lst):
                f.status = "active" if i == len(lst) - 1 else "superseded"

    # ── доступ ──
    def get(self, fid: str, version: int | None = None) -> Formula:
        if fid not in self._h:
            raise FormulaError(f"Формула «{fid}» отсутствует в библиотеке (безымянные формулы не допускаются)")
        lst = self._h[fid]
        if version is None:
            return lst[-1]
        for f in lst:
            if f.version == version:
                return f
        raise FormulaError(f"Формула «{fid}» версии {version} не найдена")

    def ids(self) -> list[str]:
        return sorted(self._h)

    def list(self, history: bool = False) -> list[Formula]:
        out = []
        for fid in sorted(self._h):
            out.extend(self._h[fid] if history else [self._h[fid][-1]])
        return out

    def versions(self, fid: str) -> list[Formula]:
        return list(self._h.get(fid, []))

    # ── версионирование ──
    def _validate(self, f: Formula):
        used = _names_in(f.expression)
        undefined = used - set(f.variables)
        if undefined:
            raise FormulaError(f"В выражении есть переменные без описания: {sorted(undefined)}")
        last = None
        for base, step in ((1.3, 0.41), (2.9, 0.77), (0.6, 0.13)):
            test = {k: base + step * i for i, k in enumerate(f.variables)}
            try:
                evaluate(f.expression, test)
                return
            except (FormulaError, ValueError, OverflowError) as e:   # деление на 0 / область определения — пробуем другой набор
                last = e
        raise FormulaError(f"Формула не вычисляется на тестовых наборах значений: {last}")

    def new_version(self, fid: str, changes: dict, author: str, reason: str) -> Formula:
        if not reason or not reason.strip():
            raise FormulaError("Для новой версии формулы требуется указать причину изменения")
        base = self.get(fid)
        rec = {k: v for k, v in asdict(base).items() if k != "_sources"}
        allowed = {"name", "display", "expression", "variables", "result", "description", "source_id", "clause", "scope", "verified"}
        for k, v in changes.items():
            if k in allowed:
                rec[k] = v
        rec["version"] = base.version + 1
        rec["date"] = date.today().isoformat()
        rec["author"] = author or "пользователь"
        rec["reason"] = reason
        rec["verified"] = bool(changes.get("verified", False))
        f = Formula(**rec)
        f._sources = self.sources
        self._validate(f)
        self._h[fid].append(f)
        self._user_ids.append(rec)
        self._refresh_status()
        self._save()
        return f

    def add_formula(self, rec: dict, author: str = "пользователь") -> Formula:
        if rec["id"] in self._h:
            raise FormulaError(f"Формула «{rec['id']}» уже существует — создайте новую версию")
        rec = dict(rec)
        rec.setdefault("version", 1)
        rec.setdefault("date", date.today().isoformat())
        rec.setdefault("author", author)
        rec.setdefault("verified", False)
        f = Formula(**{k: v for k, v in rec.items() if k in Formula.__dataclass_fields__})
        f._sources = self.sources
        self._validate(f)
        self._h[f.id] = [f]
        self._user_ids.append(rec)
        self._save()
        return f

    def _save(self):
        if not self.user_path:
            return
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_path.write_text(json.dumps(self._user_ids, ensure_ascii=False, indent=1), encoding="utf-8")

    def export(self) -> list[dict]:
        return [f.to_dict() for f in self.list(history=True)]
