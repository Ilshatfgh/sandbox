"""Запуск приложения: поднимает локальный сервер, включает автобэкап и открывает браузер."""
import os
import socket
import sys
import threading
import webbrowser

import uvicorn

from app import backup
from app.main import app

HOST, PORT = "127.0.0.1", 8765  # только этот компьютер, снаружи недоступно
URL = f"http://{HOST}:{PORT}"


def already_running():
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


if __name__ == "__main__":
    if already_running():  # второй запуск — просто открываем окно браузера
        webbrowser.open(URL)
        sys.exit()
    # Консоль Windows может быть не в UTF-8 — не падаем на кириллице
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"База лидов запущена: {URL}\nНе закрывайте это окно, пока работаете с программой.")
    backup.start_scheduler()
    if not os.environ.get("LEADS_NO_BROWSER"):  # для автотеста сборки
        threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    # log_config=None: в .exe без консольных потоков стандартный логгер uvicorn может упасть
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", log_config=None)
