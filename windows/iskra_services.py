"""Local-only background indexing, templates, and document helpers."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path


def settings_path(root):
    return Path(root) / 'settings.json'


def load_settings(root):
    try:
        data = json.loads(settings_path(root).read_text(encoding='utf-8'))
        return {'folders': [str(Path(p).resolve()) for p in data.get('folders', []) if Path(p).is_dir()],
                'interval_minutes': max(1, int(data.get('interval_minutes', 15)))}
    except (OSError, ValueError, TypeError):
        return {'folders': [], 'interval_minutes': 15}


def save_settings(root, data):
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


class AutoIndexer:
    """Single-worker periodic scan; avoids overlapping SQLite writes."""
    def __init__(self, root, index_fn, notify):
        self.root = root
        self.index_fn = index_fn
        self.notify = notify
        self.settings = load_settings(root)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def add_folder(self, folder):
        folder = str(Path(folder).resolve())
        with self._lock:
            if folder not in self.settings['folders']:
                self.settings['folders'].append(folder)
                save_settings(self.root, self.settings)
        self._wake.set()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def scan_now(self):
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                folders = list(self.settings['folders'])
                interval = self.settings['interval_minutes'] * 60
            for folder in folders:
                if self._stop.is_set():
                    break
                if not Path(folder).is_dir():
                    self.notify(f'Папка недоступна: {folder}')
                    continue
                self.notify(f'Проверка изменений: {folder}')
                try:
                    self.index_fn(folder, self.notify)
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self.notify(f'Ошибка обновления индекса: {exc}')
            self._wake.wait(interval)
            self._wake.clear()


def telegram_check(text):
    """Deterministic preflight; never invents facts or silently changes text."""
    issues = []
    if not text.strip():
        return ['Документ пуст.']
    if '  ' in text:
        issues.append('Есть повторяющиеся пробелы.')
    if '\t' in text:
        issues.append('Есть табуляция — проверьте оформление.')
    if '\n\n\n' in text:
        issues.append('Есть лишние пустые строки.')
    if any(mark in text for mark in ('[УТОЧНИТЬ]', '[ФИО]', '[ДАТА]', '[НОМЕР]')):
        issues.append('Остались незаполненные поля шаблона.')
    if not text.rstrip().endswith(('.', '!', '?', '»', '"')):
        issues.append('Проверьте знак препинания в конце.')
    issues.append('Орфография и фактическая точность требуют отдельной проверки: локальный языковой модуль пока не подключён.')
    return issues


def telegram_template():
    return ('ТЕЛЕГРАММА\n\n'
            'Кому: [УТОЧНИТЬ]\n'
            'От кого: [УТОЧНИТЬ]\n'
            'Дата: [ДАТА]\n'
            'Номер: [НОМЕР]\n\n'
            'Текст: [УТОЧНИТЬ]\n\n'
            'Подпись: [ФИО]\n')


def excel_formula(task):
    """Small explicit rule catalog; never claims general language understanding."""
    q = task.casefold()
    if 'сумм' in q:
        return '=СУММ(A2:A100)', 'Замените A2:A100 на нужный диапазон.'
    if 'средн' in q:
        return '=СРЗНАЧ(A2:A100)', 'Среднее арифметическое чисел в диапазоне.'
    if 'колич' in q and ('услов' in q or 'совпад' in q):
        return '=СЧЁТЕСЛИ(A2:A100;"Готово")', 'Измените диапазон и искомое значение.'
    if 'дней' in q or ('разниц' in q and 'дат' in q):
        return '=C4-B4', 'Если в B4 начальная дата, а в C4 конечная; ячейку результата оформите числом.'
    if 'если' in q or 'услов' in q:
        return '=ЕСЛИ(A2>0;"Да";"Нет")', 'Замените условие и возвращаемые значения.'
    if 'поиск' in q or 'впр' in q:
        return '=ВПР(E2;A:B;2;ЛОЖЬ)', 'Точное совпадение; ключ поиска должен находиться в первом столбце диапазона.'
    return None, 'Для произвольного запроса нужен локальный ИИ. Пока доступны типовые формулы: сумма, среднее, количество по условию, разница дат, ЕСЛИ, ВПР.'
