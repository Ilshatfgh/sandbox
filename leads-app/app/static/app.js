// Интерфейс приложения: вкладка «База» и вкладка «Загрузка скринов»
const $ = (s) => document.querySelector(s);
let META = { statuses: [], org_forms: [], stats: {} };
let reviewRows = []; // распознанные, но ещё не сохранённые строки

// ---------- общее ----------
async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Ошибка ${r.status}`);
  return data;
}
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 4000);
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtAmount = (n) => (n == null || n === "" ? "" : Number(n).toLocaleString("ru-RU"));
const parseAmount = (s) => { const d = String(s).replace(/\D/g, ""); return d ? Number(d) : null; };
const options = (list, cur) => list.map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");

// Переключение вкладок
document.querySelectorAll(".tab").forEach((b) => (b.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== b.dataset.tab));
  if (b.dataset.tab === "base") loadLeads();
}));

// ---------- вкладка «База» ----------
function filters() {
  const p = new URLSearchParams();
  if ($("#q").value.trim()) p.set("q", $("#q").value.trim());
  if ($("#fStatus").value) p.set("status", $("#fStatus").value);
  if ($("#fDue").checked) p.set("callback_due", "true");
  return p.toString();
}

async function loadMeta() {
  META = await api("/api/meta");
  $("#backupInfo").textContent = META.last_backup ? `Бэкап: ${META.last_backup.slice(6, 16)}` : "Бэкапа ещё нет";
  $("#fStatus").innerHTML = `<option value="">Все статусы</option>` + options(META.statuses, $("#fStatus").value);
  // Плашки-счётчики по статусам; клик = фильтр
  $("#stats").innerHTML = META.statuses.map((s) =>
    `<div class="stat" data-s="${esc(s)}"><b>${META.stats[s] || 0}</b>${esc(s)}</div>`).join("");
  document.querySelectorAll(".stat").forEach((el) => (el.onclick = () => {
    $("#fStatus").value = $("#fStatus").value === el.dataset.s ? "" : el.dataset.s; loadLeads();
  }));
}

async function loadLeads() {
  await loadMeta();
  const leads = await api("/api/leads?" + filters());
  const today = new Date().toISOString().slice(0, 10);
  $("#empty").hidden = leads.length > 0;
  $("#leadsBody").innerHTML = leads.map((l) => {
    const due = l.status === "Перезвонить" && l.callback_at && l.callback_at.slice(0, 10) <= today;
    return `<tr data-id="${l.id}" class="${due ? "due" : ""}">
      <td contenteditable data-f="lead_date">${esc(l.lead_date)}</td>
      <td contenteditable data-f="phone">${esc(l.phone)}</td>
      <td contenteditable data-f="name">${esc(l.name)}</td>
      <td><select data-f="org_form"><option></option>${options(META.org_forms, l.org_form)}</select></td>
      <td contenteditable data-f="amount" class="num">${fmtAmount(l.amount)}</td>
      <td><select data-f="status">${options(META.statuses, l.status)}</select></td>
      <td><input type="datetime-local" data-f="callback_at" value="${esc((l.callback_at || "").replace(" ", "T"))}"></td>
      <td contenteditable data-f="comment">${esc(l.comment)}</td>
      <td><button class="link" data-del title="Удалить">✕</button></td>
    </tr>`;
  }).join("");
}

// Сохранение изменений ячейки (по уходу фокуса / смене значения)
async function saveField(el) {
  const tr = el.closest("tr"), f = el.dataset.f;
  let v = el.matches("select,input") ? el.value : el.textContent.trim();
  if (f === "amount") v = parseAmount(v);
  if (f === "callback_at") v = v ? v.replace("T", " ") : null;
  const body = { [f]: v === "" ? null : v };
  // «Перезвонить» без даты — сразу просим дату
  if (f === "status" && v === "Перезвонить" && !tr.querySelector('[data-f="callback_at"]').value) {
    const d = prompt("Когда перезвонить? (ГГГГ-ММ-ДД ЧЧ:ММ)", new Date(Date.now() + 864e5).toISOString().slice(0, 10) + " 10:00");
    if (!d) { loadLeads(); return; }
    body.callback_at = d;
  }
  try { await api(`/api/leads/${tr.dataset.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  catch (e) { toast(e.message, true); }
  loadLeads();
}
$("#leadsBody").addEventListener("change", (e) => e.target.dataset.f && saveField(e.target));
$("#leadsBody").addEventListener("focusout", (e) => e.target.isContentEditable && saveField(e.target));
$("#leadsBody").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.isContentEditable) { e.preventDefault(); e.target.blur(); } });
$("#leadsBody").addEventListener("click", async (e) => {
  if (!e.target.matches("[data-del]")) return;
  const tr = e.target.closest("tr");
  if (!confirm("Удалить лид?")) return;
  await api(`/api/leads/${tr.dataset.id}`, { method: "DELETE" });
  loadLeads();
});
let qTimer; $("#q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(loadLeads, 300); };
$("#fStatus").onchange = loadLeads; $("#fDue").onchange = loadLeads;
$("#exportBtn").onclick = () => (location.href = "/api/export.xlsx?" + filters());

// ---------- вкладка «Загрузка скринов» ----------
async function parseFiles(files) {
  files = [...files].filter((f) => f.type.startsWith("image/"));
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f, i) => fd.append("files", f, f.name || `screenshot_${i + 1}.png`));
  $("#parseInfo").textContent = `Распознаю ${files.length} файл(ов)…`;
  try {
    const res = await api("/api/parse", { method: "POST", body: fd });
    reviewRows = reviewRows.concat(res.rows);
    $("#parseInfo").textContent = `Найдено строк: ${res.rows.length}` + (res.errors.length ? `. Ошибки: ${res.errors.join("; ")}` : "");
    renderReview();
  } catch (e) { $("#parseInfo").textContent = ""; toast(e.message, true); }
}

