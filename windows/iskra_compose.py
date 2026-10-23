"""Черновики телеграмм: ответ на входящую по её пунктам, указание, запрос сведений, напоминание о сроке,
доклад с цифрами из свода Excel. Ничего не выдумывается: что нужно вписать человеку — помечено [УТОЧНИТЬ: …]."""
import re
from datetime import date

import iskra_assistant as assistant
from iskra_telegram import INSTRUCTION, INTRO_PREFIX, parse, tidy

PLACEHOLDER = re.compile(r'\[(УТОЧНИТЬ|ФИО|ДАТА|НОМЕР|ДОЛЖНОСТЬ|ОСНОВАНИЕ|звание)[^\]]*\]', re.IGNORECASE)
NO_SIGNATURE = ['[ДОЛЖНОСТЬ]', '[звание] [И.О. Фамилия]']

KINDS = ['Ответ на входящую', 'Указание', 'Рапорт', 'Запрос сведений', 'Напоминание о сроке']


def _today():
    return date.today().strftime('%d.%m.%Y')


def _lines(title='ТЕЛЕГРАММА', to='', frm='', subject='', number=''):
    out = [title, '', f'Кому: {to or "[УТОЧНИТЬ: кому]"}', f'От кого: {frm or "[УТОЧНИТЬ: от кого]"}',
           f'Дата: {_today()}', f'Номер: {number or "[НОМЕР]"}']
    if subject:
        out.append(f'Тема: {subject}')
    return out + ['', 'Текст:']


def _signature(me):
    sig = [s for s in (me or {}).get('signature', '').splitlines() if s.strip()]
    return ['', 'Подпись:'] + (sig or NO_SIGNATURE)


def _short(sentence, limit=140):
    s = re.sub(r'\s+', ' ', sentence).strip().rstrip('.')
    return s if len(s) <= limit else s[:limit].rsplit(' ', 1)[0] + '…'


def reference(text):
    """(номер, дата) входящей: из полей «Номер:», «Дата:» или из начала текста."""
    t = parse('', text)
    number = (t.fields.get('Номер') or [''])[0]
    when = (t.fields.get('Дата') or [''])[0]
    head = text[:2500]
    if not (number and when):
        n2, w2 = _own_reference(head)
        number, when = number or n2, when or w2
    return number.lstrip('№ ').strip(), when


BASIS_REF = re.compile(r'(приказ|распоряжени|директив|постановлени|указани|телеграмм|письм|во исполнение|согласно|на основании|'
                       r'в соответствии|на ваш|на № )\w*[^.\n]{0,60}$', re.IGNORECASE)
PAIR = re.compile(r'(?:(исх|вх)\w*\.?\s*)?№\s*([0-9][\w/.-]*)\s*(?:от|,)?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})?'
                  r'|от\s*(\d{1,2}\.\d{1,2}\.\d{2,4})\s*(?:г\.?|года)?\s*№\s*([0-9][\w/.-]*)', re.IGNORECASE)


def _own_reference(text):
    """Номер и дата САМОГО документа: «Исх. № 12/345 от 20.10.2026» важнее ссылок на основание
    («во исполнение приказа от 01.09.2026 № 345»)."""
    best = None
    for m in PAIR.finditer(text):
        number = m.group(2) or m.group(5)
        when = m.group(3) or m.group(4) or ''
        before = text[max(0, m.start() - 80):m.start()]
        score = (3 if m.group(1) and m.group(1).lower().startswith('исх') else 0) + (1 if when else 0)
        if BASIS_REF.search(before):
            score -= 5                                # ссылка на чужой документ, а не номер этого
        if best is None or score > best[0]:
            best = (score, number.rstrip('.'), when)
    if best and best[0] > -5:
        return best[1], best[2]
    dates = [d for d in assistant.all_dates(text[:800])]
    return '', dates[0].value if dates else ''


