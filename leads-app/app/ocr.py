"""Распознавание скринов: картинка -> список лидов.

Основной режим — таблица CRM с заголовком: колонки находим по словам заголовка
(«Дата лида», «lead_phone», «форма организации», «запрошенная сумма», «компания лида»),
затем раскладываем слова строк по колонкам по их X-координате.
Запасной режим (нет заголовка, например скрин сообщения) — ищем телефон, сумму,
ИП/ООО регулярками и собираем один лид на каждый найденный телефон.
"""
import os
import re
import shutil
from datetime import datetime

from PIL import Image, ImageOps
import pytesseract

SCALE = 2  # увеличение картинки перед OCR: мелкий шрифт скринов так читается заметно лучше

# Ключевые слова заголовков -> поле базы. Сравниваем по началу слова, в нижнем регистре.
HEADER_KEYS = {
    "дата": "lead_date",
    "lead_phone": "phone",
    "форма": "org_form",
    "запрошенная": "amount",
    "компания": "name",
}

ORG_FORMS = ["ИП", "ООО", "АО", "ПАО", "ЗАО", "НКО", "КФХ", "САМОЗАНЯТЫЙ"]


def setup_tesseract():
    """Ищем tesseract.exe в стандартных местах Windows, если его нет в PATH."""
    if shutil.which("tesseract"):
        return
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return


setup_tesseract()


# ---------- нормализация значений ----------

def norm_phone(text):
    """Любая запись телефона -> +7XXXXXXXXXX. None, если цифр не 10/11."""
    if not text:
        return None
    d = re.sub(r"\D", "", str(text))
    if len(d) == 11 and d[0] in "78":
        d = d[1:]
    if len(d) != 10:
        return None
    return "+7" + d


def norm_amount(text):
    """«1 200 000», «1200000 ₽», «1 200 000,00» -> 1200000."""
    if text is None:
        return None
    s = str(text).replace("\u00a0", " ")
    s = re.split(r"[.,]\d{1,2}\b", s)[0]  # отбрасываем копейки
    d = re.sub(r"\D", "", s)
    return int(d) if d else None


def norm_org_form(text):
    """OCR часто путает «О» и «0»: «000», «OOO» -> «ООО»."""
    if not text:
        return None
    t = str(text).strip().upper()
    t = t.translate(str.maketrans({"0": "О", "O": "О", "A": "А", "P": "Р", "C": "С", "N": "П"}))
    for f in ORG_FORMS:
        if t.startswith(f):
            return f
    return t or None


DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m.%y"]


