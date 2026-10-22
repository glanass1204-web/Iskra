"""Проверка телеграммы перед отправкой: прошедшие и невозможные сроки, выходные, незаполненные места,
нумерация пунктов, подпись, числа, которых нет в исходных документах, чужие звания у людей из справочника.
Ничего не исправляет сама — только перечисляет, что посмотреть."""
import re
from datetime import date, datetime

DATE = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b')
DEADLINE_WORDS = re.compile(r'(до|не позднее|к|в срок до|срок|в течение)\s*$', re.IGNORECASE)
PLACEHOLDER = re.compile(r'\[(?:УТОЧНИТЬ|ДАТА|НОМЕР|ФИО|ДОЛЖНОСТЬ|звание|И\.О\. Фамилия)[^\]]*\]', re.IGNORECASE)
SIGN = re.compile(r'([А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+|[А-ЯЁ][а-яё]+\s[А-ЯЁ]\.\s?[А-ЯЁ]\.)')
POINT = re.compile(r'^\s*(\d{1,2})[.)]\s', re.MULTILINE)
WEEKDAYS = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']


def body(text):
    """Без служебного хвоста «--- ИСТОЧНИКИ …»."""
    return text.split('--- ИСТОЧНИКИ')[0]


def check(text, today=None, sources=(), people=None):
    """[(уровень, сообщение)]: уровень 'ошибка' — так отправлять нельзя, 'внимание' — посмотреть."""
    today = today or date.today()
    text = body(text)
    out = []
    if not text.strip():
        return [('ошибка', 'Текст пуст.')]

    left = PLACEHOLDER.findall(text)
    if left:
        out.append(('ошибка', 'Не заполнено: ' + ', '.join(dict.fromkeys(left))[:300]))

    for m in DATE.finditer(text):
        d, mo, y = map(int, m.groups())
        try:
            when = date(y, mo, d)
        except ValueError:
            out.append(('ошибка', f'Такой даты не бывает: {m.group(0)}.'))
            continue
        before = text[max(0, m.start() - 25):m.start()]
        is_deadline = bool(DEADLINE_WORDS.search(before.strip() + ' ')) or bool(re.search(r'(до|позднее|срок)\s*$', before.strip(), re.I))
        if is_deadline and when < today:
            out.append(('ошибка', f'Срок {m.group(0)} уже прошёл (сегодня {today.strftime("%d.%m.%Y")}).'))
        elif is_deadline and when.weekday() >= 5:
            out.append(('внимание', f'Срок {m.group(0)} приходится на {WEEKDAYS[when.weekday()]}.'))
        if abs(when.year - today.year) > 1:
            out.append(('внимание', f'Проверьте год: {m.group(0)}.'))

    nums = [int(n) for n in POINT.findall(text)]
    if nums:
        expected = list(range(1, len(nums) + 1))
        if nums != expected:
            out.append(('внимание', 'Нумерация пунктов сбита: ' + ', '.join(map(str, nums)) + '.'))

    tail = '\n'.join([l for l in text.strip().splitlines() if l.strip()][-4:])
    if not SIGN.search(tail) and 'Подпись' not in tail:
        out.append(('внимание', 'В конце не видно подписи (должность, звание, И.О. Фамилия).'))

    if re.search(r'\b(\w+)\s+\1\b', text, re.IGNORECASE):
        word = re.search(r'\b(\w+)\s+\1\b', text, re.IGNORECASE).group(1)
        out.append(('внимание', f'Слово повторяется подряд: «{word}».'))

    if sources:
        import iskra_ai
        doubtful = iskra_ai.unverified(text, list(sources))
        if doubtful:
            out.append(('внимание', 'Этих чисел и дат нет в исходных документах: ' + ', '.join(doubtful[:12]) + '.'))

    if people is not None:
        import iskra_people
        out += [('внимание', x) for x in iskra_people.mismatches(text, people)]

    try:
        from iskra_spell import SpellChecker
        bad = SpellChecker().check(text, with_style=False)
        if bad:
            words = list(dict.fromkeys(i.text for i in bad))[:10]
            out.append(('внимание', f'Возможные опечатки ({len(bad)}): ' + ', '.join(words) + '.'))
    except Exception:
        pass
    return out


def report(issues):
    if not issues:
        return 'Замечаний нет: сроки, нумерация, подпись и числа в порядке.'
    order = {'ошибка': 0, 'внимание': 1}
    return '\n'.join(('⛔ ' if lvl == 'ошибка' else '⚠ ') + msg for lvl, msg in sorted(issues, key=lambda i: order[i[0]]))