def instructions(text):
    """Пункты входящей, которые требуют действий: «представить…», «обеспечить…», «доложить…»."""
    t = parse('', text)
    out = []
    for paragraph in t.body:
        for s in assistant.sentences(paragraph):
            s = INTRO_PREFIX.sub('', s).strip()
            if INSTRUCTION.search(s) and len(s) > 12:
                out.append(s)
    return out


def reply(text, me=None, name=''):
    """Ответ (доклад) на входящую телеграмму: по каждому её пункту — строка, где вписать, что сделано."""
    me = me or {}
    t = parse(name, text)
    number, when = reference(text)
    to = (t.fields.get('От кого') or [''])[0] or ' '.join(t.signature[:1])
    ref = f'На № {number}' if number else 'На Вашу телеграмму'
    ref += f' от {when}' if when else ''
    lines = _lines(to=to, frm=me.get('from', ''), subject=ref)
    points = instructions(text)
    if points:
        lines.append(f'{ref} докладываю:')
        for i, s in enumerate(points, 1):
            deadline = assistant.deadlines(s)
            due = f' (срок {deadline[0].value})' if deadline else ''
            lines.append(f'{i}. По пункту «{_short(s)}»{due}: [УТОЧНИТЬ: что сделано].')
    else:
        lines.append(f'{ref} докладываю: [УТОЧНИТЬ: суть доклада].')
    lines += _signature(me)
    lines += ['', '--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---', f'1. {name or "входящая телеграмма"}']
    return '\n'.join(lines)


def reminder(item, me=None):
    """Напоминание о сроке по записи журнала входящих (или любому документу с номером и сроком)."""
    me = me or {}
    number = item.get('number', '').replace('№ ', '')
    ref = f'телеграмме № {number}' if number else f'документу «{item.get("name", "")}»'
    ref += f' от {item["date"]}' if item.get('date') else ''
    deadline = item.get('deadline') or '[ДАТА]'
    what = _short(item.get('deadline_text', ''), 160) if item.get('deadline_text') else '[УТОЧНИТЬ: что представить]'
    lines = _lines(to=item.get('sender', ''), frm=me.get('from', ''), subject='Напоминание о сроке')
    lines.append(f'Напоминаю, что по {ref} установлен срок {deadline}: «{what}».')
    lines.append('Прошу обеспечить выполнение в установленный срок, о результатах доложить.')
    lines += _signature(me)
    return '\n'.join(lines)


def raport_text(p):
    """Начало рапорта как принято в войсках: «Настоящим докладываю, что…», «Прошу полагать меня прибывшим
    (убывшим)…», «Прошу…»."""
    low = p[:1].lower() + p[1:]
    if re.match(r'^(прошу|настоящим|ходатайствую)', low, re.IGNORECASE):
        return p[:1].upper() + p[1:]
    m = re.match(r'^(?:меня\s+)?(?:полагать\s+(?:меня\s+)?)?(прибывш\w*|прибыл\w*|прибыти\w*|убывш\w*|убыл\w*|убыти\w*)\s*(.*)$',
                 low, re.IGNORECASE | re.DOTALL)
    if m:
        state = 'прибывшим' if m.group(1).lower().startswith('прибы') else 'убывшим'
        rest = m.group(2).strip()
        return f'Прошу полагать меня {state}' + (' ' + rest if rest else ' [УТОЧНИТЬ: откуда / куда, с какого числа].')
    if re.match(r'^(полагать)', low):
        return 'Прошу ' + low
    if re.match(r'^(докладываю[,:]?\s*)', low):
        return 'Настоящим ' + low
    if re.match(r'^(что|о том|об?\s)', low):
        return 'Настоящим докладываю, ' + low if low.startswith('что') else 'Настоящим докладываю ' + low
    return 'Прошу ' + low


MONTHS_GEN = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
              'ноября', 'декабря')
INITIALS = re.compile(r'^(?:[А-ЯЁ]\.\s?){1,2}$')
_MORPH = None


def _morph():
    global _MORPH
    if _MORPH is None:
        try:
            import pymorphy3
            _MORPH = pymorphy3.MorphAnalyzer()
        except Exception:                                  # noqa: BLE001 — без словаря просто не склоняем
            _MORPH = False
    return _MORPH


