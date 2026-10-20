"""Local-only background indexing, templates, and document helpers."""
import json
import os
import sqlite3
import threading
from pathlib import Path


def settings_path(root):
    return Path(root) / 'settings.json'


def load_settings(root):
    try:
        data = json.loads(settings_path(root).read_text(encoding='utf-8'))
        # Keep folders that are offline right now (network drive, USB): the indexer reports them,
        # and dropping them here would erase them from settings on the next save.
        return {'folders': [str(Path(p).resolve()) for p in data.get('folders', []) if str(p).strip()],
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

    def remove_folder(self, folder):
        folder = str(Path(folder).resolve())
        with self._lock:
            if folder in self.settings['folders']:
                self.settings['folders'].remove(folder)
                save_settings(self.root, self.settings)

    def folders(self):
        with self._lock:
            return list(self.settings['folders'])

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


FORMULAS = [
    # (ключевые слова — все должны встретиться, формула, пояснение). Порядок важен: сначала более точные.
    (('сумм', 'услов'), '=СУММЕСЛИ(A2:A100;"Москва";B2:B100)', 'Сумма чисел из B, где в A стоит «Москва».'),
    (('сумм', 'нескольк'), '=СУММЕСЛИМН(C2:C100;A2:A100;"Москва";B2:B100;">=01.01.2026")', 'Сумма по нескольким условиям.'),
    (('колич', 'нескольк'), '=СЧЁТЕСЛИМН(A2:A100;"Москва";B2:B100;"Готово")', 'Количество строк, где выполнены оба условия.'),
    (('колич', 'услов'), '=СЧЁТЕСЛИ(A2:A100;"Готово")', 'Количество ячеек с заданным значением.'),
    (('колич', 'непуст'), '=СЧЁТЗ(A2:A100)', 'Количество заполненных ячеек.'),
    (('колич', 'пуст'), '=СЧИТАТЬПУСТОТЫ(A2:A100)', 'Количество пустых ячеек.'),
    (('средн', 'услов'), '=СРЗНАЧЕСЛИ(A2:A100;"Москва";B2:B100)', 'Среднее по условию.'),
    (('рабоч', 'дн'), '=ЧИСТРАБДНИ(B2;C2)', 'Рабочие дни между датами B2 и C2 (праздники — третьим аргументом).'),
    (('лет',), '=РАЗНДАТ(B2;СЕГОДНЯ();"y")', 'Полных лет с даты в B2 до сегодня (стаж, возраст).'),
    (('месяц', 'между'), '=РАЗНДАТ(B2;C2;"m")', 'Полных месяцев между датами.'),
    (('дней',), '=C2-B2', 'Дней между датами B2 и C2; ячейку результата оформите числом.'),
    (('разниц', 'дат'), '=C2-B2', 'Дней между датами B2 и C2; ячейку результата оформите числом.'),
    (('сегодн',), '=СЕГОДНЯ()', 'Текущая дата, обновляется при открытии файла.'),
    (('впр',), '=ВПР(E2;A:B;2;ЛОЖЬ)', 'Ищет E2 в первом столбце A:B и возвращает значение из второго. ЛОЖЬ — точное совпадение.'),
    (('найти', 'значен'), '=ИНДЕКС(B:B;ПОИСКПОЗ(E2;A:A;0))', 'Поиск значения: надёжнее ВПР, искомый столбец может быть где угодно.'),
    (('подтян',), '=ЕСЛИОШИБКА(ВПР(E2;Лист2!A:B;2;ЛОЖЬ);"нет")', 'Подтянуть данные с другого листа, «нет» — если не найдено.'),
    (('ошибк',), '=ЕСЛИОШИБКА(A2/B2;0)', 'Вместо ошибки (#ДЕЛ/0!, #Н/Д) показать 0 или другой текст.'),
    (('процент',), '=B2/C2', 'Доля B2 от C2; ячейку оформите в формате «Процентный».'),
    (('округл',), '=ОКРУГЛ(A2;2)', 'Округлить до 2 знаков после запятой.'),
    (('объедин',), '=СЦЕП(A2;" ";B2)', 'Склеить текст из ячеек через пробел (в старых Excel — СЦЕПИТЬ).'),
    (('сцеп',), '=СЦЕП(A2;" ";B2)', 'Склеить текст из ячеек через пробел (в старых Excel — СЦЕПИТЬ).'),
    (('дат', 'текст'), '=ТЕКСТ(A2;"ДД.ММ.ГГГГ")', 'Дата как текст в нужном формате.'),
    (('пробел',), '=СЖПРОБЕЛЫ(A2)', 'Убрать лишние пробелы из текста.'),
    (('макс',), '=МАКС(A2:A100)', 'Наибольшее значение.'),
    (('мин',), '=МИН(A2:A100)', 'Наименьшее значение.'),
    (('уник',), '=УНИК(A2:A100)', 'Список без повторов (Excel 2021/365).'),
    (('сумм',), '=СУММ(A2:A100)', 'Сумма диапазона. Замените A2:A100 на нужный.'),
    (('средн',), '=СРЗНАЧ(A2:A100)', 'Среднее арифметическое.'),
    (('колич',), '=СЧЁТ(A2:A100)', 'Количество чисел в диапазоне.'),
    (('если',), '=ЕСЛИ(A2>0;"Да";"Нет")', 'Замените условие и возвращаемые значения.'),
    (('услов',), '=ЕСЛИ(A2>0;"Да";"Нет")', 'Замените условие и возвращаемые значения.'),
]


def excel_formula(task):
    """Explicit rule catalog for the Russian Excel locale; never claims general language understanding."""
    q = task.casefold().replace('ё', 'е')
    for words, formula, note in FORMULAS:
        if all(w in q for w in words):
            return formula, note + ' Формулы для русского Excel; проверьте диапазоны.'
    return None, ('Не нашла подходящую формулу. Попробуйте: сумма, сумма по условию, количество по условию, среднее, '
                  'ВПР, найти значение, подтянуть с другого листа, рабочие дни, лет (стаж), разница дат, '
                  'процент, округлить, объединить текст, убрать пробелы, если ошибка, уникальные.')
