"""Локальный веб-сервер приложения. Открывается в браузере: http://127.0.0.1:8765"""
import re
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, ocr
from .export import norm_datetime, norm_status, read_report, to_xlsx

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


# ---------- отчёт по отработке (Excel) ----------

class ReportChange(BaseModel):
    id: int
    status: str | None = None
    callback_at: str | None = None
    comment: str | None = None


@app.post("/api/report/parse")
async def report_parse(file: UploadFile = File(...)):
    """Разобрать отчёт и показать, что изменится. В базу не пишет."""
    try:
        items = read_report(file.file)
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    result = []
    for it in items:
        r = {"row_no": it["row_no"], "raw_phone": it.get("phone"), "raw_name": it.get("name"),
             "raw_status": it.get("status"), "lead": None, "errors": [], "changes": {}}
        # 1. Ищем лида: по телефону, иначе по точному имени
        phone = ocr.norm_phone(it.get("phone"))
        lead = db.find_by_phones(con, [phone]).get(phone) if phone else None
        if not lead and it.get("name"):
            found = db.find_by_name(con, it["name"])
            if len(found) == 1:
                lead = found[0]
            elif len(found) > 1:
                r["errors"].append("Несколько лидов с таким именем — укажите телефон")
        if not lead:
            if not r["errors"]:
                r["errors"].append("Клиент не найден в базе")
            result.append(r)
            continue
        r["lead"] = {k: lead[k] for k in ("id", "phone", "name", "status", "callback_at", "comment")}
        # 2. Что меняется
        status = norm_status(it.get("status"))
        if it.get("status") not in (None, "") and not status:
            r["errors"].append(f"Неизвестный статус «{it['status']}»")
        callback = norm_datetime(it.get("callback_at"))
        if callback and not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", callback):
            r["errors"].append(f"Не понял дату «{callback}»")
            callback = None
        comment = str(it["comment"]).strip() if it.get("comment") not in (None, "") else None
        ch = r["changes"]
        if status and status != lead["status"]:
            ch["status"] = status
        if callback and callback != lead["callback_at"]:
            ch["callback_at"] = callback
        if comment and comment != (lead["comment"] or ""):
            ch["comment"] = comment
        if (ch.get("status") or lead["status"]) == "Перезвонить" and not (callback or lead["callback_at"]):
            r["errors"].append("Статус «Перезвонить» без даты")
        result.append(r)
    return {"rows": result}


@app.post("/api/report/apply")
def report_apply(changes: list[ReportChange]):
    """Применить подтверждённые оператором изменения."""
    for c in changes:
        fields = c.model_dump(exclude={"id"}, exclude_none=True)
        if fields.get("status") and fields["status"] not in db.STATUSES:
            raise HTTPException(400, f"Неизвестный статус: {fields['status']}")
        db.update_lead(con, c.id, fields)
    con.commit()
    return {"updated": len(changes)}


@app.get("/api/export.xlsx")
def export(status: str | None = None, q: str | None = None, callback_due: bool = False):
    data = to_xlsx(db.list_leads(con, status, q, callback_due))
    name = f"leads_{date.today().isoformat()}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