def _gent(word, surname=False):
    """Слово в именительном → родительный («майор» → «майора», «Перов» → «Перова»); иначе как есть."""
    m = _morph()
    if not m or not re.fullmatch(r'[А-Яа-яЁё-]+', word):
        return word, None
    parses = [x for x in m.parse(word.lower()) if x.tag.case == 'nomn' and x.tag.POS in ('NOUN', 'ADJF')
              and ('plur' not in x.tag)]
    if surname:
        parses = [x for x in parses if 'Surn' in x.tag] or parses
    parses.sort(key=lambda x: (x.tag.POS != 'ADJF', -x.score))           # «старший лейтенант»: прилагательное
    for x in parses:
        g = x.inflect({'gent'})
        if g:
            out = g.word
            return (out[:1].upper() + out[1:] if word[:1].isupper() else out), x.tag.POS
    return word, None


def genitive_position(text):
    """«Заместитель командира 1 мсб» → «заместителя командира 1 мсб»: склоняется только начало до первого
    существительного, остальное уже стоит в родительном."""
    out, done = [], False
    for w in text.split():
        if done:
            out.append(w)
            continue
        g, pos = _gent(w)
        out.append(g)
        done = pos == 'NOUN'
    res = ' '.join(out)
    return res[:1].lower() + res[1:] if res[:1].isupper() and not res[:2].isupper() else res


def genitive_person(text):
    """«майор Перов В. В.» → «майора Перова В. В.»; «гвардии капитан И.И. Иванов» → «гвардии капитана И.И. Иванова»."""
    out = []
    for w in text.split():
        if INITIALS.match(w) or not re.search('[а-яё]', w):
            out.append(w)
        else:
            out.append(_gent(w, surname=w[:1].isupper())[0])
    return ' '.join(out)


def _split_rank(line):
    """«капитан И.И. Иванов» → («капитан», «И.И. Иванов»): звание и имя для строки подписи."""
    m = re.search(r'((?:[А-ЯЁ]\.\s?){1,2}\s*[А-ЯЁ][а-яё-]+|[А-ЯЁ][а-яё-]+\s+(?:[А-ЯЁ]\.\s?){1,2})\s*$', line)
    if not m:
        return line, ''
    return line[:m.start()].strip(), m.group(1).strip()


def word_date(d=None):
    from datetime import date
    d = d or date.today()
    return f'{d.day} {MONTHS_GEN[d.month - 1]} {d.year} г.'


def raport(me=None, to='', basis='', points=None, subject=''):
    """Рапорт как в войсках: справа — кому, «от» кого (должность, звание, фамилия в родительном), дата словами;
    «РАПОРТ»; текст от первого лица; внизу должность, затем звание — подпись — фамилия."""
    me = me or {}
    points = [p.strip() for p in (points or []) if p.strip()]
    sig = [x.strip() for x in me.get('signature', '').splitlines() if x.strip()]
    header = [to or 'Командиру войсковой части [НОМЕР]\n[звание] [Фамилия И. О.]']
    if sig:
        rank_line = sig[-1]
        position = ' '.join(sig[:-1])
        header.append('от ' + (genitive_position(position) + '\n' if position else '') + genitive_person(rank_line))
    else:
        header.append('от [должность, звание, фамилия — в родительном падеже]')
    lines = header + [word_date(), '', 'РАПОРТ', '']
    if subject:
        lines += [subject, '']
    if len(points) == 1:
        text = raport_text(tidy(points[0]))
        lines.append(text if text.endswith(('.', ']')) else text + '.')
    elif points:
        lines.append('Прошу:')
        lines += [f'{i}. {tidy(p)}' for i, p in enumerate(points, 1)]
    else:
        lines.append('Прошу [УТОЧНИТЬ: о чём просите].')
    if basis:
        lines.append(f'Основание: {basis}.')
    if sig:
        rank, name = _split_rank(sig[-1])
        lines += [''] + sig[:-1] + [f'{rank}\t\t\t\t{name}' if name else sig[-1]]
    else:
        lines += ['', '[должность]', '[звание]\t\t\t\t[Фамилия И. О.]']
    return '\n'.join(lines)


