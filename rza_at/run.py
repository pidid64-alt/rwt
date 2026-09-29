"""Запуск веб-приложения РЗА-АТ:  python run.py [порт]"""
import sys
import uvicorn

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run("rza.web.app:app", host="0.0.0.0", port=port, log_level="info")
