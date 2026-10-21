"""Черновики телеграмм: ответ на входящую по её пунктам, указание, запрос сведений, напоминание о сроке,
доклад с цифрами из свода Excel. Ничего не выдумывается: что нужно вписать человеку — помечено [УТОЧНИТЬ: …]."""
import re
from datetime import date

import iskra_assistant as assistant
from iskra_telegram import INSTRUCTION, INTRO_PREFIX, parse, tidy

PLACEHOLDER = re.compile(r'\[(УТОЧНИТЬ|ФИО|ДАТА|НОМЕР|ДОЛЖНОСТЬ|ОСНОВАНИЕ|звание)[^\]]*\]', re.IGNORECASE)
NO_SIGNATURE = ['[ДОЛЖНОСТЬ]', '[звание] [И.О. Фамилия]']

KINDS = ['Ответ на входящую', 'Доклад', 'Указание', 'Запрос сведений', 'Напоминание о сроке']


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
    head = text[:1500]
    if not number:
        nums = assistant.numbers(head)
        number = nums[0].value.replace('№ ', '') if nums else ''
    if not when:
        dates = assistant.all_dates(head)
        when = dates[0].value if dates else ''
    return number.lstrip('№ ').strip(), when


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


def compose(kind, me=None, to='', basis='', subject='', points=None, deadline=''):
    """Новый черновик по виду телеграммы."""
    me = me or {}
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
    else:  # Доклад
        lines.append(f'{"Во исполнение " + basis + " д" if basis else "Д"}окладываю:')
        lines += items or ['1. [УТОЧНИТЬ: суть доклада].']
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
