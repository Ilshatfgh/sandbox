"""Хранилище: один файл SQLite в папке data рядом с программой."""
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime

# Справочные поля кредитора (в подборе не участвуют, показываются в результатах)
LENDER_INFO = [
    dict(key="name", label="Кредитор", type="text"),
    dict(key="product", label="Продукт / программа", type="text", hint="напр. «Беззалоговый оборотный»"),
    dict(key="rate", label="Ставка", type="text", hint="напр. «от 18% годовых»"),
    dict(key="commission", label="Вознаграждение брокеру, %", type="text"),
    dict(key="decision_time", label="Срок решения", type="text"),
    dict(key="website", label="Сайт", type="text"),
    dict(key="watch_url", label="Страница с условиями (для отслеживания)", type="text"),
    dict(key="contacts", label="Контакты менеджера", type="textarea"),
    dict(key="docs", label="Документы для заявки", type="textarea"),
    dict(key="notes", label="Заметки", type="textarea"),
]
INFO_KEYS = [f["key"] for f in LENDER_INFO]

SCHEMA = """
CREATE TABLE IF NOT EXISTS lenders (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL, product TEXT DEFAULT '', rate TEXT DEFAULT '', commission TEXT DEFAULT '',
    decision_time TEXT DEFAULT '', website TEXT DEFAULT '', watch_url TEXT DEFAULT '',
    contacts TEXT DEFAULT '', docs TEXT DEFAULT '', notes TEXT DEFAULT '',
    active INTEGER DEFAULT 1, criteria TEXT DEFAULT '{}', updated_at TEXT
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY, name TEXT DEFAULT '', inn TEXT DEFAULT '',
    data TEXT DEFAULT '{}', checks TEXT DEFAULT '[]', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS custom_fields (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL  -- bool | number
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY, lender_id INTEGER, filename TEXT, stored TEXT, uploaded_at TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    lender_id INTEGER PRIMARY KEY, url TEXT, text TEXT, prev_text TEXT, hash TEXT,
    checked_at TEXT, changed_at TEXT
);
"""


def data_dir():
    """Папка данных: BROKER_DATA_DIR, иначе data рядом с .exe / с проектом."""
    if os.environ.get("BROKER_DATA_DIR"):
        d = os.environ["BROKER_DATA_DIR"]
    elif getattr(sys, "frozen", False):
        d = os.path.join(os.path.dirname(sys.executable), "data")
    else:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(os.path.join(d, "files"), exist_ok=True)
    return d


def db_path():
    return os.path.join(data_dir(), "broker.db")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@contextmanager
def connect():
    """Соединение на одну операцию: коммит при успехе и обязательное закрытие файла."""
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


# ---------- Кредиторы ----------
def _lender(row):
    d = dict(row)
    d["criteria"] = json.loads(d.get("criteria") or "{}")
    return d


def list_lenders():
    with connect() as con:
        rows = con.execute("SELECT * FROM lenders ORDER BY active DESC, name, product").fetchall()
        return [_lender(r) for r in rows]


def get_lender(lid):
    with connect() as con:
        r = con.execute("SELECT * FROM lenders WHERE id=?", (lid,)).fetchone()
        return _lender(r) if r else None


def save_lender(info: dict, criteria: dict, active=1, lid=None):
    vals = [info.get(k, "") or "" for k in INFO_KEYS]
    with connect() as con:
        if lid:
            sets = ", ".join(f"{k}=?" for k in INFO_KEYS)
            con.execute(f"UPDATE lenders SET {sets}, active=?, criteria=?, updated_at=? WHERE id=?",
                        vals + [active, json.dumps(criteria, ensure_ascii=False), now(), lid])
            return lid
        cols = ", ".join(INFO_KEYS)
        qs = ", ".join("?" * len(INFO_KEYS))
        cur = con.execute(f"INSERT INTO lenders ({cols}, active, criteria, updated_at) VALUES ({qs}, ?, ?, ?)",
                          vals + [active, json.dumps(criteria, ensure_ascii=False), now()])
        return cur.lastrowid


def set_lender_active(lid, active):
    with connect() as con:
        con.execute("UPDATE lenders SET active=? WHERE id=?", (1 if active else 0, lid))


def delete_lender(lid):
    for a in list_attachments(lid):
        delete_attachment(a["id"])
    with connect() as con:
        con.execute("DELETE FROM lenders WHERE id=?", (lid,))
        con.execute("DELETE FROM snapshots WHERE lender_id=?", (lid,))


# ---------- Вложения (скриншоты, PDF, Word с условиями) ----------
def list_attachments(lid):
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM attachments WHERE lender_id=? ORDER BY id", (lid,)).fetchall()]


