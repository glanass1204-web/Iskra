"""Работа со сводной таблицей (ПУ, подразделения): доклад об изменениях, история по объектам, кто не прислал.
Всё по данным таблиц, без нейросети: в доклад попадают только значения из документов."""
import json
import os
import re
import time
from pathlib import Path

HISTORY_KEEP = 300


def _root():
    from iskra_index import ROOT
    return ROOT


def norm(text):
    return re.sub(r'\s+', ' ', (text or '').lower().replace('ё', 'е')).strip(' .,;:')


def _low_first(s):
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


# ---------- доклад ----------

def report_points(changes, long_stay=()):
    """Пункты доклада: по каждому объекту — что стало (и что было); новые объекты; кто дольше порога."""
    by_object, order, new_rows = {}, [], []
    for c in changes:
        if c.get('new_row'):
            new_rows.append(c)
            continue
        if c['object'] not in by_object:
            by_object[c['object']] = []
            order.append(c['object'])
        by_object[c['object']].append(c)
    points = []
    for obj in order:
        parts = []
        for c in by_object[obj]:
            new = ' '.join(c['new'].split())
            old = ' '.join(c['old'].split())
            parts.append(f'{_low_first(c["column"])} — {new}' + (f' (было {old})' if old else ''))
        points.append(f'{obj}: ' + '; '.join(parts))
    for c in new_rows:
        values = [f'{_low_first(k)} — {" ".join(v.split())}' for k, v in c.get('values', {}).items() if norm(v) != norm(c['object'])]
        where = f' ({c["section"].upper()})' if c.get('section') else ''
        points.append(f'Новый: {c["object"]}{where}' + (': ' + '; '.join(values) if values else ''))
    if long_stay:
        points.append('Находятся в районе дольше установленного: ' + '; '.join(long_stay))
    return points


def report_draft(changes, long_stay=(), me=None, to='', subject=''):
    """Телеграмма-донесение об изменениях (черновик для редактора)."""
    import iskra_compose as compose
    from datetime import date
    points = report_points(changes, long_stay)
    if not points:
        points = ['изменений нет']
    return compose.compose('Донесение', me=me, to=to, subject=subject or f'Об изменениях по состоянию на {date.today():%d.%m.%Y}',
                           points=[p if p.endswith('.') else p + '.' for p in points])


# ---------- история ----------

def _history_path():
    return _root() / 'pu_history.jsonl'


def save_snapshot(snapshot, document='', files=()):
    """Запомнить состояние таблиц после сбора."""
    if not snapshot or not any(t.get('rows') for t in snapshot):
        return False
    path = _history_path()
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = []
    lines.append(json.dumps({'time': time.strftime('%d.%m.%Y %H:%M'), 'document': os.path.basename(str(document)),
                             'files': [os.path.basename(str(f)) for f in files], 'tables': snapshot}, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines[-HISTORY_KEEP:]) + '\n', encoding='utf-8')
    return True


def snapshots():
    out = []
    try:
        for line in _history_path().read_text(encoding='utf-8').splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _objects(snap):
    out = {}
    for t in snap.get('tables', []):
        for r in t.get('rows', []):
            if r.get('object'):
                out[norm(r['object'])] = r
    return out


def history(query='', limit=500):
    """Изменения по объектам между соседними снимками: [(время, объект, столбец, было, стало)], новые сверху.
    query — часть названия («5447», «ЗКП»); пусто — все объекты."""
    snaps = snapshots()
    q = norm(query)
    hit = re.compile(r'(?<![а-яa-z0-9])' + re.escape(q)) if q else None   # «кп 5447» — не «зкп 5447»
    out = []
    for prev, cur in zip(snaps, snaps[1:]):
        a, b = _objects(prev), _objects(cur)
        for key, row in b.items():
            if hit and not hit.search(key):
                continue
            old = a.get(key)
            if old is None:
                out.append((cur['time'], row['object'], 'появился', '', ' | '.join(v for v in row['cells'].values() if v)))
                continue
            for col, value in row['cells'].items():
                before = old['cells'].get(col, '')
                if norm(before) != norm(value):
                    out.append((cur['time'], row['object'], col, before, value))
        for key, row in a.items():
            if key not in b and (not hit or hit.search(key)):
                out.append((cur['time'], row['object'], 'убран из таблицы', '', ''))
    if snaps and not out and q:
        last = _objects(snaps[-1])
        for key, row in last.items():
            if hit.search(key):
                out.append((snaps[-1]['time'], row['object'], 'сейчас', '', ' | '.join(v for v in row['cells'].values() if v)))
    out.reverse()
    return out[:limit]


def query_from_phrase(text):
    """«где был КП 5447 на прошлой неделе» → «кп 5447»: номер или название объекта из фразы."""
    m = re.search(r'((?:з?кп|пу|пункт|рота|батальон|в/ч)\s*[\w/-]*\d[\w/-]*)', text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'\d{2,}', text)
    return m.group(0) if m else ''


# ---------- кто не прислал ----------

def parse_expected(text):
    return [x.strip() for x in re.split(r'[,;\n]', text or '') if x.strip()]


def check_senders(expected, paths, read=None):
    """(прислали {кто: файл}, не прислали [кто]). Ищем название в имени файла, а если там нет — в начале документа."""
    if read is None:
        from iskra_index import extract
        read = lambda p: extract(Path(p))[:3000]             # noqa: E731 — достаточно начала документа
    got, texts = {}, {}
    for who in expected:
        key = norm(who)
        if not key:
            continue
        for p in paths:
            if key in norm(Path(p).stem.replace('_', ' ')):
                got[who] = p
                break
        else:
            for p in paths:
                if p not in texts:
                    try:
                        texts[p] = norm(read(p))
                    except Exception:                      # noqa: BLE001 — нечитаемый файл просто не учитываем
                        texts[p] = ''
                if re.search(r'(?<![а-яa-z0-9])' + re.escape(key) + r'(?![а-яa-z0-9])', texts[p]):
                    got[who] = p
                    break
    return got, [w for w in expected if w not in got]


def reminder_draft(missing, me=None, deadline=''):
    import iskra_compose as compose
    return compose.compose('Напоминание о сроке', me=me, to=', '.join(missing),
                           basis='представления сведений (изменений по своей таблице)', deadline=deadline,
                           points=['Изменения выделить зелёным цветом.'])
