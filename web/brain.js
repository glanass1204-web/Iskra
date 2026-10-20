// Локальный «мозг» Искры: понимает команды на русском без интернета.
// Всё, что он не распознал, уходит к Claude (если есть сеть и ключ).
import { store, uid } from './store.js';

const WORD_NUMBERS = {
  'один': 1, 'одну': 1, 'одна': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5,
  'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10, 'пятнадцать': 15,
  'двадцать': 20, 'тридцать': 30, 'сорок': 40, 'пятьдесят': 50,
};

export const normalize = (s) => s.toLowerCase().replace(/ё/g, 'е').replace(/[!?.,]+$/g, '').trim();

const fmtTime = (d) => d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
const fmtDate = (d) => d.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
const fmtMoney = (n) => n.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' ₽';

function toNumber(token) {
  if (token == null) return NaN;
  const n = Number(String(token).replace(',', '.').replace(/\s/g, ''));
  return Number.isFinite(n) ? n : WORD_NUMBERS[token] ?? NaN;
}

// Разбирает «через 10 минут», «через час», «в 18:30», «завтра в 9», «в 7 вечера».
export function parseWhen(text, now = new Date()) {
  let m = text.match(/через\s+(полчаса|пол часа)/);
  if (m) return { due: new Date(now.getTime() + 30 * 60e3), rest: text.replace(m[0], '') };

  m = text.match(/через\s+(?:(\S+)\s+)?(секунд\S*|минут\S*|час\S*|дн\S*|день)/);
  if (m) {
    const n = m[1] ? toNumber(m[1]) : 1;
    if (Number.isFinite(n)) {
      const unit = m[2].startsWith('секунд') ? 1e3
        : m[2].startsWith('минут') ? 60e3
        : m[2].startsWith('час') ? 3600e3 : 86400e3;
      return { due: new Date(now.getTime() + n * unit), rest: text.replace(m[0], '') };
    }
  }

  m = text.match(/(завтра\s+)?в\s+(\d{1,2})(?:[:.](\d{2}))?(?:\s*(утра|дня|вечера|ночи))?/);
  if (m) {
    let h = Number(m[2]);
    const min = Number(m[3] || 0);
    if (m[4] === 'вечера' || (m[4] === 'дня' && h < 12)) h = h === 12 ? 12 : h + 12;
    if (h > 23 || min > 59) return null;
    const due = new Date(now);
    due.setHours(h, min, 0, 0);
    if (m[1]) due.setDate(due.getDate() + 1);
    else if (due <= now) due.setDate(due.getDate() + 1);
    return { due, rest: text.replace(m[0], '') };
  }
  return null;
}

const cleanTail = (s) => s.replace(/^\s*(что|чтобы|о том,? что|про)\s+/, '').replace(/\s+/g, ' ').trim();

const HELP = `Вот что я умею:
• «Запомни, что …» / «Что ты помнишь?» / «Забудь …»
• «Задача …» / «Мои задачи» / «Готово 2»
• «Напомни через 15 минут …» / «Напомни в 18:30 …» / «Напоминания»
• «Позвони 89991234567» / «Напиши смс 8999… текст» — только с подтверждением
• «Маршрут до …» / «Заряд батареи» / «Который час?»
• «Найди …» / «Что такое …» — нужен интернет
• «Следи за …» / «Проверь мониторинг»
• «Доход 5000 проект Сайт» / «Расход 300» / «Баланс» / «Идеи заработка»
Без интернета работают память, задачи, напоминания и команды телефона.`;

const IDEAS = `Несколько направлений, с которых можно начать (выберем вместе и распишем план):
1. Услуги на фрилансе: тексты, переводы, монтаж коротких видео, оформление карточек для маркетплейсов.
2. Ведение соцсетей для местного бизнеса — кафе, салоны, мастерские.
3. Перепродажа и ремонт техники: телефоны, аксессуары, мелкая электроника.
4. Цифровые продукты: шаблоны, гайды, мини-курсы по тому, в чём ты силён.
5. Подработка через приложения доставки и сервисов — быстрый старт, но меньше масштаба.
Скажи «доход 1000 проект …», и я начну вести учёт по каждому проекту.`;

/**
 * @param {string} raw
 * @param {{ confirm: (text: string) => Promise<boolean>, online: () => boolean,
 *           search: (q: string) => Promise<{text: string, link?: {href: string, label: string}}>,
 *           ask: ((q: string) => Promise<string>) | null,
 *           checkWatches: () => Promise<string> }} ctx
 * @returns {Promise<{text: string, link?: {href: string, label: string}}>}
 */