def compose(kind, me=None, to='', basis='', subject='', points=None, deadline=''):
    """Новый черновик по виду телеграммы."""
    me = me or {}
    if kind == 'Рапорт':
        return raport(me, to, basis, points, subject)
    points = [p for p in (points or []) if p.strip()]
    lines = _lines(to=to, frm=me.get('from', ''), subject=subject)
    due = deadline or '[ДАТА]'
    items = [f'{i}. {tidy(p)}' for i, p in enumerate(points, 1)]
    if kind == 'Указание':
        lines.append(f'Во исполнение {basis or "[ОСНОВАНИЕ]"} ТРЕБУЮ:')
        lines += items or ['1. [УТОЧНИТЬ: что сделать].', '2. [УТОЧНИТЬ].']
        lines.append(f'О выполнении доложить до {due}.')
    elif kind == 'Запрос сведений':
        lines.append(f'{"В целях " + basis if basis else "В целях [УТОЧНИТЬ: зачем]"} прошу в срок до {due} представить:')
        lines += items or ['1. [УТОЧНИТЬ: какие сведения].']
        lines.append('Ответственный: [ФИО, телефон].')
    elif kind == 'Напоминание о сроке':
        lines.append(f'Напоминаю, что срок {basis or "[УТОЧНИТЬ: по какому документу]"} истекает {due}.')
        lines += items
        lines.append('Прошу обеспечить выполнение в установленный срок, о результатах доложить.')
    else:  # «Докладываю:» — телеграмма о выполнении, об изменениях
        lines.append(f'{"Во исполнение " + basis + " д" if basis else "Д"}окладываю:')
        lines += items or ['1. [УТОЧНИТЬ: суть доклада].']
        if deadline:
            lines.append(f'Срок: {deadline}.')            # поле «Срок» в окне не должно пропадать и у доклада
    lines += _signature(me)
    return '\n'.join(lines)


def _n(v):
    if isinstance(v, float):
        return f'{v:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
    return str(v)


def svod_report(svod, me=None, to='', basis=''):
    """Доклад телеграммой по своду Excel: по каждой организации — её цифры, затем итог."""
    from iskra_svod import numeric_columns
    me = me or {}
    cols = numeric_columns(svod)
    short = {c: c.split(' / ')[-1] for c in cols}
    if len(set(short.values())) != len(short):
        short = {c: c for c in cols}
    lines = _lines(to=to, frm=me.get('from', ''), subject=f'Сведения по состоянию на {_today()}')
    lines.append(f'{"Во исполнение " + basis + " д" if basis else "Д"}окладываю сведения по состоянию на {_today()}:')
    n = 0
    for org in svod.orgs:
        parts = []
        for c in cols:
            v, _ = svod.value(org, c)
            if v is not None:
                parts.append(f'{short[c]} — {_n(v)}')
        n += 1
        lines.append(f'{n}. {org.name}: ' + (', '.join(parts) if parts else '[УТОЧНИТЬ: нет данных]') + ';')
    totals = []
    for c in cols:
        values = [svod.value(o, c)[0] for o in svod.orgs]
        total = sum(v for v in values if isinstance(v, (int, float)))
        totals.append(f'{short[c]} — {_n(round(total, 6) if isinstance(total, float) else total)}')
    if lines[-1].endswith(';'):
        lines[-1] = lines[-1][:-1] + '.'
    if totals:
        lines.append('Итого: ' + ', '.join(totals) + '.')
    lines += _signature(me)
    return '\n'.join(lines)


def unfilled(text):
    """Незаполненные места черновика."""
    return [m.group(0) for m in PLACEHOLDER.finditer(text.split('--- ИСТОЧНИКИ')[0])]
