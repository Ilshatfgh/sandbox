"""Автобэкап базы: копия при запуске и раз в сутки, пока программа открыта.

Файлы: data/backups/leads_ГГГГ-ММ-ДД.db, храним последние KEEP штук.
Копия делается через sqlite backup API — безопасно, даже если база сейчас открыта.
"""
import sqlite3
import threading
from datetime import date

from . import db

BACKUP_DIR = db.DATA_DIR / "backups"
KEEP = 30
INTERVAL = 6 * 3600  # проверяем каждые 6 часов; новый файл появляется раз в день


def make_backup(src=None, folder=None):
    """Сделать бэкап за сегодня (если ещё нет). Возвращает путь к файлу или None."""
    src = src or db.DB_PATH
    folder = folder or BACKUP_DIR
    if not src.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"leads_{date.today().isoformat()}.db"
    if not target.exists():
        with sqlite3.connect(src) as s, sqlite3.connect(target) as t:
            s.backup(t)
    # Чистим старые, оставляем KEEP последних (имена сортируются по дате)
    for old in sorted(folder.glob("leads_*.db"))[:-KEEP]:
        old.unlink()
    return target


def last_backup(folder=None):
    files = sorted((folder or BACKUP_DIR).glob("leads_*.db"))
    return files[-1].name if files else None


def start_scheduler():
    """Фоновый поток: бэкап сразу и затем каждые INTERVAL секунд."""
    def loop():
        while True:
            try:
                make_backup()
            except Exception as e:  # бэкап не должен ронять программу
                print("Бэкап не удался:", e)
            stop.wait(INTERVAL)
    stop = threading.Event()
    threading.Thread(target=loop, daemon=True).start()
    return stop
