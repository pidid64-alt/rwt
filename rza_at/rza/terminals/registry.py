"""Реестр терминалов: профили загружаются из каталогов — встроенного и пользовательского. Жёстко зашитого списка устройств нет.

Добавление устройства = сохранение JSON-профиля в user_data/terminals (через мастер или импорт); после этого оно
автоматически появляется в списке доступных терминалов. Расчётное ядро при этом не меняется.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..errors import ProfileError
from .profile import TerminalProfile

BUILTIN_DIR = Path(__file__).parent / "profiles"
USER_DIR = Path(__file__).resolve().parents[2] / "user_data" / "terminals"


class TerminalRegistry:
    def __init__(self, builtin_dir: Path = BUILTIN_DIR, user_dir: Path = USER_DIR):
        self.builtin_dir, self.user_dir = builtin_dir, user_dir
        self._profiles: dict[str, TerminalProfile] = {}
        self.reload()

    def reload(self):
        self._profiles.clear()
        for origin, d in (("builtin", self.builtin_dir), ("user", self.user_dir)):
            if not d.exists():
                continue
            for f in sorted(d.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if data.get("schema", "").startswith("rza-terminal-profile"):
                        p = TerminalProfile(data, origin, f)
                        self._profiles[p.id] = p
                except (json.JSONDecodeError, OSError):
                    continue

    def list(self) -> list[TerminalProfile]:
        return sorted(self._profiles.values(), key=lambda p: (p.data.get("manufacturer", ""), p.data.get("model", "")))

    def get(self, pid: str) -> TerminalProfile:
        if pid not in self._profiles:
            raise ProfileError(f"Профиль терминала «{pid}» не найден")
        return self._profiles[pid]

    def has(self, pid: str) -> bool:
        return pid in self._profiles

    def add(self, data: dict, overwrite: bool = False) -> TerminalProfile:
        """Добавить (или обновить) пользовательский профиль. Проверяется схема; ошибки блокируют сохранение."""
        prof = TerminalProfile(data, "user")
        prof.validate_or_raise()
        pid = prof.id
        if pid in self._profiles and self._profiles[pid].origin == "builtin":
            raise ProfileError(f"Профиль «{pid}» встроенный и не может быть перезаписан; создайте копию с другим идентификатором")
        if pid in self._profiles and not overwrite:
            raise ProfileError(f"Профиль «{pid}» уже существует")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", pid)
        path = self.user_dir / f"{safe}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        prof.path = path
        self._profiles[pid] = prof
        return prof

    def remove(self, pid: str):
        p = self.get(pid)
        if p.origin == "builtin":
            raise ProfileError("Встроенный профиль удалить нельзя")
        if p.path and p.path.exists():
            p.path.unlink()
        self._profiles.pop(pid, None)


_reg: TerminalRegistry | None = None


def terminal_registry() -> TerminalRegistry:
    global _reg
    if _reg is None:
        _reg = TerminalRegistry()
    return _reg


def reset_terminal_registry():
    global _reg
    _reg = None
