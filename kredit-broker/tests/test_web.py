"""Сквозной сценарий через интерфейс: кредиторы -> клиент -> подбор."""
import io
import json

import pytest

from broker import checks, db, monitor


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BROKER_DATA_DIR", str(tmp_path))
    from broker.web import create_app
    app = create_app()
    app.testing = True
    return app.test_client()


def add_lender(c, **form):
    data = {"name": "Банк", "active": "1"} | form
    return c.post("/lenders/new", data=data, follow_redirects=True)


def test_full_flow(app_client):
    c = app_client
    assert c.get("/lenders").status_code == 200
    r = add_lender(c, name="Альфа", product="Беззалог", c_business_age_min="6", c_revenue_year_min="30 млн",
                   c_legal_forms=["ООО", "ИП"], commission="2")
    assert "Кредитор сохранён" in r.text
    add_lender(c, name="Бета", c_revenue_year_min="100 млн")
    add_lender(c, name="Гамма", c_turnover_month_min="2 млн", s_turnover_month_min="1")
    lenders = db.list_lenders()
    alfa = next(l for l in lenders if l["name"] == "Альфа")
    assert alfa["criteria"]["revenue_year_min"] == {"v": 30e6, "soft": False}
    assert alfa["criteria"]["legal_forms"]["v"] == ["ООО", "ИП"]

    # Форма кредитора открывается и показывает сохранённое значение
    page = c.get(f"/lenders/{alfa['id']}").text
    assert 'value="30 млн"' in page

    r = c.post("/clients/new", data={"name": "ООО Ромашка", "inn": "7707083893", "legal_form": "ООО",
                                     "reg_date": "2020-01-01", "revenue_year": "60 млн", "amount": "5 млн",
                                     "action": "match"}, follow_redirects=True)
    assert r.status_code == 200
    text = r.text
    assert "Рекомендовано направить" in text and "1. Альфа — Беззалог" in text
    assert "Гамма" in text and "уточнить" in text  # обороты неизвестны
    assert text.index("Альфа") < text.index("Бета")


def test_inn_check_flow(app_client, monkeypatch):
    def fake_run(inn):
        res = [dict(source="ЕГРЮЛ", url="", ok=True, error="", fields={}, facts=["Действующая"])]
        return res, {"name": "ООО Найдено", "reg_date": "2019-05-05", "bankruptcy": "yes"}
    monkeypatch.setattr(checks, "run_checks", fake_run)
    r = app_client.post("/clients/new", data={"inn": "7707083893", "action": "check"}, follow_redirects=True)
    assert "ООО Найдено" in r.text and "Действующая" in r.text
    cid = db.list_clients()[0]["id"]
    add_lender(app_client, name="Любой")
    r = app_client.get(f"/clients/{cid}/result")
    assert "Стоп-факторы" in r.text and "не направлять" in r.text


def test_bad_inn(app_client):
    r = app_client.post("/clients/new", data={"inn": "123", "action": "check"}, follow_redirects=True)
    assert "ИНН некорректен" in r.text


def test_custom_field_and_export_import(app_client):
    c = app_client
    c.post("/settings", data={"name": "Госконтракты", "kind": "bool"})
    cf = db.list_custom_fields()[0]
    add_lender(c, name="Гос", **{f"cf{cf['id']}_mode": "yes"})
    assert db.list_lenders()[0]["criteria"][f"cf{cf['id']}"]["mode"] == "yes"
    assert "Госконтракты" in c.get("/clients/new").text

    exported = c.get("/export").data
    payload = json.loads(exported)
    assert payload["lenders"][0]["name"] == "Гос"
    payload["lenders"][0]["rate"] = "от 15%"
    r = c.post("/import", data={"file": (io.BytesIO(json.dumps(payload).encode()), "x.json")},
               follow_redirects=True)
    assert "добавлено 0, обновлено 1" in r.text
    assert db.list_lenders()[0]["rate"] == "от 15%"


def test_attachments_copy_toggle_delete(app_client):
    c = app_client
    c.post("/lenders/new", data={"name": "Файлы", "active": "1",
                                 "files": (io.BytesIO(b"PDF"), "usloviya.pdf")}, follow_redirects=True)
    lid = db.list_lenders()[0]["id"]
    a = db.list_attachments(lid)[0]
    assert c.get(f"/files/{a['id']}").data == b"PDF"
    c.post(f"/lenders/{lid}/copy")
    assert len(db.list_lenders()) == 2
    c.post(f"/lenders/{lid}/toggle")
    assert db.get_lender(lid)["active"] == 0
    c.post(f"/lenders/{lid}/delete")
    assert db.get_lender(lid) is None and db.list_attachments(lid) == []


def test_monitor(app_client, monkeypatch):
    add_lender(app_client, name="Сайт", watch_url="https://example.com/usloviya")
    pages = iter(["<p>Ставка 18%</p>", "<p>Ставка 18%</p>", "<p>Ставка 21%</p>"])
    monkeypatch.setattr(monitor.requests, "get", lambda *a, **k: type("R", (), {"text": next(pages)}))
    assert "Снимок сохранён" in app_client.post("/monitor").text
    assert "Без изменений" in app_client.post("/monitor").text
    r = app_client.post("/monitor").text
    assert "Страница изменилась" in r and "Ставка 21%" in r


def test_pages_render(app_client):
    for url in ["/", "/clients", "/clients/new", "/lenders", "/lenders/new", "/monitor", "/settings", "/backup"]:
        assert app_client.get(url, follow_redirects=True).status_code == 200, url
