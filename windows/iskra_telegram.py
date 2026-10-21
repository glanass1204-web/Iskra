"""Merge several telegrams into one draft: header fields are combined (conflicts are marked for checking),
repeated sentences are kept once, every point says which telegram it came from. Nothing is invented."""
import re

FIELD = re.compile(r'^\s*(Кому|От кого|Отправитель|Адресат|Дата|Номер|№|Исх\.?\s*№?|Тема|О чем|Срочность|Гриф|Подпись)\s*:\s*(.*)$',
                   re.IGNORECASE)
CANON = {'кому': 'Кому', 'адресат': 'Кому', 'от кого': 'От кого', 'отправитель': 'От кого', 'дата': 'Дата',
         'номер': 'Номер', '№': 'Номер', 'исх': 'Номер', 'тема': 'Тема', 'о чем': 'Тема', 'срочность': 'Срочность',
         'гриф': 'Гриф', 'подпись': 'Подпись'}
ORDER = ['Гриф', 'Срочность', 'Кому', 'От кого', 'Дата', 'Номер', 'Тема']
TITLE = re.compile(r'^\s*(ТЕЛЕГРАММА|ТЕЛЕФОНОГРАММА|ШИФРТЕЛЕГРАММА)\s*$', re.IGNORECASE)
TEXT_LABEL = re.compile(r'^\s*Текст\s*:\s*', re.IGNORECASE)
SPLIT = re.compile(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9«"])')


def _canon(label):
    key = re.sub(r'[\s.№]+$', '', label.strip().lower().replace('ё', 'е'))
    key = 'исх' if key.startswith('исх') else key
    return CANON.get(key, label.strip().capitalize())


def _key(sentence):
    return re.sub(r'[^\wа-яё]+', ' ', sentence.lower().replace('ё', 'е')).strip()


def parse(text):
    fields, body, title = {}, [], 'ТЕЛЕГРАММА'
    for line in text.replace('\r\n', '\n').split('\n'):
        if TITLE.match(line):
            title = line.strip().upper()
            continue
        m = FIELD.match(line)
        if m and m.group(2).strip():
            fields.setdefault(_canon(m.group(1)), []).append(m.group(2).strip())
            continue
        line = TEXT_LABEL.sub('', line).strip()
        if line:
            body.append(line)
    return title, fields, body


def merge_telegrams(sources):
    """sources: [(name, text)], at least two. Returns (merged text, [report lines])."""
    if len(sources) < 2:
        raise ValueError('Выберите хотя бы две телеграммы.')
    parsed = [(name,) + parse(text) for name, text in sources]
    report = []
    header = {}
    for field in ORDER + ['Подпись']:
        values = []
        for _, _, fields, _ in parsed:
            for v in fields.get(field, []):
                if v not in values:
                    values.append(v)
        if not values:
            continue
        if field in ('Кому', 'Тема'):
            header[field] = '; '.join(values)
        elif field in ('Дата', 'Номер'):
            header[field] = f'[{field.upper()}]'
            if len(values) > 1:
                report.append(f'{field}: в исходных телеграммах разные значения ({", ".join(values)}) — укажите новые.')
        elif len(values) == 1:
            header[field] = values[0]
        else:
            header[field] = '[УТОЧНИТЬ: ' + ' / '.join(values) + ']'
            report.append(f'{field}: значения различаются — {" / ".join(values)}.')
    seen = set()
    points = []
    dropped = 0
    for name, _, _, body in parsed:
        kept = []
        for paragraph in body:
            sentences = []
            for s in SPLIT.split(paragraph):
                k = _key(s)
                if not k:
                    continue
                if k in seen:
                    dropped += 1
                    continue
                seen.add(k)
                sentences.append(s.strip())
            if sentences:
                kept.append(' '.join(sentences))
        if kept:
            points.append((name, kept))
        else:
            report.append(f'«{name}»: весь текст повторяет другие телеграммы.')
    if dropped:
        report.append(f'Убрано повторяющихся предложений: {dropped}.')
    titles = {t for _, t, _, _ in parsed}
    lines = [titles.pop() if len(titles) == 1 else 'ТЕЛЕГРАММА', '']
    for field in ORDER:
        if field in header:
            lines.append(f'{field}: {header[field]}')
    for field in ('Дата', 'Номер'):
        if field not in header:
            lines.append(f'{field}: [{field.upper()}]')
    lines += ['', 'Текст:']
    for i, (name, paragraphs) in enumerate(points, 1):
        first, *rest = paragraphs
        lines.append(f'{i}. {first}')
        lines += rest
    lines += ['', 'Подпись: ' + header.get('Подпись', '[ФИО]')]
    lines += ['', '--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---']
    lines += [f'{i}. {name}' for i, (name, _) in enumerate(points, 1)]
    report.insert(0, f'Объединено телеграмм: {len(sources)}, пунктов: {len(points)}.')
    return '\n'.join(lines), report
