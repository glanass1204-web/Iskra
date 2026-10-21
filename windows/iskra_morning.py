"""Утренняя сводка: что пришло со вчера, какие сроки сегодня и завтра, что просрочено, что ещё не обработано,
как идёт свод за день. Собирается из входящих, контроля поручений, сроков в документах и автосвода."""
from datetime import date, datetime, timedelta

import iskra_assistant as assistant

DATE_FMT = '%d.%m.%Y'


def _d(value):
    try:
        return datetime.strptime(value, DATE_FMT).date()
    except (TypeError, ValueError):
        return None


def _added(item):
    try:
        return datetime.strptime(item.get('added', ''), '%d.%m.%Y %H:%M')
    except ValueError:
        return None


def build(inbox_items=(), control=None, doc_deadlines=(), autosvod_lines=(), today=None, since=None):
    """Разделы сводки: [(заголовок, [строки])]. since — с какого момента считать «пришло» (по умолчанию сутки)."""
    today = today or date.today()
    since = since or datetime.combine(today - timedelta(days=1), datetime.min.time())
    sections = []

    new = [i for i in inbox_items if (_added(i) or datetime.min) >= since]
    sections.append(('ПРИШЛО', [
        f'{i["kind"]} «{i["name"]}»' + (f' {i["number"]}' if i.get('number') else '') +
        (f' от {i["sender"]}' if i.get('sender') else '') + (f' — срок {i["deadline"]}' if i.get('deadline') else '')
        for i in new]))

    soon, late = [], []
    if control is not None:
        for t in control.due(1, today):
            when = 'сегодня' if _d(t['deadline']) == today else 'завтра'
            soon.append(f'{t["deadline"]} ({when}) — {t["text"]}' + (f' [{t["responsible"]}]' if t['responsible'] else ''))
        for t in control.overdue(today):
            late.append(f'{t["deadline"]} (просрочено на {(today - _d(t["deadline"])).days} дн.) — {t["text"]}' +
                        (f' [{t["responsible"]}]' if t['responsible'] else ''))
    # Срок документа уже виден через его поручения — сам документ второй раз не показываем.
    covered = {(t['source'], t['deadline']) for t in control.open_items()} if control is not None else set()
    seen = set()
    for i in inbox_items:
        d = _d(i.get('deadline'))
        if not d or i.get('status') == 'выполнен' or (i.get('name'), i.get('deadline')) in covered:
            continue
        line = f'{i["deadline"]} — {i["kind"].lower()} «{i["name"]}»'
        if today <= d <= today + timedelta(days=1) and line.split(' — ', 1)[-1] not in seen:
            soon.append(line + (' (сегодня)' if d == today else ' (завтра)'))
        elif d < today and i.get('status') != 'выполнен':
            late.append(line + f' (просрочено на {(today - d).days} дн.)')
    for d, status, path, sentence in doc_deadlines:
        if today <= d <= today + timedelta(days=1):
            soon.append(f'{d.strftime(DATE_FMT)} ({status}) — {path.split("/")[-1].split(chr(92))[-1]}: {sentence[:120]}')
    sections.append(('СРОКИ СЕГОДНЯ И ЗАВТРА', soon))
    sections.append(('ПРОСРОЧЕНО', late))

    waiting = [i for i in inbox_items if i.get('status') == 'новый' and (_added(i) or datetime.max) < since]
    sections.append(('НЕ ОБРАБОТАНО (пришло раньше, ещё не открыто)', [f'{i["kind"]} «{i["name"]}» — пришло {i["added"]}' for i in waiting]))
    if autosvod_lines:
        sections.append(('СВОД ЗА ДЕНЬ', list(autosvod_lines)))
    return sections


def text(sections, today=None):
    today = today or date.today()
    out = [f'СВОДКА НА {today.strftime(DATE_FMT)}', '']
    for title, lines in sections:
        out.append(f'{title}: {len(lines)}' if lines else f'{title}: нет')
        out += [f'  • {x}' for x in lines[:30]]
        if len(lines) > 30:
            out.append(f'  …и ещё {len(lines) - 30}')
        out.append('')
    return '\n'.join(out).rstrip()


def counts(sections):
    return {title: len(lines) for title, lines in sections}


def upcoming_from_docs(docs, today=None):
    """Сроки из всех документов поиска на сегодня-завтра."""
    return assistant.upcoming(docs, today, ahead=1, behind=0)
