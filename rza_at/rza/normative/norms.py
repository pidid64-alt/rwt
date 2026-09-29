"""Нормативные значения (коэффициенты чувствительности, отстройки, возврата…) с выбором по приоритету источников.

Для каждого критерия хранится список значений из разных документов (источник, пункт, значение).
При расчёте выбирается значение из источника с наивысшим приоритетом (настраивается в проекте),
остальные значения сохраняются в трассе как альтернативы — расхождения видны инженеру.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .sources import DEFAULT_PRIORITY, SourceRegistry
from ..errors import DataError

DATA = Path(__file__).parent / "data"


@dataclass
class NormValue:
    id: str
    title: str
    value: float
    source_id: str
    clause: str
    note: str = ""
    verified: bool = False
    alternatives: list = field(default_factory=list)

    def ref(self, sources: SourceRegistry) -> str:
        return f"{sources.get(self.source_id).short}, {self.clause}"

    def to_dict(self, sources: SourceRegistry | None = None) -> dict:
        d = {"id": self.id, "title": self.title, "value": self.value, "source_id": self.source_id, "clause": self.clause,
             "note": self.note, "verified": self.verified, "alternatives": self.alternatives}
        if sources:
            d["ref"] = self.ref(sources)
        return d


class NormRegistry:
    def __init__(self, sources: SourceRegistry, user_dir: Path | None = None):
        self.sources = sources
        self._items: dict[str, dict] = {r["id"]: r for r in json.loads((DATA / "norms.json").read_text(encoding="utf-8"))}
        self.user_path = (user_dir / "norms_user.json") if user_dir else None
        if self.user_path and self.user_path.exists():
            for r in json.loads(self.user_path.read_text(encoding="utf-8")):
                self._items[r["id"]] = r

    def ids(self):
        return sorted(self._items)

    def resolve(self, norm_id: str, priority: list[str] | None = None, override: dict | None = None) -> NormValue:
        """Выбрать значение из источника с наивысшим приоритетом.

        override — {norm_id: value} значения, заданные проектом/эксплуатирующей организацией (уровень PROJECT/OPERATOR).
        """
        if norm_id not in self._items:
            raise DataError(f"Нормативный критерий «{norm_id}» не найден в базе")
        rec = self._items[norm_id]
        pr = priority or DEFAULT_PRIORITY
        cands = list(rec["values"])
        if override and norm_id in override:
            ov = override[norm_id]
            cands.append({"source": ov.get("source", "PROJECT"), "clause": ov.get("clause", "требование проекта / эксплуатирующей организации"),
                          "value": ov["value"], "note": ov.get("note", ""), "verified": False})
        cands.sort(key=lambda c: self.sources.rank(c["source"], pr))
        best = cands[0]
        alts = [{"source": c["source"], "short": self.sources.get(c["source"]).short, "clause": c["clause"], "value": c["value"]}
                for c in cands[1:]]
        return NormValue(norm_id, rec["title"], float(best["value"]), best["source"], best["clause"], best.get("note", ""),
                         bool(best.get("verified", False)), alts)

    def list(self):
        out = []
        for nid in sorted(self._items):
            rec = self._items[nid]
            out.append({"id": nid, "title": rec["title"], "values": [
                dict(v, short=self.sources.get(v["source"]).short) for v in rec["values"]]})
        return out
