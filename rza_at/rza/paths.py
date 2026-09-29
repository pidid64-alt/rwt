"""Единые пути приложения: ресурсы (только чтение) и пользовательские данные (запись).

В обычном режиме ресурсы лежит в каталоге rza_at/, пользовательские данные — в rza_at/user_data/.
В режиме PyInstaller (onefile) ресурсы упакованы внутрь exe и доступны через sys._MEIPASS
(структура путей в бандле сохранена: rza/web/static, rza/normative/data, rza/terminals/profiles,
tests/data), а пользовательские данные создаются РЯДОМ с исполняемым файлом (или в каталоге,
указанном переменной окружения RZA_USER_DATA).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN: bool = bool(getattr(sys, "frozen", False))

if FROZEN:
    # каталог распакованных ресурсов внутри exe
    RES_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    # каталог самого exe — здесь живут user_data
    APP_DIR = Path(sys.executable).resolve().parent
else:
    RES_ROOT = Path(__file__).resolve().parents[1]   # rza_at/
    APP_DIR = RES_ROOT

#: пользовательские данные (проекты, профили терминалов, формулы) — всегда в перезаписываемом месте
USER_DATA = Path(os.environ.get("RZA_USER_DATA") or (APP_DIR / "user_data"))

# ресурсы (только чтение)
STATIC_DIR = RES_ROOT / "rza" / "web" / "static"
NORM_DATA = RES_ROOT / "rza" / "normative" / "data"
PROFILE_DIR = RES_ROOT / "rza" / "terminals" / "profiles"
SELFTEST_DATA = RES_ROOT / "tests" / "data"
