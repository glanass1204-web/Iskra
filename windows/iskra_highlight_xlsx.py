"""Перенос изменений по подсветке для Excel — те же правила, что и для Word (iskra_highlight):
шаблон (как должно выглядеть) + документ (куда вносить) + присланные таблицы подразделений (откуда брать).
Изменение — всё, что исполнитель отметил зелёным/салатовым: цветом шрифта, заливкой ячейки или частью текста
(«с-в окраина ЗАЛУПИНСК» + зелёным «ПЕЧОРИНСК» с новой строки). В итоге изменения — зелёным шрифтом, остальное
чёрным, прошлые отметки снимаются; строки узнаются по названию («Наименование ПУ»), а не по номеру; при смене
положения «Время нахождения в районе» — заново «1 сут. с <сегодня>»; шрифт, размер, ширина столбцов — по шаблону."""
import copy
import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import PatternFill
from openpyxl.styles.colors import COLOR_INDEX

import iskra_highlight as H

GREEN = 'FF' + H.GREEN_RGB
YELLOW = PatternFill('solid', fgColor='FFFF00')
MARKER = PatternFill('solid', fgColor='92D050')


# ---------- цвет ----------

# Цвета темы книги (верхние ряды палитры Excel): номер → RRGGBB. Office 2013+ по умолчанию; читается из файла.
THEME = ['FFFFFF', '000000', 'E7E6E6', '44546A', '4472C4', 'ED7D31', 'A5A5A5', 'FFC000', '5B9BD5', '70AD47']


def use_theme(wb):
    """Палитра темы этой книги — чтобы «зелёный, акцент 6, светлее 40 %» распознавался как зелёный."""
    global THEME
    xml = getattr(wb, 'loaded_theme', None)
    if not xml:
        return
    try:
        text = xml.decode('utf-8', 'replace') if isinstance(xml, bytes) else str(xml)
        scheme = re.search(r'<a:clrScheme.*?</a:clrScheme>', text, re.S).group(0)
        names = ['dk1', 'lt1', 'dk2', 'lt2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6']
        found = {}
        for n in names:
            m = re.search(rf'<a:{n}>.*?(?:srgbClr val="([0-9A-Fa-f]{{6}})"|lastClr="([0-9A-Fa-f]{{6}})").*?</a:{n}>', scheme, re.S)
            if m:
                found[n] = (m.group(1) or m.group(2)).upper()
        order = ['lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6']
        if len(found) == len(order):
            THEME = [found[n] for n in order]
    except (AttributeError, re.error):
        pass


def _tint(hex6, tint):
    """Светлее/темнее, как в Excel («светлее 40 %» — tint 0.4)."""
    if not tint:
        return hex6
    out = []
    for i in (0, 2, 4):
        c = int(hex6[i:i + 2], 16)
        c = c + (255 - c) * tint if tint > 0 else c * (1 + tint)
        out.append(f'{max(0, min(255, round(c))):02X}')
    return ''.join(out)