export async function handle(raw, ctx) {
  const t = normalize(raw);
  const data = store.get();
  const name = data.settings.name || 'дружище';
  let m;

  if (!t) return { text: 'Я тебя слушаю.' };

  if (/^(привет|здравствуй|хай|добр(ое|ый) \S+)/.test(t)) {
    return { text: `Привет, ${name}! Я Искра. Чем займёмся?` };
  }
  if (/(как тебя зовут|кто ты)/.test(t)) {
    return { text: 'Я Искра — твой персональный помощник. Работаю и без интернета, а важные действия выполняю только после твоего подтверждения.' };
  }
  if (/(что ты умеешь|помощь|команды|справка)/.test(t)) return { text: HELP };
  if (/(спасибо|благодарю)/.test(t)) return { text: `Всегда пожалуйста, ${name}!` };

  // Память
  if ((m = t.match(/^(?:запомни|запиши себе)[,:]?\s+(.+)/))) {
    const text = cleanTail(m[1]);
    store.update((d) => d.memory.push({ id: uid(), text, at: Date.now() }));
    return { text: `Запомнила: «${text}».` };
  }
  if ((m = raw.trim().match(/^меня зовут\s+(.+?)[.!]?$/i))) {
    const newName = m[1].trim();
    store.update((d) => { d.settings.name = newName; });
    return { text: `Приятно познакомиться, ${newName}! Буду так к тебе обращаться.` };
  }
  if (/(что ты (обо мне )?(помнишь|знаешь)|моя память)/.test(t)) {
    if (!data.memory.length) return { text: 'Пока ничего не запомнила. Скажи «запомни, что …».' };
    return { text: 'Вот что я помню:\n' + data.memory.map((x, i) => `${i + 1}. ${x.text}`).join('\n') };
  }
  if ((m = t.match(/^забудь\s+(.+)/))) {
    const q = cleanTail(m[1]);
    const hits = data.memory.filter((x) => normalize(x.text).includes(q));
    if (!hits.length) return { text: `Не нашла в памяти ничего про «${q}».` };
    if (!(await ctx.confirm(`Удалить из памяти ${hits.length} запис(ь/и)?\n` + hits.map((h) => '• ' + h.text).join('\n')))) {
      return { text: 'Хорошо, ничего не удаляю.' };
    }
    store.update((d) => { d.memory = d.memory.filter((x) => !hits.includes(x)); });
    return { text: 'Готово, забыла.' };
  }

  // Напоминания (раньше задач: «напомни» не должно стать задачей)
  if ((m = t.match(/^напомни(?:\s+мне)?\s+(.+)/))) {
    const when = parseWhen(m[1]);
    if (!when) return { text: 'Когда напомнить? Например: «напомни через 20 минут позвонить маме» или «напомни в 18:30 …».' };
    const text = cleanTail(when.rest) || 'то, о чём ты просил';
    store.update((d) => d.reminders.push({ id: uid(), text, due: when.due.getTime(), fired: false }));
    const sameDay = when.due.toDateString() === new Date().toDateString();
    return { text: `Напомню ${sameDay ? 'сегодня' : fmtDate(when.due)} в ${fmtTime(when.due)}: «${text}».` };
  }
  if (/^(напоминания|мои напоминания|какие напоминания)/.test(t)) {
    const list = data.reminders.filter((r) => !r.fired).sort((a, b) => a.due - b.due);
    if (!list.length) return { text: 'Активных напоминаний нет.' };
    return { text: list.map((r) => `• ${fmtTime(new Date(r.due))} — ${r.text}`).join('\n') };
  }

  // Задачи
  if ((m = t.match(/^(?:добавь\s+)?задач[аиу]\s*[:\-]?\s+(.+)/)) || (m = t.match(/^(?:добавь в список|надо|нужно)\s+(.+)/))) {
    const text = cleanTail(m[1]);
    store.update((d) => d.tasks.push({ id: uid(), text, done: false, at: Date.now() }));
    return { text: `Добавила задачу: «${text}».` };
  }
  if (/^(мои задачи|список задач|задачи|что (мне )?(нужно|надо) сделать)$/.test(t)) {
    const open = data.tasks.filter((x) => !x.done);
    if (!open.length) return { text: 'Открытых задач нет. Отличная работа!' };
    return { text: 'Открытые задачи:\n' + open.map((x, i) => `${i + 1}. ${x.text}`).join('\n') };
  }
  if ((m = t.match(/^(?:готово|выполнил[а]?|сделал[а]?)(?:\s+задачу)?\s+(\S+)/))) {
    const open = data.tasks.filter((x) => !x.done);
    const n = toNumber(m[1]);
    const task = Number.isFinite(n) ? open[n - 1] : open.find((x) => normalize(x.text).includes(m[1]));
    if (!task) return { text: 'Не нашла такую задачу. Скажи «мои задачи», чтобы увидеть номера.' };
    store.update(() => { task.done = true; });
    return { text: `Отметила как выполненную: «${task.text}». 🔥` };
  }

  // Время и устройство
  if (/(который час|сколько времени|время)$/.test(t)) return { text: `Сейчас ${fmtTime(new Date())}.` };
  if (/(какое сегодня число|какой сегодня день|дата)$/.test(t)) return { text: `Сегодня ${fmtDate(new Date())}.` };
  if (/(заряд|батаре)/.test(t)) {
    if (!navigator.getBattery) return { text: 'Браузер не даёт мне доступ к батарее.' };
    const b = await navigator.getBattery();
    return { text: `Заряд ${Math.round(b.level * 100)}%${b.charging ? ', заряжается' : ''}.` };
  }
  if (/^(вибрац|провибрируй)/.test(t)) {
    navigator.vibrate?.([120, 80, 120]);
    return { text: 'Бзз-бзз!' };
  }

  // Действия телефона — только с подтверждением
  if ((m = t.match(/^(?:позвони|набери|вызов)\s+(?:на\s+)?([+\d][\d\s()-]{4,})/))) {
    const phone = m[1].replace(/[^\d+]/g, '');
    if (!(await ctx.confirm(`Позвонить на номер ${phone}?`))) return { text: 'Звонок отменён.' };
    location.href = `tel:${phone}`;
    return { text: `Открываю звонок на ${phone}.` };
  }
  if ((m = raw.trim().match(/^(?:напиши|отправь)\s+смс\s+(?:на\s+)?(\+?\d[\d()-]{4,})\s+(.+)/i))) {
    const phone = m[1].replace(/[^\d+]/g, '');
    const body = m[2].trim();
    if (!(await ctx.confirm(`Подготовить СМС на ${phone}?\n«${body}»\n(Отправишь сам в приложении сообщений.)`))) {
      return { text: 'СМС отменено.' };
    }
    location.href = `sms:${phone}?body=${encodeURIComponent(body)}`;
    return { text: 'Открыла сообщения — проверь текст и нажми «Отправить».' };
  }
  if ((m = t.match(/^(?:маршрут|проложи маршрут|как доехать|открой карту)\s+(?:до\s+|к\s+)?(.+)/))) {
    const place = m[1];
    if (!(await ctx.confirm(`Открыть карты с маршрутом до «${place}»?`))) return { text: 'Хорошо, не открываю.' };
    location.href = `geo:0,0?q=${encodeURIComponent(place)}`;
    return { text: `Открываю карты: ${place}.` };
  }

  // Заработок
  if ((m = normalize(raw).match(/^(доход|заработал[а]?|получил[а]?|расход|потратил[а]?)\s+(\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?)(?:\s*(?:руб\S*|₽|р))?(?:\s+(?:на|за|проект|по проекту)\s+(.+))?/))) {
    const kind = /^(доход|заработал|получил)/.test(m[1]) ? 'income' : 'expense';
    const amount = toNumber(m[2]);
    // Название проекта берём из исходной фразы, чтобы сохранить регистр.
    const project = m[3] ? raw.trim().replace(/[.!]$/, '').slice(-m[3].length).trim() : 'Общее';
    store.update((d) => d.ledger.push({ id: uid(), kind, amount, project, at: Date.now() }));
    return { text: `${kind === 'income' ? 'Доход' : 'Расход'} ${fmtMoney(amount)} записан в «${project}».` };
  }
  if (/^(баланс|сколько (я )?заработал|итоги|проекты)/.test(t)) {
    if (!data.ledger.length) return { text: 'Записей пока нет. Скажи, например: «доход 3000 проект Видео».' };
    const by = {};
    for (const e of data.ledger) {
      by[e.project] ??= 0;
      by[e.project] += e.kind === 'income' ? e.amount : -e.amount;
    }
    const total = Object.values(by).reduce((a, b) => a + b, 0);
    return { text: `Итого: ${fmtMoney(total)}\n` + Object.entries(by).map(([p, v]) => `• ${p}: ${fmtMoney(v)}`).join('\n') };
  }
  if (/(идеи|как) (для )?заработ/.test(t)) return { text: IDEAS };

  // Мониторинг
  if ((m = t.match(/^(?:следи за|мониторь|отслеживай)\s+(.+)/))) {
    const query = m[1].trim();
    store.update((d) => d.watches.push({ id: uid(), query, last: '', checkedAt: 0 }));
    return { text: `Добавила в мониторинг: «${query}». Проверю, когда будет сеть, или скажи «проверь мониторинг».` };
  }
  if (/^(проверь мониторинг|что нового)/.test(t)) {
    if (!ctx.online()) return { text: 'Сейчас нет сети — проверю мониторинг, как только она появится.' };
    return { text: await ctx.checkWatches() };
  }

  // Поиск
  if ((m = t.match(/^(?:найди|поищи|загугли|что такое|кто такой|кто такая)\s+(.+)/))) {
    if (!ctx.online()) return { text: 'Сейчас нет интернета. Могу записать это в задачи: скажи «задача найти …».' };
    if (ctx.ask) return { text: await ctx.ask(raw) };
    return ctx.search(m[1]);
  }

  // Всё остальное — Claude, если доступен
  if (ctx.ask && ctx.online()) return { text: await ctx.ask(raw) };
  if (!ctx.online()) {
    return { text: 'Без сети я понимаю только команды — скажи «что ты умеешь». Вопрос можно задать, когда появится интернет.' };
  }
  return { text: 'Это я пока не умею. Добавь ключ Claude в настройках — тогда смогу отвечать на любые вопросы. А ещё можно сказать «найди …».' };
}
