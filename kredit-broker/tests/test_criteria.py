from datetime import date

from broker.criteria import (STATUS_MAYBE, STATUS_NO, STATUS_OK, evaluate_lender, fmt_money, match,
                             normalize_client, okved_match, parse_money)

TODAY = date(2026, 10, 23)


def client(**kw):
    base = dict(name="ООО Тест", legal_form="ООО", reg_date="2023-01-10", region="Москва", okved="47.11",
                tax_system="УСН", revenue_year="60 млн", amount="5 млн", term_months="12",
                collateral_type="Нет", overdue_now="no", bankruptcy="no", liquidation="no")
    base.update(kw)
    return normalize_client(base, TODAY)


def lender(name="Банк", **crit):
    # crit: key=value или key=(value, soft)
    c = {}
    for k, v in crit.items():
        v, soft = v if isinstance(v, tuple) else (v, False)
        c[k] = {"v": v, "soft": soft}
    return {"id": 1, "name": name, "product": "", "active": 1, "criteria": c}


def test_parse_money():
    assert parse_money("12,5 млн") == 12_500_000
    assert parse_money("800 тыс") == 800_000
    assert parse_money("1 500 000 ₽") == 1_500_000
    assert parse_money("300к") == 300_000
    assert parse_money("") is None
    assert parse_money("abc") is None
    assert fmt_money(12_500_000) == "12,5 млн ₽"


def test_business_age():
    assert client()["business_age_months"] == 45


def test_okved():
    assert okved_match("47.11", ["47"])
    assert okved_match("47.11", ["46", "47.1"])
    assert not okved_match("46.90", ["47"])


def test_all_pass():
    r = evaluate_lender(lender(business_age_min=12.0, revenue_year_min=30e6, amount_max=10e6,
                               legal_forms=["ООО", "ИП"], no_overdue_now=True), client(), [])
    assert r["status"] == STATUS_OK and r["score"] == 100


def test_hard_fail_and_soft_fail():
    hard = evaluate_lender(lender(revenue_year_min=100e6), client(), [])
    assert hard["status"] == STATUS_NO
    assert "60 млн ₽ < 100 млн ₽" in hard["failed"][0]["msg"]
    soft = evaluate_lender(lender(revenue_year_min=(100e6, True)), client(), [])
    assert soft["status"] == STATUS_MAYBE


def test_unknown_goes_to_maybe():
    r = evaluate_lender(lender(turnover_month_min=3e6), client(), [])
    assert r["status"] == STATUS_MAYBE and r["unknown"][0]["label"].startswith("Обороты")


def test_collateral():
    l = lender(collateral_required=True, collateral_types=["Недвижимость"], ltv_max=70.0)
    assert evaluate_lender(l, client(), [])["status"] == STATUS_NO  # залога нет
    ok = client(collateral_type="Недвижимость", collateral_value="10 млн")
    assert evaluate_lender(l, ok, [])["status"] == STATUS_OK
    too_much = client(collateral_type="Недвижимость", collateral_value="6 млн")  # 5 млн > 70% от 6 млн
    assert evaluate_lender(l, too_much, [])["status"] == STATUS_NO
    wrong_type = client(collateral_type="Автотранспорт", collateral_value="10 млн")
    assert evaluate_lender(l, wrong_type, [])["status"] == STATUS_NO
    # Кредитор без обязательного залога: вид залога клиента не важен
    unsecured = lender(collateral_types=["Недвижимость"])
    assert evaluate_lender(unsecured, wrong_type, [])["status"] == STATUS_OK


def test_regions_and_okved_stop():
    assert evaluate_lender(lender(regions_excluded=["Москва"]), client(), [])["status"] == STATUS_NO
    assert evaluate_lender(lender(regions_allowed=["Москва"]), client(), [])["status"] == STATUS_OK
    assert evaluate_lender(lender(okved_excluded="47, 64"), client(), [])["status"] == STATUS_NO


def test_custom_fields():
    cfs = [{"id": 1, "name": "Госконтракты", "kind": "bool"}, {"id": 2, "name": "Лет опыта", "kind": "number"}]
    l = lender()
    l["criteria"]["cf1"] = {"mode": "yes", "soft": False}
    l["criteria"]["cf2"] = {"mode": "min", "v": 3, "soft": False}
    assert evaluate_lender(l, client(cf1="yes", cf2="5"), cfs)["status"] == STATUS_OK
    assert evaluate_lender(l, client(cf1="no", cf2="5"), cfs)["status"] == STATUS_NO
    assert evaluate_lender(l, client(cf1="yes"), cfs)["status"] == STATUS_MAYBE


def test_match_order_and_global_stops():
    lenders = [lender("Строгий", revenue_year_min=100e6), lender("Мягкий", turnover_month_min=1e6),
               lender("Простой", amount_max=10e6)]
    res = match(lenders, client(), [])
    assert [r["lender"]["name"] for r in res["results"]] == ["Простой", "Мягкий", "Строгий"]
    assert res["stops"] == []
    res = match(lenders, client(bankruptcy="yes"), [])
    assert any("банкрот" in s for s in res["stops"])


def test_stop_when_nobody_accepts_criterion():
    young = client(reg_date="2026-09-20")  # 1 месяц
    res = match([lender("A", business_age_min=3.0), lender("B", business_age_min=6.0)], young, [])
    assert any("Срок работы" in s for s in res["stops"])
    # Если хотя бы один кредитор без требования — это не общий стоп-фактор
    res = match([lender("A", business_age_min=3.0), lender("B")], young, [])
    assert res["stops"] == []


def test_inactive_lender_ignored():
    l = lender("Выкл", amount_max=1e6)
    l["active"] = 0
    assert match([l], client(), [])["results"] == []


def test_purposes():
    tender = lender("Тендер", purposes=["Тендерный заём (обеспечение заявки)"])
    assert evaluate_lender(tender, client(purpose_type="Пополнение оборотных средств"), [])["status"] == STATUS_NO
    assert evaluate_lender(tender, client(purpose_type="Тендерный заём (обеспечение заявки)"), [])["status"] == STATUS_OK
    # Цель не указана — кредитор «условно», а не отсечён
    assert evaluate_lender(tender, client(), [])["status"] == STATUS_MAYBE


def test_pct_of_month_revenue():
    l = lender(debt_load_max_pct=35.0, arbitr_max_pct=25.0)
    # выручка 60 млн/год = 5 млн/мес: лимит нагрузки 1,75 млн, арбитража 1,25 млн
    ok = client(loan_payments_month="1,5 млн", arbitr_defendant_sum="1 млн")
    assert evaluate_lender(l, ok, [])["status"] == STATUS_OK
    bad = client(loan_payments_month="2 млн", arbitr_defendant_sum="0")
    r = evaluate_lender(l, bad, [])
    assert r["status"] == STATUS_NO and "1,75 млн ₽" in r["failed"][0]["msg"]
    # обороты в месяц приоритетнее годовой выручки
    assert evaluate_lender(l, client(turnover_month="10 млн", loan_payments_month="2 млн",
                                     arbitr_defendant_sum="0"), [])["status"] == STATUS_OK
    assert evaluate_lender(l, client(revenue_year="", arbitr_defendant_sum="0",
                                     loan_payments_month="1"), [])["status"] == STATUS_MAYBE
