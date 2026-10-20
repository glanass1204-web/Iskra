import { store } from './store.js';
import { handle } from './brain.js';
import { askClaude, resetConversation } from './claude.js';

const $ = (sel) => document.querySelector(sel);
const feed = $('#feed');
const input = $('#input');
const micBtn = $('#mic');
const statusEl = $('#status');

const online = () => navigator.onLine;
const setStatus = (text) => { statusEl.textContent = text; };

// ---------- Чат ----------

function addMessage(who, text, link) {
  const li = document.createElement('li');
  li.className = `msg ${who}`;
  li.textContent = text;
  if (link) {
    const a = document.createElement('a');
    a.href = link.href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = link.label;
    li.append(document.createElement('br'), a);
  }
  feed.append(li);
  li.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function remember(who, text) {
  store.update((d) => {
    d.chat.push({ who, text, at: Date.now() });
    if (d.chat.length > 200) d.chat.splice(0, d.chat.length - 200);
  });
}

function speak(text) {
  if (!store.get().settings.voice || !('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[•🔥]/g, ''));
  u.lang = 'ru-RU';
  const ru = speechSynthesis.getVoices().find((v) => v.lang.startsWith('ru'));
  if (ru) u.voice = ru;
  speechSynthesis.speak(u);
}

const confirmDialog = $('#confirm');
function confirmAction(text) {
  $('#confirm-text').textContent = text;
  speak('Подтверди, пожалуйста.');
  return new Promise((resolve) => {
    confirmDialog.addEventListener('close', () => resolve(confirmDialog.returnValue === 'yes'), { once: true });
    confirmDialog.returnValue = '';
    confirmDialog.showModal();
  });
}

// Поиск без ключа Claude: краткая справка из Википедии + ссылка на полный поиск.
async function search(query) {
  const link = { href: `https://duckduckgo.com/?q=${encodeURIComponent(query)}&kl=ru-ru`, label: `Открыть поиск: ${query}` };
  try {
    const res = await fetch(`https://ru.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(query)}`);
    if (res.ok) {
      const j = await res.json();
      if (j.extract) return { text: j.extract, link };
    }
  } catch {
    // Сеть отвалилась — просто дадим ссылку.
  }
  return { text: `Короткого ответа не нашла. Вот поиск по запросу «${query}».`, link };
}

async function checkWatches() {
  const { watches } = store.get();
  if (!watches.length) return 'В мониторинге пока ничего нет. Скажи «следи за …».';
  const lines = [];
  for (const w of watches) {
    const r = await search(w.query);
    const changed = r.text !== w.last;
    store.update(() => { w.last = r.text; w.checkedAt = Date.now(); });
    lines.push(`• ${w.query}: ${changed ? 'есть обновления' : 'без изменений'}`);
  }
  return lines.join('\n');
}

let busy = false;
async function submit(text) {
  text = text.trim();
  if (!text || busy) return;
  busy = true;
  addMessage('me', text);
  remember('me', text);
  setStatus('Думаю…');

  const data = store.get();
  const canAsk = data.settings.apiKey && online();
  try {
    const reply = await handle(text, {
      confirm: confirmAction,
      online,
      search,
      checkWatches,
      ask: canAsk ? (q) => askClaude(q, store.get()) : null,
    });
    addMessage('her', reply.text, reply.link);
    remember('her', reply.text);
    speak(reply.text);
  } catch (err) {
    console.error(err);
    const msg = online() ? 'Что-то пошло не так. Попробуй ещё раз.' : 'Нет сети — эта функция сейчас недоступна.';
    addMessage('her', msg);
  } finally {
    busy = false;
    setStatus(online() ? 'Готова' : 'Готова · офлайн-режим');
  }
}

$('#composer').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = '';
  submit(text);
});

$('#chips').addEventListener('click', (e) => {
  const say = e.target.closest('button')?.dataset.say;
  if (say) submit(say);
});

// ---------- Голос ----------

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;

if (Recognition) {
  rec = new Recognition();
  rec.lang = 'ru-RU';
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  // На Android можно скачать русский пакет распознавания, тогда голос работает без сети.
  if ('processLocally' in rec) rec.processLocally = !online();

  rec.onstart = () => { micBtn.classList.add('listening'); setStatus('Слушаю…'); };
  rec.onend = () => { micBtn.classList.remove('listening'); if (!busy) setStatus('Готова'); };
  rec.onerror = (e) => {
    const why = {
      'not-allowed': 'Разреши доступ к микрофону в настройках браузера.',
      'network': 'Для распознавания речи нужна сеть или офлайн-пакет русского языка (Настройки → Google → Голосовой ввод).',
      'no-speech': 'Ничего не услышала. Нажми на микрофон и говори.',
    }[e.error];
    if (why) addMessage('her', why);
  };
  rec.onresult = (e) => {
    const result = e.results[e.results.length - 1];
    input.value = result[0].transcript;
    if (result.isFinal) {
      const text = input.value;
      input.value = '';
      submit(text);
    }
  };
}

micBtn.addEventListener('click', () => {
  if (!rec) {
    addMessage('her', 'Этот браузер не поддерживает голосовой ввод. Открой Искру в Chrome или Samsung Internet.');
    return;
  }
  speechSynthesis?.cancel();
  if (micBtn.classList.contains('listening')) rec.stop();
  else {
    if ('processLocally' in rec) rec.processLocally = !online();
    rec.start();
  }
});

// ---------- Напоминания ----------

async function notify(text) {
  navigator.vibrate?.([300, 120, 300]);
  if ('Notification' in window && Notification.permission === 'granted') {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) reg.showNotification('Искра напоминает', { body: text, icon: 'icon.svg', tag: text });
    else new Notification('Искра напоминает', { body: text, icon: 'icon.svg' });
  }
}

