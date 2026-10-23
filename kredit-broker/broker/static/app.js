// Мелкие удобства интерфейса. Всё работает и без этого скрипта.

// Фильтр по длинным спискам (регионы)
document.querySelectorAll('.checklist .filter').forEach(inp => {
  inp.addEventListener('input', () => {
    const q = inp.value.trim().toLowerCase();
    inp.parentElement.querySelectorAll('label').forEach(l => {
      l.style.display = l.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
});

// Кнопка «Скопировать» для резюме
document.querySelectorAll('[data-copy]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const text = document.querySelector(btn.dataset.copy).innerText;
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      // запасной вариант для старых браузеров
      const ta = Object.assign(document.createElement('textarea'), { value: text });
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    }
    btn.textContent = 'Скопировано ✓';
    setTimeout(() => (btn.textContent = 'Скопировать'), 1500);
  });
});

// Подсказка «= 12,5 млн ₽» под денежными полями
function parseMoney(s) {
  let t = (s || '').toLowerCase().replace(/[\s ₽]/g, '').replace('руб', '');
  if (!t) return null;
  let mult = 1;
  for (const [suf, m] of [['млрд', 1e9], ['млн', 1e6], ['м', 1e6], ['тыс', 1e3], ['т', 1e3], ['к', 1e3]]) {
    if (t.endsWith(suf)) { t = t.slice(0, -suf.length).replace(/\.$/, ''); mult = m; break; }
  }
  const n = parseFloat(t.replace(',', '.'));
  return isNaN(n) ? null : n * mult;
}
function fmtMoney(x) {
  if (x >= 1e6) return (Math.round(x / 1e4) / 100).toLocaleString('ru-RU') + ' млн ₽';
  if (x >= 1e3) return (Math.round(x / 1e2) / 10).toLocaleString('ru-RU') + ' тыс ₽';
  return x.toLocaleString('ru-RU') + ' ₽';
}
document.querySelectorAll('#client-form input[inputmode=decimal]').forEach(inp => {
  const label = inp.closest('label');
  if (!label || !label.textContent.includes('₽')) return;
  let hint = label.querySelector('.money-hint');
  if (!hint) { hint = Object.assign(document.createElement('span'), { className: 'muted money-hint' }); label.appendChild(hint); }
  const upd = () => { const v = parseMoney(inp.value); hint.textContent = v === null ? '' : '= ' + fmtMoney(v); };
  inp.addEventListener('input', upd); upd();
});
