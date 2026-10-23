"""Парсеры источников на подменённых ответах (без интернета)."""
from broker import checks, monitor


class FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    """Отдаёт ответы по подстроке URL."""

    def __init__(self, routes):
        self.routes = routes

    def _find(self, url):
        for part, data in self.routes.items():
            if part in url:
                if isinstance(data, Exception):
                    raise data
                return FakeResp(data)
        raise AssertionError(f"неожиданный запрос {url}")

    def get(self, url, **kw):
        return self._find(url)

    def post(self, url, **kw):
        return self._find(url + "#post")


def test_valid_inn():
    assert checks.valid_inn("7707083893")      # Сбербанк
    assert not checks.valid_inn("7707083890")
    assert checks.valid_inn("500100732259")    # корректный 12-значный
    assert not checks.valid_inn("12345")


def test_egrul_company():
    s = FakeSession({
        "egrul.nalog.ru/#post": {"t": "tok"},
        "search-result/tok": {"rows": [{"k": "ul", "c": "ООО \"РОМАШКА\"", "n": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ "
                                        "ОТВЕТСТВЕННОСТЬЮ \"РОМАШКА\"", "o": "1167746123456", "r": "14.03.2016",
                                        "g": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР: ИВАНОВ ИВАН ИВАНОВИЧ", "a": "Г. МОСКВА"}]},
    })
    r = checks.check_egrul("7707083893", s)
    assert r["ok"] and not r["error"]
    f = r["fields"]
    assert f["legal_form"] == "ООО" and f["reg_date"] == "2016-03-14"
    assert f["region"] == "Москва" and f["liquidation"] == "no"
    assert f["director"] == "Иванов Иван Иванович"


def test_egrul_liquidated_ip():
    s = FakeSession({"egrul.nalog.ru/#post": {"t": "x"},
                     "search-result/x": {"rows": [{"k": "fl", "n": "ПЕТРОВ ПЁТР", "o": "316500100012345",
                                                   "r": "01.02.2016", "e": "01.02.2020"}]}})
    f = checks.check_egrul("500100732259", s)["fields"]
    assert f["legal_form"] == "ИП" and f["liquidation"] == "yes" and f["region"] == "Московская область"


def test_egrul_error_does_not_raise():
    s = FakeSession({"egrul.nalog.ru/#post": ConnectionError("нет сети")})
    r = checks.check_egrul("7707083893", s)
    assert not r["ok"] and "нет сети" in r["error"]


def test_bo_revenue():
    s = FakeSession({
        "organizations/search": {"content": [{"id": 42, "okved2": {"id": "47.11", "name": "Торговля"}}]},
        "organizations/42/bfo": [
            {"period": "2024", "typeCorrections": [{"correction": {"financialResult": {
                "current2110": 60500, "current2400": 1200}}}]},
            {"period": "2023", "typeCorrections": [{"correction": {"financialResult": {"current2110": 1}}}]},
        ],
    })
    r = checks.check_bo("7707083893", s)
    assert r["fields"]["revenue_year"] == 60_500_000
    assert r["fields"]["profitable"] == "yes" and r["fields"]["okved"] == "47.11"


def test_bankrot_found():
    s = FakeSession({"cmpbankrupts": {"pageData": [{"inn": "7707083893", "lastLegalCase": {
        "number": "А40-1/2024", "status": {"description": "Конкурсное производство"}}}]}})
    r = checks.check_bankrot("7707083893", s)
    assert r["fields"]["bankruptcy"] == "yes" and "А40-1/2024" in r["facts"][0]


def test_merge_fields_keeps_manual_values_but_forces_stops():
    data = {"name": "Моё название", "revenue_year": "", "bankruptcy": "no"}
    changed = checks.merge_fields(data, {"name": "ООО X", "revenue_year": 60500000.0, "bankruptcy": "yes"})
    assert data["name"] == "Моё название"
    assert data["revenue_year"] == "60500000"
    assert data["bankruptcy"] == "yes" and set(changed) == {"revenue_year", "bankruptcy"}


def test_page_text_and_diff():
    t = monitor.page_text("<html><head><title>x</title></head><body><script>var a</script>"
                          "<p>Ставка  от 18%</p><div>Сумма до 10 млн</div></body></html>")
    assert t == "Ставка от 18%\nСумма до 10 млн"
    d = monitor.diff(t, t.replace("18%", "21%"))
    assert ("-", "Ставка от 18%") in d and ("+", "Ставка от 21%") in d
