"""Распознавание скринов: картинка -> список лидов.

Основной режим — любая таблица с заголовком (CRM, Excel): строку заголовка узнаём по
синонимам колонок («Телефон», «lead_phone», «ФИО», «Компания», «Сумма», «Дата», «Форма»…),
границы колонок берём по реальному расположению текста в строках (работает при любом
выравнивании), затем раскладываем слова по колонкам.
Запасной режим (нет заголовка, например скрин сообщения) — ищем телефон, сумму,
ИП/ООО регулярками; если телефоны в разных строках — каждая строка отдельный лид.
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

SCALE = 3  # увеличение картинки перед OCR: мелкий шрифт скринов так читается заметно лучше

# Синонимы заголовков -> поле базы. Сравниваем по началу слова, в нижнем регистре.
# Порядок важен: первое совпадение решает (у «форма организации» — форма, не компания).
HEADER_SYNONYMS = [
    ("phone", ["lead_phone", "телефон", "тел.", "тел", "phone", "мобильный", "моб."]),
    ("lead_date", ["дата", "date", "создан"]),
    ("org_form", ["форма", "опф", "орг.форма"]),
    ("amount", ["запрошенная", "сумма", "сумм", "amount"]),
    ("name", ["компания", "фио", "клиент", "наименование", "название", "контрагент", "имя", "name"]),
]


def header_field(text):
    t = text.lower().strip(" :#\"'«»")
    for field, keys in HEADER_SYNONYMS:
        if any(t.startswith(k) for k in keys):
            return field
    return None


ORG_FORMS = ["ИП", "ООО", "АО", "ПАО", "ЗАО", "НКО", "КФХ", "САМОЗАНЯТЫЙ"]


class TesseractNotFound(RuntimeError):
    pass


TESSERACT_CMD = None  # путь к tesseract.exe; None — не найден


def ascii_copy(folder):
    """Tesseract на Windows падает на русских буквах в пути («Illegal byte sequence»).
    Если папка программы такая — один раз копируем Tesseract в C:\\ProgramData\\LeadsBase."""
    if str(folder).isascii():
        return folder
    for base in (os.environ.get("ProgramData", r"C:\ProgramData"), r"C:\LeadsBaseOCR"):
        target = Path(base) / "LeadsBase" / "tesseract"
        if not str(target).isascii():
            continue
        try:
            # Копируем, если копии нет или она от другой сборки (сверяем размеры файлов)
            same = target.exists() and all(
                (target / f.relative_to(folder)).exists()
                and (target / f.relative_to(folder)).stat().st_size == f.stat().st_size
                for f in folder.rglob("*") if f.is_file())
            if not same:
                shutil.copytree(folder, target, dirs_exist_ok=True)
            return target
        except OSError:
            continue
    return folder


def setup_tesseract():
    """Ищем Tesseract: рядом с .exe (сборка) -> PATH -> стандартные папки Windows."""
    global TESSERACT_CMD
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "tesseract"
        if (bundled / "tesseract.exe").exists():
            TESSERACT_CMD = str(ascii_copy(bundled) / "tesseract.exe")
            return
    TESSERACT_CMD = shutil.which("tesseract")
    if TESSERACT_CMD:
        return
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
        if os.path.exists(p):
            TESSERACT_CMD = p
            return


def run_tesseract(img):
    """Распознать картинку: передаём PNG через stdin, читаем TSV из stdout.
    Без временных файлов — русские буквы в имени пользователя Windows (папка TEMP) не мешают."""
    if not TESSERACT_CMD:
        raise TesseractNotFound("Tesseract не найден")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    tess_dir = Path(TESSERACT_CMD).parent
    data_dir = tess_dir / "tessdata"
    cmd = [TESSERACT_CMD, "stdin", "stdout", "-l", "rus+eng", "--psm", "11", "-c", "tessedit_create_tsv=1"]
    if data_dir.exists():
        cmd[1:1] = ["--tessdata-dir", str(data_dir)]
    res = subprocess.run(cmd, input=buf.getvalue(), capture_output=True, cwd=str(tess_dir),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if res.returncode != 0:
        raise RuntimeError("Ошибка распознавания: " + res.stderr.decode("utf-8", "replace").strip()[-300:])
    return list(csv.DictReader(io.StringIO(res.stdout.decode("utf-8", "replace")),
                               delimiter="\t", quoting=csv.QUOTE_NONE))


setup_tesseract()


# ---------- нормализация значений ----------

def norm_phone(text):
    """Любая запись телефона -> +7XXXXXXXXXX. None, если цифр не 10/11."""
    if not text:
        return None
    d = re.sub(r"\D", "", str(text))
    if len(d) > 11:
        # Мусор слева (уголок Excel прочитан как «7.») — номер в конце строки
        d = d[-11:] if d[-11] in "78" else d[-10:]
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


EMPTY = {"null", "none", "nan", "-", "—", "–"}


def clean(text):
    """Пустые значения CRM («null», «—») -> None."""
    if text is None:
        return None
    t = str(text).strip()
    return None if not t or t.lower() in EMPTY else t


def norm_org_form(text):
    """OCR путает похожие буквы: «000», «OOO» -> «ООО», «UN», «un» -> «ИП»."""
    text = clean(text)
    if not text:
        return None
    t = text.upper()
    t = t.translate(str.maketrans({"0": "О", "O": "О", "A": "А", "P": "Р", "C": "С", "N": "П", "U": "И"}))
    for f in ORG_FORMS:
        if t.startswith(f):
            return f
    return t or None


DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m.%y"]


MONTHS = [("янв", 1), ("фев", 2), ("мар", 3), ("апр", 4), ("ма", 5), ("июн", 6), ("июл", 7),
          ("авг", 8), ("сен", 9), ("окт", 10), ("ноя", 11), ("дек", 12)]  # «мар» раньше «ма» (май/мая)
MONTH_DATE_RE = re.compile(r"^(\d{1,2})[.\s-]*([а-яё]{3,})\.?(?:[.\s-]*(\d{2,4}))?", re.I)


def month_name_date(t):
    """«12.янв», «12 января 2026» -> ISO. Без года: текущий год (или прошлый, если дата в будущем)."""
    m = MONTH_DATE_RE.match(t)
    if not m:
        return None
    mon = next((n for k, n in MONTHS if m.group(2).lower().startswith(k)), None)
    if not mon:
        return None
    today = datetime.now()
    year = int(m.group(3)) if m.group(3) else today.year
    if year < 100:
        year += 2000
    try:
        dt = datetime(year, mon, int(m.group(1)))
    except ValueError:
        return None
    if not m.group(3) and dt > today:
        dt = dt.replace(year=year - 1)
    return dt.strftime("%Y-%m-%d")


def norm_date(text):
    """Дата в одном из привычных форматов -> ISO. Если не разобрали — возвращаем как есть."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip()
    if month_name_date(t):
        return month_name_date(t)
    t = re.sub(r"^(\d{2})[ ,](\d{2})[ ,.](\d{4})", r"\1.\2.\3", t)  # OCR потерял точки: 05 07 2026
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
    name = clean(name)
    if not name:
        return None
    parts = name.split(maxsplit=1)
    if len(parts) == 2 and (norm_org_form(parts[0]) in ORG_FORMS or garbled_ip_prefix(name)):
        name = parts[1]
    # Кавычки любого вида и «*» (так OCR иногда читает закрывающую кавычку) по краям — убираем
    return name.strip(" \"'«»“”„*") or None


