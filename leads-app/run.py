"""Запуск приложения: поднимает локальный сервер и открывает браузер."""
import threading
import webbrowser

import uvicorn

HOST, PORT = "127.0.0.1", 8765  # только этот компьютер, снаружи недоступно

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")
