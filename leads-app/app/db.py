"""Хранилище лидов: один файл SQLite в папке data/ рядом с приложением."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# В собранном .exe данные лежат рядом с программой, а не во временной папке PyInstaller
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "leads.db"

# Порядок важен: так статусы показываются в интерфейсе и в экспорте
STATUSES = ["Новый", "В работе", "Перезвонить", "Успешно", "Отказ клиента", "Не проходит по критериям"]

# Поля, которые можно менять через API (защита от записи в произвольные колонки)
EDITABLE = {"lead_date", "phone", "name", "org_form", "amount", "status", "callback_at", "comment"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_date   TEXT,               -- дата лида, ISO: 2026-10-20 или 2026-10-20 14:32
    phone       TEXT NOT NULL UNIQUE, -- нормализованный +7XXXXXXXXXX, ключ для поиска дублей
    name        TEXT,               -- компания или ФИО
    org_form    TEXT,               -- ИП / ООО / ...
    amount      INTEGER,            -- запрошенная сумма, руб.
    status      TEXT NOT NULL DEFAULT 'Новый',
    callback_at TEXT,               -- когда перезвонить (для статуса «Перезвонить»)
    comment     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def list_leads(con, status=None, q=None, callback_due=False):
    """Список лидов с фильтрами. callback_due — «Перезвонить» на сегодня и просроченные."""
    sql, args = "SELECT * FROM leads WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if q:
        # Поиск по имени и по цифрам телефона
        sql += " AND (name LIKE ? OR phone LIKE ?)"
        digits = "".join(c for c in q if c.isdigit())
        args += [f"%{q}%", f"%{digits}%" if digits else f"%{q}%"]
    if callback_due:
        sql += " AND status = 'Перезвонить' AND callback_at IS NOT NULL AND date(callback_at) <= date('now','localtime')"
    sql += " ORDER BY COALESCE(lead_date, created_at) DESC, id DESC"
    return [dict(r) for r in con.execute(sql, args)]


def find_by_phones(con, phones):
    """Словарь phone -> лид для уже существующих в базе телефонов."""
    phones = list({p for p in phones if p})
    found = {}
    for i in range(0, len(phones), 500):  # лимит параметров SQLite — большие файлы частями
        chunk = phones[i:i + 500]
        rows = con.execute(f"SELECT * FROM leads WHERE phone IN ({','.join('?' * len(chunk))})", chunk)
        found.update({r["phone"]: dict(r) for r in rows})
    return found


def insert_lead(con, row):
    ts = now()
    cur = con.execute(
        "INSERT INTO leads (lead_date, phone, name, org_form, amount, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (row.get("lead_date"), row["phone"], row.get("name"), row.get("org_form"),
         row.get("amount"), row.get("status") or "Новый", ts, ts),
    )
    return cur.lastrowid


def update_lead(con, lead_id, fields):
    fields = {k: v for k, v in fields.items() if k in EDITABLE}
    if not fields:
        return
    fields["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    con.execute(f"UPDATE leads SET {sets} WHERE id = ?", [*fields.values(), lead_id])


def stats(con):
    counts = {s: 0 for s in STATUSES}
    for r in con.execute("SELECT status, COUNT(*) c FROM leads GROUP BY status"):
        counts[r["status"]] = r["c"]
    return counts


def find_by_name(con, name):
    """Лиды с точно таким именем (без учёта регистра и лишних пробелов)."""
    key = " ".join(str(name).split()).lower()
    return [dict(r) for r in con.execute("SELECT * FROM leads") if " ".join((r["name"] or "").split()).lower() == key]


def get_by_ids(con, ids):
    """Лиды по списку id в том же порядке (порядок строк как в таблице интерфейса)."""
    if not ids:
        return []
    found = {}
    for i in range(0, len(ids), 500):  # лимит параметров SQLite
        chunk = ids[i:i + 500]
        rows = con.execute(f"SELECT * FROM leads WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        found.update({r["id"]: dict(r) for r in rows})
    return [found[i] for i in ids if i in found]
