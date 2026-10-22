"""Тесты: нормализация, распознавание тестового скрина, API импорта/статусов/экспорта.
Запуск: python -m pytest tests"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import db, ocr

FIXTURE = Path(__file__).parent / "fixtures" / "crm_table.png"


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


def test_parse_table_screenshot():
    rows = ocr.parse_image(FIXTURE)
    got = [(r["lead_date"], r["phone"], r["name"], r["org_form"], r["amount"]) for r in rows]
    assert got == [
        ("2026-10-20 14:32", "+79161234567", "Иванов Иван Иванович", "ИП", 500000),
        ("2026-10-20 15:01", "+79035550011", "Ромашка", "ООО", 1200000),
        ("2026-10-21 09:15", "+79269998877", "Вектор Плюс", "ООО", 3500000),
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
    assert ws.max_row == 4 and ws["A1"].value == "Дата лида"
