"""Искра сама учится по документам в папках поиска (в фоне, раз в несколько часов):
1) Люди: подписи и упоминания вида «Начальник штаба / полковник / И.И. Иванов» → кандидаты в справочник
   (data/people_found.json). В справочник попадают только те, кого человек подтвердит, — Искра лишь предлагает.
2) Словарь: слова, которые часто встречаются в ваших документах (названия, сокращения, термины), но которых нет в
   общем словаре, — data/auto_words.txt. Проверка орфографии перестаёт их подчёркивать. Частая опечатка не
   выучивается: если рядом в документах намного чаще встречается правильное слово, похожее на неё, — это опечатка."""
import json
import os
import re
import time
from collections import Counter, defaultdict

RANK_WORDS = ('рядовой', 'ефрейтор', 'младший сержант', 'старший сержант', 'сержант', 'старшина', 'старший прапорщик',
              'прапорщик', 'младший лейтенант', 'старший лейтенант', 'лейтенант', 'капитан', 'майор', 'подполковник',
              'полковник', 'генерал-майор', 'генерал-лейтенант', 'генерал-полковник', 'генерал армии')
RANK = r'(?i:' + '|'.join(re.escape(r) for r in RANK_WORDS) + r')(?:\s+(?:медицинской|юстиции|внутренней|полиции)\s+службы|\s+юстиции)?'
INITIALS = r'[А-ЯЁ]\.\s?[А-ЯЁ]\.'
SURNAME = r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?'
# «полковник И.И. Иванов», «полковник Иванов И.И.» — именительный падеж (подпись, «исполнитель»)
PERSON = re.compile(rf'(?<![А-Яа-яЁё])({RANK})\s+(?:({INITIALS})\s?({SURNAME})|({SURNAME})\s({INITIALS}))(?![А-Яа-яЁё])')
POSITION = re.compile(r'^\s*((?:врио|вриод|и\.\s?о\.\s*)?(?:начальник|командир|заместитель|помощник|старший|главный|'
                      r'руководитель|директор|офицер|инспектор|специалист|заведующ\w+|дежурный|исполнитель)[^\n]{0,90})$',
                      re.IGNORECASE)
WORD = re.compile(r'(?<![А-Яа-яЁё-])[А-Яа-яЁё]{4,}(?:-[А-Яа-яЁё]{2,})*(?![А-Яа-яЁё])')
MAX_WORDS = 3000


def _root():
    from iskra_index import ROOT
    return ROOT


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


# ---------- люди ----------

def people_in(text):
    """[(фио «Иванов И.И.», звание, должность)] из текста. Должность — строка над званием в подписи."""
    out = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for m in PERSON.finditer(line):
            rank = re.sub(r'\s+', ' ', m.group(1)).lower()
            if m.group(2):
                surname, initials = m.group(3), m.group(2).replace(' ', '')
            else:
                surname, initials = m.group(4), m.group(5).replace(' ', '')
            if surname.lower() in RANK_WORDS:
                continue
            position = ''
            before = line[:m.start()].strip(' ,')
            if POSITION.match(before):
                position = before
            else:
                prev = [x for x in lines[max(0, i - 3):i] if x.strip()]
                for p in reversed(prev[-2:]):
                    if POSITION.match(p):
                        position = p.strip(' ,')
                        break
            out.append((f'{surname} {initials}', rank, position[:120]))
    return out


def harvest_people(docs, known):
    """docs: [(путь, текст)]; known — фамилии из справочника (нижний регистр). → кандидаты по убыванию частоты."""
    found = {}
    for path, text in docs:
        for fio, rank, position in people_in(text):
            surname = fio.split()[0].lower()
            if surname in known:
                continue
            c = found.setdefault(fio.lower(), {'fio': fio, 'rank': rank, 'position': position, 'count': 0,
                                               'file': os.path.basename(path), 'ranks': Counter(), 'positions': Counter()})
            c['count'] += 1
            c['ranks'][rank] += 1
            if position:
                c['positions'][position] += 1
    out = []
    for c in found.values():
        c['rank'] = c.pop('ranks').most_common(1)[0][0]                 # звание могли повысить — берём частое
        positions = c.pop('positions')
        c['position'] = positions.most_common(1)[0][0] if positions else ''
        c['position'] = c['position'][:1].upper() + c['position'][1:]
        out.append(c)
    out.sort(key=lambda c: (-c['count'], c['fio']))
    return out


def candidates():
    try:
        data = json.loads((_root() / 'people_found.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    hidden = set(data.get('hidden', []))
    return [c for c in data.get('found', []) if c['fio'].lower() not in hidden]


def hide(fios):
    path = _root() / 'people_found.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    data['hidden'] = sorted(set(data.get('hidden', [])) | {f.lower() for f in fios})
    _write_json(path, data)


# ---------- словарь ----------

def harvest_words(docs, known, suggest=None, min_docs=3, min_total=5):
    """Частые в своих документах слова, которых нет в словаре. known(слово) — есть ли в словаре;
    suggest(слово) — варианты исправления (для отсева частых опечаток)."""
    total, docs_with = Counter(), Counter()
    for _, text in docs:
        words = [w.lower().replace('ё', 'е') for w in WORD.findall(text)]
        total.update(words)
        docs_with.update(set(words))
    out = []
    for w, n in total.most_common():
        if docs_with[w] < min_docs or n < min_total:
            continue
        if known(w):
            continue
        if suggest is not None:
            try:
                variants = [s.lower().replace('ё', 'е') for s in suggest(w)[:5]]
            except Exception:                          # noqa: BLE001 — подсказки не обязательны
                variants = []
            if any(total.get(v, 0) >= 5 * n for v in variants if v != w):
                continue                               # рядом много правильного написания — это опечатка
        out.append(w)
        if len(out) >= MAX_WORDS:
            break
    return out


def auto_words():
    try:
        return {w.strip() for w in (_root() / 'auto_words.txt').read_text(encoding='utf-8').splitlines() if w.strip()}
    except OSError:
        return set()


# ---------- запуск ----------

def run(people=None, spell=None, max_docs=5000, pause=None):
    """Пройти по проиндексированным документам. people — справочник (iskra_people.People), spell — SpellChecker.
    pause() вызывается между документами (уступить окно). Возвращает {'people': n, 'words': n}."""
    from iskra_index import iter_documents
    docs = []
    for i, (path, content) in enumerate(iter_documents()):
        if i >= max_docs:
            break
        text = content if len(content) < 40_000 else content[:30_000] + '\n' + content[-6_000:]
        docs.append((path, text))
        if pause and i % 50 == 0:
            pause()
    result = {'people': 0, 'words': 0}
    known_people = set()
    if people is not None:
        from iskra_people import split_fio
        known_people = {split_fio(p['fio'])[0].lower().replace('ё', 'е') for p in people.items}
    found = harvest_people(docs, known_people)
    path = _root() / 'people_found.json'
    try:
        old = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        old = {}
    _write_json(path, {'time': time.strftime('%Y-%m-%d %H:%M'), 'found': found[:300], 'hidden': old.get('hidden', [])})
    result['people'] = len(candidates())
    if spell is not None and spell.available:
        words = harvest_words(docs, lambda w: spell.known(w, learned=False), spell.suggest)
        (_root() / 'auto_words.txt').write_text('\n'.join(words) + '\n', encoding='utf-8')
        spell.auto_words = set(words)
        result['words'] = len(words)
    return result
