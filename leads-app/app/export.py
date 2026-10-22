"""Выгрузка базы в Excel."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

COLUMNS = [  # (поле, заголовок, ширина)
    ("lead_date", "Дата лида", 18), ("phone", "Телефон", 16), ("name", "Компания / ФИО", 36),
    ("org_form", "Форма", 8), ("amount", "Сумма запроса", 15), ("status", "Статус", 24),
    ("callback_at", "Перезвонить", 18), ("comment", "Комментарий", 50), ("updated_at", "Изменён", 18),
]


def to_xlsx(leads) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Лиды"
    ws.append([c[1] for c in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF7")
    for lead in leads:
        ws.append([lead.get(c[0]) for c in COLUMNS])
    for i, (_, _, width) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for cell in ws["E"][1:]:
        cell.number_format = "# ##0"  # сумма с разделителем разрядов
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