function renderReview() {
  $("#review").hidden = reviewRows.length === 0;
  $("#reviewBody").innerHTML = reviewRows.map((r, i) => {
    const notes = [...(r.warnings || [])];
    if (r.dup_lead) notes.unshift(`Уже в базе: ${r.dup_lead.name || ""} (${r.dup_lead.status})`);
    if (r.dup_in_batch) notes.unshift("Повтор в этой загрузке");
    // По умолчанию: дубль пропускаем, новый добавляем
    const action = r.action || (r.dup_lead || r.dup_in_batch ? "skip" : "add");
    r.action = action;
    const acts = [["add", "Добавить"], ["skip", "Пропустить"]].concat(r.dup_lead ? [["update", "Обновить в базе"]] : []);
    return `<tr data-i="${i}" class="${notes.length ? "warn" : ""}">
      <td contenteditable data-f="lead_date">${esc(r.lead_date)}</td>
      <td contenteditable data-f="phone">${esc(r.phone)}</td>
      <td contenteditable data-f="name">${esc(r.name)}</td>
      <td><select data-f="org_form"><option></option>${options(META.org_forms, r.org_form)}</select></td>
      <td contenteditable data-f="amount" class="num">${fmtAmount(r.amount)}</td>
      <td class="notes">${notes.map(esc).join("<br>") || "✓"}</td>
      <td><select data-f="action">${acts.map(([v, t]) => `<option value="${v}" ${v === action ? "selected" : ""}>${t}</option>`).join("")}</select></td>
    </tr>`;
  }).join("");
}
// Правки в таблице проверки сохраняем в reviewRows
$("#reviewBody").addEventListener("input", (e) => {
  const el = e.target, r = reviewRows[el.closest("tr").dataset.i], f = el.dataset.f;
  const v = el.matches("select") ? el.value : el.textContent.trim();
  r[f] = f === "amount" ? parseAmount(v) : v || null;
});
$("#reviewBody").addEventListener("change", (e) => e.target.dispatchEvent(new Event("input", { bubbles: true })));

$("#saveBtn").onclick = async () => {
  try {
    const res = await api("/api/leads/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reviewRows.map(({ lead_date, phone, name, org_form, amount, action }) =>
        ({ lead_date, phone: phone || "", name, org_form, amount, action }))),
    });
    toast(`Добавлено: ${res.added}, обновлено: ${res.updated}, пропущено: ${res.skipped}` + (res.errors.length ? `. Ошибки: ${res.errors.join("; ")}` : ""), res.errors.length > 0);
    reviewRows = []; renderReview(); $("#parseInfo").textContent = "";
    loadMeta();
  } catch (e) { toast(e.message, true); }
};
$("#clearBtn").onclick = () => { reviewRows = []; renderReview(); $("#parseInfo").textContent = ""; };

