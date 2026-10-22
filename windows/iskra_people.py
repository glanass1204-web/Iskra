"""Справочник людей и организаций: ФИО, звание, должность, организация. Искра ставит их в нужный падеж
(«Начальнику госпиталя полковнику медицинской службы Иванову И.И.»), подсказывает нейросети верные должности
и замечает в тексте фамилию с чужой должностью или званием. Хранится в data/people.json, правится в окне
или через Excel (выгрузить → поправить → загрузить)."""
import json
import os
import re
from pathlib import Path

FIELDS = ['fio', 'rank', 'position', 'org', 'sex', 'note']
TITLES = {'fio': 'Фамилия И.О.', 'rank': 'Звание', 'position': 'Должность', 'org': 'Организация',
          'sex': 'Пол (м/ж)', 'note': 'Заметка'}

_MORPH = None


def morph():
    global _MORPH
    if _MORPH is None:
        try:
            import pymorphy3
            _MORPH = pymorphy3.MorphAnalyzer()
        except Exception:
            _MORPH = False
    return _MORPH or None


CASES = {'datv': 'кому', 'gent': 'кого', 'ablt': 'кем', 'nomn': 'кто'}


def _keep_case(src, word):
    if src.isupper() and len(src) > 1:
        return word.upper()
    if src[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def _inflect_word(word, case, want_adj=False):
    m = morph()
    if '-' in word:                                  # генерал-майор → генерал-майору: склоняется последняя часть
        head, _, last = word.rpartition('-')
        return head + '-' + _inflect_word(last, case)
    if m is None:
        return _rule_word(word, case)
    parses = [p for p in m.parse(word.lower()) if 'nomn' in p.tag]
    if want_adj:
        parses = [p for p in parses if {'ADJF'} & p.tag.grammemes] or parses
    for p in parses:
        if 'plur' in p.tag:
            continue
        form = p.inflect({case})
        if form:
            return _keep_case(word, form.word)
    return word


def _rule_word(word, case):
    """Запасные правила, если словарь не загрузился (только дательный падеж мужского рода)."""
    if case != 'datv':
        return word
    low = word.lower()
    for end, new in (('ый', 'ому'), ('ой', 'ому'), ('ий', 'ему'), ('ь', 'ю'), ('й', 'ю'), ('а', 'е')):
        if low.endswith(end):
            return _keep_case(word, low[:-len(end)] + new)
    if low[-1:] in 'бвгджзклмнпрстфхцчшщ':
        return _keep_case(word, low + 'у')
    return word


def inflect_phrase(phrase, case='datv'):
    """Должность или звание: склоняются начальные согласованные слова до первого существительного
    («старший помощник начальника» → «старшему помощнику начальника»)."""
    words = phrase.split()
    out, done = [], False
    for w in words:
        if done or not re.match(r'^[А-Яа-яЁё-]+$', w):
            out.append(w); continue
        # Прилагательное перед существительным («старший», «главный», «первый»): склоняем и идём дальше.
        is_noun = not (w.lower().endswith(('ый', 'ий', 'ой', 'ая', 'яя')) and len(out) + 1 < len(words))
        out.append(_inflect_word(w, case, want_adj=not is_noun))
        if is_noun:
            done = True
    return ' '.join(out)


SURNAME_RULES_M = [('ский', {'datv': 'скому', 'gent': 'ского', 'ablt': 'ским'}),
                   ('цкий', {'datv': 'цкому', 'gent': 'цкого', 'ablt': 'цким'}),
                   ('ой', {'datv': 'ому', 'gent': 'ого', 'ablt': 'ым'}),
                   ('ый', {'datv': 'ому', 'gent': 'ого', 'ablt': 'ым'}),
                   ('ий', {'datv': 'ию', 'gent': 'ия', 'ablt': 'ием'})]
SURNAME_RULES_F = [('ская', {'datv': 'ской', 'gent': 'ской', 'ablt': 'ской'}),
                   ('цкая', {'datv': 'цкой', 'gent': 'цкой', 'ablt': 'цкой'}),
                   ('ова', {'datv': 'овой', 'gent': 'овой', 'ablt': 'овой'}),
                   ('ева', {'datv': 'евой', 'gent': 'евой', 'ablt': 'евой'}),
                   ('ёва', {'datv': 'ёвой', 'gent': 'ёвой', 'ablt': 'ёвой'}),
                   ('ина', {'datv': 'иной', 'gent': 'иной', 'ablt': 'иной'}),
                   ('ына', {'datv': 'ыной', 'gent': 'ыной', 'ablt': 'ыной'}),
                   ('ская', {'datv': 'ской', 'gent': 'ской', 'ablt': 'ской'}),
                   ('ая', {'datv': 'ой', 'gent': 'ой', 'ablt': 'ой'}),
                   ('яя', {'datv': 'ей', 'gent': 'ей', 'ablt': 'ей'})]
UNDECLINED = ('ко', 'их', 'ых', 'аго', 'яго', 'о', 'е', 'и', 'у', 'ю', 'э')


def inflect_surname(surname, case='datv', sex='м'):
    if case == 'nomn':
        return surname
    if '-' in surname:
        return '-'.join(inflect_surname(p, case, sex) for p in surname.split('-'))
    low = surname.lower()
    female = (sex or 'м').lower().startswith('ж')
    if low.endswith(UNDECLINED):
        return surname
    for end, forms in (SURNAME_RULES_F if female else SURNAME_RULES_M):
        if low.endswith(end):
            return _keep_case(surname, low[:-len(end)] + forms[case])
    if female:
        return surname                                 # Кох, Шмидт (ж) — не склоняются
    if low.endswith(('ов', 'ев', 'ёв', 'ин', 'ын')):
        return _keep_case(surname, low + {'datv': 'у', 'gent': 'а', 'ablt': 'ым'}[case])
    if low[-1:] in 'бвгджзклмнпрстфхцчшщ':            # Шмидт, Кравец → Шмидту, Кравцу (беглую гласную не трогаем)
        return _keep_case(surname, low + {'datv': 'у', 'gent': 'а', 'ablt': 'ом'}[case])
    if low.endswith('ь'):
        return _keep_case(surname, low[:-1] + {'datv': 'ю', 'gent': 'я', 'ablt': 'ем'}[case])
    if low.endswith('а'):
        gent = 'и' if low[-2:-1] in 'гкхжшщч' else 'ы'
        return _keep_case(surname, low[:-1] + {'datv': 'е', 'gent': gent, 'ablt': 'ой'}[case])
    if low.endswith('я'):
        return _keep_case(surname, low[:-1] + {'datv': 'е', 'gent': 'и', 'ablt': 'ей'}[case])
    return surname


FIO = re.compile(r'^\s*([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?)\s*$')
FIO_REV = re.compile(r'^\s*([А-ЯЁ]\.\s?(?:[А-ЯЁ]\.)?)\s*([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s*$')


def split_fio(fio):
    """«Иванов И.И.» или «И.И. Иванов» → (фамилия, инициалы)."""
    m = FIO.match(fio or '')
    if m:
        return m.group(1), m.group(2).replace(' ', '')
    m = FIO_REV.match(fio or '')
    if m:
        return m.group(2), m.group(1).replace(' ', '')
    parts = (fio or '').split()
    return (parts[0], ' '.join(parts[1:])) if parts else ('', '')


def addressee(person, case='datv'):
    """Строки адресата: должность, звание, фамилия с инициалами — в нужном падеже."""
    surname, initials = split_fio(person.get('fio', ''))
    lines = []
    if person.get('position'):
        pos = inflect_phrase(person['position'], case)
        lines.append(pos[:1].upper() + pos[1:])
    if person.get('rank'):
        lines.append(inflect_phrase(person['rank'], case))
    if surname:
        lines.append(f'{inflect_surname(surname, case, person.get("sex", "м"))} {initials}'.strip())
    return lines


def signature(person):
    """Подпись: должность, звание, И.О. Фамилия (именительный падеж)."""
    surname, initials = split_fio(person.get('fio', ''))
    lines = [x for x in (person.get('position', ''), person.get('rank', '')) if x]
    if surname:
        lines.append(f'{initials} {surname}'.strip())
    lines[:1] = [lines[0][:1].upper() + lines[0][1:]] if lines else []
    return '\n'.join(lines)


class People:
    def __init__(self, root):
        self.path = Path(root) / 'people.json'
        try:
            self.items = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.items = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, self.path)

    def add(self, **fields):
        item = {f: str(fields.get(f, '') or '').strip() for f in FIELDS}
        if not item['fio']:
            return None
        self.items = [p for p in self.items if p['fio'].lower() != item['fio'].lower()] + [item]
        self.items.sort(key=lambda p: p['fio'].lower())
        self.save()
        return item

    def remove(self, fio):
        self.items = [p for p in self.items if p['fio'] != fio]
        self.save()

    def find(self, text):
        """Люди, чья фамилия (в любом падеже) или организация встречается в тексте."""
        low = (text or '').lower().replace('ё', 'е')
        out = []
        for p in self.items:
            surname, _ = split_fio(p['fio'])
            stem = surname.lower().replace('ё', 'е')[:max(4, len(surname) - 2)]
            if (stem and re.search(r'\b' + re.escape(stem), low)) or (p['org'] and p['org'].lower() in low):
                out.append(p)
        return out

    def context(self, text, limit=8):
        """Строки для нейросети: верные должности и звания упомянутых людей."""
        return [f'{p["fio"]} — {p["rank"]} {p["position"]} {("(" + p["org"] + ")") if p["org"] else ""}'.replace('  ', ' ').strip()
                for p in self.find(text)[:limit]]

    # ---------- Excel ----------

    def to_xlsx(self, path):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = 'Справочник'
        ws.append([TITLES[f] for f in FIELDS])
        for c in ws[1]:
            c.font = Font(bold=True)
        for p in self.items:
            ws.append([p.get(f, '') for f in FIELDS])
        for col, width in zip('ABCDEF', (24, 28, 40, 30, 10, 30)):
            ws.column_dimensions[col].width = width
        wb.save(path)

    def from_xlsx(self, path):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(wb.worksheets[0].iter_rows(values_only=True))
        finally:
            wb.close()
        if not rows:
            return 0
        head = [str(h or '').strip().lower() for h in rows[0]]
        index = {}
        for f in FIELDS:
            title = TITLES[f].lower()
            for i, h in enumerate(head):
                if h == title or h.startswith(title.split()[0].lower()):
                    index[f] = i
                    break
        if 'fio' not in index:
            index = {f: i for i, f in enumerate(FIELDS)}      # без заголовков — по порядку столбцов
            rows = [rows[0]] + rows
        n = 0
        for r in rows[1:]:
            fields = {f: (r[i] if i < len(r) and r[i] is not None else '') for f, i in index.items()}
            if self.add(**fields):
                n += 1
        return n


SURNAME_IN_TEXT = re.compile(r'([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?([А-ЯЁ][а-яё]+)')


def mismatches(text, people):
    """Фамилия из справочника, а рядом (в той же строке или строкой выше) — чужая должность или звание."""
    out = []
    if not people.items:
        return out
    lines = text.splitlines()
    m = morph()

    def lemma(w):
        return m.parse(w.lower())[0].normal_form if m is not None else w.lower()
    ranks = {lemma(p['rank'].split()[-1]) for p in people.items if p['rank']}
    for i, line in enumerate(lines):
        for match in SURNAME_IN_TEXT.finditer(line):
            name = match.group(1) or match.group(2)
            found = [p for p in people.find(name) if split_fio(p['fio'])[0].lower()[:4] == name.lower()[:4]]
            if len(found) != 1:
                continue
            p = found[0]
            around = ' '.join(lines[max(0, i - 2):i + 1]).lower()
            words = {lemma(w) for w in re.findall(r'[а-яё]+', around)}
            if p['rank']:
                own = lemma(p['rank'].split()[-1])
                other = (ranks - {own}) & words
                if other and own not in words:
                    out.append(f'{name}: в справочнике звание «{p["rank"]}», а в тексте рядом — «{sorted(other)[0]}».')
    return out
