"""Описание полей клиента, требований кредитора и движок подбора.

Всё описано данными: чтобы добавить новый критерий, достаточно добавить
поле в CLIENT_FIELDS и требование в LENDER_CRITERIA — формы и подбор
подхватят его автоматически.
"""
import re
from datetime import date

from .refs import COLLATERAL_TYPES, LEGAL_FORMS, REGIONS, TAX_SYSTEMS

YES, NO = "yes", "no"

# ---------- Поля анкеты клиента ----------
# type: text | textarea | money | number | date | choice | tri (да/нет/неизвестно)
CLIENT_FIELDS = [
    # Компания
    dict(key="name", label="Наименование", type="text", group="Компания"),
    dict(key="inn", label="ИНН", type="text", group="Компания"),
    dict(key="ogrn", label="ОГРН / ОГРНИП", type="text", group="Компания"),
    dict(key="legal_form", label="Форма", type="choice", options=LEGAL_FORMS, group="Компания"),
    dict(key="reg_date", label="Дата регистрации", type="date", group="Компания"),
    dict(key="region", label="Регион", type="choice", options=REGIONS, group="Компания"),
    dict(key="okved", label="Основной ОКВЭД", type="text", group="Компания", hint="например 47.11"),
    dict(key="tax_system", label="Налоговый режим", type="choice", options=TAX_SYSTEMS, group="Компания"),
    dict(key="employees", label="Сотрудников, чел.", type="number", group="Компания"),
    dict(key="director", label="Руководитель", type="text", group="Компания"),
    # Финансы
    dict(key="revenue_year", label="Выручка за год, ₽", type="money", group="Финансы",
         hint="можно «45 млн», «800 тыс»"),
    dict(key="turnover_month", label="Обороты по счёту в месяц, ₽", type="money", group="Финансы"),
    dict(key="profitable", label="Прибыль по итогам года", type="tri", group="Финансы"),
    # Запрос
    dict(key="amount", label="Запрашиваемая сумма, ₽", type="money", group="Запрос"),
    dict(key="term_months", label="Срок, мес.", type="number", group="Запрос"),
    dict(key="purpose", label="Цель", type="text", group="Запрос"),
    dict(key="collateral_type", label="Залог", type="choice", options=COLLATERAL_TYPES, group="Запрос"),
    dict(key="collateral_value", label="Стоимость залога, ₽", type="money", group="Запрос"),
    dict(key="guarantor", label="Поручительство собственника", type="tri", group="Запрос"),
    dict(key="owner_age", label="Возраст собственника, лет", type="number", group="Запрос"),
    # Риски
    dict(key="overdue_now", label="Текущие просрочки по кредитам", type="tri", group="Риски"),
    dict(key="overdue_max_days", label="Макс. просрочка за год, дней", type="number", group="Риски"),
    dict(key="active_loans", label="Действующих кредитов/займов, шт.", type="number", group="Риски"),
    dict(key="tax_debt", label="Долг по налогам, ₽", type="money", group="Риски"),
    dict(key="fssp_sum", label="Исполнительные производства (ФССП), ₽", type="money", group="Риски"),
    dict(key="arbitr_defendant_sum", label="Арбитраж: иски к клиенту (активные), ₽", type="money",
         group="Риски"),
    dict(key="mass_address", label="Массовый адрес / недостоверность", type="tri", group="Риски"),
    dict(key="owner_change", label="Смена собственника/директора < 6 мес.", type="tri", group="Риски"),
    dict(key="liquidation", label="Ликвидация / прекращение деятельности", type="tri", group="Риски",
         hint="стоп-фактор"),
    dict(key="bankruptcy", label="Банкротство (ЕФРСБ)", type="tri", group="Риски", hint="стоп-фактор"),
    dict(key="notes", label="Заметки по интервью", type="textarea", group="Заметки"),
]
CLIENT_FIELD_MAP = {f["key"]: f for f in CLIENT_FIELDS}

