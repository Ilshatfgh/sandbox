"""Запуск программы: поднимает локальный сервер и открывает браузер.

Сервер слушает только 127.0.0.1 — с других компьютеров он недоступен.
"""
import socket
import threading
import webbrowser

from broker import __version__
from broker.db import data_dir
from broker.web import create_app

HOST, PORT = "127.0.0.1", 8765
URL = f"http://{HOST}:{PORT}/"


def port_busy():
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def main():
    if port_busy():
        # Программа уже запущена — просто открываем окно браузера
        webbrowser.open(URL)
        return
    print(f"Подбор кредитора v{__version__}")
    print(f"Данные: {data_dir()}")
    print(f"Адрес: {URL}")
    print("Не закрывайте это окно, пока работаете. Закрыли окно — программа остановлена.")
    threading.Timer(1.0, lambda: webbrowser.open(URL)).start()
    create_app().run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