// Загрузка: клик, перетаскивание, вставка из буфера (удобно для Win+Shift+S)
const drop = $("#drop");
$("#files").onchange = (e) => { parseFiles(e.target.files); e.target.value = ""; };
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); parseFiles(e.dataTransfer.files); };
document.addEventListener("paste", (e) => {
  if ($("#upload").hidden) return;
  const files = [...e.clipboardData.items].filter((it) => it.kind === "file").map((it) => it.getAsFile());
  if (files.length) parseFiles(files);
});

// ---------- вкладка «Отчёт по отработке» ----------
let repRows = [];

async function parseReport(file) {
  if (!file) return;
  const fd = new FormData(); fd.append("file", file);
  $("#repInfo").textContent = "Читаю отчёт…";
  try {
    repRows = (await api("/api/report/parse", { method: "POST", body: fd })).rows;
    const ready = repRows.filter((r) => !r.errors.length && Object.keys(r.changes).length).length;
    const errs = repRows.filter((r) => r.errors.length).length;
    $("#repInfo").textContent = `Строк: ${repRows.length}. К изменению: ${ready}. С ошибками: ${errs}. Без изменений: ${repRows.length - ready - errs}.`;
    renderReport();
  } catch (e) { $("#repInfo").textContent = ""; toast(e.message, true); }
}

function renderReport() {
  $("#repReview").hidden = repRows.length === 0;
  // Сначала ошибки, потом изменения, в конце «без изменений»
  const rank = (r) => (r.errors.length ? 0 : Object.keys(r.changes).length ? 1 : 2);
  const order = repRows.map((r, i) => i).sort((a, b) => rank(repRows[a]) - rank(repRows[b]));
  $("#repBody").innerHTML = order.map((i) => {
    const r = repRows[i], l = r.lead, ch = r.changes, has = Object.keys(ch).length > 0;
    const ok = has && !r.errors.length;
    const cls = r.errors.length ? "err" : has ? "" : "same";
    const who = l ? `${esc(l.name || "")}<br><span class="muted">${esc(l.phone)}</span>` : esc(r.raw_name || r.raw_phone || "—");
    const st = l ? (ch.status ? `${esc(l.status)}<span class="arrow">→</span><b>${esc(ch.status)}</b>` : esc(l.status)) : esc(r.raw_status || "");
    return `<tr class="${cls}" data-i="${i}">
      <td><input type="checkbox" class="repChk" ${ok ? "checked" : "disabled"}></td>
      <td>${r.row_no}</td><td>${who}</td><td>${st}</td>
      <td>${esc(ch.callback_at || l?.callback_at || "")}</td>
      <td>${ch.comment ? `<b>${esc(ch.comment)}</b>` : esc(l?.comment || "")}</td>
      <td class="notes">${r.errors.map(esc).join("<br>") || (has ? "✓" : "без изменений")}</td>
    </tr>`;
  }).join("");
}

$("#repAll").onchange = (e) => document.querySelectorAll(".repChk:not(:disabled)").forEach((c) => (c.checked = e.target.checked));
$("#repApply").onclick = async () => {
  const picked = [...document.querySelectorAll(".repChk:checked")].map((c) => repRows[c.closest("tr").dataset.i]);
  if (!picked.length) return toast("Ничего не отмечено", true);
  try {
    const res = await api("/api/report/apply", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(picked.map((r) => ({ id: r.lead.id, ...r.changes }))),
    });
    toast(`Обновлено лидов: ${res.updated}`);
    repRows = []; renderReport(); $("#repInfo").textContent = "";
  } catch (e) { toast(e.message, true); }
};
$("#repClear").onclick = () => { repRows = []; renderReport(); $("#repInfo").textContent = ""; };
const repDrop = $("#repDrop");
$("#repFile").onchange = (e) => { parseReport(e.target.files[0]); e.target.value = ""; };
repDrop.ondragover = (e) => { e.preventDefault(); repDrop.classList.add("over"); };
repDrop.ondragleave = () => repDrop.classList.remove("over");
repDrop.ondrop = (e) => { e.preventDefault(); repDrop.classList.remove("over"); parseReport(e.dataTransfer.files[0]); };

loadLeads();
