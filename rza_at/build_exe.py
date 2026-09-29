"""Сборка однофайловой версии РЗА-АТ (PyInstaller).

    python build_exe.py              →  dist/RZA-AT.exe (Windows) / dist/RZA-AT (Linux)
    python build_exe.py --one-dir    →  каталог dist/RZA-AT/ (быстрее старт)

Ресурсы (интерфейс, нормативная база, профили терминалов, контрольные примеры) упаковываются
внутрь файла. Пользовательские данные (проекты, карты уставок, пользовательские профили)
создаются в каталоге user_data РЯДОМ с exe — его можно свободно копировать вместе с программой.

Для сборки Windows-.exe запускайте скрипт НА Windows (PyInstaller не кросс-компилирует).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Устанавливаю PyInstaller…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])

    mode = "--onedir" if "--one-dir" in sys.argv else "--onefile"
    sep = ";" if os.name == "nt" else ":"

    datas = [
        ("rza/web/static", "rza/web/static"),            # веб-интерфейс
        ("rza/normative/data", "rza/normative/data"),    # нормативная база, формулы, нормы
        ("rza/terminals/profiles", "rza/terminals/profiles"),  # профили терминалов
        ("tests/data", "tests/data"),                    # контрольные примеры 13Б
    ]
    hidden = [
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", mode,
        "--name", "RZA-AT",
        "--collect-all", "uvicorn",   # uvicorn подгружает модули динамически
    ]
    for src, dst in datas:
        cmd += ["--add-data", f"{ROOT / src}{sep}{dst}"]
    for h in hidden:
        cmd += ["--hidden-import", h]
    cmd.append(str(ROOT / "run.py"))

    print("Команда сборки:\n ", " ".join(cmd), "\n")
    subprocess.check_call(cmd, cwd=ROOT)

    out = ROOT / "dist" / ("RZA-AT.exe" if os.name == "nt" else "RZA-AT")
    if out.exists():
        mb = out.stat().st_size / 1e6 if out.is_file() else sum(f.stat().st_size for f in out.rglob("*")) / 1e6
        print(f"\n✅ Готово: {out}  ({mb:.0f} МБ)")
        print("Запуск: двойной клик (откроется браузер) либо  RZA-AT.exe 8080 --no-browser")
        print("Данные проектов: user_data/ рядом с exe (либо каталог из RZA_USER_DATA)")
    else:
        print("Проверьте вывод PyInstaller выше — файл не найден:", out)


if __name__ == "__main__":
    main()
