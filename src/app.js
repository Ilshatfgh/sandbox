// ===== Логика курса: навигация, прогресс, копирование, конструктор, тесты =====
(function () {
  const KEY = 'claude-s-nulya-progress-v1';
  const TIER = { free: 'Бесплатно', paid: 'Платный тариф', mixed: 'Частично бесплатно' };

  // --- Прогресс хранится только в браузере пользователя; при ошибке работаем без сохранения ---
  let state = { lessons: {}, quiz: {} };
  try { const s = JSON.parse(localStorage.getItem(KEY)); if (s && s.lessons) state = s; } catch (e) {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} };

  // --- Плоский список страниц для кнопок «назад/вперёд» ---
  const PAGES = [];
  COURSE.forEach(m => {
    m.lessons.forEach(l => PAGES.push({ id: l.id, mod: m, lesson: l }));
    PAGES.push({ id: m.id + 'quiz', mod: m, quiz: true });
  });
  const ALL_LESSONS = PAGES.filter(p => p.lesson).length;

  const $ = s => document.querySelector(s);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const modDone = m => m.lessons.filter(l => state.lessons[l.id]).length;
  const totalDone = () => Object.keys(state.lessons).filter(k => state.lessons[k]).length;

  // --- Оглавление ---
  function renderNav(cur) {
    const pct = Math.round(totalDone() / ALL_LESSONS * 100);
    let h = `<a class="brand" href="#home"><span class="logo">C</span><span><b>Claude с нуля</b><small>курс для новичков</small></span></a>
      <div class="overall">Пройдено ${totalDone()} из ${ALL_LESSONS} уроков · ${pct}%<div class="bar"><i style="width:${pct}%"></i></div></div>
      <div class="nav-top">
        <a class="nav-link ${cur === 'home' ? 'on' : ''}" href="#home">Как устроен курс</a>
        <a class="nav-link ${cur === 'plan' ? 'on' : ''}" href="#plan">План на 8 недель</a>
        <a class="nav-link ${cur === 'glossary' ? 'on' : ''}" href="#glossary">Словарь терминов</a>
        <a class="nav-link ${cur === 'author' ? 'on' : ''}" href="#author">Об авторе</a>
      </div>`;
    COURSE.forEach(m => {
      const open = cur.startsWith(m.id);
      h += `<div class="mod"><button class="mod-h" data-mod="${m.id}" aria-expanded="${open}">
          <span class="mod-n">${String(m.num).padStart(2, '0')}</span><span class="mod-t">${esc(m.title)}</span>
          <span class="mod-p">${modDone(m)}/${m.lessons.length}</span></button>
        <ul ${open ? '' : 'hidden'} id="ul-${m.id}">`;
      m.lessons.forEach(l => {
        h += `<li><a href="#${l.id}" class="${cur === l.id ? 'on' : ''}"><span class="dot ${state.lessons[l.id] ? 'done' : ''}"></span>${esc(l.t)}</a></li>`;
      });
      const qs = state.quiz[m.id];
      h += `<li><a href="#${m.id}quiz" class="${cur === m.id + 'quiz' ? 'on' : ''}"><span class="dot ${qs !== undefined ? 'done' : ''}"></span>Проверка знаний${qs !== undefined ? ` · ${qs}/${m.quiz.length}` : ''}</a></li></ul></div>`;
    });
    $('#side').innerHTML = h;
    // Раскрытие модулей в оглавлении
    document.querySelectorAll('.mod-h').forEach(b => b.addEventListener('click', () => {
      const ul = $('#ul-' + b.dataset.mod); ul.hidden = !ul.hidden; b.setAttribute('aria-expanded', String(!ul.hidden));
    }));
  }

  // --- Кнопки «назад / вперёд» ---
  function pager(id) {
    const i = PAGES.findIndex(p => p.id === id);
    const prev = PAGES[i - 1], next = PAGES[i + 1];
    const name = p => p.quiz ? 'Проверка знаний: ' + p.mod.title : p.lesson.t;
    return `<nav class="pager">${prev ? `<a href="#${prev.id}"><small>← Назад</small>${esc(name(prev))}</a>` : '<span></span>'}
      ${next ? `<a class="next" href="#${next.id}"><small>Дальше →</small>${esc(name(next))}</a>` : `<a class="next" href="#plan"><small>Курс пройден →</small>План на 8 недель</a>`}</nav>`;
  }

  // --- Страница урока ---
  function renderLesson(p) {
    const m = p.mod, l = p.lesson, n = m.lessons.indexOf(l) + 1;
    let h = `<div class="crumb"><span>Модуль ${m.num} · Урок ${n} из ${m.lessons.length}</span><span>${l.min} мин</span><span class="tag ${l.tier}">${TIER[l.tier]}</span></div>
      <h1>${esc(l.t)}</h1>${l.body}`;
    if (l.builder) h += builderHTML();
    h += `<section class="block"><div class="block-h">Где пригодится</div><div class="uses">${l.uses.map(u => `<div class="use"><b>${esc(u[0])}</b>${esc(u[1])}</div>`).join('')}</div></section>`;
    h += `<section class="block"><div class="block-h">Попробуйте: скопируйте и вставьте в Claude</div>${l.prompts.map(t => `<div class="prompt"><div class="who">Вы пишете</div><p>${esc(t)}</p><button class="copy" data-text="${esc(t)}">Копировать</button></div>`).join('')}
      <p class="note">Текст в квадратных скобках замените своими данными.</p></section>`;
    h += `<section class="block task"><b>Практика</b>${esc(l.task)}</section>`;
    const done = !!state.lessons[l.id];
    h += `<div class="done-row"><span>${done ? 'Урок отмечен как пройденный.' : 'Выполнили практику? Отметьте урок.'}</span>
      <button class="btn ${done ? 'ok' : 'primary'}" id="mark">${done ? '✓ Пройдено' : 'Отметить пройденным'}</button></div>${pager(l.id)}`;
    return h;
  }

  // --- Конструктор запроса (урок 0.3) ---
  function builderHTML() {
    return `<div class="builder" id="builder">
      <label for="b-ctx">1. Контекст <span>Кто вы и в какой ситуации</span><input id="b-ctx" placeholder="Я учитель начальных классов, готовлюсь к родительскому собранию"></label>
      <label for="b-task">2. Задача <span>Что сделать, одним глаголом</span><input id="b-task" placeholder="Напиши вступительную речь"></label>
      <label for="b-det">3. Детали <span>Что учесть, чего избегать</span><textarea id="b-det" placeholder="Тема: поведение детей на переменах. Тон доброжелательный, без упрёков родителям"></textarea></label>
      <label for="b-fmt">4. Формат <span>Как должен выглядеть результат</span><input id="b-fmt" placeholder="Не больше 2 минут речи, 3 ключевые мысли"></label>
      <label for="b-ex">5. Пример <span>Необязательно: образец, который нравится</span><input id="b-ex" placeholder=""></label>
      <div class="block-h" style="margin:4px 0 0">Ваш запрос</div>
      <div class="out" id="b-out">Заполните поля выше</div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button class="btn primary" id="b-copy">Копировать запрос</button><span class="quality" id="b-q"></span></div>
    </div>`;
  }
  function bindBuilder() {
    const f = ['ctx', 'task', 'det', 'fmt', 'ex'].map(k => $('#b-' + k));
    const upd = () => {
      const [c, t, d, fm, ex] = f.map(x => x.value.trim());
      const parts = [];
      if (c) parts.push(c.replace(/\.?$/, '.'));
      if (t) parts.push(t.replace(/\.?$/, '.'));
      if (d) parts.push(d.replace(/\.?$/, '.'));
      if (fm) parts.push('Формат: ' + fm.replace(/\.?$/, '.'));
      if (ex) parts.push('Пример того, что мне нравится: ' + ex);
      $('#b-out').textContent = parts.length ? parts.join(' ') : 'Заполните поля выше';
      const filled = [c, t, d, fm].filter(Boolean).length;
      $('#b-q').textContent = filled ? `Заполнено ${filled} из 4 основных элементов${filled === 4 ? ': сильный запрос' : ''}` : '';
    };
    f.forEach(x => x.addEventListener('input', upd));
    $('#b-copy').addEventListener('click', e => copy($('#b-out').textContent, e.currentTarget, 'Копировать запрос'));
  }

  // --- Тест модуля ---
  function renderQuiz(p) {
    const m = p.mod;
    let h = `<div class="crumb"><span>Модуль ${m.num}</span><span>${m.quiz.length} вопроса</span></div><h1>Проверка знаний: ${esc(m.title)}</h1>
      <p class="lead" style="font-size:16px">Выберите ответ. Объяснение появится сразу.</p>`;
    m.quiz.forEach((q, qi) => {
      h += `<div class="q" data-q="${qi}"><h3>${qi + 1}. ${esc(q.q)}</h3><div class="opts">${q.a.map((a, ai) => `<button class="opt" data-a="${ai}">${esc(a)}</button>`).join('')}</div><div class="expl" hidden></div></div>`;
    });
    h += `<div class="score" id="score"></div>${pager(p.id)}`;
    return h;
  }
  function bindQuiz(p) {
    const m = p.mod; let answered = 0, right = 0;
    document.querySelectorAll('.q').forEach(box => {
      const q = m.quiz[+box.dataset.q];
      box.querySelectorAll('.opt').forEach(b => b.addEventListener('click', () => {
        const a = +b.dataset.a;
        box.querySelectorAll('.opt').forEach(x => { x.disabled = true; if (+x.dataset.a === q.c) x.classList.add('right'); });
        if (a !== q.c) b.classList.add('wrong'); else right++;
        const ex = box.querySelector('.expl'); ex.hidden = false; ex.textContent = (a === q.c ? 'Верно. ' : 'Не совсем. ') + q.e;
        answered++;
        if (answered === m.quiz.length) {
          state.quiz[m.id] = right; save(); renderNav(p.id);
          $('#score').textContent = `Результат: ${right} из ${m.quiz.length}. ${right === m.quiz.length ? 'Отлично, можно идти дальше.' : 'Перечитайте уроки, где были ошибки.'}`;
        }
      }));
    });
  }

  // --- Главная ---
  function renderHome() {
    const next = PAGES.find(p => p.lesson && !state.lessons[p.id]);
    let h = `<section class="hero"><div class="eyebrow">Интерактивный курс</div>
      <h1>Claude <em>с нуля</em></h1>
      <p class="lead">Пошаговый курс для тех, кто ещё ни разу не пользовался нейросетями. За 8 недель вы научитесь поручать Claude письма, расчёты, документы, исследования и рутину, а в конце поймёте, как превратить эти навыки в доход.</p>
      <div class="facts"><span><b>9</b>модулей</span><span><b>${ALL_LESSONS}</b>уроков</span><span><b>8</b>недель по 30 минут в день</span><span><b>${COURSE.reduce((s, m) => s + m.lessons.reduce((a, l) => a + l.prompts.length, 0), 0)}</b>готовых запросов</span></div>
      <a class="btn primary" href="#${next ? next.id : 'plan'}">${totalDone() ? 'Продолжить: ' + esc(next ? next.lesson.t : 'план') : 'Начать с первого урока'} →</a></section>
      <h2>Как проходить курс</h2>
      <ol class="steps">
        <li><span>Откройте урок и прочитайте его. Каждый занимает 5–12 минут.</span></li>
        <li><span>Скопируйте готовый запрос из блока «Попробуйте» и вставьте его в Claude. Замените текст в квадратных скобках своими данными.</span></li>
        <li><span>Выполните практическое задание на своей реальной задаче.</span></li>
        <li><span>Отметьте урок пройденным. Прогресс сохраняется в этом браузере.</span></li>
        <li><span>В конце модуля пройдите короткую проверку знаний.</span></li>
      </ol>
      <div class="key"><b>Что понадобится.</b> Сам курс открывается в любом браузере без регистрации. Для практики нужен аккаунт на claude.ai: первые модули проходятся на бесплатном тарифе. Пометка у каждого урока подскажет, нужен ли платный тариф.</div>
      <a class="author-strip" href="#author"><span class="portrait sm">${AUTHOR.photo ? `<img src="${AUTHOR.photo}" alt="">` : `<span>${esc(AUTHOR.name[0])}</span>`}</span>
        <span><small>Автор курса</small><b>${esc(AUTHOR.name)}</b><span>${esc(AUTHOR.role)}. Подробнее →</span></span></a>
      <h2>Модули</h2><div class="grid-mods">`;
    COURSE.forEach(m => {
      const d = modDone(m), pct = Math.round(d / m.lessons.length * 100);
      h += `<a class="card" href="#${m.lessons[0].id}"><span class="n">МОДУЛЬ ${String(m.num).padStart(2, '0')} · ${esc(m.week)}</span><span class="t">${esc(m.title)}</span><span class="w">${esc(m.goal)}</span><div class="bar"><i style="width:${pct}%"></i></div></a>`;
    });
    h += `</div><p class="foot">Возможности и тарифы Claude регулярно обновляются. Актуальные условия смотрите на claude.com/pricing и support.claude.com. Курс актуален на октябрь 2026.<br>
      <button class="reset" id="reset">Сбросить мой прогресс</button> <span id="reset-confirm" hidden> · Точно? <button class="reset" id="reset-yes">Да, сбросить</button></span></p>`;
    return h;
  }

  // --- План ---
  function renderPlan() {
    let h = `<div class="crumb"><span>8 недель · 30–40 минут в день</span></div><h1>План на 8 недель</h1>
      <p class="lead" style="font-size:16px">Одна неделя — один модуль. Не торопитесь: польза появляется, когда приём входит в привычку.</p>`;
    ROADMAP.forEach(r => {
      const ls = r.m.flatMap(id => COURSE.find(m => m.id === id).lessons);
      const d = ls.filter(l => state.lessons[l.id]).length;
      h += `<div class="week"><div class="wn">НЕДЕЛЯ ${r.w}</div><div><div class="wt">${esc(r.t)}</div><div class="wd">${esc(r.d)}</div>
        <div class="wl">${r.m.map(id => { const m = COURSE.find(x => x.id === id); return `<a href="#${m.lessons[0].id}">Модуль ${m.num}</a>`; }).join('')}</div></div>
        <div class="wp">${d}/${ls.length}${d === ls.length ? ' ✓' : ''}</div></div>`;
    });
    return h;
  }

  // --- Словарь ---
  function renderGlossary() {
    return `<h1>Словарь терминов</h1><input class="search" id="gs" placeholder="Найти термин…" aria-label="Поиск по словарю">
      <dl class="gl" id="gl" style="margin-top:12px">${GLOSSARY.map(g => `<div data-k="${esc((g[0] + ' ' + g[1]).toLowerCase())}"><dt>${esc(g[0])}</dt><dd>${esc(g[1])}</dd></div>`).join('')}</dl>`;
  }

  // --- Об авторе ---
  function renderAuthor() {
    const a = AUTHOR;
    const pic = a.photo ? `<img src="${a.photo}" alt="${esc(a.name)}">` : `<span>${esc(a.name[0])}</span>`;
    const chips = arr => arr.map(x => `<li>${esc(x)}</li>`).join('');
    return `<div class="crumb"><span>Автор курса</span></div>
      <div class="author-head"><div class="portrait">${pic}</div>
        <div><h1 style="margin-bottom:6px">${esc(a.name)}</h1><p class="lead" style="font-size:17px;margin:0">${esc(a.role)}</p>
        <p class="since">${esc(a.since)}</p></div></div>
      <p>Ильшат начал работать с нейросетями в те месяцы, когда о них только начали говорить, и с тех пор прошёл весь путь вместе с отраслью: от первых осторожных экспериментов до ежедневной работы, в которой нейросети стали полноценными коллегами. Он не теоретик и не наблюдатель. Каждый приём из этого курса он сначала проверил на собственных задачах.</p>
      <p>По профессии Ильшат — руководитель продаж в финтехе. Он построил с нуля несколько отделов продаж, создал собственный бизнес и знает цену времени, качественному решению и понятному процессу. Именно этот управленческий взгляд он переносит на работу с нейросетями: не «поиграть с новинкой», а встроить инструмент так, чтобы он приносил результат каждый день.</p>
      <h2>С какими нейросетями работает автор</h2>
      <div class="ai-grid">
        <div class="ai-col"><div class="block-h">Российские</div><ul class="chips">${chips(a.ru)}</ul></div>
        <div class="ai-col"><div class="block-h">Зарубежные</div><ul class="chips">${chips(a.world)}</ul></div>
      </div>
      <p>Такой широкий опыт позволяет честно сравнивать инструменты и выбирать лучший под задачу. Claude в этом курсе в центре внимания не случайно: по набору возможностей для работы с документами, исследованиями, автоматизацией и созданием собственных решений он стал для автора основным рабочим инструментом.</p>
      <h2>Где нейросети работают в его жизни</h2>
      <div class="uses">
        <div class="use"><b>Рабочие процессы</b>Регламенты, скрипты, аналитика, обучение сотрудников, подготовка к переговорам и отчёты для руководства.</div>
        <div class="use"><b>Собственный бизнес</b>Тексты и предложения для клиентов, анализ рынка, автоматизация рутины, проектирование новых сервисов.</div>
        <div class="use"><b>Обучение и развитие</b>Изучение новых тем, языковая практика, конспекты книг и видео, личная база знаний.</div>
        <div class="use"><b>Творчество</b>Музыкальные проекты, идеи, тексты и визуальные материалы.</div>
        <div class="use"><b>Финансы и быт</b>Планирование бюджета, разбор документов, подготовка к важным решениям.</div>
      </div>
      <div class="key" style="margin-top:28px"><b>Почему этот курс.</b> Автор сам когда-то начинал с нуля и помнит, какие вопросы возникают у новичка. Поэтому курс написан простым языком, без технического жаргона, и построен на задачах, знакомых каждому: письма, бюджет, документы, учёба, свой бизнес. Цель — чтобы через 8 недель нейросеть стала для вас таким же привычным помощником, как для автора.</div>
      <div class="pager"><a href="#home"><small>← На главную</small>Как устроен курс</a><a class="next" href="#m0l1"><small>Начать →</small>Первый урок</a></div>`;
  }

  // --- Копирование с запасным вариантом (выделение текста) ---
  function copy(text, btn, label) {
    const ok = () => { btn.textContent = 'Скопировано'; btn.classList.add('done'); setTimeout(() => { btn.textContent = label; btn.classList.remove('done'); }, 1600); };
    const fallback = () => {
      const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select();
      try { document.execCommand('copy'); ok(); } catch (e) { btn.textContent = 'Выделите и скопируйте вручную'; }
      t.remove();
    };
    try { navigator.clipboard.writeText(text).then(ok, fallback); } catch (e) { fallback(); }
  }

  // --- Роутер по #якорю ---
  function route() {
    const id = (location.hash || '#home').slice(1) || 'home';
    const page = PAGES.find(p => p.id === id);
    let html;
    if (page && page.lesson) html = renderLesson(page);
    else if (page && page.quiz) html = renderQuiz(page);
    else if (id === 'plan') html = renderPlan();
    else if (id === 'glossary') html = renderGlossary();
    else if (id === 'author') html = renderAuthor();
    else html = renderHome();
    $('#page').innerHTML = html;
    // Широкие таблицы прокручиваются внутри своего контейнера
    document.querySelectorAll('#page table.tbl').forEach(t => { const w = document.createElement('div'); w.className = 'tbl-wrap'; t.parentNode.insertBefore(w, t); w.appendChild(t); });
    renderNav(page ? page.id : id);
    closeMenu();
    window.scrollTo(0, 0);

    // Привязка обработчиков текущей страницы
    document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', () => copy(b.dataset.text, b, 'Копировать')));
    if (page && page.lesson) {
      if (page.lesson.builder) bindBuilder();
      $('#mark').addEventListener('click', () => { state.lessons[page.id] = !state.lessons[page.id]; save(); route(); });
    }
    if (page && page.quiz) bindQuiz(page);
    if (id === 'glossary') $('#gs').addEventListener('input', e => {
      const v = e.target.value.toLowerCase().trim();
      document.querySelectorAll('#gl > div').forEach(d => { d.hidden = v && !d.dataset.k.includes(v); });
    });
    const r = $('#reset');
    if (r) { r.addEventListener('click', () => { $('#reset-confirm').hidden = false; }); $('#reset-yes').addEventListener('click', () => { state = { lessons: {}, quiz: {} }; save(); route(); }); }
  }

  // --- Мобильное меню ---
  function closeMenu() { $('#side').classList.remove('open'); const s = $('#scrim'); if (s) s.hidden = true; }
  $('#menu').addEventListener('click', () => { $('#side').classList.add('open'); $('#scrim').hidden = false; });
  $('#scrim').addEventListener('click', closeMenu);

  window.addEventListener('hashchange', route);
  route();
})();
