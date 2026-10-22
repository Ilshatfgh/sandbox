"""Тесты: нормализация, распознавание тестового скрина, API импорта/статусов/экспорта.
Запуск: python -m pytest tests"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import db, ocr

FIXTURE = Path(__file__).parent / "fixtures" / "crm_table.png"
FIXTURE_REAL = Path(__file__).parent / "fixtures" / "crm_real.png"  # раскладка реального скрина


@pytest.mark.parametrize("raw,exp", [
    ("79161234567", "+79161234567"), ("8 (916) 123-45-67", "+79161234567"),
    ("+7 916 123 45 67", "+79161234567"), ("9161234567", "+79161234567"), ("12345", None),
])
def test_norm_phone(raw, exp):
    assert ocr.norm_phone(raw) == exp


def test_norm_other():
    assert ocr.norm_amount("1 200 000,00 ₽") == 1200000
    assert ocr.norm_org_form("000") == "ООО"
    assert ocr.norm_org_form("ип") == "ИП"
    assert ocr.norm_date("2026-10-2014:32") == "2026-10-20 14:32"
    assert ocr.norm_date("20.10.2026") == "2026-10-20"
    assert ocr.strip_org_form("ООО \"Ромашка\"", "ООО") == "Ромашка"
    assert ocr.norm_org_form("un") == "ИП"           # мелкое «ИП» OCR читает как «un»
    assert ocr.norm_org_form("null") is None
    assert ocr.guess_org_form("U", None) == (None, None)  # серый «null» — не ошибка
    assert ocr.guess_org_form("wn", "ИП Петрова Анна") == ("ИП", None)
    assert ocr.guess_org_form(None, "Сидоров Олег Игоревич") == ("ИП", None)


def test_parse_table_screenshot():
    rows = ocr.parse_image(FIXTURE)
    got = [(r["lead_date"], r["phone"], r["name"], r["org_form"], r["amount"]) for r in rows]
    assert got == [
        ("2026-10-20 14:32", "+79161234567", "Иванов Иван Иванович", "ИП", 500000),
        ("2026-10-20 15:01", "+79035550011", "Ромашка", "ООО", 1200000),
        ("2026-10-21 09:15", "+79269998877", "Вектор Плюс", "ООО", 3500000),
    ]


def test_parse_real_layout():
    rows = ocr.parse_image(FIXTURE_REAL)
    got = [(r["lead_date"], r["phone"], r["name"], r["org_form"], r["amount"]) for r in rows]
    assert got == [
        ("2026-10-18 23:41", "+79001112233", None, None, 1000000),
        ("2026-10-18 23:36", "+79002223344", "Петрова Анна Сергеевна", "ИП", 1500000),
        ("2026-10-18 23:05", "+79003334455", "Сидоров Олег Игоревич", "ИП", 100000),
    ]


def test_free_text_fallback():
    rows = ocr.parse_free_text("Новая заявка 21.10.2026\nООО Альфа, тел 8 (999) 111-22-33, сумма 750 000 руб")
    assert len(rows) == 1
    r = rows[0]
    assert (r["phone"], r["org_form"], r["amount"], r["lead_date"]) == ("+79991112233", "ООО", 750000, "2026-10-21")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "con", db.connect(tmp_path / "t.db"))
    return TestClient(main.app)


def test_flow(client):
    # 1. Распознать скрин
    with open(FIXTURE, "rb") as f:
        res = client.post("/api/parse", files=[("files", ("a.png", f, "image/png"))]).json()
    assert len(res["rows"]) == 3 and not res["rows"][0]["dup_lead"]

    # 2. Сохранить
    rows = [{k: r[k] for k in ("lead_date", "phone", "name", "org_form", "amount")} for r in res["rows"]]
    assert client.post("/api/leads/import", json=rows).json()["added"] == 3

    # 3. Повторная загрузка — дубли найдены и пропущены
    with open(FIXTURE, "rb") as f:
        res2 = client.post("/api/parse", files=[("files", ("a.png", f, "image/png"))]).json()
    assert all(r["dup_lead"] for r in res2["rows"])
    assert client.post("/api/leads/import", json=rows).json() == {"added": 0, "updated": 0, "skipped": 3, "errors": []}

    # 4. Статусы: «Перезвонить» без даты нельзя, с датой можно
    lead = client.get("/api/leads").json()[0]
    assert client.patch(f"/api/leads/{lead['id']}", json={"status": "Перезвонить"}).status_code == 400
    r = client.patch(f"/api/leads/{lead['id']}", json={"status": "Перезвонить", "callback_at": "2020-01-01 10:00"})
    assert r.status_code == 200
    assert [l["id"] for l in client.get("/api/leads?callback_due=true").json()] == [lead["id"]]
    assert client.patch(f"/api/leads/{lead['id']}", json={"status": "Бред"}).status_code == 400

    # 5. Экспорт в Excel
    wb = load_workbook(io.BytesIO(client.get("/api/export.xlsx").content))
    ws = wb.active
    assert ws.max_row == 4 and ws["A1"].value == "Телефон" and ws["F1"].value == "Статус"


def test_report_roundtrip(client):
    """Экспорт -> оператор заполняет статусы в Excel -> загрузка -> предпросмотр -> применение."""
    rows = [{"phone": p, "name": n} for p, n in
            [("79001112233", "Альфа"), ("79002223344", "Бета"), ("79003334455", "Гамма"), ("79004445566", "Дельта")]]
    client.post("/api/leads/import", json=rows)
    wb = load_workbook(io.BytesIO(client.get("/api/export.xlsx").content))
    ws = wb.active
    by_phone = {ws.cell(r, 1).value: r for r in range(2, ws.max_row + 1)}
    ws.cell(by_phone["+79001112233"], 6).value = "Успешно"
    ws.cell(by_phone["+79002223344"], 6).value = "отказ"            # свободная формулировка
    ws.cell(by_phone["+79002223344"], 8).value = "Дорого"
    ws.cell(by_phone["+79003334455"], 6).value = "Перезвонить"      # без даты — ошибка
    ws.cell(by_phone["+79004445566"], 6).value = "Перезвонить"
    ws.cell(by_phone["+79004445566"], 7).value = "25.10.2026 15:00"
    ws.append(["+79990000000", "Нет в базе", None, None, None, "Успешно"])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)

    res = client.post("/api/report/parse", files={"file": ("r.xlsx", buf, "application/octet-stream")}).json()["rows"]
    by = {(r["lead"] or {}).get("phone") or r["raw_phone"]: r for r in res}
    assert by["+79001112233"]["changes"] == {"status": "Успешно"}
    assert by["+79002223344"]["changes"] == {"status": "Отказ клиента", "comment": "Дорого"}
    assert by["+79003334455"]["errors"] == ["Статус «Перезвонить» без даты"]
    assert by["+79004445566"]["changes"] == {"status": "Перезвонить", "callback_at": "2026-10-25 15:00"}
    assert by["+79990000000"]["errors"] == ["Клиент не найден в базе"]

    ok = [r for r in res if r["changes"] and not r["errors"]]
    assert client.post("/api/report/apply", json=[{"id": r["lead"]["id"], **r["changes"]} for r in ok]).json() == {"updated": 3}
    st = {l["phone"]: (l["status"], l["comment"]) for l in client.get("/api/leads").json()}
    assert st["+79002223344"] == ("Отказ клиента", "Дорого") and st["+79003334455"][0] == "Новый"
