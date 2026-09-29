"""Реестр нормативных источников с настраиваемым приоритетом."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

DATA = Path(__file__).parent / "data"

# Базовая структура приоритета (ТЗ, раздел 3). Настраивается в проекте.
DEFAULT_PRIORITY = [
    "KZ_LAW", "PUE_RK", "PTE_RK", "KEGOC", "OPERATOR", "PROJECT", "VENDOR", "METHOD", "B13",
]


@dataclass
class Source:
    id: str
    title: str
    short: str
    kind: str                     # law | pue | pte | operator | project | vendor | method | b13 | other
    level: str                    # ключ уровня приоритета из DEFAULT_PRIORITY
    issuer: str = ""
    version: str = ""
    date: str = ""
    url: str = ""
    verified: bool = False        # содержимое пунктов сверено с первоисточником при подготовке базы
    notes: str = ""
    sha256: str = ""

    def to_dict(self):
        return asdict(self)


class SourceRegistry:
    def __init__(self, user_dir: Path | None = None):
        self._items: dict[str, Source] = {}
        for rec in json.loads((DATA / "sources.json").read_text(encoding="utf-8")):
            self._items[rec["id"]] = Source(**rec)
        self.user_path = (user_dir / "sources_user.json") if user_dir else None
        if self.user_path and self.user_path.exists():
            for rec in json.loads(self.user_path.read_text(encoding="utf-8")):
                self._items[rec["id"]] = Source(**rec)

    def get(self, sid: str) -> Source:
        if sid not in self._items:
            return Source(id=sid, title=sid, short=sid, kind="other", level="METHOD", notes="источник не найден в реестре")
        return self._items[sid]

    def list(self) -> list[Source]:
        return list(self._items.values())

    def add(self, rec: dict) -> Source:
        s = Source(**rec)
        self._items[s.id] = s
        if self.user_path:
            user = [x.to_dict() for x in self._items.values() if x.notes.startswith("[пользовательский]")]
            self.user_path.parent.mkdir(parents=True, exist_ok=True)
            self.user_path.write_text(json.dumps(user, ensure_ascii=False, indent=1), encoding="utf-8")
        return s

    def rank(self, sid: str, priority: list[str] | None = None) -> int:
        pr = priority or DEFAULT_PRIORITY
        lvl = self.get(sid).level
        return pr.index(lvl) if lvl in pr else len(pr)
