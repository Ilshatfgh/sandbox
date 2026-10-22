# Генератор tests/fixtures/crm_real.png: раскладка как у реального скрина CRM
# (формат даты ДД.ММ.ГГГГ ЧЧ:ММ:СС, «null» серым курсивом, мелкий шрифт). Данные вымышленные.
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
F = ImageFont.truetype(FONT, 11)
FI = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf", 11)
cols = [("Дата лида", 12), ("lead_phone", 133), ("source_group", 219), ("utm_source", 314), ("utm_campaign", 541),
        ("utm_medium", 767), ("utm_term", 861), ("lead_client_id", 1078), ("lead_id", 1173), ("lead_final_step", 1234),
        ("статус лида", 1337), ("форма\nорганизации", 1432), ("запрошенная\nсумма", 1527), ("инн лида", 1616),
        ("компания лида", 1708)]
rows = [
    ["18.10.2026 23:41:00", "79001112233", "Boostra", "boostra_calc", "null", "null", "null", "26 355", "34 750",
     "company", "active", "null", "1 000 000", "", ""],
    ["18.10.2026 23:36:51", "79002223344", "CPA", "bankiru", "vitrina", "cpa", "9a3147d003fecf9c6e8a", "26 354",
     "34 749", "submit", "active", "ИП", "1 500 000", "110402700000", "ИП Петрова Анна Сергеевна"],
    ["18.10.2026 23:05:46", "79003334455", "Boostra", "boostra_lk_reject", "null", "null", "null", "26 353",
     "34 748", "submit", "active", "ИП", "100 000", "971500000000", "ИП Сидоров Олег Игоревич"],
]
img = Image.new("RGB", (2000, 139), "white")
d = ImageDraw.Draw(img)
for name, x in cols:
    d.multiline_text((x, 22), name, font=F, fill="#222", spacing=2)
for i, r in enumerate(rows):
    y = 72 + i * 26
    d.line((10, y - 8, 1990, y - 8), fill="#e8e8e8")
    for (name, x), v in zip(cols, r):
        d.text((x, y), v, font=FI if v == "null" else F, fill="#999" if v == "null" else "#111")
img.save(Path(__file__).parent / "fixtures" / "crm_real.png")
