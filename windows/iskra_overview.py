"""Обзор папки по всем её документам: сколько и каких файлов, телеграммы и от кого, ближайшие и просроченные сроки,
о чём документы (частые темы), последние поступления, вложенные папки. Только то, что есть в самих документах."""
import os
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import iskra_assistant as assistant
from iskra_inbox import kind_of, sender_of

TOPIC_STOP = set('''это этот эта эти того тому также который которая которые которых является являются было были будет
будут может могут иные иных других другой свой своих всех всего более менее очень только после перед через между
прошу просим необходимо обеспечить представить провести направить доложить организовать выполнить исполнить
приказ приказа приказываю телеграмма телеграммы распоряжение указание письмо документ документа документы
года году годы число числа месяца время срок сроки сроков дата даты номер номера случае целях связи соответствии
основании исполнение исполнения порядке части пункт пункта пунктов настоящим сведения сведений информацию
информации отдела отдел начальник начальника начальнику заместитель штаба подпись январь февраль март апрель
июнь июль август сентябрь октябрь ноябрь декабрь января февраля марта апреля мая июня июля августа сентября
октября ноября декабря кого кому вашего вашей нашего довожу доводим сообщаю сообщаем уважаемый уважаемые
полковник подполковник майор капитан лейтенант старший младший генерал прапорщик сержант рядовой гвардии
полковника подполковника майора капитана генерала'''.split())
LABEL_LINE = re.compile(r'^\s*[А-ЯЁа-яё. ]{2,20}:', re.MULTILINE)
WORD = re.compile(r'[А-Яа-яЁё]{4,}')


def _body(text):
    # В индексе первая строка — имя файла (для поиска по названию).
    return text.split('\n', 1)[1] if '\n' in text else text


def _norm(w):
    w = w.lower().replace('ё', 'е')
    return w[:7] if len(w) > 7 else w


def topics(texts, top=10):
    """Частые сочетания из двух значимых слов («личного состава», «готовности техники») по числу документов."""
    df, shown = Counter(), {}
    for text in texts:
        seen = set()
        text = '\n'.join(line for line in text[:20000].split('\n') if not LABEL_LINE.match(line))
        for sentence in assistant.sentences(text):
            words = WORD.findall(sentence)
            for a, b in zip(words, words[1:]):
                if a.lower() in TOPIC_STOP or b.lower() in TOPIC_STOP:
                    continue
                key = (_norm(a), _norm(b))
                if key not in seen:
                    seen.add(key)
                    df[key] += 1
                    shown.setdefault(key, f'{a.lower()} {b.lower()}')
    return [(shown[k], n) for k, n in df.most_common(top) if n >= 2]


def inside(path, folder):
    try:
        return os.path.normcase(str(Path(path).resolve())).startswith(os.path.normcase(str(Path(folder).resolve())) + os.sep)
    except OSError:
        return False


def folder_overview(folder, docs, today=None, top=8):
    """docs: [(путь, текст)] — например, из индекса. Берутся документы внутри folder (включая вложенные папки)."""
    today = today or date.today()
    folder = Path(folder)
    by_ext, by_kind, senders, subfolders = Counter(), Counter(), Counter(), Counter()
    upcoming, overdue, telegrams, recent, texts = [], [], [], [], []
    total = 0
    for path, text in docs:
        if not inside(path, folder):
            continue
        total += 1
        p = Path(path)
        body = _body(text)
        texts.append(body)
        by_ext[p.suffix.lower().lstrip('.') or 'прочее'] += 1
        try:
            rel = p.resolve().relative_to(folder.resolve())
        except (ValueError, OSError):
            rel = Path(p.name)
        subfolders[rel.parts[0] if len(rel.parts) > 1 else '(в самой папке)'] += 1
        kind = kind_of(p, body)
        by_kind[kind] += 1
        sender = sender_of(body) if kind != 'Таблица Excel' else ''
        if sender:
            senders[sender[:60]] += 1
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0
        recent.append((mtime, p.name, kind))
        for d in assistant.deadlines(body, today):
            days = (d.sort_key - today).days
            if 0 <= days <= 30:
                upcoming.append((d.sort_key, p.name, d.context[:160]))
            elif -30 <= days < 0:
                overdue.append((d.sort_key, p.name, d.context[:160]))
        if kind == 'Телеграмма':
            from iskra_compose import reference
            number, when = reference(body)
            first = (assistant.summary(body, 1) or [''])[0][:160]
            telegrams.append((mtime, p.name, number, when, sender[:60], first))
    recent.sort(reverse=True)
    telegrams.sort(reverse=True)
    upcoming.sort()
    overdue.sort(reverse=True)
    return {'folder': str(folder), 'total': total, 'by_ext': by_ext.most_common(), 'by_kind': by_kind.most_common(),
            'senders': senders.most_common(top), 'subfolders': subfolders.most_common(),
            'upcoming': upcoming[:15], 'overdue': overdue[:15], 'telegrams': telegrams[:top],
            'recent': [(datetime.fromtimestamp(m).strftime('%d.%m.%Y') if m else '', n, k) for m, n, k in recent[:top]],
            'topics': topics(texts)}


