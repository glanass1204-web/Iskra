"""«Входящие»: Искра следит за папками, замечает новые файлы и разбирает каждый: что это (телеграмма, таблица,
приказ…), номер, дата, от кого, срок исполнения, кратко о чём. Журнал хранится в data/inbox.json.
Файлы не перемещаются и не изменяются."""
import json
import os
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

import iskra_assistant as assistant
from iskra_index import EXT, extract

KINDS = [
    (re.compile(r'^\s*(шифр)?телеграмм|^\s*телефонограмм', re.IGNORECASE | re.MULTILINE), 'Телеграмма'),
    (re.compile(r'^\s*приказ\b', re.IGNORECASE | re.MULTILINE), 'Приказ'),
    (re.compile(r'^\s*распоряжени', re.IGNORECASE | re.MULTILINE), 'Распоряжение'),
    (re.compile(r'^\s*(указани[ея]|директив)', re.IGNORECASE | re.MULTILINE), 'Указание'),
    (re.compile(r'^\s*(донесени|доклад|рапорт)', re.IGNORECASE | re.MULTILINE), 'Доклад'),
    (re.compile(r'^\s*(акт|протокол)\b', re.IGNORECASE | re.MULTILINE), 'Акт / протокол'),
    (re.compile(r'^\s*(уважаем|прошу|направляю|сообщаю|доводим|довожу)', re.IGNORECASE | re.MULTILINE), 'Письмо'),
]
FROM = re.compile(r'^\s*(от кого|отправитель|от)\s*:\s*(.+)$', re.IGNORECASE | re.MULTILINE)
STATUSES = ('новый', 'в работе', 'выполнен')


def same(a, b):
    """Один и тот же файл: на Windows путь может быть записан по-разному (регистр, короткие имена RUNNER~1)."""
    if a == b:
        return True
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def _now():
    return datetime.now().strftime('%d.%m.%Y %H:%M')


def kind_of(path, text):
    ext = Path(path).suffix.lower()
    if ext in ('.xlsx', '.xlsm', '.csv'):
        return 'Таблица Excel'
    head = '\n'.join(text.strip().splitlines()[:12])
    for pattern, name in KINDS:
        if pattern.search(head):
            return name
    return 'Документ'


def sender_of(text):
    m = FROM.search(text)
    if m:
        return m.group(2).strip()[:120]
    from iskra_telegram import parse
    t = parse('', text)
    return ' '.join(t.signature)[:120] if t.signature else ''


def analyze(path, today=None):
    """Разбор одного файла: словарь для журнала. Не бросает исключений — ошибка пишется в поле «note»."""
    path = Path(path)
    item = {'path': str(path), 'name': path.name, 'added': _now(), 'status': 'новый', 'kind': 'Документ',
            'number': '', 'date': '', 'sender': '', 'deadline': '', 'deadline_text': '', 'summary': '', 'note': ''}
    try:
        text = extract(path) or ''
    except Exception as exc:
        item['note'] = f'не удалось прочитать: {exc}'[:200]
        return item
    item['kind'] = kind_of(path, text)
    if item['kind'] != 'Таблица Excel':
        from iskra_compose import reference
        number, when = reference(text)
        item['number'] = f'№ {number}' if number else ''
        item['date'] = when
    if item['kind'] != 'Таблица Excel':
        item['sender'] = sender_of(text)
    soon = [d for d in assistant.deadlines(text, today) if d.sort_key >= (today or date.today())] or assistant.deadlines(text, today)
    if soon:
        item['deadline'] = soon[0].value
        item['deadline_text'] = soon[0].context[:300]
    if item['kind'] == 'Таблица Excel' and path.suffix.lower() in ('.xlsx', '.xlsm'):
        try:
            from iskra_svod import read_tables
            tables = read_tables(path)
            if tables:
                rows = sum(len(t.rows) for t in tables)
                item['summary'] = f'таблица по организациям: {rows} строк, столбцы: ' + ', '.join(tables[0].columns[:6])
                item['svod'] = True
        except Exception:
            pass
    if not item['summary']:
        item['summary'] = ' '.join(assistant.summary(text, 2))[:400]
    return item


