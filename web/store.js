// Личная память Искры: всё хранится только в localStorage этого телефона.
const KEY = 'iskra:data';

const empty = () => ({
  settings: { name: 'дружище', apiKey: '', voice: true },
  memory: [],     // { id, text, at }
  tasks: [],      // { id, text, done, at }
  reminders: [], // { id, text, due, fired }
  watches: [],   // { id, query, last, checkedAt }
  ledger: [],    // { id, kind: 'income' | 'expense', amount, project, at }
  chat: [],      // { who: 'me' | 'her', text, at }
});

let data = load();
const listeners = new Set();

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return empty();
    const parsed = JSON.parse(raw);
    const base = empty();
    return { ...base, ...parsed, settings: { ...base.settings, ...parsed.settings } };
  } catch {
    return empty();
  }
}

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(data));
  } catch {
    // Хранилище недоступно (приватный режим) — работаем в памяти.
  }
  listeners.forEach((fn) => fn(data));
}

export const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

export const store = {
  get: () => data,
  update(fn) {
    fn(data);
    save();
  },
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  wipe() {
    data = empty();
    save();
  },
  export() {
    const { settings, ...rest } = data;
    return JSON.stringify({ ...rest, settings: { ...settings, apiKey: '' } }, null, 2);
  },
};