function tickReminders() {
  const now = Date.now();
  const due = store.get().reminders.filter((r) => !r.fired && r.due <= now);
  if (!due.length) return;
  store.update(() => due.forEach((r) => { r.fired = true; }));
  for (const r of due) {
    const text = `Напоминаю: ${r.text}`;
    addMessage('her', text);
    remember('her', text);
    speak(text);
    notify(r.text);
  }
}
setInterval(tickReminders, 10_000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) tickReminders(); });

// ---------- Вкладки ----------

document.querySelector('.tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-tab]');
  if (!btn) return;
  document.querySelectorAll('.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b === btn)));
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${btn.dataset.tab}`));
  input.parentElement.hidden = btn.dataset.tab !== 'chat';
});

function renderList(el, items, render, emptyText) {
  el.replaceChildren();
  if (!items.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = emptyText;
    el.append(li);
    return;
  }
  for (const item of items) el.append(render(item));
}

function row({ text, sub, done, onToggle, onDelete }) {
  const li = document.createElement('li');
  if (done) li.classList.add('done');
  if (onToggle) {
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = !!done;
    box.addEventListener('change', onToggle);
    li.append(box);
  }
  const body = document.createElement('div');
  body.className = 'grow';
  body.textContent = text;
  if (sub) {
    const s = document.createElement('small');
    s.textContent = sub;
    body.append(s);
  }
  li.append(body);
  if (onDelete) {
    const del = document.createElement('button');
    del.className = 'icon-btn';
    del.setAttribute('aria-label', 'Удалить');
    del.textContent = '×';
    del.addEventListener('click', onDelete);
    li.append(del);
  }
  return li;
}

const removeFrom = (key, item, label) => async () => {
  if (!(await confirmAction(`Удалить ${label}?\n«${item.text ?? item.query ?? item.project}»`))) return;
  store.update((d) => { d[key] = d[key].filter((x) => x !== item); });
  if (key === 'memory') resetConversation();
};

const fmt = (ts) => new Date(ts).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const money = (n) => n.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' ₽';

function render(d) {
  renderList($('#task-list'), [...d.tasks].sort((a, b) => a.done - b.done), (t) => row({
    text: t.text,
    done: t.done,
    onToggle: () => store.update(() => { t.done = !t.done; }),
    onDelete: removeFrom('tasks', t, 'задачу'),
  }), 'Задач нет — скажи «задача …»');

  renderList($('#reminder-list'), d.reminders.filter((r) => !r.fired).sort((a, b) => a.due - b.due), (r) => row({
    text: r.text, sub: fmt(r.due), onDelete: removeFrom('reminders', r, 'напоминание'),
  }), 'Нет активных напоминаний');

  renderList($('#memory-list'), d.memory, (x) => row({
    text: x.text, sub: fmt(x.at), onDelete: removeFrom('memory', x, 'из памяти'),
  }), 'Скажи «запомни, что …»');

  renderList($('#watch-list'), d.watches, (w) => row({
    text: w.query, sub: w.checkedAt ? `проверено ${fmt(w.checkedAt)}` : 'ещё не проверялось',
    onDelete: removeFrom('watches', w, 'из мониторинга'),
  }), 'Скажи «следи за …»');

  const income = d.ledger.filter((e) => e.kind === 'income').reduce((a, e) => a + e.amount, 0);
  const expense = d.ledger.filter((e) => e.kind === 'expense').reduce((a, e) => a + e.amount, 0);
  $('#money-summary').replaceChildren();
  for (const [label, value] of [['Доход', income], ['Расход', expense], ['Итого', income - expense]]) {
    const cell = document.createElement('div');
    const b = document.createElement('b');
    b.textContent = money(value);
    const s = document.createElement('span');
    s.textContent = label;
    cell.append(b, s);
    $('#money-summary').append(cell);
  }
  renderList($('#ledger-list'), [...d.ledger].reverse(), (e) => row({
    text: `${e.kind === 'income' ? '+' : '−'}${money(e.amount)} · ${e.project}`,
    sub: fmt(e.at),
    onDelete: removeFrom('ledger', e, 'запись'),
  }), 'Скажи «доход 5000 проект …»');
}

store.subscribe(render);
render(store.get());

// ---------- Настройки ----------

const s = store.get().settings;
$('#set-name').value = s.name;
$('#set-key').value = s.apiKey;
$('#set-voice').checked = s.voice;

$('#set-name').addEventListener('change', (e) => { store.update((d) => { d.settings.name = e.target.value.trim() || 'дружище'; }); resetConversation(); });
$('#set-key').addEventListener('change', (e) => { store.update((d) => { d.settings.apiKey = e.target.value.trim(); }); resetConversation(); });
$('#set-voice').addEventListener('change', (e) => store.update((d) => { d.settings.voice = e.target.checked; }));

$('#btn-notify').addEventListener('click', async () => {
  if (!('Notification' in window)) return addMessage('her', 'Уведомления в этом браузере недоступны.');
  const p = await Notification.requestPermission();
  addMessage('her', p === 'granted' ? 'Уведомления включены.' : 'Уведомления не разрешены.');
});

$('#btn-export').addEventListener('click', () => {
  const blob = new Blob([store.export()], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `iskra-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
});

$('#btn-wipe').addEventListener('click', async () => {
  if (!(await confirmAction('Стереть всю память, задачи, напоминания, записи и ключ? Это нельзя отменить.'))) return;
  store.wipe();
  resetConversation();
  location.reload();
});

// ---------- Сеть и запуск ----------

function updateNet() {
  const on = online();
  const net = $('#net');
  net.textContent = on ? 'онлайн' : 'офлайн';
  net.classList.toggle('online', on);
  if (!busy) setStatus(on ? 'Готова' : 'Готова · офлайн-режим');
  if (on && store.get().watches.length) {
    const stale = store.get().watches.some((w) => Date.now() - w.checkedAt > 6 * 3600e3);
    if (stale) checkWatches().catch(() => {});
  }
}
window.addEventListener('online', updateNet);
window.addEventListener('offline', updateNet);
updateNet();

const past = store.get().chat.slice(-30);
if (past.length) past.forEach((m) => addMessage(m.who, m.text));
else addMessage('her', `Привет, ${s.name}! Я Искра 🔥 Нажми на микрофон и скажи, чем помочь. Скажи «что ты умеешь», чтобы увидеть команды.`);
tickReminders();

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