class Inbox:
    """Слежение за папками входящих. notify(items) вызывается из фонового потока со списком новых записей."""

    def __init__(self, root, notify=None, interval=30):
        self.path = Path(root) / 'inbox.json'
        self.notify = notify
        self.interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._pending = {}                 # путь -> (размер, время) — файл ещё копируется
        try:
            self.state = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault('folders', [])
        self.state.setdefault('seen', {})
        self.state.setdefault('items', [])

    # ---------- настройки ----------

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, self.path)

    def folders(self):
        with self._lock:
            return list(self.state['folders'])

    def add_folder(self, folder, take_existing=False):
        """Новая папка. Уже лежащие в ней файлы считаются старыми (take_existing=True — разобрать и их)."""
        folder = str(Path(folder).resolve())
        with self._lock:
            if folder in self.state['folders']:
                return
            self.state['folders'].append(folder)
            if not take_existing:
                for p in self._files(folder):
                    self.state['seen'][str(p)] = self._sign(p)
            self._save()
        self._wake.set()

    def remove_folder(self, folder):
        folder = str(Path(folder).resolve())
        with self._lock:
            if folder in self.state['folders']:
                self.state['folders'].remove(folder)
                self._save()

    # ---------- журнал ----------

    def items(self):
        with self._lock:
            return [dict(i) for i in self.state['items']]

    def set_status(self, path, status):
        with self._lock:
            for i in self.state['items']:
                if same(i['path'], path):
                    i['status'] = status
            self._save()

    def update(self, path, **fields):
        with self._lock:
            for i in self.state['items']:
                if same(i['path'], path):
                    i.update(fields)
            self._save()

    def forget(self, path):
        with self._lock:
            self.state['items'] = [i for i in self.state['items'] if not same(i['path'], path)]
            self._save()

    def counts(self):
        with self._lock:
            new = sum(1 for i in self.state['items'] if i['status'] == 'новый')
            work = sum(1 for i in self.state['items'] if i['status'] == 'в работе')
        return new, work

    # ---------- сканирование ----------

    @staticmethod
    def _files(folder):
        root = Path(folder)
        if not root.is_dir():
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(('.', '~')) and d != 'Обработано Искрой']
            if Path(dirpath).relative_to(root).parts.__len__() > 2:
                dirnames[:] = []
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() in EXT and not name.startswith(('~$', '.')):
                    yield p

    @staticmethod
    def _sign(p):
        try:
            st = p.stat()
            return [st.st_size, int(st.st_mtime)]
        except OSError:
            return None

    def scan(self, today=None, settle=2.0):
        """Один проход: новые и изменённые файлы. Файл, который ещё копируется (размер меняется), ждёт следующего прохода."""
        found = []
        for folder in self.folders():
            for p in self._files(folder):
                key, sign = str(p), self._sign(p)
                if sign is None:
                    continue
                with self._lock:
                    known = self.state['seen'].get(key)
                if known == sign:
                    continue
                prev = self._pending.get(key)
                if settle and (prev is None or prev[0] != sign):
                    self._pending[key] = (sign, time.time())
                    continue
                if settle and time.time() - prev[1] < settle:
                    continue
                self._pending.pop(key, None)
                item = analyze(p, today)
                item['changed'] = known is not None
                found.append(item)
                with self._lock:
                    self.state['seen'][key] = sign
                    self.state['items'] = [i for i in self.state['items'] if i['path'] != key]
                    self.state['items'].insert(0, item)
                    del self.state['items'][500:]
        if found:
            with self._lock:
                self._save()
        return found

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def check_now(self):
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                found = self.scan()
                if found and self.notify:
                    self.notify(found)
            except Exception:
                pass                       # сетевая папка пропала и т. п. — попробуем в следующий раз
            # Пока файл копируется — проверяем чаще.
            self._wake.wait(3 if self._pending else self.interval)
            self._wake.clear()
