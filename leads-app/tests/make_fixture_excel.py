# Генератор тестовых скринов в стиле Excel (сетка, зелёные уголки, заголовки по центру).
# Раскладка как у присланных примеров, данные вымышленные.
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

F = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 13)
FB = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 13)
OUT = Path(__file__).parent / "fixtures"


def sheet(path, cols, rows, bold_head=False, center_head=False, triangles=()):
    """cols: [(заголовок, ширина, выравнивание данных 'l'|'r')]"""
    rh = 20
    w = sum(c[1] for c in cols) + 1
    img = Image.new("RGB", (w, rh * (len(rows) + 1) + 1), "white")
    d = ImageDraw.Draw(img)
    x = 0
    for ci, (title, cw, align) in enumerate(cols):
        f = FB if bold_head else F
        tw = d.textlength(title, font=f)
        d.text((x + (cw - tw) / 2 if center_head else x + 3, 3), title, font=f, fill="#000")
        for ri, row in enumerate(rows):
            y = rh * (ri + 1)
            v = row[ci]
            tw = d.textlength(v, font=F)
            d.text((x + cw - tw - 3 if align == "r" else x + 3, y + 3), v, font=F, fill="#000")
            if ci in triangles:  # зелёный уголок «число как текст»
                d.polygon([(x + 1, y + 1), (x + 6, y + 1), (x + 1, y + 6)], fill="#1e7b34")
        x += cw
        d.line((x, 0, x, img.height), fill="#d4d4d4")
    for ri in range(len(rows) + 2):
        d.line((0, ri * rh, w, ri * rh), fill="#d4d4d4")
    img.save(path)


# 1) Выгрузка CRM в Excel: Дата лида | lead_phone | запрошенная сумма | инн лида | компания лида
sheet(OUT / "excel_leads.png",
      [("Дата лида", 130, "r"), ("lead_phone", 95, "l"), ("запрошенная сумма", 125, "r"),
       ("инн лида", 105, "r"), ("компания лида", 300, "l")],
      [["05.07.2026 23:53:51", "79001234501", "1 000 000", "410100000001", "ИП Смирнова Ольга Петровна"],
       ["05.07.2026 21:50:30", "79001234502", "1 500 000", "710000000002", "ИП Кузнецов Павел Андреевич"],
       ["05.07.2026 21:35:00", "79001234503", "2 000 000", "4100000003", "ООО \"ЛУЧ\""]],
      triangles=(1, 3))

# 2) Таблица с ФИО: # | Дата (12.янв) | ФИО | Телефон | ИНН | e-mail; заголовки жирные по центру
sheet(OUT / "excel_fio.png",
      [("#", 30, "r"), ("Дата", 60, "r"), ("ФИО", 230, "l"), ("Телефон", 110, "l"),
       ("ИНН", 110, "r"), ("e-mail", 190, "l")],
      [["22", "12.янв", "Орлова Мария Ивановна", "+79001234504", "590800000004", "orlova@example.ru"],
       ["23", "12.янв", "Степан", "+79001234505", "701700000005", "stepan@example.ru"],
       ["24", "13.янв", "Лебедев Игорь Олегович", "+79001234506", "240100000006", "lebedev@example.ru"]],
      bold_head=True, center_head=True, triangles=(3, 4))

# 3) Сообщение в Telegram: ФИО, телефон, ИНН (10 цифр), e-mail, время — без заголовков
img = Image.new("RGB", (470, 64), "#eeffde")
d = ImageDraw.Draw(img)
FT = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 15)
d.text((8, 8), "Сафина Алия Ринатовна", font=FT, fill="#000")
d.text((200, 8), "+79001234507", font=FT, fill="#3a8a3a")
d.text((320, 8), "6600000007", font=FT, fill="#3a8a3a")
d.text((8, 32), "info@example.ru", font=FT, fill="#3a8a3a")
d.text((400, 40), "14:08", font=ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 11), fill="#5fa85f")
img.save(OUT / "telegram_msg.png")
