"""Искра учится на правках: что нейросеть написала → что человек сохранил в Word.
Из пар «было/стало» выводятся устойчивые правки (повторились хотя бы в двух документах): «вместо «прошу
представить» пишите «представить»», «не пишите «в кратчайшие сроки»». Они и последний утверждённый текст
(с замаскированными датами и номерами — чтобы старые факты не переносились) добавляются к задаче нейросети.
Всё хранится только на этом компьютере: data/learned_edits.jsonl. Забыть — меню Файл."""
import difflib
import json
import re
import time
from collections import Counter

KEEP = 40                      # последних пар хватает, старая манера постепенно забывается
MAX_SPAN = 6                   # правка длиннее — это уже смысл, а не манера
TAIL = re.compile(r'\n-{3}\s*(ИСТОЧНИКИ|МАТЕРИАЛЫ)', re.IGNORECASE)
WORD = re.compile(r'\S+')
FACT = re.compile(r'^[\d.,:;№/\-–—()«»"\[\]]+$')


def _file():
    from iskra_index import ROOT
    return ROOT / 'learned_edits.jsonl'


def body(text):
    """Текст документа без приложенного списка источников."""
    m = TAIL.search(text or '')
    return (text[:m.start()] if m else text or '').strip()


def _words(text):
    return WORD.findall(text)


def similarity(a, b):
    return difflib.SequenceMatcher(None, _words(a), _words(b), autojunk=False).ratio()


def load():
    try:
        lines = _file().read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def remember(ai_text, final_text):
    """Запомнить правку, если человек поправил текст нейросети, а не заменил его другим. True — запомнено."""
    a, b = body(ai_text), body(final_text)
    if not a or not b or a == b:
        return False
    ratio = similarity(a, b)
    if ratio > 0.995 or ratio < 0.35:              # почти без правок или вовсе другой документ
        return False
    if not changes(a, b):
        return False                               # правились только цифры и даты — это факты, не манера
    pairs = load()
    if pairs and pairs[-1].get('ai') == a[:5000]:
        pairs.pop()                                # тот же документ сохранили ещё раз — одна пара, не две
    pairs.append({'time': time.strftime('%Y-%m-%d %H:%M'), 'ai': a[:5000], 'final': b[:5000]})
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(p, ensure_ascii=False) + '\n' for p in pairs[-KEEP:]), encoding='utf-8')
    return True


def _clean(words):
    return ' '.join(words).strip(' ,.;:')


def changes(a, b):
    """Короткие правки манеры: [(было, стало)]; «стало» пустое — фразу удалили. Цифры и даты пропускаются."""
    wa, wb = _words(a), _words(b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op not in ('replace', 'delete'):
            continue
        old, new = wa[i1:i2], wb[j1:j2]
        if len(old) > MAX_SPAN or len(new) > MAX_SPAN:
            continue
        if all(FACT.match(w) for w in old + new):
            continue
        old_s, new_s = _clean(old), _clean(new)
        if old_s and old_s.lower() != new_s.lower():
            out.append((old_s, new_s))
    return out


def rules(pairs=None, min_count=2, limit=12):
    """Правки, повторившиеся хотя бы в min_count документах."""
    pairs = load() if pairs is None else pairs
    seen = Counter()
    for p in pairs:
        seen.update({(o.lower(), n.lower()) for o, n in changes(p.get('ai', ''), p.get('final', ''))})
    out = []
    for (old, new), n in seen.most_common():
        if n < min_count or len(out) >= limit:
            continue
        out.append(f'вместо «{old}» пишите «{new}»' if new else f'не пишите «{old}»')
    return out


def mask(text):
    """Старые даты и номера — в пометки, чтобы нейросеть не перенесла их в новый документ."""
    text = re.sub(r'\b\d{1,2}\.\d{1,2}\.\d{2,4}\b', '[ДАТА]', text)
    text = re.sub(r'№\s*[\w/.-]+', '№ [НОМЕР]', text)
    return re.sub(r'\b\d{2,}\b', '[N]', text)


def prompt_block(max_chars=1500, example=True):
    """Добавка к задаче нейросети. Пусто, если человек ещё ничего не правил."""
    pairs = load()
    if not pairs:
        return ''
    rs = rules(pairs)
    if not example and not rs:
        return ''
    out = '\nКак пользователь правит такие тексты — пиши сразу в его манере:\n'
    if rs:
        out += '\n'.join('- ' + r for r in rs) + '\n'
    if not example:
        return out
    out += ('Последний текст в том виде, как его утвердил пользователь (образец манеры и порядка частей; факты, номера, '
            'даты и адресатов из него НЕ переносить):\n---\n' + mask(pairs[-1]['final'])[:max_chars] + '\n---\n')
    return out


def count():
    return len(load())


def forget():
    try:
        _file().unlink()
    except OSError:
        pass
