# Генератор тестового скрина tests/fixtures/crm_table.png (имитация таблицы CRM)
from PIL import Image, ImageDraw, ImageFont
F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
B = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
cols = [("Дата лида",20),("lead_phone",140),("source_group",230),("utm_source",330),("utm_campaign",560),
        ("utm_medium",790),("utm_term",885),("lead_client_id",1105),("lead_id",1200),("lead_final_step",1265),
        ("статус лида",1370),("форма\nорганизации",1465),("запрошенная\nсумма",1563),("инн лида",1655),("компания лида",1748)]
rows = [
 ["2026-10-20 14:32","79161234567","direct","yandex","rko_msk_2026","cpc","кредит бизнес","8812345","553311","step_3","новый","ИП","500 000","771234567890","ИП Иванов Иван Иванович"],
 ["2026-10-20 15:01","79035550011","seo","google","brand","organic","","8812346","553312","step_5","новый","ООО","1 200 000","7701234567","ООО \"Ромашка\""],
 ["2026-10-21 09:15","79269998877","direct","yandex","rko_spb","cpc","овердрафт","8812347","553313","step_2","в работе","ООО","3500000","7809876543","ООО Вектор Плюс"],
]
img = Image.new("RGB",(2000,60+len(rows)*36),"white"); d = ImageDraw.Draw(img)
d.text((8,10),"Операционная статистика по лидам",font=B,fill="#222")
for name,x in cols: d.multiline_text((x,40) if "\n" not in name else (x,36),name,font=F,fill="#222",spacing=1)
for i,r in enumerate(rows):
    y=78+i*36; d.line((10,y-8,1990,y-8),fill="#e5e5e5")
    for (name,x),v in zip(cols,r): d.text((x,y),v,font=F,fill="#111")
img.save(__file__.replace("make_fixture.py", "fixtures/crm_table.png")); print(img.size)