def _rgb(color):
    """Цвет openpyxl → 'RRGGBB' или None: обычный, из стандартной палитры (indexed) или цвет темы с оттенком."""
    if color is None:
        return None
    try:
        kind = color.type
        if kind == 'rgb' and isinstance(color.rgb, str):
            return color.rgb[-6:].upper()
        if kind == 'indexed' and color.indexed is not None and color.indexed < len(COLOR_INDEX):
            return COLOR_INDEX[color.indexed][-6:].upper()
        if kind == 'theme' and color.theme is not None and 0 <= color.theme < len(THEME):
            return _tint(THEME[color.theme], color.tint or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _green(hex6):
    """Зелёный шрифт — в том числе светлые оттенки палитры Excel («зелёный, светлее 40 %» — A9CE91)."""
    if not hex6 or not re.fullmatch(r'[0-9A-Fa-f]{6}', hex6):
        return False
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return g >= 90 and g >= max(r, b) + 25


def _font_green(font):
    return font is not None and _green(_rgb(getattr(font, 'color', None)))


def _fill_rgb(cell):
    f = cell.fill
    if f is None or f.fill_type not in ('solid', 'gray125', 'darkGray', 'mediumGray', 'lightGray'):
        return ''
    return (_rgb(f.fgColor) or '').upper()


# ---------- чтение ----------

def _text(value):
    if value is None:
        return ''
    if isinstance(value, CellRichText):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime('%d.%m.%Y') if value.time() == datetime.min.time() else value.strftime('%d.%m.%Y %H:%M')
    if isinstance(value, date):
        return value.strftime('%d.%m.%Y')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parts(cell):
    """[(текст, отмечен)] — как segments() в Word: части текста, отмеченные зелёным шрифтом."""
    v = cell.value
    whole = _font_green(cell.font)
    if isinstance(v, CellRichText):
        out = []
        for block in v:
            if isinstance(block, TextBlock):
                g = _green(_rgb(block.font.color)) if block.font is not None and block.font.color is not None else whole
                out.append((block.text, g))
            else:
                out.append((str(block), whole))
        return [(t, g) for t, g in out if t]
    t = _text(v)
    return [(t, whole)] if t else []


class XCell:
    def __init__(self, ws, r, c):
        self.ws, self.r, self.c = ws, r, c
        cell = ws.cell(r, c)
        self.value = cell.value
        self.parts = _parts(cell)
        self.text = ''.join(t for t, _ in self.parts).strip()
        self.fill = _fill_rgb(cell)
        self.resolve()

    def resolve(self, template_fills=()):
        shaded = H._green_hex(self.fill) and self.fill not in template_fills
        if shaded:
            self.parts = [(t, True) for t, _ in self.parts]
        marked = ''.join(t for t, g in self.parts if g)
        self.green = bool(marked.strip()) or (shaded and not self.text)
        self.all_green = self.green and not ''.join(t for t, g in self.parts if not g).strip()


class Sheet(list):
    """Таблица листа по позициям (как Grid в Word): объединённая ячейка — один объект во всех своих клетках.
    head — первая строка данных (индекс в списке), headers — заголовки столбцов, rows — номера строк Excel."""
    head = 1
    headers = ()
    rows = ()
    cols = ()


def _merged(ws):
    owner = {}
    for rng in ws.merged_cells.ranges:
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                owner[(r, c)] = (rng.min_row, rng.min_col)
    return owner


def _is_numbering(texts):
    t = [x for x in texts if x]
    return len(t) > 1 and t == [str(i) for i in range(1, len(t) + 1)]


def read_sheet(ws, limit_rows=3000):
    """Лист → Sheet. Шапка — строка с наибольшим числом подписей среди первых 15 (с объединёнными под ней
    строками двухуровневой шапки); строка «1 2 3 …» под шапкой пропускается."""
    owner = _merged(ws)
    max_r = min(ws.max_row, limit_rows)
    max_c = ws.max_column
    cache = {}

    def cell(r, c):
        key = owner.get((r, c), (r, c))
        if key not in cache:
            cache[key] = XCell(ws, *key)
        return cache[key]

    def labels(r):
        seen, n = set(), 0
        for c in range(1, max_c + 1):
            x = cell(r, c)
            if id(x) in seen:
                continue
            seen.add(id(x))
            if x.text and not re.fullmatch(r'[\d.,\s]+', x.text):
                n += 1
        return n
    if max_r < 1:
        return None
    head_r = max(range(1, min(15, max_r) + 1), key=lambda r: (labels(r), -r))
    if labels(head_r) < 2:
        return None
    last_head = head_r
    for rng in ws.merged_cells.ranges:                      # двухуровневая шапка: объединение вниз из строки шапки
        if rng.min_row == head_r and rng.max_row > last_head and rng.max_row - head_r < 4:
            last_head = rng.max_row
    if last_head + 1 <= max_r and _is_numbering([cell(last_head + 1, c).text for c in range(1, max_c + 1)]):
        last_head += 1
    first = head_r
    # пустые столбцы справа (без подписи и данных) — не считаем
    used = [c for c in range(1, max_c + 1)
            if any(cell(r, c).text for r in range(first, max_r + 1))]
    if not used:
        return None
    cols = list(range(min(used), max(used) + 1))
    s = Sheet()
    s.rows = list(range(first, max_r + 1))
    s.cols = cols
    for r in s.rows:
        s.append([cell(r, c) for c in cols])
    s.head = last_head - first + 1
    headers = []
    for k, c in enumerate(cols):
        parts = []
        for r in range(head_r, last_head + 1):
            t = cell(r, c).text
            if t and t not in parts and not _is_numbering([cell(r, x).text for x in cols]):
                parts.append(t)
        headers.append(' '.join(parts))
    s.headers = headers
    while len(s) > s.head and H.is_empty(s[-1]):              # хвост пустых строк — не данные, но место для новых
        if len(s) - s.head <= 1:
            break
        if not any(H.is_empty(s[i]) for i in range(s.head, len(s) - 1)):
            break
        s.pop(); s.rows.pop()
    return s


def section_of(s, i):
    for j in range(i, s.head - 1, -1):
        if H.is_section(s[j]):
            return H.norm(s[j][0].text)
    return ''


def fills(sheet):
    return {c.fill for row in sheet for c in row if c.fill}


# ---------- сопоставление строк ----------

def match_row(row, mapping, dst, ident, include_green=False):
    """Как в Word: сначала по названию (столбец «Наименование…»), потом по неотмеченным ячейкам."""
    found = H._by_ident(row, mapping, dst, dst.head, ident)
    if found is not None:
        return found, ''
    keys, seen = [], set()
    for j, c in enumerate(row):
        if j in mapping and (include_green or not c.all_green) and H.norm(c.text) and id(c) not in seen:
            seen.add(id(c)); keys.append((j, c))
    if not keys:
        return None, ''
    scores = []
    for i in range(dst.head, len(dst)):
        if H.is_section(dst[i]):
            continue
        sc = 0.0
        for j, c in keys:
            k = mapping[j]
            if k < len(dst[i]):
                sim = H._similar(c.text, dst[i][k].text)
                sc += 1 if sim == 1 else (0.5 if sim >= 0.85 else 0)
        scores.append((sc, i))
    scores.sort(key=lambda x: -x[0])
    if not scores or scores[0][0] < max(1, len(keys) / 2):
        return None, ''
    if len(scores) > 1 and scores[1][0] == scores[0][0]:
        return None, 'неоднозначно'
    return scores[0][1], ''


# ---------- запись ----------

def _plain_value(src):
    """Значение для записи: число остаётся числом, дата — датой, текст — текстом."""
    v = src.value
    if isinstance(v, CellRichText):
        return str(v)
    return v


def _font_with(font, color):
    f = copy.copy(font)
    f.color = color
    return f


def write_cell(ws, r, c, src, mark):
    """Значение присланной ячейки — в ячейку документа; отмеченные части — зелёным шрифтом (mark=FONT),
    салатовой заливкой (mark=True) или без выделения."""
    cell = ws.cell(r, c)
    base = _font_with(cell.font, None)
    parts = src.parts or [('', False)]
    mixed = len({g for _, g in parts}) > 1
    if mark == H.FONT and mixed:
        inline = dict(rFont=base.name, sz=base.sz, b=base.b, i=base.i)
        cell.value = CellRichText([TextBlock(InlineFont(color=GREEN if g else None, **inline), t) for t, g in parts])
        cell.font = base
        return
    cell.value = _plain_value(src) if not mixed else ''.join(t for t, _ in parts)
    green = any(g for _, g in parts)
    cell.font = _font_with(base, GREEN) if (mark == H.FONT and green) else base
    if mark is True and green:
        cell.fill = copy.copy(MARKER)


def set_text(ws, r, c, text, mark, green=True):
    cell = ws.cell(r, c)
    base = _font_with(cell.font, None)
    cell.value = text
    cell.font = _font_with(base, GREEN) if (mark == H.FONT and green) else base
    if mark is True and green:
        cell.fill = copy.copy(MARKER)


def clear_marks(wb):
    """Прошлые зелёные отметки шрифтом — снять (видно только новое). Заливку не трогаем: это может быть раскраска."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                if _font_green(cell.font):
                    cell.font = _font_with(cell.font, None)
                if isinstance(cell.value, CellRichText):
                    blocks = []
                    for b in cell.value:
                        if isinstance(b, TextBlock) and b.font is not None and _green(_rgb(b.font.color)):
                            f = copy.copy(b.font); f.color = None
                            b = TextBlock(f, b.text)
                        blocks.append(b)
                    cell.value = CellRichText(blocks)


def _row_label(row):
    return next((x.text for x in row if H.norm(x.text) and not re.match(r'^\d+\.?$', H.norm(x.text))), '')


# ---------- сутки ----------

def update_days(wb, today, threshold, report):
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, CellRichText):
                    new_blocks, changed = [], False
                    for b in v:
                        text = b.text if isinstance(b, TextBlock) else str(b)
                        new, n, long = _recount(text, today, threshold)
                        if new != text:
                            changed = True
                            report.days.append(f'{text} → {new}')
                        if long:
                            report.long_stay.append(new); cell.fill = copy.copy(YELLOW)
                        new_blocks.append(TextBlock(b.font, new) if isinstance(b, TextBlock) else new)
                    if changed:
                        cell.value = CellRichText(new_blocks)
                elif isinstance(v, str) and H.DAYS.search(v):
                    new, n, long = _recount(v, today, threshold)
                    if new != v:
                        report.days.append(f'{v} → {new}')
                        cell.value = new
                    if long:
                        report.long_stay.append(new); cell.fill = copy.copy(YELLOW)


def _recount(text, today, threshold):
    long = False
    n_last = None

    def repl(m):
        nonlocal long, n_last
        n = H.days_since(m.group(3), m.group(4), m.group(5), today)
        if n is None:
            return m.group(0)
        n_last = n
        if threshold is not None and n > threshold:
            long = True
        return f'{n}{m.group(2)}{m.group(3)}.{m.group(4)}.{m.group(5)}'
    return H.DAYS.sub(repl, text), n_last, long


# ---------- оформление по шаблону ----------

def apply_format(wb, template):
    """Строго по шаблону: шрифт (имя, размер, начертание), выравнивание, рамки, формат чисел, ширина столбцов,
    высота строк шапки, поля и ориентация страницы. Цвет шрифта (зелёные отметки) и заливка-отметка остаются."""
    tpl = load_workbook(str(template), rich_text=True)
    tsheets = [(ws, read_sheet(ws)) for ws in tpl.worksheets]
    tsheets = [(ws, s) for ws, s in tsheets if s]
    for ws in wb.worksheets:
        s = read_sheet(ws)
        if s is None or not tsheets:
            continue
        tws, t = max(tsheets, key=lambda x: H.table_score(s, x[1]))
        if H.table_score(s, t) < 0.3:
            continue
        mapping = H.column_map(s.headers, t.headers)
        for k, c in enumerate(s.cols):
            tk = mapping.get(k, k)
            if tk < len(t.cols):
                letter_t = tws.cell(1, t.cols[tk]).column_letter
                letter = ws.cell(1, c).column_letter
                if tws.column_dimensions[letter_t].width:
                    ws.column_dimensions[letter].width = tws.column_dimensions[letter_t].width
        ws.page_setup.orientation = tws.page_setup.orientation
        ws.page_margins = copy.copy(tws.page_margins)
        data = [i for i in range(t.head, len(t)) if not H.is_section(t[i])]
        sections = [i for i in range(t.head, len(t)) if H.is_section(t[i])]
        for i, row in enumerate(s):
            if i < s.head:
                ti = min(i, t.head - 1)
                if tws.row_dimensions[t.rows[ti]].height:
                    ws.row_dimensions[s.rows[i]].height = tws.row_dimensions[t.rows[ti]].height
            elif H.is_section(row):
                ti = sections[0] if sections else None
            else:
                ti = data[min(i - s.head, len(data) - 1)] if data else None
            if ti is None:
                continue
            for k, c in enumerate(s.cols):
                tk = mapping.get(k, k)
                if tk >= len(t.cols):
                    continue
                src = tws.cell(t.rows[ti], t.cols[tk])
                dst = ws.cell(s.rows[i], c)
                if dst.coordinate in ws.merged_cells and (s.rows[i], c) != (row[k].r, row[k].c):
                    continue                                   # внутренняя клетка объединения
                color = dst.font.color if (_font_green(dst.font)) else None
                f = copy.copy(src.font); f.color = color
                dst.font = f
                dst.alignment = copy.copy(src.alignment)
                dst.border = copy.copy(src.border)
                if not isinstance(dst.value, (int, float)) or src.number_format != 'General':
                    dst.number_format = src.number_format
                if isinstance(dst.value, CellRichText):        # части текста — шрифтом шаблона, цвет свой
                    blocks = []
                    for b in dst.value:
                        if isinstance(b, TextBlock):
                            col = b.font.color if b.font is not None else None
                            b = TextBlock(InlineFont(rFont=f.name, sz=f.sz, b=f.b, i=f.i, color=col), b.text)
                        blocks.append(b)
                    dst.value = CellRichText(blocks)


# ---------- новые строки ----------

def _insert_row(ws, at):
    """Вставить строку перед at, сдвинув объединения ниже (openpyxl сам их не двигает); вид — как у строки выше."""
    moved = []
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row >= at:
            moved.append((rng.min_row, rng.min_col, rng.max_row, rng.max_col))
            ws.unmerge_cells(str(rng))
    ws.insert_rows(at)
    for r1, c1, r2, c2 in moved:
        ws.merge_cells(start_row=r1 + 1, start_column=c1, end_row=r2 + 1, end_column=c2)
    if at > 1:
        for c in range(1, ws.max_column + 1):
            above, new = ws.cell(at - 1, c), ws.cell(at, c)
            new.font, new.border, new.alignment = copy.copy(above.font), copy.copy(above.border), copy.copy(above.alignment)
            new.number_format, new.fill = above.number_format, copy.copy(above.fill)
        if ws.row_dimensions[at - 1].height:
            ws.row_dimensions[at].height = ws.row_dimensions[at - 1].height


def _add_rows(ws, sheet_dst, rows, mark, report):
    """Новые строки — в первую пустую строку своего раздела, иначе новой строкой после последней строки раздела."""
    for cells, name, section in rows:
        start, stop = sheet_dst.head, len(sheet_dst)
        if section:
            at = next((i for i in range(sheet_dst.head, len(sheet_dst)) if H.is_section(sheet_dst[i])
                       and H.norm(sheet_dst[i][0].text) == section), None)
            if at is not None:
                start = at + 1
                stop = next((i for i in range(start, len(sheet_dst)) if H.is_section(sheet_dst[i])), len(sheet_dst))
        empty = next((i for i in range(start, stop) if H.is_empty(sheet_dst[i])), None)
        if empty is not None:
            r = sheet_dst.rows[empty]
        else:
            last = stop - 1
            while last >= start and H.TOTAL.match(_row_label(sheet_dst[last]) or ''):
                last -= 1
            r = (sheet_dst.rows[last] if last >= sheet_dst.head else sheet_dst.rows[sheet_dst.head - 1]) + 1
            _insert_row(ws, r)
        for k, src in cells.items():
            write_cell(ws, r, sheet_dst.cols[k], src, mark)
        label = next((src.text for src in cells.values() if H.norm(src.text)), '')
        report.added_rows.append(f'{label} ({name})' + (f' — раздел «{section}»' if section else ''))
        report.placed.append(f'новая строка «{label}» ({name})')
        # лист изменился — перечитать, чтобы следующие строки встали правильно
        fresh = read_sheet(ws)
        if fresh is not None:
            sheet_dst[:] = fresh
            sheet_dst.rows, sheet_dst.cols, sheet_dst.head, sheet_dst.headers = fresh.rows, fresh.cols, fresh.head, fresh.headers


# ---------- главное ----------

def merge(template, sources, output, mark=H.FONT, accept=(), days=True, threshold=None, today=None, base=None,
          take_all=False):
    """Как iskra_highlight.merge, но для .xlsx. Возвращает тот же Report."""
    report = H.Report()
    accept = set(accept)
    today = today or date.today()
    wb = load_workbook(str(base or template), rich_text=True)
    use_theme(wb)
    if base or mark == H.FONT:
        clear_marks(wb)
    dst_sheets = [(ws, read_sheet(ws)) for ws in wb.worksheets]
    dst_sheets = [(ws, s) for ws, s in dst_sheets if s]
    values, info, new_rows = {}, {}, {}
    for path in sources:
        name = Path(path).name
        src_wb = load_workbook(str(path), rich_text=True, data_only=True)
        use_theme(src_wb)
        found_marks = False
        for s_index, sws in enumerate(src_wb.worksheets):
            s = read_sheet(sws)
            if s is None or not dst_sheets:
                continue
            best = max(range(len(dst_sheets)), key=lambda i: H.table_score(s, dst_sheets[i][1]))
            dws, d = dst_sheets[best]
            tf = fills(d)
            for row in s:
                for c in row:
                    c.resolve(tf)
            marked_sheet = any(c.green for row in s for c in row)
            found_marks = found_marks or marked_sheet
            if H.table_score(s, d) < 0.3:
                if marked_sheet:
                    report.unplaced.append(f'{name}, лист «{sws.title}»: в документе нет такой таблицы')
                continue
            mapping = H.column_map(s.headers, d.headers)
            ident = H.ident_column(s.headers)
            for i in range(s.head, len(s)):
                row = s[i]
                if H.is_section(row) or H.is_empty(row) or H.TOTAL.match(_row_label(row) or ''):
                    continue
                marked = any(c.green for c in row)
                target, why = match_row(row, mapping, d, ident)
                if target is None and marked and all(c.all_green or not H.norm(c.text) for c in row):
                    target, why = match_row(row, mapping, d, ident, include_green=True)
                    if target is None:
                        _new_row(new_rows, best, row, mapping, name, section_of(s, i)); continue
                if target is None:
                    if marked:
                        report.unplaced.append(f'{name}: строка «{" | ".join(c.text for c in row)}» — '
                                               + ('подходит к нескольким строкам документа' if why else 'нет такой строки в документе'))
                    elif sum(1 for c in set(row) if H.norm(c.text)) >= 2:
                        uid = (str(path), s_index, i, 'row')
                        if uid in accept or take_all:
                            for c in set(row):
                                _mark_all(c)
                            _new_row(new_rows, best, row, mapping, name, section_of(s, i))
                        else:
                            report.unmarked.append({'id': uid, 'file': name, 'object': _row_label(row), 'column': 'новая строка',
                                                    'old': '', 'new': ' | '.join(dict.fromkeys(c.text for c in row if c.text))})
                    continue
                done = set()
                for j, c in enumerate(row):
                    if id(c) in done or j not in mapping:
                        if c.green and j not in mapping and id(c) not in done:
                            report.unplaced.append(f'{name}: «{c.text}» — нет столбца «{s.headers[j]}» в документе')
                        done.add(id(c)); continue
                    done.add(id(c))
                    goal = d[target][mapping[j]]
                    if not c.green and H._green_hex(c.fill) and c.fill != goal.fill and H.norm(c.text):
                        _mark_all(c)
                    if H.norm(c.text) == H.norm(goal.text) and not c.green:
                        continue
                    uid = (str(path), s_index, i, j)
                    if c.green or uid in accept or take_all:
                        if not c.green:
                            _mark_all(c)
                        key = (best, goal.r, goal.c)
                        values.setdefault(key, {}).setdefault(H.norm(c.text), [c, []])[1].append(name)
                        info[key] = (_row_label(d[target]), d.headers[mapping[j]], goal.text, target)
                    elif H.norm(c.text):
                        report.unmarked.append({'id': uid, 'file': name, 'object': _row_label(d[target]),
                                                'column': d.headers[mapping[j]], 'old': goal.text, 'new': c.text})
        if not found_marks:
            report.files_without_marks.append(name)

    use_theme(wb)                                       # дальше — палитра документа, а не последнего присланного
    moved = set()
    for (b, r, c), variants in values.items():
        dws, d = dst_sheets[b]
        label, header, old, target = info[(b, r, c)]
        where = f'{label} / {header}'
        if len(variants) == 1:
            src, files = next(iter(variants.values()))
            write_cell(dws, r, c, src, mark)
            same = ' — то же значение, отмечено как изменение' if H.norm(old) == H.norm(src.text) else ''
            report.placed.append(f'{where}: «{src.text}» ({", ".join(files)}){same}')
            report.changes.append({'object': label, 'column': header, 'old': old, 'new': src.text, 'files': files})
            if H.POSITION.search(header or '') and H.norm(old) != H.norm(src.text):
                moved.add((b, target))
        else:
            text = '[УТОЧНИТЬ: ' + ' или '.join(f'{v[0].text} ({", ".join(v[1])})' for v in variants.values()) + ']'
            set_text(dws, r, c, text, mark)
            dws.cell(r, c).fill = copy.copy(YELLOW)
            report.conflicts.append(f'{where}: {text[11:-1]}')
    for b, target in sorted(moved):
        dws, d = dst_sheets[b]
        placed_cols = {c for (bb, r, c) in values if bb == b and r == d.rows[target]}
        _restart_days(dws, d, target, placed_cols, mark, today, report)
    if days:                                           # пересчёт — до новых строк: у них сутки уже свои
        update_days(wb, today, threshold, report)
    for b, rows in new_rows.items():
        dws, d = dst_sheets[b]
        _add_rows(dws, d, rows, mark, report)
    if base and Path(str(base)).resolve() != Path(str(template)).resolve():
        try:
            apply_format(wb, template)
        except Exception as exc:                       # noqa: BLE001 — изменения важнее оформления
            report.unplaced.append(f'Оформление по шаблону применено не полностью ({type(exc).__name__}) — '
                                   'изменения перенесены, проверьте шрифт.')
    report.snapshot = snapshot(wb)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output))
    return report


def _mark_all(c):
    c.parts = [(t, True) for t, _ in c.parts]
    c.green = c.all_green = True


def _new_row(new_rows, best, row, mapping, name, section):
    cells = {}
    for j, c in enumerate(row):
        if j in mapping and c not in cells.values():
            cells[mapping[j]] = c
    sig = tuple(H.norm(c.text) for c in cells.values())
    if sig not in {tuple(H.norm(c.text) for c in x[0].values()) for x in new_rows.get(best, [])}:
        new_rows.setdefault(best, []).append((cells, name, section))


def _restart_days(ws, d, target, placed_cols, mark, today, report):
    row = d[target]
    col = next((k for k, h in enumerate(d.headers) if H.STAY.search(h or '')), None)
    if col is None:
        col = next((k for k, c in enumerate(row) if H.DAYS.search(c.text or '')), None)
    if col is None or row[col].c in placed_cols:
        return
    cell = row[col]
    old = cell.text
    m = H.DAYS.search(old or '')
    when = today.strftime('%d.%m.%Y')
    new = (old[:m.start()] + '1' + m.group(2) + when + old[m.end():]) if m else f'1 сут. с {when}'
    set_text(ws, cell.r, cell.c, new, mark)
    report.placed.append(f'{_row_label(row)} / {d.headers[col]}: «{new}» (положение сменилось — сутки заново)')
    report.changes.append({'object': _row_label(row), 'column': d.headers[col], 'old': old, 'new': new, 'files': []})


def snapshot(wb):
    out = []
    for ws in wb.worksheets:
        s = read_sheet(ws)
        if s is None:
            continue
        rows = []
        for i in range(s.head, len(s)):
            row = s[i]
            if H.is_section(row) or H.is_empty(row) or H.TOTAL.match(_row_label(row) or ''):
                continue
            cells, seen = {}, set()
            for k, c in enumerate(row):
                if id(c) in seen:
                    continue
                seen.add(id(c))
                cells[s.headers[k] or f'столбец {k + 1}'] = c.text
            rows.append({'object': _row_label(row), 'section': section_of(s, i), 'cells': cells})
        out.append({'headers': list(s.headers), 'rows': rows})
    return out
