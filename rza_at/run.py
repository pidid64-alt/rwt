"""Запуск веб-приложения РЗА-АТ.

Обычный режим:   python run.py [порт] [--no-browser]
Режим exe (PyInstaller): двойной клик по RZA-AT.exe — сервер поднимается и открывается браузер.

Пользовательские данные (проекты, профили терминалов, формулы) хранятся в каталоге user_data
рядом с исполняемым файлом (либо в каталоге из переменной окружения RZA_USER_DATA).
"""
import sys
import threading
import time
import webbrowser

from rza import paths


def main() -> None:
    args = [a for a in sys.argv[1:]]
    no_browser = "--no-browser" in args
    args = [a for a in args if a != "--no-browser"]
    port = 8000
    for a in args:
        if a.isdigit():
            port = int(a)

    # импорт приложения — статический (важно для упаковки PyInstaller)
    import uvicorn
    from rza.web.app import app

    if paths.FROZEN and not no_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=_open, daemon=True).start()

    print(f"РЗА-АТ: http://localhost:{port}   (данные: {paths.USER_DATA})")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