# Стоп-факторы, общие для всех кредиторов
GLOBAL_STOPS = [
    ("bankruptcy", "Клиент найден в реестре банкротов (ЕФРСБ)"),
    ("liquidation", "Компания ликвидирована или в процессе ликвидации"),
]

# ---------- Требования кредитора ----------
# kind:
#   min / max       — число клиента должно быть >= / <= значения
#   in / not_in     — значение клиента должно входить / не входить в список
#   require_yes     — у клиента должно быть «да»
#   forbid_yes      — у клиента не должно быть «да»
#   okved_in / okved_not_in — ОКВЭД начинается / не начинается с указанных кодов
#   collateral_required, collateral_types, ltv_max — залог
LENDER_CRITERIA = [
    dict(key="legal_forms", label="Формы клиента", kind="in", field="legal_form", options=LEGAL_FORMS,
         group="Клиент", hint="пусто = любые"),
    dict(key="business_age_min", label="Срок работы бизнеса от, мес.", kind="min",
         field="business_age_months", group="Клиент"),
    dict(key="regions_allowed", label="Только регионы", kind="in", field="region", options=REGIONS,
         group="Клиент", hint="пусто = вся РФ"),
    dict(key="regions_excluded", label="Исключённые регионы", kind="not_in", field="region",
         options=REGIONS, group="Клиент"),
    dict(key="okved_allowed", label="Только ОКВЭД (коды через запятую)", kind="okved_in", field="okved",
         group="Клиент", hint="напр. 46, 47.1"),
    dict(key="okved_excluded", label="Стоп-ОКВЭД (коды через запятую)", kind="okved_not_in",
         field="okved", group="Клиент", hint="напр. 64, 92, 41.2"),
    dict(key="tax_systems", label="Налоговые режимы", kind="in", field="tax_system", options=TAX_SYSTEMS,
         group="Клиент", hint="пусто = любые"),
    dict(key="employees_min", label="Сотрудников от", kind="min", field="employees", group="Клиент"),
    dict(key="owner_age_min", label="Возраст собственника от", kind="min", field="owner_age", group="Клиент"),
    dict(key="owner_age_max", label="Возраст собственника до", kind="max", field="owner_age", group="Клиент"),

    dict(key="revenue_year_min", label="Выручка за год от, ₽", kind="min", field="revenue_year",
         money=True, group="Финансы"),
    dict(key="turnover_month_min", label="Обороты в месяц от, ₽", kind="min", field="turnover_month",
         money=True, group="Финансы"),
    dict(key="profitable_required", label="Требуется прибыль", kind="require_yes", field="profitable",
         group="Финансы"),

    dict(key="amount_min", label="Сумма от, ₽", kind="min", field="amount", money=True, group="Продукт"),
    dict(key="amount_max", label="Сумма до, ₽", kind="max", field="amount", money=True, group="Продукт"),
    dict(key="term_min", label="Срок от, мес.", kind="min", field="term_months", group="Продукт"),
    dict(key="term_max", label="Срок до, мес.", kind="max", field="term_months", group="Продукт"),

    dict(key="collateral_required", label="Залог обязателен", kind="collateral_required",
         field="collateral_type", group="Залог"),
    dict(key="collateral_types", label="Принимаемые виды залога", kind="collateral_types",
         field="collateral_type", options=COLLATERAL_TYPES[1:], group="Залог",
         hint="проверяется, если залог обязателен"),
    dict(key="ltv_max", label="Сумма не более, % от залога", kind="ltv_max", field="collateral_value",
         group="Залог"),
    dict(key="guarantor_required", label="Поручительство собственника обязательно", kind="require_yes",
         field="guarantor", group="Залог"),

    dict(key="no_overdue_now", label="Без текущих просрочек", kind="forbid_yes", field="overdue_now",
         group="Риски"),
    dict(key="overdue_max_days_max", label="Просрочки за год не более, дней", kind="max",
         field="overdue_max_days", group="Риски"),
    dict(key="active_loans_max", label="Действующих кредитов не более", kind="max", field="active_loans",
         group="Риски"),
    dict(key="tax_debt_max", label="Долг по налогам не более, ₽", kind="max", field="tax_debt", money=True,
         group="Риски", hint="0 = недопустим"),
    dict(key="fssp_max", label="ФССП не более, ₽", kind="max", field="fssp_sum", money=True, group="Риски"),
    dict(key="arbitr_max", label="Арбитраж (ответчик) не более, ₽", kind="max",
         field="arbitr_defendant_sum", money=True, group="Риски"),
    dict(key="no_mass_address", label="Без массового адреса / недостоверности", kind="forbid_yes",
         field="mass_address", group="Риски"),
    dict(key="no_owner_change", label="Без недавней смены собственника", kind="forbid_yes",
         field="owner_change", group="Риски"),
]
CRITERIA_MAP = {c["key"]: c for c in LENDER_CRITERIA}
LIST_KINDS = {"in", "not_in", "collateral_types"}
BOOL_KINDS = {"require_yes", "forbid_yes", "collateral_required"}