def add_attachment(lid, filename, stored):
    with connect() as con:
        con.execute("INSERT INTO attachments (lender_id, filename, stored, uploaded_at) VALUES (?,?,?,?)",
                    (lid, filename, stored, now()))


def get_attachment(aid):
    with connect() as con:
        r = con.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None


def delete_attachment(aid):
    a = get_attachment(aid)
    if not a:
        return
    path = os.path.join(data_dir(), "files", a["stored"])
    if os.path.exists(path):
        os.remove(path)
    with connect() as con:
        con.execute("DELETE FROM attachments WHERE id=?", (aid,))


# ---------- Клиенты ----------
def _client(row):
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    d["checks"] = json.loads(d.get("checks") or "[]")
    return d


def list_clients(q=""):
    with connect() as con:
        if q:
            like = f"%{q}%"
            rows = con.execute("SELECT * FROM clients WHERE name LIKE ? OR inn LIKE ? ORDER BY id DESC",
                               (like, like)).fetchall()
        else:
            rows = con.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
        return [_client(r) for r in rows]


def get_client(cid):
    with connect() as con:
        r = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
        return _client(r) if r else None


def save_client(data: dict, checks=None, cid=None):
    name, inn = data.get("name", ""), data.get("inn", "")
    payload = json.dumps(data, ensure_ascii=False)
    with connect() as con:
        if cid:
            if checks is None:
                con.execute("UPDATE clients SET name=?, inn=?, data=?, updated_at=? WHERE id=?",
                            (name, inn, payload, now(), cid))
            else:
                con.execute("UPDATE clients SET name=?, inn=?, data=?, checks=?, updated_at=? WHERE id=?",
                            (name, inn, payload, json.dumps(checks, ensure_ascii=False), now(), cid))
            return cid
        cur = con.execute(
            "INSERT INTO clients (name, inn, data, checks, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (name, inn, payload, json.dumps(checks or [], ensure_ascii=False), now(), now()))
        return cur.lastrowid


def delete_client(cid):
    with connect() as con:
        con.execute("DELETE FROM clients WHERE id=?", (cid,))


# ---------- Доп. критерии ----------
def list_custom_fields():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM custom_fields ORDER BY id").fetchall()]


def add_custom_field(name, kind):
    with connect() as con:
        return con.execute("INSERT INTO custom_fields (name, kind) VALUES (?, ?)", (name, kind)).lastrowid


def delete_custom_field(fid):
    with connect() as con:
        con.execute("DELETE FROM custom_fields WHERE id=?", (fid,))


# ---------- Снимки страниц кредиторов ----------
def get_snapshot(lid):
    with connect() as con:
        r = con.execute("SELECT * FROM snapshots WHERE lender_id=?", (lid,)).fetchone()
        return dict(r) if r else None


def save_snapshot(lid, url, text, h, changed):
    old = get_snapshot(lid)
    with connect() as con:
        if old:
            if changed:
                con.execute("UPDATE snapshots SET url=?, prev_text=?, text=?, hash=?, checked_at=?, changed_at=?"
                            " WHERE lender_id=?", (url, old["text"], text, h, now(), now(), lid))
            else:
                con.execute("UPDATE snapshots SET url=?, checked_at=? WHERE lender_id=?", (url, now(), lid))
        else:
            con.execute("INSERT INTO snapshots (lender_id, url, text, prev_text, hash, checked_at, changed_at)"
                        " VALUES (?,?,?,?,?,?,?)", (lid, url, text, "", h, now(), None))


# ---------- Экспорт / импорт ----------
def export_all():
    """Кредиторы и доп. критерии — для переноса на другой ПК / коллеге."""
    cfs = list_custom_fields()
    lenders = []
    for l in list_lenders():
        lenders.append({k: l[k] for k in INFO_KEYS} | {"active": l["active"], "criteria": l["criteria"]})
    return {"version": 1, "custom_fields": cfs, "lenders": lenders}


def import_all(payload: dict):
    """Добавляет/обновляет кредиторов по паре (name, product). Доп. критерии сопоставляются по имени."""
    existing_cf = {(c["name"], c["kind"]): c["id"] for c in list_custom_fields()}
    remap = {}
    for cf in payload.get("custom_fields", []):
        key = (cf["name"], cf["kind"])
        if key not in existing_cf:
            existing_cf[key] = add_custom_field(cf["name"], cf["kind"])
        remap[f"cf{cf['id']}"] = f"cf{existing_cf[key]}"
    by_name = {(l["name"], l["product"]): l["id"] for l in list_lenders()}
    added = updated = 0
    for l in payload.get("lenders", []):
        crit = {remap.get(k, k): v for k, v in (l.get("criteria") or {}).items()}
        lid = by_name.get((l.get("name", ""), l.get("product", "")))
        save_lender(l, crit, l.get("active", 1), lid)
        if lid:
            updated += 1
        else:
            added += 1
    return added, updated
