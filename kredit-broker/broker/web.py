"""Веб-интерфейс (открывается в браузере на этом же ПК, наружу не виден)."""
import json
import os
import shutil
import uuid
from datetime import datetime

from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from . import checks, db, monitor
from .criteria import (BOOL_KINDS, CLIENT_FIELDS, CRITERIA_MAP, LENDER_CRITERIA, LIST_KINDS, STATUS_MAYBE,
                       STATUS_NO, STATUS_OK, fmt_age, fmt_client_value, fmt_money, fmt_num, is_set, match,
                       normalize_client, parse_money)


def create_app():
    app = Flask(__name__)
    app.secret_key = "local-only"
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # вложения до 50 МБ
    app.jinja_env.globals.update(fmt_money=fmt_money, fmt_num=fmt_num, fmt_age=fmt_age,
                                 CLIENT_FIELDS=CLIENT_FIELDS, LENDER_CRITERIA=LENDER_CRITERIA,
                                 LENDER_INFO=db.LENDER_INFO, LIST_KINDS=LIST_KINDS, BOOL_KINDS=BOOL_KINDS)

    @app.template_filter("groups")
    def groups(items):
        """Группирует описания полей по ключу group с сохранением порядка."""
        out = {}
        for it in items:
            out.setdefault(it["group"], []).append(it)
        return out.items()

    @app.route("/")
    def index():
        return redirect(url_for("clients"))

    # ================= Кредиторы =================
    @app.route("/lenders")
    def lenders():
        items = db.list_lenders()
        for l in items:
            l["n_criteria"] = sum(1 for k, v in l["criteria"].items()
                                  if (k in CRITERIA_MAP and is_set(CRITERIA_MAP[k], v.get("v")))
                                  or (k.startswith("cf") and v.get("mode")))
            l["n_files"] = len(db.list_attachments(l["id"]))
        return render_template("lenders.html", lenders=items)

    @app.route("/lenders/new", methods=["GET", "POST"])
    @app.route("/lenders/<int:lid>", methods=["GET", "POST"])
    def lender_edit(lid=None):
        lender = db.get_lender(lid) if lid else {"criteria": {}, "active": 1}
        if lid and not lender:
            abort(404)
        cfs = db.list_custom_fields()
        if request.method == "POST":
            info = {f["key"]: request.form.get(f["key"], "").strip() for f in db.LENDER_INFO}
            if not info["name"]:
                flash("Укажите название кредитора", "error")
                return redirect(request.url)
            crit = lender_criteria_from_form(request.form, cfs)
            lid = db.save_lender(info, crit, 1 if request.form.get("active") else 0, lid)
            for f in request.files.getlist("files"):
                save_upload(lid, f)
            flash("Кредитор сохранён", "ok")
            return redirect(url_for("lender_edit", lid=lid))
        files = db.list_attachments(lid) if lid else []
        return render_template("lender_form.html", lender=lender, cfs=cfs, files=files)

    @app.post("/lenders/<int:lid>/toggle")
    def lender_toggle(lid):
        l = db.get_lender(lid) or abort(404)
        db.set_lender_active(lid, not l["active"])
        return redirect(url_for("lenders"))

    @app.post("/lenders/<int:lid>/copy")
    def lender_copy(lid):
        l = db.get_lender(lid) or abort(404)
        l["product"] = (l["product"] + " (копия)").strip()
        new = db.save_lender(l, l["criteria"], l["active"])
        flash("Создана копия — поправьте отличающиеся условия", "ok")
        return redirect(url_for("lender_edit", lid=new))

    @app.post("/lenders/<int:lid>/delete")
    def lender_delete(lid):
        db.delete_lender(lid)
        flash("Кредитор удалён", "ok")
        return redirect(url_for("lenders"))

    @app.route("/files/<int:aid>")
    def file_open(aid):
        a = db.get_attachment(aid) or abort(404)
        return send_file(os.path.join(db.data_dir(), "files", a["stored"]), download_name=a["filename"])

    @app.post("/files/<int:aid>/delete")
    def file_delete(aid):
        a = db.get_attachment(aid) or abort(404)
        db.delete_attachment(aid)
        return redirect(url_for("lender_edit", lid=a["lender_id"]))

    # ================= Клиенты =================
    @app.route("/clients")
    def clients():
        q = request.args.get("q", "").strip()
        return render_template("clients.html", clients=db.list_clients(q), q=q)

    @app.route("/clients/new", methods=["GET", "POST"])
    @app.route("/clients/<int:cid>", methods=["GET", "POST"])
    def client_edit(cid=None):
        client = db.get_client(cid) if cid else {"data": {}, "checks": []}
        if cid and not client:
            abort(404)
        cfs = db.list_custom_fields()
        if request.method == "POST":
            data = {f["key"]: request.form.get(f["key"], "").strip() for f in CLIENT_FIELDS}
            for cf in cfs:
                data[f"cf{cf['id']}"] = request.form.get(f"cf{cf['id']}", "").strip()
            action = request.form.get("action", "save")
            check_res = None
            if action == "check":
                inn = data.get("inn", "")
                if not checks.valid_inn(inn):
                    flash("ИНН некорректен (контрольная сумма не сходится)", "error")
                else:
                    check_res, found = checks.run_checks(inn)
                    changed = checks.merge_fields(data, found)
                    errors = [r["source"] for r in check_res if r["error"]]
                    msg = f"Проверка выполнена, заполнено полей: {len(changed)}."
                    if errors:
                        msg += " Не ответили: " + ", ".join(errors) + "."
                    flash(msg, "ok" if not errors else "error")
            cid = db.save_client(data, check_res, cid)
            if action == "match":
                return redirect(url_for("client_result", cid=cid))
            return redirect(url_for("client_edit", cid=cid))
        norm = normalize_client(client["data"])
        inn = client["data"].get("inn", "")
        return render_template("client_form.html", client=client, cfs=cfs,
                               age=fmt_age(norm["business_age_months"]) if norm["business_age_months"] is not None
                               else "", links=checks.manual_links(inn) if inn else [])

    @app.post("/clients/<int:cid>/delete")
    def client_delete(cid):
        db.delete_client(cid)
        flash("Клиент удалён", "ok")
        return redirect(url_for("clients"))

    @app.route("/clients/<int:cid>/result")
    def client_result(cid):
        client = db.get_client(cid) or abort(404)
        cfs = db.list_custom_fields()
        norm = normalize_client(client["data"])
        res = match(db.list_lenders(), norm, cfs)
        summary = build_summary(norm, client["checks"], res)
        return render_template("result.html", client=client, norm=norm, res=res, summary=summary,
                               fcv=fmt_client_value, OK=STATUS_OK, MAYBE=STATUS_MAYBE, NO=STATUS_NO,
                               now=datetime.now().strftime("%d.%m.%Y %H:%M"))

    # ================= Мониторинг сайтов =================
    @app.route("/monitor", methods=["GET", "POST"])
    def monitor_page():
        lenders_ = [l for l in db.list_lenders() if (l.get("watch_url") or "").strip()]
        results = {}
        if request.method == "POST":
            only = request.form.get("lid", type=int)
            for l in lenders_:
                if only and l["id"] != only:
                    continue
                results[l["id"]] = monitor.check_lender(l)
        snaps = {l["id"]: db.get_snapshot(l["id"]) for l in lenders_}
        return render_template("monitor.html", lenders=lenders_, results=results, snaps=snaps)

    # ================= Настройки и данные =================
    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            kind = request.form.get("kind", "bool")
            if name and kind in ("bool", "number"):
                db.add_custom_field(name, kind)
                flash("Критерий добавлен — он появится в анкете клиента и карточке кредитора", "ok")
            return redirect(url_for("settings"))
        return render_template("settings.html", cfs=db.list_custom_fields(), data_dir=db.data_dir())

    @app.post("/settings/cf/<int:fid>/delete")
    def cf_delete(fid):
        db.delete_custom_field(fid)
        return redirect(url_for("settings"))

    @app.route("/export")
    def export():
        path = os.path.join(db.data_dir(), "export_kreditory.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(db.export_all(), fh, ensure_ascii=False, indent=2)
        return send_file(path, as_attachment=True,
                         download_name=f"kreditory_{datetime.now():%Y%m%d}.json")

    @app.post("/import")
    def import_():
        f = request.files.get("file")
        try:
            added, updated = db.import_all(json.load(f.stream))
            flash(f"Импорт: добавлено {added}, обновлено {updated}", "ok")
        except Exception as e:  # noqa: BLE001
            flash(f"Не удалось импортировать файл: {e}", "error")
        return redirect(url_for("settings"))

    @app.route("/backup")
    def backup():
        path = os.path.join(db.data_dir(), "backup.db")
        shutil.copyfile(db.db_path(), path)
        return send_file(path, as_attachment=True, download_name=f"broker_backup_{datetime.now():%Y%m%d}.db")

    return app


def lender_criteria_from_form(form, cfs):
    """Собирает требования кредитора из формы: {key: {'v': ..., 'soft': bool}}."""
    crit = {}
    for c in LENDER_CRITERIA:
        k = c["key"]
        if c["kind"] in LIST_KINDS:
            v = form.getlist(f"c_{k}")
        elif c["kind"] in BOOL_KINDS:
            v = bool(form.get(f"c_{k}"))
        elif c["kind"] in ("okved_in", "okved_not_in"):
            v = form.get(f"c_{k}", "").strip()
        else:
            v = parse_money(form.get(f"c_{k}", ""))
        if is_set(c, v):
            crit[k] = {"v": v, "soft": bool(form.get(f"s_{k}"))}
    for cf in cfs:
        k = f"cf{cf['id']}"
        mode = form.get(f"{k}_mode", "")
        if not mode:
            continue
        item = {"mode": mode, "soft": bool(form.get(f"{k}_soft"))}
        if cf["kind"] == "number":
            item["v"] = parse_money(form.get(f"{k}_v", ""))
            if item["v"] is None:
                continue
        crit[k] = item
    return crit


def save_upload(lid, f):
    if not f or not f.filename:
        return
    ext = os.path.splitext(f.filename)[1].lower()[:10]
    stored = f"{lid}_{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(db.data_dir(), "files", stored))
    db.add_attachment(lid, f.filename, stored)


def build_summary(c, check_results, res):
    """Текстовое резюме для копирования (в CRM, мессенджер, письмо)."""
    L = []
    L.append(f"Клиент: {c.get('name') or '—'}, ИНН {c.get('inn') or '—'}")
    facts = [f"{c.get('legal_form') or ''}".strip(), c.get("region") or ""]
    if c.get("business_age_months") is not None:
        facts.append(f"срок работы {fmt_age(c['business_age_months'])}")
    if c.get("okved"):
        facts.append(f"ОКВЭД {c['okved']}")
    if c.get("revenue_year") is not None:
        facts.append(f"выручка {fmt_money(c['revenue_year'])}/год")
    L.append(", ".join(x for x in facts if x))
    req = f"Запрос: {fmt_money(c.get('amount'))}"
    if c.get("term_months"):
        req += f" на {fmt_num(c['term_months'])} мес."
    if c.get("collateral_type") and c["collateral_type"] != "Нет":
        req += f", залог: {c['collateral_type']}"
    elif c.get("collateral_type") == "Нет":
        req += ", без залога"
    if c.get("purpose"):
        req += f", цель: {c['purpose']}"
    L.append(req)
    if check_results:
        L.append("")
        L.append("Проверка по открытым источникам:")
        for r in check_results:
            status = "; ".join(r["facts"]) if r["ok"] else f"нет ответа ({r['error']})"
            L.append(f"• {r['source']}: {status}")
    L.append("")
    if res["stops"]:
        L.append("СТОП-ФАКТОРЫ:")
        L += [f"⛔ {s}" for s in res["stops"]]
        L.append("Рекомендация: не направлять заявку.")
        return "\n".join(L)
    ok = [r for r in res["results"] if r["status"] == STATUS_OK]
    maybe = [r for r in res["results"] if r["status"] == STATUS_MAYBE]

    def title(r):
        l = r["lender"]
        return l["name"] + (f" — {l['product']}" if l.get("product") else "")

    if ok:
        L.append("Рекомендовано направить:")
        L += [f"{i}. {title(r)}" for i, r in enumerate(ok, 1)]
    if maybe:
        L.append("Возможно (после уточнения):")
        for r in maybe:
            notes = [f"{u['label']}" for u in r["unknown"]] + [f"{f['label']}: {f['msg']}" for f in r["failed"]]
            L.append(f"• {title(r)} — уточнить: {'; '.join(notes)}")
    if not ok and not maybe:
        L.append("Подходящих кредиторов нет.")
    return "\n".join(L)
