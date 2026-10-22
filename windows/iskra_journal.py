"""Журнал исходящих: номера по порядку (с начала года — заново), кому и о чём отправлено, ждём ли ответ.
Когда во входящих приходит документ «на № 45/…» — запись отмечается как отвеченная. Хранится в data/journal.json."""
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

DATE_FMT = '%d.%m.%Y'
# «на № 45», «на исх. № 45/2», «на Ваш № 45 от 01.10.2026», «ссылка: № 45»
REF = re.compile(r'(?:на|ссылк[аи]\s*:?)\s*(?:ваш(?:е|у|ей)?\s+|исх\.?\s*|исходящ\w*\s+)?№\s*([\w/.-]+)', re.IGNORECASE)


class Journal:
    def __init__(self, root):
        self.path = Path(root) / 'journal.json'
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        self.settings = data.get('settings', {'format': '{n}', 'year': date.today().year, 'next': 1})
        self.items = data.get('items', [])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'settings': self.settings, 'items': self.items}, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, self.path)

    def configure(self, fmt=None, next_number=None):
        if fmt:
            self.settings['format'] = fmt if '{n}' in fmt else fmt + '{n}'
        if next_number:
            self.settings['next'] = int(next_number)
        self.save()

    def peek(self, today=None):
        today = today or date.today()
        n = 1 if self.settings.get('year') != today.year else int(self.settings.get('next', 1))
        return self.settings.get('format', '{n}').replace('{n}', str(n)).replace('{год}', str(today.year))

    def register(self, to='', subject='', file='', reply_by='', today=None, number=None):
        """Новая исходящая. Номер — следующий по порядку (или свой, если задан). Возвращает запись."""
        today = today or date.today()
        if self.settings.get('year') != today.year:
            self.settings.update({'year': today.year, 'next': 1})
        if not number:
            number = self.peek(today)
            self.settings['next'] = int(self.settings.get('next', 1)) + 1
        item = {'number': str(number), 'date': today.strftime(DATE_FMT), 'to': to.strip(), 'subject': subject.strip()[:300],
                'file': str(file or ''), 'reply_by': reply_by.strip(), 'answered': '', 'answer_file': ''}
        self.items.append(item)
        self.save()
        return item

    def update(self, number, **fields):
        for it in self.items:
            if it['number'] == number:
                it.update({k: v for k, v in fields.items() if k in it})
        self.save()

    def remove(self, number):
        self.items = [it for it in self.items if it['number'] != number]
        self.save()

    def match_reply(self, text, file='', today=None):
        """Входящий документ ссылается на наш номер → запись отвечена. Возвращает отмеченные записи."""
        today = today or date.today()
        refs = {r.strip('.').lower() for r in REF.findall(text or '')}
        done = []
        for it in self.items:
            if not it['answered'] and it['number'].lower() in refs:
                it['answered'] = today.strftime(DATE_FMT)
                it['answer_file'] = str(file)
                done.append(it)
        if done:
            self.save()
        return done

    def waiting(self, today=None):
        """[(запись, просрочено ли)] — ждём ответа и указан срок ответа."""
        today = today or date.today()
        out = []
        for it in self.items:
            if it['answered'] or not it['reply_by']:
                continue
            try:
                due = datetime.strptime(it['reply_by'], DATE_FMT).date()
            except ValueError:
                continue
            out.append((it, due < today))
        return out

    def lines_for_morning(self, today=None):
        return [f'№ {it["number"]} от {it["date"]} — {it["to"] or "?"}: {it["subject"][:80]} — ответ до {it["reply_by"]}'
                + (' (ПРОСРОЧЕН)' if late else '') for it, late in self.waiting(today)]

    def to_xlsx(self, path):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = 'Исходящие'
        ws.append(['№', 'Дата', 'Кому', 'О чём', 'Ответ до', 'Ответ получен', 'Файл'])
        for c in ws[1]:
            c.font = Font(bold=True)
        for it in self.items:
            ws.append([it['number'], it['date'], it['to'], it['subject'], it['reply_by'], it['answered'], it['file']])
        for col, w in zip('ABCDEFG', (10, 12, 30, 60, 12, 14, 40)):
            ws.column_dimensions[col].width = w
        wb.save(path)


def addressee_from_text(text):
    """Кому: строка «Кому: …» или первые строки до пустой (блок адресата в дательном падеже)."""
    m = re.search(r'^\s*Кому\s*:\s*(.+)$', text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    lines = []
    for line in text.strip().splitlines():
        if not line.strip() or line.strip().upper() == 'ТЕЛЕГРАММА':
            if lines:
                break
            continue
        lines.append(line.strip())
        if len(lines) == 3:
            break
    return ' '.join(lines) if lines and lines[0][:1].isupper() and lines[0].split()[0].endswith(('у', 'ю', 'ам', 'ям')) else ''


def subject_from_text(text):
    body = re.sub(r'^\s*(ТЕЛЕГРАММА|Кому:.*|От кого:.*|Дата:.*|Номер:.*)\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    body = re.sub(r'^\s*Текст\s*:\s*', '', body.strip(), flags=re.IGNORECASE)
    first = next((l.strip() for l in body.splitlines() if len(l.strip()) > 15), '')
    return first[:200]


def put_number(text, number, when):
    """Вписать номер и дату в места для них («Номер: [НОМЕР]», «[УТОЧНИТЬ: номер]», «№ ___», «Дата: [ДАТА]»).
    Возвращает (текст, вписан ли номер)."""
    before = text
    text = re.sub(r'(Номер[ \t]*:[ \t]*)(\[НОМЕР\]|\[УТОЧНИТЬ:?\s*номер\]|_+|$)',
                  lambda m: m.group(1) + ('' if m.group(1).endswith((' ', '\t')) else ' ') + number, text,
                  count=1, flags=re.MULTILINE | re.IGNORECASE)
    if text == before:
        text = re.sub(r'\[(?:НОМЕР|УТОЧНИТЬ:?\s*номер)\]|№\s*_{2,}', '№ ' + number, text, count=1, flags=re.IGNORECASE)
    placed = text != before
    text = re.sub(r'(Дата\s*:\s*)(\[ДАТА\]|\[УТОЧНИТЬ:?\s*дата\]|_+)', lambda m: m.group(1) + when, text, count=1,
                  flags=re.IGNORECASE)
    text = re.sub(r'\[(?:ДАТА|УТОЧНИТЬ:?\s*дата)\]', when, text, count=1, flags=re.IGNORECASE)
    return text, placed
