"""Запуск приложения: поднимает локальный сервер, включает автобэкап и открывает браузер."""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from app import VERSION, backup
from app.main import app

HOST, PORT = "127.0.0.1", 8765  # только этот компьютер, снаружи недоступно
URL = f"http://{HOST}:{PORT}"


def already_running():
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def running_version():
    """Версия уже запущенной копии; None — старая версия без /api/version."""
    try:
        with urllib.request.urlopen(URL + "/api/version", timeout=3) as r:
            return json.load(r)["version"]
    except Exception:
        return None


def replace_running():
    """Закрыть запущенную копию другой версии. True — порт освободился."""
    try:
        urllib.request.urlopen(urllib.request.Request(URL + "/api/shutdown", method="POST"), timeout=3)
    except Exception:
        return False
    for _ in range(20):
        time.sleep(0.25)
        if not already_running():
            return True
    return False


if __name__ == "__main__":
    if already_running():
        if running_version() == VERSION:  # та же версия уже открыта — просто показываем окно
            webbrowser.open(URL)
            sys.exit()
        if not replace_running():  # старая копия без автозакрытия — просим закрыть вручную
            print("Уже запущена СТАРАЯ версия программы.\n"
                  "Закройте её чёрное окно (или Диспетчер задач -> LeadsBase.exe -> Снять задачу)\n"
                  "и запустите программу снова.")
            try:
                input("\nНажмите Enter, чтобы закрыть это окно...")
            except EOFError:  # нет консоли
                pass
            sys.exit(1)
    # Консоль Windows может быть не в UTF-8 — не падаем на кириллице
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"База лидов {VERSION} запущена: {URL}\nНе закрывайте это окно, пока работаете с программой.")
    backup.start_scheduler()
    if not os.environ.get("LEADS_NO_BROWSER"):  # для автотеста сборки
        threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    # log_config=None: в .exe без консольных потоков стандартный логгер uvicorn может упасть
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", log_config=None)
