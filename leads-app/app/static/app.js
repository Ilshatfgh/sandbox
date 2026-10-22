// Интерфейс приложения: вкладки «База», «Загрузка лидов», «Отчёт по отработке»
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
// Все лиды грузим один раз, фильтруем в браузере (лидов — тысячи, это мгновенно).
// Экспорт отправляет на сервер id видимых строк — в Excel ровно то, что в таблице.
let ALL = [];                       // все лиды из базы
let VIEW = [];                      // после всех фильтров
const colFilters = {};              // поле -> Set выбранных значений (нет ключа = фильтра нет)
let range = { from: null, to: null }; // период календаря, 'YYYY-MM-DD'
let calMonth = new Date(); calMonth.setDate(1);
const EMPTY = "(пусто)";

// Колонки таблицы и как из лида получить значение для фильтра / подпись
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const ruDate = (s) => (s ? s.slice(0, 10).split("-").reverse().join(".") : "");
const leadDay = (l) => (l.lead_date || l.created_at || "").slice(0, 10); // дата лида; нет — дата загрузки
const COLS = [
  { f: "lead_date", title: "Дата лида", key: leadDay, label: ruDate, sort: "desc" },
  { f: "phone", title: "Телефон" },
  { f: "name", title: "Компания / ФИО" },
  { f: "org_form", title: "Форма" },
  { f: "amount", title: "Сумма", num: true, label: fmtAmount, sort: "num" },
  { f: "status", title: "Статус", sort: "status" },
  { f: "callback_at", title: "Перезвонить", key: (l) => (l.callback_at || "").slice(0, 10), label: ruDate, sort: "asc" },
  { f: "comment", title: "Комментарий" },
];
const colKey = (c, l) => { const v = c.key ? c.key(l) : l[c.f]; return v == null || v === "" ? EMPTY : String(v); };
const colLabel = (c, k) => (k === EMPTY ? EMPTY : c.label ? c.label(c.num ? Number(k) : k) : k);

// Фильтрация. skip — колонка, которую не учитываем (для списка значений в её же фильтре)
function applyFilters(skip = null) {
  const q = $("#q").value.trim().toLowerCase(), qd = q.replace(/\D/g, "");
  const today = ymd(new Date());
  return ALL.filter((l) => {
    if (range.from) { const d = leadDay(l); if (d < range.from || d > range.to) return false; }
    if (q && !((l.name || "").toLowerCase().includes(q) || (qd && l.phone.includes(qd)))) return false;
    if ($("#fDue").checked && !(l.status === "Перезвонить" && l.callback_at && l.callback_at.slice(0, 10) <= today)) return false;
    for (const c of COLS) {
      if (c.f === skip || !colFilters[c.f]) continue;
      if (!colFilters[c.f].has(colKey(c, l))) return false;
    }
    return true;
  });
}

async function loadMeta() {
  META = await api("/api/meta");
  $("#version").textContent = `версия ${META.version}`;
  $("#backupInfo").textContent = META.last_backup ? `Бэкап: ${META.last_backup.slice(6, 16)}` : "Бэкапа ещё нет";
}

async function loadLeads() {
  await loadMeta();
  ALL = await api("/api/leads");
  render();
}