# ---------- OCR ----------

def ocr_words(img):
    """Слова с координатами (в масштабе исходной картинки)."""
    img = ImageOps.grayscale(img.convert("RGB"))
    big = img.resize((img.width * SCALE, img.height * SCALE), Image.LANCZOS)
    words = []
    for r in run_tesseract(big):
        t = (r.get("text") or "").strip()
        if not t or r.get("conf") in (None, "-1"):
            continue
        words.append({
            "text": t,
            "x": int(r["left"]) / SCALE, "y": int(r["top"]) / SCALE,
            "w": int(r["width"]) / SCALE, "h": int(r["height"]) / SCALE,
            "conf": float(r["conf"]),
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


def has_digits(line, n=3):
    return any(sum(ch.isdigit() for ch in w["text"]) >= n for w in line["words"])


def find_header(lines):
    """Индексы строк заголовка: строка с колонкой телефона и ещё хотя бы одной известной колонкой
    + соседние строки без цифр (двухстрочные заголовки «форма / организации»)."""
    for i, ln in enumerate(lines):
        fields = {header_field(w["text"]) for w in ln["words"]} - {None}
        if "phone" in fields and len(fields) >= 2:
            h = sorted(w["h"] for w in ln["words"])[len(ln["words"]) // 2]
            idx = [i]
            for j in (i - 1, i + 1):
                if 0 <= j < len(lines) and not has_digits(lines[j]) and abs(lines[j]["cy"] - ln["cy"]) < 2.2 * h:
                    idx.append(j)
            return sorted(idx)
    return None


def data_segments(words, pad=4):
    """Колонки данных по факту: склеиваем горизонтальные отрезки слов всех строк.
    Промежутки, где нет ни одного слова, — границы колонок (любое выравнивание текста)."""
    segs = []
    for a, b in sorted((w["x"] - pad, w["x"] + w["w"] + pad) for w in words):
        if segs and a <= segs[-1][1]:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return segs


def split_point(words, lo, hi, fallback):
    """Граница между двумя колонками внутри отрезка: самый широкий промежуток между словами
    данных на участке между центрами заголовков. Нет промежутка — левый край второго заголовка."""
    edges = sorted((w["x"], w["x"] + w["w"]) for w in words if w["x"] + w["w"] > lo and w["x"] < hi)
    best, cover = None, None
    for a, b in edges:
        if cover is not None and a > cover and lo <= (a + cover) / 2 <= hi:
            if not best or a - cover > best[1] - best[0]:
                best = (cover, a)
        cover = b if cover is None else max(cover, b)
    return (best[0] + best[1]) / 2 if best else fallback


def assign_columns(segs, header_words, data_words):
    """Каждому отрезку данных — поле по словам заголовка над ним (центр слова внутри отрезка).
    Два разных поля над одним отрезком (колонки вплотную) — делим по промежутку в данных.
    Над отрезком нет слов заголовка — берём слово с наибольшим перекрытием."""
    out = []  # (x_от, x_до, поле)
    center = lambda w: w["x"] + w["w"] / 2
    for a, b in segs:
        above = sorted((w for w in header_words if a <= center(w) <= b), key=lambda w: w["x"])
        if not above:
            best = max(header_words, key=lambda w: min(b, w["x"] + w["w"]) - max(a, w["x"]), default=None)
            if best and min(b, best["x"] + best["w"]) - max(a, best["x"]) > 0:
                above = [best]
        marks = []  # (первое слово заголовка, поле) — по одному на каждое новое поле слева направо
        for w in above:
            f = header_field(w["text"])
            if f and (not marks or marks[-1][1] != f):
                marks.append((w, f))
        if not marks:
            out.append((a, b, None))
            continue
        bounds = [a]
        for (pw, _), (nw, _) in zip(marks, marks[1:]):
            bounds.append(split_point(data_words, center(pw), center(nw), nw["x"] - 4))
        bounds.append(b)
        out += [(bounds[k], bounds[k + 1], f) for k, (_, f) in enumerate(marks)]
    return out


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


TIME_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")


def parse_table(words):
    lines = group_lines(words)
    hdr = find_header(lines)
    if not hdr:
        return None
    header_words = [w for i in hdr for w in lines[i]["words"]]
    body_lines = lines[max(hdr) + 1:]
    body_words = [w for ln in body_lines for w in ln["words"]]
    segs = assign_columns(data_segments(body_words), header_words, body_words)
    rows = []
    for ln in body_lines:
        cells = {}
        for w in ln["words"]:
            cx = w["x"] + w["w"] / 2
            field = next((f for a, b, f in segs if a <= cx <= b), None)
            if field:
                cells.setdefault(field, []).append(w)
        if "phone" not in cells:
            continue
        # Время («23:53:51»), попавшее в соседнюю колонку, относится к дате
        if "lead_date" in cells:
            for f in [f for f in cells if f != "lead_date"]:
                times = [w for w in cells[f] if TIME_RE.fullmatch(w["text"])]
                cells["lead_date"] += times
                cells[f] = [w for w in cells[f] if w not in times]
            cells = {f: ws for f, ws in cells.items() if ws}
        cells = {f: first_segment(ws) for f, ws in cells.items()}
        rows.append(build_row({f: " ".join(w["text"] for w in ws) for f, ws in cells.items()},
                              min(w["conf"] for ws in cells.values() for w in ws)))
    return rows


FIO_TAIL_RE = re.compile(r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|ична|глы|кызы)$")


def garbled_ip_prefix(name):
    """Перед полным ФИО стоит короткий мусор (так OCR читает мелкое «ИП»).
    Просто ФИО без префикса — не ИП: это может быть обычный человек (колонка «ФИО»)."""
    parts = name.split()
    return len(parts) >= 4 and len(parts[0]) <= 3 and bool(FIO_TAIL_RE.search(" ".join(parts[-3:])))


def guess_org_form(cell, name):
    """Форма организации: ячейка -> префикс в названии («ИП Иванов…») -> ФИО с отчеством = ИП.

    Возвращает (форма или None, текст ячейки, если он непонятен — для предупреждения).
    """
    cell_form = norm_org_form(cell)
    if cell_form in ORG_FORMS:
        return cell_form, None
    if name:
        first = norm_org_form(name.split()[0])
        if first in ORG_FORMS:
            return first, None
        if garbled_ip_prefix(name):
            return "ИП", None  # нечитаемое «ИП» перед ФИО («wn Сидоров Олег Игоревич»)
    # Короткая латиница («U», «nul») — это нечитаемый серый «null» из CRM, не ошибка
    if not cell or re.fullmatch(r"[A-Za-z]{1,4}", cell):
        return None, None
    return None, cell


def build_row(raw, min_conf=100.0):
    """Сырые строки ячеек -> нормализованная запись + предупреждения для оператора."""
    raw = {k: clean(v) for k, v in raw.items()}
    name = raw.get("name")
    if name:  # к названию может прилипнуть соседний ИНН или кавычка-уголок: «771234567890ИП Иванов»
        name = re.sub(r"^[\d\s\"'”“„.,-]{5,}", "", name) or None
    org, bad_org = guess_org_form(raw.get("org_form"), name)
    row = {
        "lead_date": norm_date(raw.get("lead_date")),
        "phone": norm_phone(raw.get("phone")),
        "name": strip_org_form(name, org),
        "org_form": org,
        "amount": norm_amount(raw.get("amount")),
    }
    warnings = []
    if not row["phone"]:
        warnings.append(f"Телефон не распознан: «{raw['phone']}»" if raw.get("phone")
                        else "Нет телефона — строка не будет сохранена")
    if not row["name"]:
        warnings.append("Нет названия компании / ФИО")
    if bad_org:
        warnings.append(f"Непонятная форма организации: «{bad_org}»")
    if row["lead_date"] and not re.match(r"^\d{4}-\d{2}-\d{2}", row["lead_date"]):
        warnings.append(f"Дата не распознана: «{row['lead_date']}»")
    if min_conf < 60:
        warnings.append("Низкая уверенность распознавания — проверьте строку")
    row["warnings"] = warnings
    return row


PHONE_RE = re.compile(r"(?<![\d+])(\+7|8|7)?[\s\-(]*(\d{3})[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
AMOUNT_RE = re.compile(r"(\d[\d\s\u00a0]{3,}\d)\s*(?:₽|руб|р\.)", re.I)
ORG_RE = re.compile(r"\b(ИП|ООО|АО|ПАО|ЗАО)\b\s+([«\"]?[^\n,;]{2,60})")


FIO_RE = re.compile(r"\b([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})\b")
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[.\s][а-яё]{3,}\.?)", re.I)


def free_text_row(text, phone):
    amount = AMOUNT_RE.search(text)
    org = ORG_RE.search(text)
    fio = None if org else FIO_RE.search(text)
    date = DATE_RE.search(text)
    row = build_row({
        "phone": phone,
        "amount": amount.group(1) if amount else None,
        "org_form": org.group(1) if org else None,
        "name": org.group(2).strip() if org else (fio.group(1) if fio else None),
        "lead_date": date.group(1) if date else None,
    })
    row["warnings"].insert(0, "Без таблицы — данные найдены по тексту, проверьте")
    return row


def find_phones(text):
    out = []
    for m in PHONE_RE.finditer(text):
        if not m.group(1) and not m.group(2).startswith("9"):
            continue  # 10 цифр без +7/8 и не мобильный — скорее ИНН, чем телефон
        p = norm_phone(m.group())
        if p and p not in out:
            out.append(p)
    return out


def parse_free_text(text):
    """Запасной режим: свободный текст. Телефоны в разных строках — каждая строка свой лид
    (список), иначе один текст — один лид на каждый телефон (сообщение)."""
    lines = [ln for ln in text.splitlines() if find_phones(ln)]
    if len(lines) >= 2:
        rows, seen = [], set()
        for ln in lines:
            p = find_phones(ln)[0]
            if p not in seen:
                seen.add(p)
                rows.append(free_text_row(ln, p))
        return rows
    return [free_text_row(text, p) for p in find_phones(text)]


def parse_image(path_or_file):
    """Главная функция: файл картинки -> список лидов."""
    img = Image.open(path_or_file)
    words = ocr_words(img)
    rows = parse_table(words)
    if rows:
        return rows
    text = "\n".join(" ".join(w["text"] for w in ln["words"]) for ln in group_lines(words))
    return parse_free_text(text)
