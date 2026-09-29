"""Сборка однофайловой версии РЗА-АТ (PyInstaller).

    python build_exe.py              →  dist/RZA-AT.exe (Windows) / dist/RZA-AT (Linux)
    python build_exe.py --one-dir    →  каталог dist/RZA-AT/ (быстрее старт)

Ресурсы (интерфейс, нормативная база, профили терминалов, контрольные примеры) упаковываются
внутрь файла. Пользовательские данные (проекты, карты уставок, пользовательские профили)
создаются в каталоге user_data РЯДОМ с exe — его можно свободно копировать вместе с программой.

Требования: Python 3.10.1 или новее (НЕ 3.10.0 — в нём ошибка дизассемблера dis, PyInstaller
падает с «IndexError: tuple index out of range»). Рекомендуется 3.12 / 3.13.
Для сборки Windows-.exe запускайте скрипт НА Windows (PyInstaller не кросс-компилирует).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check_python() -> None:
    """Проверка версии интерпретатора: отсекаем известные проблемные релизы."""
    v = sys.version_info[:3]
    if v == (3, 10, 0):
        sys.exit(
            "❌ Python 3.10.0 не поддерживается для сборки: в нём ошибка модуля dis\n"
            "   (IndexError: tuple index out of range при анализе байткода), из-за которой\n"
            "   PyInstaller падает на середине сборки. Исправлено в Python 3.10.1.\n"
            "   Решение: установите свежий Python (рекомендуется 3.12/3.13) с https://python.org,\n"
            "   пересоздайте окружение и повторите сборку:\n"
            "       py -m venv venv\n"
            "       venv\\Scripts\\pip install -r requirements.txt pyinstaller\n"
            "       venv\\Scripts\\python build_exe.py"
        )
    if v < (3, 10):
        sys.exit(f"❌ Требуется Python 3.10.1+ (у вас {'.'.join(map(str, v))}). Рекомендуется 3.12/3.13.")
    if v[:2] in ((3, 10), (3, 11)) and v < (3, 10, 1):
        sys.exit("❌ Требуется Python 3.10.1+ (в 3.10.0 ошибка dis, ломающая PyInstaller).")


def clean_pycache() -> None:
    """Удалить __pycache__ в дереве проекта (не в venv) — защита от .pyc чужой версии Python."""
    n = 0
    for p in ROOT.rglob("__pycache__"):
        if "venv" in p.parts or ".venv" in p.parts or "site-packages" in p.parts:
            continue
        shutil.rmtree(p, ignore_errors=True)
        n += 1
    if n:
        print(f"Очищено каталогов __pycache__: {n}")


def main() -> None:
    check_python()
    clean_pycache()

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
    try:
        subprocess.check_call(cmd, cwd=ROOT)
    except subprocess.CalledProcessError:
        print(
            "\n❌ Сборка не удалась. Частые причины:\n"
            "  1) Python 3.10.0 — ошибка dis «IndexError: tuple index out of range» → обновите Python (3.12/3.13);\n"
            "  2) скопированы __pycache__/*.pyc другой версии Python → удалите их (скрипт очищает автоматически);\n"
            "  3) не хватает памяти при сборке onefile → попробуйте:  python build_exe.py --one-dir\n"
            "После исправления удалите папки build/ и dist/, файл RZA-AT.spec и повторите."
        )
        raise SystemExit(1)

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