function render() {
  VIEW = applyFilters();
  renderHead(); renderStats(); renderCalendar();
  const today = ymd(new Date());
  $("#empty").hidden = ALL.length > 0;
  $("#shown").textContent = `Показано: ${VIEW.length} из ${ALL.length}`;
  const active = range.from || Object.keys(colFilters).length || $("#q").value.trim() || $("#fDue").checked;
  $("#resetFilters").hidden = !active;
  $("#leadsBody").innerHTML = VIEW.map((l) => {
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

// Заголовки с кнопкой фильтра; активный фильтр подсвечен и показывает число выбранных значений
function renderHead() {
  $("#leadsHead").innerHTML = COLS.map((c) => {
    const on = colFilters[c.f];
    return `<th class="${c.num ? "num" : ""}">${esc(c.title)}<button class="th-flt ${on ? "on" : ""}" data-col="${c.f}"
      title="Фильтр">${on ? on.size + " ▾" : "▾"}</button></th>`;
  }).join("") + "<th></th>";
}

// Плашки статусов: счётчики по текущему периоду и фильтрам (кроме статуса); клик — добавить/убрать статус в фильтре
function renderStats() {
  const base = applyFilters("status"), cnt = {};
  base.forEach((l) => (cnt[l.status] = (cnt[l.status] || 0) + 1));
  const sel = colFilters.status;
  $("#stats").innerHTML = META.statuses.map((s) =>
    `<div class="stat ${sel && sel.has(s) ? "on" : ""}" data-s="${esc(s)}"><b>${cnt[s] || 0}</b>${esc(s)}</div>`).join("");
}
$("#stats").addEventListener("click", (e) => {
  const el = e.target.closest(".stat"); if (!el) return;
  const s = colFilters.status || new Set();
  s.has(el.dataset.s) ? s.delete(el.dataset.s) : s.add(el.dataset.s);
  if (s.size) colFilters.status = s; else delete colFilters.status;
  render();
});

// ----- выпадающий фильтр колонки (как в Excel) -----
let cfCol = null;
function openColFilter(btn) {
  const c = COLS.find((x) => x.f === btn.dataset.col);
  cfCol = c;
  // Значения — из строк, прошедших остальные фильтры, + уже выбранные (чтобы их можно было снять)
  const counts = new Map();
  applyFilters(c.f).forEach((l) => { const k = colKey(c, l); counts.set(k, (counts.get(k) || 0) + 1); });
  (colFilters[c.f] || []).forEach((k) => counts.has(k) || counts.set(k, 0));
  const order = META.statuses;
  const keys = [...counts.keys()].sort((a, b) => {
    if (a === EMPTY) return 1; if (b === EMPTY) return -1;
    if (c.sort === "num") return Number(a) - Number(b);
    if (c.sort === "desc") return b.localeCompare(a);
    if (c.sort === "status") return order.indexOf(a) - order.indexOf(b);
    return a.localeCompare(b, "ru");
  });
  const sel = colFilters[c.f];
  $("#cfList").innerHTML = keys.map((k) => `<label data-text="${esc(colLabel(c, k).toLowerCase())}">
    <input type="checkbox" value="${esc(k)}" ${!sel || sel.has(k) ? "checked" : ""}> ${esc(colLabel(c, k))}
    <span class="cnt">${counts.get(k)}</span></label>`).join("") || `<p class="muted">Нет значений</p>`;
  $("#cfSearch").value = "";
  syncCfAll();
  const box = $("#colFilter"), r = btn.getBoundingClientRect();
  box.hidden = false;
  box.style.top = `${r.bottom + window.scrollY + 4}px`;
  box.style.left = `${Math.min(r.left + window.scrollX - 10, document.documentElement.clientWidth - box.offsetWidth - 10)}px`;
  $("#cfSearch").focus();
}
const cfBoxes = (visibleOnly) => [...document.querySelectorAll("#cfList label")]
  .filter((l) => !visibleOnly || !l.hidden).map((l) => l.querySelector("input"));
function syncCfAll() {
  const v = cfBoxes(true);
  $("#cfAll").checked = v.length > 0 && v.every((x) => x.checked);
}
$("#leadsHead").addEventListener("click", (e) => {
  const btn = e.target.closest(".th-flt"); if (!btn) return;
  e.stopPropagation();
  $("#colFilter").hidden || cfCol?.f !== btn.dataset.col ? openColFilter(btn) : ($("#colFilter").hidden = true);
});
// Поиск по списку значений: при поиске «Выделить все» работает только по найденным
$("#cfSearch").oninput = () => {
  const q = $("#cfSearch").value.trim().toLowerCase();
  document.querySelectorAll("#cfList label").forEach((l) => (l.hidden = q && !l.dataset.text.includes(q)));
  syncCfAll();
};
$("#cfAll").onchange = () => cfBoxes(true).forEach((x) => (x.checked = $("#cfAll").checked));
$("#cfList").addEventListener("change", syncCfAll);
$("#cfOk").onclick = () => {
  const q = $("#cfSearch").value.trim();
  // Если искали — берём отмеченные среди найденных (как в Excel), иначе — все отмеченные
  const boxes = cfBoxes(!!q), checked = boxes.filter((x) => x.checked).map((x) => x.value);
  if (!q && checked.length === boxes.length) delete colFilters[cfCol.f];
  else colFilters[cfCol.f] = new Set(checked);
  $("#colFilter").hidden = true; render();
};
$("#cfReset").onclick = () => { delete colFilters[cfCol.f]; $("#colFilter").hidden = true; render(); };
$("#cfSearch").addEventListener("keydown", (e) => e.key === "Enter" && $("#cfOk").click());
document.addEventListener("click", (e) => {
  if (!$("#colFilter").hidden && !e.target.closest("#colFilter")) $("#colFilter").hidden = true;
});
document.addEventListener("keydown", (e) => e.key === "Escape" && ($("#colFilter").hidden = true));

// ----- календарь периода -----
const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
let pickStart = null; // первый клик выбран, ждём второй

function renderCalendar() {
  const y = calMonth.getFullYear(), m = calMonth.getMonth();
  $("#calTitle").textContent = `${MONTHS[m]} ${y}`;
  const days = new Set(ALL.map(leadDay)); // дни, в которые есть лиды — точка под числом
  const first = new Date(y, m, 1), shift = (first.getDay() + 6) % 7; // неделя с понедельника
  const today = ymd(new Date());
  let html = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => `<div class="dow">${d}</div>`).join("");
  for (let i = 0; i < 42; i++) {
    const d = new Date(y, m, 1 - shift + i), k = ymd(d);
    const cls = ["day"];
    if (d.getMonth() !== m) cls.push("out");
    if (k === today) cls.push("today");
    if (days.has(k)) cls.push("has");
    const from = pickStart || range.from, to = pickStart || range.to;
    if (from && k >= from && k <= to) cls.push(k === from || k === to ? "edge" : "in");
    html += `<button class="${cls.join(" ")}" data-d="${k}">${d.getDate()}</button>`;
  }
  $("#calGrid").innerHTML = html;
  $("#periodBtn").classList.toggle("on", !!range.from);
  $("#periodText").textContent = pickStart ? `${ruDate(pickStart)} — выберите конец периода`
    : range.from ? (range.from === range.to ? ruDate(range.from) : `${ruDate(range.from)} — ${ruDate(range.to)}`) : "весь";
}
function setRange(from, to) {
  pickStart = null;
  $("#cal").hidden = true; // период выбран — сворачиваем календарь в строку
  range = from ? { from: from < to ? from : to, to: from < to ? to : from } : { from: null, to: null };
  render();
}
$("#calGrid").addEventListener("click", (e) => {
  const b = e.target.closest(".day"); if (!b) return;
  const k = b.dataset.d;
  if (!pickStart) { pickStart = k; range = { from: k, to: k }; render(); } // один клик = один день
  else setRange(pickStart, k);
});
$("#periodBtn").onclick = (e) => {
  e.stopPropagation();
  const cal = $("#cal");
  if (cal.hidden && range.from) { calMonth = new Date(range.from); calMonth.setDate(1); } // открываем на выбранном месяце
  cal.hidden = !cal.hidden;
  if (cal.hidden && pickStart) setRange(pickStart, pickStart); else renderCalendar();
};
// Клики внутри календаря не «всплывают»: дни перерисовываются, и клик иначе выглядел бы как клик мимо
$("#cal").addEventListener("click", (e) => e.stopPropagation());
// Клик мимо календаря / Esc — свернуть (недовыбранный период = один день)
function closeCal() {
  if ($("#cal").hidden) return;
  if (pickStart) setRange(pickStart, pickStart); else $("#cal").hidden = true;
}
document.addEventListener("click", (e) => { if (!e.target.closest(".period-wrap")) closeCal(); });
document.addEventListener("keydown", (e) => e.key === "Escape" && closeCal());
document.querySelectorAll(".cal-nav").forEach((b) => (b.onclick = () => {
  calMonth.setMonth(calMonth.getMonth() + Number(b.dataset.nav)); renderCalendar();
}));
$("#calTitle").onclick = () => {
  const y = calMonth.getFullYear(), m = calMonth.getMonth();
  setRange(ymd(new Date(y, m, 1)), ymd(new Date(y, m + 1, 0)));
};
document.querySelectorAll(".cal-presets button").forEach((b) => (b.onclick = () => {
  const t = new Date(), d = (n) => ymd(new Date(t.getFullYear(), t.getMonth(), t.getDate() + n));
  const p = b.dataset.preset;
  if (p === "today") setRange(d(0), d(0));
  if (p === "yesterday") setRange(d(-1), d(-1));
  if (p === "week") setRange(d(-6), d(0));
  if (p === "month") setRange(ymd(new Date(t.getFullYear(), t.getMonth(), 1)), ymd(new Date(t.getFullYear(), t.getMonth() + 1, 0)));
  if (p === "prevmonth") setRange(ymd(new Date(t.getFullYear(), t.getMonth() - 1, 1)), ymd(new Date(t.getFullYear(), t.getMonth(), 0)));
  if (p === "all") setRange(null);
  if (p !== "all") { calMonth = new Date(range.to); calMonth.setDate(1); renderCalendar(); }
}));

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
let qTimer; $("#q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(render, 200); };
$("#fDue").onchange = render;
$("#resetFilters").onclick = () => {
  Object.keys(colFilters).forEach((k) => delete colFilters[k]);
  $("#q").value = ""; $("#fDue").checked = false; setRange(null);
};

// Экспорт: видимые строки; имя файла — по периоду календаря
$("#exportBtn").onclick = async () => {
  if (!VIEW.length) return toast("Нет строк для выгрузки", true);
  const r = await fetch("/api/export.xlsx", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: VIEW.map((l) => l.id), date_from: range.from, date_to: range.to }),
  });
  if (!r.ok) return toast("Не удалось выгрузить", true);
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || "leads.xlsx";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

// ---------- вкладка «Загрузка лидов»: скрины и файлы ----------
async function parseFiles(files) {
  // Скрины и файлы с готовыми данными; остальное (например, PDF) — сразу понятное сообщение
  const ok = /\.(png|jpe?g|webp|bmp|gif|tiff?|xlsx|xlsm|xls|csv|docx|doc|txt)$/i;
  const bad = [...files].filter((f) => !f.type.startsWith("image/") && !ok.test(f.name));
  if (bad.length) toast(`Не поддерживается: ${bad.map((f) => f.name).join(", ")}`, true);
  files = [...files].filter((f) => !bad.includes(f));
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f, i) => fd.append("files", f, f.name || `screenshot_${i + 1}.png`));
  $("#parseInfo").textContent = `Обрабатываю ${files.length} файл(ов)…`;
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
    const action = r.action || (r.dup_lead || r.dup_in_batch || !r.phone ? "skip" : "add"); // без телефона — не сохраняем
    r.action = action;
    const acts = [["add", "Добавить"], ["skip", "Пропустить"]].concat(r.dup_lead ? [["update", "Обновить в базе"]] : []);
    return `<tr data-i="${i}" class="${notes.length ? "warn" : ""}">
      <td contenteditable data-f="lead_date">${esc(r.lead_date)}</td>
      <td contenteditable data-f="phone">${esc(r.phone)}</td>
      <td contenteditable data-f="name">${esc(r.name)}</td>
      <td><select data-f="org_form"><option></option>${options(META.org_forms, r.org_form)}</select></td>
      <td contenteditable data-f="amount" class="num">${fmtAmount(r.amount)}</td>
      <td class="muted small">${esc(r.source)}</td>
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
