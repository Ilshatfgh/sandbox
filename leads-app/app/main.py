"""Локальный веб-сервер приложения. Открывается в браузере: http://127.0.0.1:8765"""
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, ocr
from .export import to_xlsx

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="База лидов")
con = db.connect()


class LeadIn(BaseModel):
    lead_date: str | None = None
    phone: str
    name: str | None = None
    org_form: str | None = None
    amount: int | None = None
    action: str = "add"  # add — новый; update — обновить существующий дубль; skip — пропустить


class LeadPatch(BaseModel):
    lead_date: str | None = None
    phone: str | None = None
    name: str | None = None
    org_form: str | None = None
    amount: int | None = None
    status: str | None = None
    callback_at: str | None = None
    comment: str | None = None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    return {"statuses": db.STATUSES, "org_forms": ocr.ORG_FORMS, "stats": db.stats(con)}


@app.get("/api/leads")
def leads(status: str | None = None, q: str | None = None, callback_due: bool = False):
    return db.list_leads(con, status, q, callback_due)


@app.post("/api/parse")
async def parse(files: list[UploadFile] = File(...)):
    """Распознать скрины. В базу ничего не пишет — оператор сначала проверяет результат."""
    rows, errors = [], []
    for f in files:
        try:
            for r in ocr.parse_image(f.file):
                r["source"] = f.filename
                rows.append(r)
        except ocr.pytesseract.TesseractNotFoundError:
            errors.append("Не установлен Tesseract OCR — см. README, раздел «Установка»")
            break
        except Exception as e:  # битый файл и т.п. — показываем оператору
            errors.append(f"{f.filename}: {e}")
    mark_duplicates(rows)
    return {"rows": rows, "errors": errors}


def mark_duplicates(rows):
    """Помечаем дубли: с базой (dup_lead) и внутри самой загрузки (dup_in_batch)."""
    existing = db.find_by_phones(con, [r["phone"] for r in rows])
    seen = set()
    for r in rows:
        r["dup_lead"] = existing.get(r["phone"])
        r["dup_in_batch"] = bool(r["phone"]) and r["phone"] in seen
        seen.add(r["phone"])


@app.post("/api/leads/import")
def import_leads(rows: list[LeadIn]):
    """Сохранить проверенные оператором строки."""
    added = updated = skipped = 0
    errors = []
    for r in rows:
        phone = ocr.norm_phone(r.phone)
        if r.action == "skip":
            skipped += 1
            continue
        if not phone:
            errors.append(f"Некорректный телефон: {r.phone}")
            continue
        data = r.model_dump(exclude={"action"}) | {"phone": phone}
        found = db.find_by_phones(con, [phone]).get(phone)
        if found:
            if r.action == "update":
                # Обновляем только данные лида, статус и комментарий не трогаем
                db.update_lead(con, found["id"], {k: v for k, v in data.items() if v not in (None, "")})
                updated += 1
            else:
                skipped += 1  # дубль, а оператор не выбрал «обновить»
        else:
            db.insert_lead(con, data)
            added += 1
    con.commit()
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}


@app.patch("/api/leads/{lead_id}")
def patch_lead(lead_id: int, patch: LeadPatch):
    fields = patch.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in db.STATUSES:
        raise HTTPException(400, "Неизвестный статус")
    if fields.get("status") == "Перезвонить" and not fields.get("callback_at"):
        cur = con.execute("SELECT callback_at FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not cur or not cur["callback_at"]:
            raise HTTPException(400, "Для статуса «Перезвонить» укажите дату")
    if "phone" in fields:
        fields["phone"] = ocr.norm_phone(fields["phone"])
        if not fields["phone"]:
            raise HTTPException(400, "Некорректный телефон")
    try:
        db.update_lead(con, lead_id, fields)
        con.commit()
    except Exception as e:  # например, телефон совпал с другим лидом
        con.rollback()
        raise HTTPException(400, f"Не сохранено: {e}")
    row = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Лид не найден")
    return dict(row)


@app.delete("/api/leads/{lead_id}")
def delete_lead(lead_id: int):
    con.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    con.commit()
    return {"ok": True}


@app.get("/api/export.xlsx")
def export(status: str | None = None, q: str | None = None, callback_due: bool = False):
    data = to_xlsx(db.list_leads(con, status, q, callback_due))
    name = f"leads_{date.today().isoformat()}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