def render(ov):
    """Обзор текстом по-русски."""
    if not ov['total']:
        return (f'В папке «{ov["folder"]}» нет документов в поиске. Добавьте её кнопкой «Папки…» '
                'и дождитесь окончания индексации.')
    out = [f'ПАПКА: {ov["folder"]}', f'Документов: {ov["total"]} — ' + ', '.join(f'{e}: {n}' for e, n in ov['by_ext'])]
    out.append('По видам: ' + ', '.join(f'{k.lower()} — {n}' for k, n in ov['by_kind']))
    if len(ov['subfolders']) > 1:
        out.append('Вложенные папки: ' + ', '.join(f'{k} ({n})' for k, n in ov['subfolders'][:12]))
    if ov['topics']:
        out.append('\nО ЧЁМ ДОКУМЕНТЫ (частые темы, в скольких документах):')
        out.append('  ' + '; '.join(f'{t} ({n})' for t, n in ov['topics']))
    if ov['senders']:
        out.append('\nОТ КОГО ЧАЩЕ ВСЕГО:')
        out += [f'  • {s} — {n}' for s, n in ov['senders']]
    if ov['overdue']:
        out.append('\nПРОСРОЧЕНО (за последние 30 дней):')
        out += [f'  • {d.strftime("%d.%m.%Y")} — {n}: {c}' for d, n, c in ov['overdue'][:8]]
    if ov['upcoming']:
        out.append('\nБЛИЖАЙШИЕ СРОКИ (30 дней):')
        out += [f'  • {d.strftime("%d.%m.%Y")} — {n}: {c}' for d, n, c in ov['upcoming'][:10]]
    if ov['telegrams']:
        out.append('\nПОСЛЕДНИЕ ТЕЛЕГРАММЫ:')
        for _, name, number, when, sender, first in ov['telegrams']:
            head = name + (f' № {number}' if number else '') + (f' от {when}' if when else '') + (f' ({sender})' if sender else '')
            out.append(f'  • {head}' + (f'\n      {first}' if first else ''))
    if ov['recent']:
        out.append('\nПОСЛЕДНИЕ ИЗМЕНЁННЫЕ:')
        out += [f'  • {d} — {n} ({k.lower()})' for d, n, k in ov['recent']]
    return '\n'.join(out)


def folders_summary(roots, docs, today=None):
    """Коротко по каждой папке поиска — для чата («что в папках»)."""
    docs = list(docs)
    lines = []
    for root in roots:
        ov = folder_overview(root, docs, today)
        if not ov['total']:
            lines.append(f'• {root}: пока нет документов в поиске')
            continue
        kinds = ', '.join(f'{k.lower()} — {n}' for k, n in ov['by_kind'][:4])
        line = f'• {Path(root).name or root}: {ov["total"]} док. ({kinds})'
        if ov['upcoming']:
            d, n, _ = ov['upcoming'][0]
            line += f'; ближайший срок {d.strftime("%d.%m.%Y")} ({n})'
        if ov['overdue']:
            line += f'; просрочено: {len(ov["overdue"])}'
        lines.append(line)
    return lines


def candidate_folders():
    """Папки для первого запуска: Документы, Рабочий стол, Загрузки (и в OneDrive), сетевые диски."""
    home = Path.home()
    names = [('Документы', ['Documents', 'Мои документы', 'OneDrive/Documents', 'OneDrive/Документы']),
             ('Рабочий стол', ['Desktop', 'Рабочий стол', 'OneDrive/Desktop', 'OneDrive/Рабочий стол']),
             ('Загрузки', ['Downloads', 'Загрузки'])]
    out, seen = [], set()
    for label, variants in names:
        for v in variants:
            p = home / v
            if p.is_dir() and str(p.resolve()) not in seen:
                seen.add(str(p.resolve()))
                out.append((label, str(p.resolve())))
                break
    if os.name == 'nt':
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if mask >> i & 1:
                    drive = f'{chr(65 + i)}:\\'
                    if ctypes.windll.kernel32.GetDriveTypeW(drive) == 4:      # DRIVE_REMOTE — сетевой диск
                        out.append((f'Сетевой диск {drive}', drive))
        except Exception:
            pass
    return out