# ---------- Разбор и форматирование значений ----------
def parse_money(s):
    """'12,5 млн' -> 12500000.0; '800 тыс' -> 800000.0; '' -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().lower().replace(" ", "").replace(" ", "").replace("₽", "").replace("руб", "")
    if not t:
        return None
    mult = 1
    for suffix, m in (("млрд", 1e9), ("млн", 1e6), ("м", 1e6), ("тыс", 1e3), ("т", 1e3), ("к", 1e3)):
        if t.endswith(suffix):
            t, mult = t[: -len(suffix)].rstrip("."), m
            break
    t = t.replace(",", ".")
    try:
        return float(t) * mult
    except ValueError:
        return None


def parse_number(s):
    return parse_money(s)


def fmt_num(x):
    """Число без лишних нулей: 12.0 -> '12', 12.5 -> '12,5'."""
    if x is None:
        return ""
    return f"{x:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")


def fmt_money(x):
    if x is None or x == "":
        return "—"
    x = float(x)
    if abs(x) >= 1e6:
        return f"{fmt_num(round(x / 1e6, 2))} млн ₽"
    if abs(x) >= 1e3:
        return f"{fmt_num(round(x / 1e3, 1))} тыс ₽"
    return f"{fmt_num(x)} ₽"


def months_between(d1: date, d2: date) -> int:
    m = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        m -= 1
    return max(m, 0)


def fmt_age(months):
    if months is None:
        return "—"
    y, m = divmod(int(months), 12)
    parts = []
    if y:
        parts.append(f"{y} г.")
    if m or not y:
        parts.append(f"{m} мес.")
    return " ".join(parts)


def normalize_client(raw: dict, today: date = None) -> dict:
    """Приводит анкету к типам: числа -> float/None, да/нет -> 'yes'/'no'/''.
    Добавляет вычисляемое поле business_age_months."""
    today = today or date.today()
    out = {}
    for f in CLIENT_FIELDS:
        v = raw.get(f["key"], "")
        if f["type"] in ("money", "number"):
            out[f["key"]] = parse_money(v)
        elif f["type"] == "tri":
            out[f["key"]] = v if v in (YES, NO) else ""
        else:
            out[f["key"]] = (v or "").strip() if isinstance(v, str) else v
    out["business_age_months"] = None
    if out.get("reg_date"):
        try:
            out["business_age_months"] = months_between(date.fromisoformat(out["reg_date"]), today)
        except ValueError:
            pass
    # Доп. критерии (cf<id>) проходят как есть
    for k, v in raw.items():
        if k.startswith("cf"):
            out[k] = v
    return out


def fmt_client_value(field, v):
    if v is None or v == "":
        return "не указано"
    if field == "business_age_months":
        return fmt_age(v)
    f = CLIENT_FIELD_MAP.get(field, {})
    if f.get("type") == "money" or field == "collateral_value":
        return fmt_money(v)
    if f.get("type") == "tri":
        return "да" if v == YES else "нет"
    if isinstance(v, float):
        return fmt_num(v)
    return str(v)


def fmt_req_value(c, v):
    if c["kind"] in LIST_KINDS:
        return ", ".join(v)
    if c.get("money"):
        return fmt_money(v)
    if c["field"] == "business_age_months":
        return fmt_age(v)
    if isinstance(v, float):
        return fmt_num(v)
    return str(v)


def is_set(c, v):
    """Задано ли требование кредитора."""
    if c["kind"] in LIST_KINDS:
        return bool(v)
    if c["kind"] in BOOL_KINDS:
        return bool(v)
    if c["kind"] in ("okved_in", "okved_not_in"):
        return bool(okved_codes(v))
    return v is not None and v != ""


def okved_codes(text):
    return [x for x in re.split(r"[,;\s]+", text or "") if x]


def okved_match(code, prefixes):
    """ОКВЭД иерархичен: '47.11' входит в '47', '47.1', '47.11'."""
    code = (code or "").strip()
    return any(code.startswith(p.rstrip(".")) for p in prefixes)


# ---------- Проверка одного требования ----------
def check_one(c, req, client, lender_criteria):
    """Возвращает (результат, пояснение); результат: 'pass' | 'fail' | 'unknown' | 'skip'."""
    kind, field = c["kind"], c["field"]
    cv = client.get(field)
    known = cv not in (None, "")
    need = fmt_req_value(c, req)
    have = fmt_client_value(field, cv)

    if kind == "min":
        if not known:
            return "unknown", f"нужно ≥ {need}"
        return ("pass", "") if cv >= req else ("fail", f"{have} < {need}")
    if kind == "max":
        if not known:
            return "unknown", f"нужно ≤ {need}"
        return ("pass", "") if cv <= req else ("fail", f"{have} > {need}")
    if kind == "in":
        if not known:
            return "unknown", f"допустимо: {need}"
        return ("pass", "") if cv in req else ("fail", f"{have} — не входит в: {need}")
    if kind == "not_in":
        if not known:
            return "unknown", f"исключены: {need}"
        return ("pass", "") if cv not in req else ("fail", f"{have} — в списке исключений")
    if kind == "require_yes":
        if not known:
            return "unknown", "требуется «да»"
        return ("pass", "") if cv == YES else ("fail", "нет")
    if kind == "forbid_yes":
        if not known:
            return "unknown", "должно быть «нет»"
        return ("pass", "") if cv == NO else ("fail", "есть")
    if kind == "okved_in":
        if not known:
            return "unknown", f"допустимы: {req}"
        return ("pass", "") if okved_match(cv, okved_codes(req)) else ("fail", f"{cv} — не из списка {req}")
    if kind == "okved_not_in":
        if not known:
            return "unknown", f"стоп-ОКВЭД: {req}"
        return ("pass", "") if not okved_match(cv, okved_codes(req)) else ("fail", f"{cv} — стоп-ОКВЭД")
    if kind == "collateral_required":
        if not known:
            return "unknown", "нужен залог"
        return ("pass", "") if cv != "Нет" else ("fail", "залога нет")
    if kind == "collateral_types":
        # Вид залога важен, только если кредитор вообще требует залог
        if not lender_criteria.get("collateral_required", {}).get("v"):
            return "skip", ""
        if not known or cv == "Нет":
            return "skip", ""  # отсутствие залога уже учтено в collateral_required
        return ("pass", "") if cv in req else ("fail", f"{cv} — не принимается ({need})")
    if kind == "ltv_max":
        if not lender_criteria.get("collateral_required", {}).get("v"):
            return "skip", ""
        amount = client.get("amount")
        if not known or amount is None:
            return "unknown", f"сумма ≤ {need}% от залога"
        limit = cv * req / 100
        return ("pass", "") if amount <= limit else (
            "fail", f"{fmt_money(amount)} > {fmt_num(req)}% от залога ({fmt_money(limit)})")
    return "skip", ""


def check_custom(cf, req, client):
    """Доп. критерий: cf = {'id','name','kind'}; req = {'mode','v','soft'}."""
    cv = client.get(f"cf{cf['id']}", "")
    mode = req.get("mode")
    if cf["kind"] == "bool":
        if not cv:
            return "unknown", f"требуется «{'да' if mode == 'yes' else 'нет'}»"
        return ("pass", "") if cv == mode else ("fail", "да" if cv == YES else "нет")
    # число
    val, num = req.get("v"), parse_money(cv)
    if num is None:
        return "unknown", f"нужно {'≥' if mode == 'min' else '≤'} {fmt_num(val)}"
    ok = num >= val if mode == "min" else num <= val
    return ("pass", "") if ok else ("fail", f"{fmt_num(num)} {'<' if mode == 'min' else '>'} {fmt_num(val)}")


# ---------- Подбор ----------
STATUS_OK, STATUS_MAYBE, STATUS_NO = "ok", "maybe", "no"


def evaluate_lender(lender, client, custom_fields):
    """Оценивает одного кредитора. lender['criteria'] = {key: {'v':..., 'soft': bool}}."""
    crit = lender.get("criteria") or {}
    passed, failed, unknown = [], [], []

    def account(label, res, msg, soft, key):
        if res == "pass":
            passed.append(label)
        elif res == "fail":
            failed.append(dict(key=key, label=label, msg=msg, soft=soft))
        elif res == "unknown":
            unknown.append(dict(key=key, label=label, msg=msg))

    for c in LENDER_CRITERIA:
        req = crit.get(c["key"])
        if not req or not is_set(c, req.get("v")):
            continue
        res, msg = check_one(c, req["v"], client, crit)
        account(c["label"], res, msg, bool(req.get("soft")), c["key"])

    for cf in custom_fields:
        req = crit.get(f"cf{cf['id']}")
        if not req or not req.get("mode"):
            continue
        res, msg = check_custom(cf, req, client)
        account(cf["name"], res, msg, bool(req.get("soft")), f"cf{cf['id']}")

    hard_fail = any(not f["soft"] for f in failed)
    if hard_fail:
        status = STATUS_NO
    elif failed or unknown:
        status = STATUS_MAYBE
    else:
        status = STATUS_OK
    total = len(passed) + len(failed) + len(unknown)
    score = round(100 * len(passed) / total) if total else 100
    return dict(lender=lender, status=status, score=score, passed=passed, failed=failed, unknown=unknown)


def match(lenders, client, custom_fields):
    """Подбор по всем активным кредиторам.
    Возвращает dict(results, stops): results отсортированы — подходят, условно, не подходят;
    stops — стоп-факторы клиента (общие и «никто не принимает по критерию X»)."""
    active = [l for l in lenders if l.get("active", 1)]
    results = [evaluate_lender(l, client, custom_fields) for l in active]
    order = {STATUS_OK: 0, STATUS_MAYBE: 1, STATUS_NO: 2}
    results.sort(key=lambda r: (order[r["status"]], -r["score"],
                                -(parse_money(r["lender"].get("commission")) or 0),
                                r["lender"].get("name", "")))

    stops = [msg for key, msg in GLOBAL_STOPS if client.get(key) == YES]

    # Критерий, по которому жёстко отказали ВСЕ кредиторы, — тоже стоп-фактор
    if results:
        fail_sets = [{f["key"] for f in r["failed"] if not f["soft"]} for r in results]
        common = set.intersection(*fail_sets)
        for key in sorted(common):
            label = CRITERIA_MAP[key]["label"] if key in CRITERIA_MAP else key
            sample = next(f for f in results[0]["failed"] if f["key"] == key)
            stops.append(f"Ни один кредитор не принимает: {label} ({sample['msg']})")
    return dict(results=results, stops=stops)