def norm_date(text):
    """Дата в одном из привычных форматов -> ISO. Если не разобрали — возвращаем как есть."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip()
    # OCR иногда склеивает дату и время: 2026-10-2014:32
    t = re.sub(r"^(\d{4}-\d{2}-\d{2})(\d{1,2}:\d{2})", r"\1 \2", t)
    t = re.sub(r"^(\d{2}\.\d{2}\.\d{4})(\d{1,2}:\d{2})", r"\1 \2", t)
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(t, fmt)
            return dt.strftime("%Y-%m-%d %H:%M") if "%H" in fmt else dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return t


def strip_org_form(name, org_form):
    """«ИП Иванов И.И.» -> «Иванов И.И.», форма хранится отдельно."""
    if not name:
        return name
    name = name.strip()
    if org_form:
        name = re.sub(rf"^(?:{org_form}|{org_form.replace('О', '0')}|{org_form.replace('О', 'O')})\s+",
                      "", name, flags=re.I)
    return name.strip(" \"'«»") or None


# ---------- OCR ----------

def ocr_words(img):
    """Слова с координатами (в масштабе исходной картинки)."""
    img = ImageOps.grayscale(img.convert("RGB"))
    big = img.resize((img.width * SCALE, img.height * SCALE), Image.LANCZOS)
    d = pytesseract.image_to_data(big, lang="rus+eng", config="--psm 11",
                                  output_type=pytesseract.Output.DICT)
    words = []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not t:
            continue
        words.append({
            "text": t,
            "x": d["left"][i] / SCALE, "y": d["top"][i] / SCALE,
            "w": d["width"][i] / SCALE, "h": d["height"][i] / SCALE,
            "conf": float(d["conf"][i]),
        })
    return words


def group_lines(words, tol=None):
    """Группируем слова в строки по вертикальному центру."""
    words = sorted(words, key=lambda w: w["y"] + w["h"] / 2)
    lines = []
    for w in words:
        cy = w["y"] + w["h"] / 2
        t = tol or max(6, w["h"] * 0.6)
        if lines and abs(lines[-1]["cy"] - cy) <= t:
            lines[-1]["words"].append(w)
            n = len(lines[-1]["words"])
            lines[-1]["cy"] += (cy - lines[-1]["cy"]) / n
        else:
            lines.append({"cy": cy, "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x"])
    return lines


def find_columns(words):
    """Ищем строку заголовка. Возвращаем (колонки, низ заголовка) или (None, None).

    Колонка = {"field": имя поля или None, "x": левая граница}.
    """
    anchors = [w for w in words if any(w["text"].lower().startswith(k) for k in HEADER_KEYS)]
    if not any(w["text"].lower().startswith("lead_phone") for w in anchors):
        return None, None
    phone_w = next(w for w in anchors if w["text"].lower().startswith("lead_phone"))
    # Заголовок может быть в 2 строки («форма / организации») — берём полосу ±25px
    band = [w for w in words if abs(w["y"] - phone_w["y"]) <= 25]
    band.sort(key=lambda w: w["x"])
    # Слова заголовка, стоящие рядом (зазор < 15px), — одна колонка
    cols = []
    for w in band:
        if cols and w["x"] - cols[-1]["right"] < 15:
            cols[-1]["right"] = max(cols[-1]["right"], w["x"] + w["w"])
            cols[-1]["words"].append(w["text"].lower())
        else:
            cols.append({"x": w["x"], "right": w["x"] + w["w"], "words": [w["text"].lower()]})
    result = []
    for c in cols:
        field = None
        for k, f in HEADER_KEYS.items():
            if any(t.startswith(k) for t in c["words"]):
                # «статус лида» и «инн лида» содержат «лида», но не наши ключи — пропустятся сами
                field = f
                break
        result.append({"field": field, "x": c["x"]})
    header_bottom = max(w["y"] + w["h"] for w in band)
    return result, header_bottom


def first_segment(ws, gap=25):
    """Оставляем первый непрерывный кусок ячейки.

    OCR может склеить два заголовка в одно слово («запрошеннаяинн») — тогда в колонку
    попадает и соседняя. Внутри одной ячейки слова идут плотно, большой зазор = чужая колонка.
    """
    out = [ws[0]]
    for w in ws[1:]:
        if w["x"] - (out[-1]["x"] + out[-1]["w"]) > gap:
            break
        out.append(w)
    return out


def parse_table(words):
    cols, header_bottom = find_columns(words)
    if not cols:
        return None
    body = [w for w in words if w["y"] > header_bottom + 2]
    rows = []
    for ln in group_lines(body):
        cells = {}
        for w in ln["words"]:
            # Колонка — последняя, чья левая граница левее слова (с допуском 8px)
            idx = max((i for i, c in enumerate(cols) if c["x"] - 8 <= w["x"]), default=None)
            if idx is None or not cols[idx]["field"]:
                continue
            cells.setdefault(cols[idx]["field"], []).append(w)
        if "phone" not in cells:
            continue
        cells = {f: first_segment(ws) for f, ws in cells.items()}
        rows.append(build_row({f: " ".join(w["text"] for w in ws) for f, ws in cells.items()},
                              min(w["conf"] for ws in cells.values() for w in ws)))
    return rows


def build_row(raw, min_conf=100.0):
    """Сырые строки ячеек -> нормализованная запись + предупреждения для оператора."""
    org = norm_org_form(raw.get("org_form"))
    name = raw.get("name")
    # Форма может прийти только в имени: «ООО Ромашка»
    if not org and name:
        org = norm_org_form(name.split()[0]) if norm_org_form(name.split()[0]) in ORG_FORMS else None
    row = {
        "lead_date": norm_date(raw.get("lead_date")),
        "phone": norm_phone(raw.get("phone")),
        "name": strip_org_form(name, org),
        "org_form": org if org in ORG_FORMS else (raw.get("org_form") or None),
        "amount": norm_amount(raw.get("amount")),
    }
    warnings = []
    if not row["phone"]:
        warnings.append(f"Телефон не распознан: «{raw.get('phone', '')}»")
    if not row["name"]:
        warnings.append("Нет названия компании / ФИО")
    if row["org_form"] and row["org_form"] not in ORG_FORMS:
        warnings.append(f"Непонятная форма организации: «{row['org_form']}»")
    if row["lead_date"] and not re.match(r"^\d{4}-\d{2}-\d{2}", row["lead_date"]):
        warnings.append(f"Дата не распознана: «{row['lead_date']}»")
    if min_conf < 60:
        warnings.append("Низкая уверенность распознавания — проверьте строку")
    row["warnings"] = warnings
    return row


PHONE_RE = re.compile(r"(?:\+7|8|7)?[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
AMOUNT_RE = re.compile(r"(\d[\d\s\u00a0]{3,}\d)\s*(?:₽|руб|р\.)", re.I)
ORG_RE = re.compile(r"\b(ИП|ООО|АО|ПАО|ЗАО)\b\s+([«\"]?[^\n,;]{2,60})")


def parse_free_text(text):
    """Запасной режим: свободный текст (сообщение). Один лид на каждый телефон."""
    rows = []
    phones = []
    for m in PHONE_RE.finditer(text):
        p = norm_phone(m.group())
        if p and p not in phones:
            phones.append(p)
    amount = AMOUNT_RE.search(text)
    org = ORG_RE.search(text)
    date = re.search(r"\b(\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})\b", text)
    for p in phones:
        row = build_row({
            "phone": p,
            "amount": amount.group(1) if amount else None,
            "org_form": org.group(1) if org else None,
            "name": org.group(2).strip() if org else None,
            "lead_date": date.group(1) if date else None,
        })
        row["warnings"].insert(0, "Скрин без таблицы — данные найдены по тексту, проверьте")
        rows.append(row)
    return rows


def parse_image(path_or_file):
    """Главная функция: файл картинки -> список лидов."""
    img = Image.open(path_or_file)
    words = ocr_words(img)
    rows = parse_table(words)
    if rows:
        return rows
    text = "\n".join(" ".join(w["text"] for w in ln["words"]) for ln in group_lines(words))
    return parse_free_text(text)
