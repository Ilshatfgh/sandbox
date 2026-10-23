"""Проверка клиента по ИНН в бесплатных открытых источниках.

Каждый источник независим: если один недоступен (сайт поменялся, капча,
нет интернета) — остальные всё равно отработают, а в отчёте будет причина.
Источники, которые без капчи не автоматизировать (картотека арбитражных
дел, ФССП), даны ссылками для ручной проверки.
"""
import re
import time
from datetime import date, datetime

import requests

from .refs import region_by_ogrn

TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def valid_inn(inn: str) -> bool:
    """Проверка контрольных цифр ИНН (10 — юрлицо, 12 — ИП/физлицо)."""
    if not re.fullmatch(r"\d{10}|\d{12}", inn or ""):
        return False
    d = [int(c) for c in inn]

    def cs(coefs):
        return sum(c * x for c, x in zip(coefs, d)) % 11 % 10

    if len(d) == 10:
        return cs([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (cs([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
            and cs([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])


def _ru_date(s):
    """'14.03.2019' -> '2019-03-14'."""
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").date().isoformat()
    except (ValueError, AttributeError):
        return ""


def _result(source, url):
    # fields — что подставить в анкету; facts — строки для отчёта
    return dict(source=source, url=url, ok=False, error="", fields={}, facts=[])


# ---------- ЕГРЮЛ / ЕГРИП ----------
def check_egrul(inn, session=None):
    s = session or requests.Session()
    r = _result("ЕГРЮЛ/ЕГРИП (ФНС)", "https://egrul.nalog.ru/")
    try:
        resp = s.post("https://egrul.nalog.ru/", data={"query": inn, "vyp3CaptchaToken": "", "page": ""},
                      headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        token = resp.json().get("t")
        if not token:
            raise RuntimeError("сайт запросил капчу — проверьте вручную")
        rows = None
        for _ in range(10):  # результат готовится асинхронно
            res = s.get(f"https://egrul.nalog.ru/search-result/{token}", headers=HEADERS, timeout=TIMEOUT).json()
            if res.get("status") != "wait":
                rows = res.get("rows") or []
                break
            time.sleep(1)
        if rows is None:
            raise RuntimeError("ФНС не успела ответить, повторите позже")
        if not rows:
            r["ok"] = True
            r["facts"].append("Не найдено в ЕГРЮЛ/ЕГРИП")
            return r
        row = rows[0]
        f = r["fields"]
        is_ip = row.get("k") == "fl"
        f["name"] = ("ИП " + row.get("n", "")) if is_ip else (row.get("c") or row.get("n", ""))
        f["ogrn"] = row.get("o", "")
        f["reg_date"] = _ru_date(row.get("r", ""))
        name_up = row.get("n", "").upper()
        if is_ip:
            f["legal_form"] = "ИП"
        elif "ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ" in name_up or name_up.startswith("ООО"):
            f["legal_form"] = "ООО"
        elif "АКЦИОНЕРНОЕ" in name_up or re.match(r"^(П?АО|ЗАО)\b", name_up):
            f["legal_form"] = "АО"
        region = region_by_ogrn(f["ogrn"])
        if region:
            f["region"] = region
        if row.get("g"):
            f["director"] = row["g"].split(":", 1)[-1].strip().title()
        if row.get("e"):
            f["liquidation"] = "yes"
            r["facts"].append(f"⛔ Деятельность прекращена {row['e']}")
        else:
            f["liquidation"] = "no"
            r["facts"].append("Действующая")
        r["facts"].append(f"Зарегистрирована {row.get('r', '?')}, ОГРН {f['ogrn']}")
        if row.get("a"):
            r["facts"].append(f"Адрес: {row['a']}")
        if row.get("g"):
            r["facts"].append(row["g"])
        r["ok"] = True
    except Exception as e:  # noqa: BLE001 — источник не должен ронять проверку
        r["error"] = str(e)
    return r


# ---------- ГИР БО: бухотчётность (выручка, прибыль) ----------
def _find_values(obj, keys, acc):
    """Рекурсивно ищет в JSON ключи вида current2110 / current2400."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (int, float)) and k not in acc:
                acc[k] = v
            else:
                _find_values(v, keys, acc)
    elif isinstance(obj, list):
        for x in obj:
            _find_values(x, keys, acc)
    return acc


def check_bo(inn, session=None):
    s = session or requests.Session()
    r = _result("ГИР БО (бухотчётность)", f"https://bo.nalog.ru/search?query={inn}")
    if len(inn) != 10:
        r["ok"] = True
        r["facts"].append("ИП не сдают бухотчётность — выручку уточните у клиента")
        return r
    try:
        h = HEADERS | {"Referer": "https://bo.nalog.ru/"}
        found = s.get("https://bo.nalog.ru/advanced-search/organizations/search",
                      params={"query": inn, "page": 0}, headers=h, timeout=TIMEOUT).json()
        content = found.get("content") or []
        if not content:
            r["ok"] = True
            r["facts"].append("Отчётность не найдена")
            return r
        org = content[0]
        r["url"] = f"https://bo.nalog.ru/organizations-card/{org['id']}"
        okved = org.get("okved2") or {}
        if isinstance(okved, dict) and okved.get("id"):
            r["fields"]["okved"] = okved["id"]
            r["facts"].append(f"ОКВЭД {okved['id']} {okved.get('name', '')}".strip())
        reports = s.get(f"https://bo.nalog.ru/nbo/organizations/{org['id']}/bfo/", headers=h,
                        timeout=TIMEOUT).json()
        # Берём самый свежий период
        reports = sorted(reports, key=lambda x: str(x.get("period", "")), reverse=True)
        if not reports:
            r["ok"] = True
            r["facts"].append("Отчётность не найдена")
            return r
        last = reports[0]
        vals = _find_values(last, {"current2110", "current2400"}, {})
        period = last.get("period", "?")
        if "current2110" in vals:  # в отчётности — тыс. руб.
            r["fields"]["revenue_year"] = vals["current2110"] * 1000
            r["facts"].append(f"Выручка за {period}: {vals['current2110'] / 1000:,.1f} млн ₽".replace(",", " "))
        if "current2400" in vals:
            profit = vals["current2400"]
            r["fields"]["profitable"] = "yes" if profit > 0 else "no"
            r["facts"].append(f"Чистая прибыль за {period}: {profit / 1000:,.1f} млн ₽".replace(",", " "))
        r["ok"] = True
    except Exception as e:  # noqa: BLE001
        r["error"] = str(e)
    return r


# ---------- ЕФРСБ: реестр банкротов ----------
def check_bankrot(inn, session=None):
    s = session or requests.Session()
    r = _result("ЕФРСБ (банкротство)", f"https://bankrot.fedresurs.ru/bankrupts?searchString={inn}")
    try:
        h = HEADERS | {"Referer": "https://bankrot.fedresurs.ru/"}
        # Для ИП ищем и среди компаний, и среди физлиц
        kinds = ["cmpbankrupts"] if len(inn) == 10 else ["prsnbankrupts", "cmpbankrupts"]
        hits = []
        for kind in kinds:
            data = s.get(f"https://bankrot.fedresurs.ru/backend/{kind}",
                         params={"searchString": inn, "isActiveLegalCase": "null", "limit": 15, "offset": 0},
                         headers=h, timeout=TIMEOUT).json()
            hits += [x for x in data.get("pageData") or [] if str(x.get("inn", inn)) == inn]
        if hits:
            r["fields"]["bankruptcy"] = "yes"
            for x in hits:
                case = x.get("lastLegalCase") or {}
                status = (case.get("status") or {}).get("description", "")
                r["facts"].append(f"⛔ Найден в ЕФРСБ: дело {case.get('number', '?')} {status}".strip())
        else:
            r["fields"]["bankruptcy"] = "no"
            r["facts"].append("Не найден")
        r["ok"] = True
    except Exception as e:  # noqa: BLE001
        r["error"] = str(e)
    return r


# ---------- Ссылки для ручной проверки ----------
def manual_links(inn):
    return [
        ("Прозрачный бизнес ФНС (долги, массовый адрес, режим)",
         f"https://pb.nalog.ru/search.html#t=1&mode=search-all&queryAll={inn}"),
        ("Картотека арбитражных дел (вставьте ИНН)", "https://kad.arbitr.ru/"),
        ("ФССП — исполнительные производства", "https://fssp.gov.ru/iss/ip/"),
        ("Rusprofile (сводка)", f"https://www.rusprofile.ru/search?query={inn}"),
        ("Checko (арбитраж, ФССП, финансы)", f"https://checko.ru/search?query={inn}"),
        ("Реестр МСП", "https://rmsp.nalog.ru/search.html"),
        ("Реестр недобросовестных поставщиков",
         f"https://zakupki.gov.ru/epz/dishonestsupplier/search/results.html?searchString={inn}"),
    ]


SOURCES = [check_egrul, check_bo, check_bankrot]


def run_checks(inn):
    """Все автоматические проверки. Возвращает (список результатов, поля для анкеты)."""
    inn = (inn or "").strip()
    session = requests.Session()
    results, fields = [], {}
    for src in SOURCES:
        res = src(inn, session)
        res["checked_at"] = date.today().isoformat()
        results.append(res)
        for k, v in res["fields"].items():
            fields.setdefault(k, v)
    return results, fields


def merge_fields(data: dict, found: dict):
    """Подставляет найденное в анкету. Пустые поля заполняются; стоп-флаги «да»
    (банкротство, ликвидация) перезаписываются всегда — их пропуск опаснее."""
    changed = []
    for k, v in found.items():
        if v in ("", None):
            continue
        if isinstance(v, float):  # в анкете значения хранятся строками
            v = str(int(v)) if v.is_integer() else str(v)
        if not data.get(k) or (k in ("bankruptcy", "liquidation") and v == "yes"):
            if data.get(k) != v:
                changed.append(k)
            data[k] = v
    return changed
