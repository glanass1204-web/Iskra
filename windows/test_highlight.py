import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import iskra_highlight as H

TMP = Path(tempfile.mkdtemp())
HEAD = ['№', 'Город', 'Расстояние, км', 'Ответственный', 'Численность']
ROWS = [['1', 'Москва', '120', 'Иванов И.И.', '15'], ['2', 'Тверь', '180', 'Петров П.П.', '10'],
        ['3', 'Клин', '90', 'Сидоров С.С.', '8'], ['Итого', '', '', '', '33']]


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:fill'), fill)
    tc_pr.append(shd)


def make(name, head, rows, marks=(), cell_shade=(), paragraph=None):
    """marks: {(строка, столбец)} — выделить салатовым; cell_shade — залить ячейку 92D050."""
    doc = Document()
    doc.add_paragraph('ПЛАН ПЕРЕВОЗКИ')
    t = doc.add_table(rows=0, cols=len(head))
    for r_i, row in enumerate([head] + rows):
        cells = t.add_row().cells
        for c_i, v in enumerate(row):
            run = cells[c_i].paragraphs[0].add_run(v)
            if (r_i, c_i) in marks:
                run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
            if (r_i, c_i) in cell_shade:
                shade(cells[c_i], '92D050')
    p = doc.add_paragraph('Срок прибытия ')
    date = p.add_run(paragraph or '25.10.2026')
    if paragraph:
        date.font.highlight_color = WD_COLOR_INDEX.GREEN
    path = TMP / name
    doc.save(path)
    return path


def table_text(path):
    t = Document(str(path)).tables[0]
    out = []
    for row in t.rows:
        seen, cells = set(), []
        for c in row.cells:
            if id(c._tc) not in seen:
                seen.add(id(c._tc)); cells.append(c.text)
        out.append(cells)
    return out


class Merge(unittest.TestCase):
    def test_three_documents_into_template(self):
        template = make('образец.docx', HEAD, ROWS)
        a_rows = [r[:] for r in ROWS]; a_rows[1][2] = '185'; a_rows[1][3] = 'Смирнов А.А.'
        a = make('рота1.docx', HEAD, a_rows, marks={(2, 2)}, cell_shade={(2, 3)})
        # другой формат: без №, столбцы в другом порядке, своя подпись столбца
        head_b = ['Город', 'Ответственный', 'Численность, чел.', 'Расстояние (км)']
        b_rows = [['Москва', 'Иванов И.И.', '15', '120'], ['Клин', 'Сидоров С.С.', '12', '90'],
                  ['Дмитров', 'Козлов К.К.', '5', '70']]
        b = make('рота2.docx', head_b, b_rows, marks={(2, 2), (3, 0), (3, 1), (3, 2), (3, 3)})
        c_rows = [r[:] for r in ROWS]; c_rows[1][2] = '190'
        c = make('рота3.docx', HEAD, c_rows, marks={(2, 2)}, paragraph='27.10.2026')
        d = make('без_пометок.docx', HEAD, ROWS)
        out = TMP / 'итог.docx'
        rep = H.merge(template, [a, b, c, d], out)
        rows = table_text(out)
        tver = next(r for r in rows if r[1] == 'Тверь')
        self.assertIn('[УТОЧНИТЬ: 185 (рота1.docx) или 190 (рота3.docx)]', tver[2])
        self.assertEqual(tver[3], 'Смирнов А.А.')                      # залитая ячейка — тоже изменение
        klin = next(r for r in rows if r[1] == 'Клин')
        self.assertEqual(klin[4], '12')                                # из файла другого формата — в свой столбец
        names = [r[1] for r in rows]
        self.assertLess(names.index('Дмитров'), [r[0] for r in rows].index('Итого'))   # новая строка — перед «Итого»
        dm = rows[names.index('Дмитров')]
        self.assertEqual((dm[2], dm[3], dm[4]), ('70', 'Козлов К.К.', '5'))
        self.assertEqual(rows[-1][4], '42')                            # 15 + 10 + 12 + 5
        para = [p.text for p in Document(str(out)).paragraphs if p.text.startswith('Срок')][0]
        self.assertEqual(para, 'Срок прибытия 27.10.2026')
        self.assertEqual(rep.files_without_marks, ['без_пометок.docx'])
        self.assertEqual(len(rep.conflicts), 1)
        self.assertIn('33 → 42', ' '.join(rep.totals))
        self.assertEqual(rep.unplaced, [])
        # изменения выделены в итоговом документе
        cell = Document(str(out)).tables[0].rows[3].cells[4]
        self.assertTrue(any(r.font.highlight_color == WD_COLOR_INDEX.BRIGHT_GREEN for p in cell.paragraphs for r in p.runs))
        self.assertIn('Перенесено изменений', rep.text())

    def test_unknown_row_is_reported(self):
        template = make('о2.docx', HEAD, ROWS)
        rows = [r[:] for r in ROWS]; rows[2] = ['3', 'Казань', '800', 'Орлов О.О.', '4']
        src = make('чужой.docx', HEAD, rows, marks={(3, 4)})
        rep = H.merge(template, [src], TMP / 'и2.docx')
        self.assertEqual(len(rep.unplaced), 1)
        self.assertIn('Казань', rep.unplaced[0])

    def test_two_level_header_and_other_layout(self):
        def doc_two_level(name, rows, marks=()):
            d = Document()
            t = d.add_table(rows=2 + len(rows), cols=4)
            h = t.rows[0].cells
            h[0].text = 'Город'; h[1].text = 'Расстояние, км'; h[3].text = 'Численность'
            h[1].merge(h[2]); t.cell(0, 0).merge(t.cell(1, 0)); t.cell(0, 3).merge(t.cell(1, 3))
            t.cell(1, 1).text = 'туда'; t.cell(1, 2).text = 'обратно'
            for i, row in enumerate(rows, 2):
                for k, v in enumerate(row):
                    run = t.cell(i, k).paragraphs[0].add_run(v)
                    if (i, k) in marks:
                        run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
            d.save(TMP / name)
            return TMP / name
        base = [['Москва', '120', '125', '15'], ['Тверь', '180', '180', '10']]
        template = doc_two_level('шаблон2.docx', base)
        changed = [r[:] for r in base]; changed[1][2] = '200'
        src = doc_two_level('изм2.docx', changed, marks={(3, 2)})
        flat = make('плоский.docx', ['Город', 'Численность', 'Расстояние туда', 'Расстояние обратно'],
                    [['Москва', '17', '120', '125']], marks={(1, 1)})
        out = TMP / 'и3.docx'
        rep = H.merge(template, [src, flat], out)
        t = Document(str(out)).tables[0]
        self.assertEqual(t.cell(3, 2).text, '200')
        self.assertEqual(t.cell(3, 1).text, '180')
        self.assertEqual(t.cell(2, 3).text, '17')                      # из файла с другой шапкой
        self.assertEqual(rep.unplaced, [])

    def test_screenshot_case_green_font_and_coloured_rows(self):
        """Как на снимке: шапка, строка-раздел, строки «77 км»/«105 км» с заливкой образца, изменения — зелёным шрифтом."""
        from docx.shared import RGBColor
        heads = ['Наименование ПУ', 'Подчиненные в/ч', 'Удаление от линии фронта', 'Старший на ПУ', 'Телефоны',
                 'Количество ОС/ВВСТ', 'Положение', 'Характер ПУ, количество запасных районов', 'Время нахождения в районе']

        def build(name, kp, green=(), extra=None):
            d = Document()
            t = d.add_table(rows=6 + (1 if extra else 0) + 3, cols=9)
            for k, h in enumerate(heads):
                t.cell(0, k).text = h
            sec = t.cell(1, 0).merge(t.cell(1, 8)); sec.text = 'СЕВЕРОДОНЕЦКОЕ НАПРАВЛЕНИЕ'
            for r, km in ((2, '77 км'), (3, '105 км')):
                t.cell(r, 0).merge(t.cell(r, 1))
                t.cell(r, 2).text = km
                for k in range(9):
                    shade(t.cell(r, k), 'C2D69B' if k % 2 else '9BBB59')   # «оливковая» раскраска образца
            for k, v in enumerate(kp):
                cell = t.cell(4, k)
                for i, line in enumerate(v.split('\n')):
                    par = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
                    run = par.add_run(line)
                    if (k, i) in green or (k, -1) in green:
                        run.font.color.rgb = RGBColor(0x00, 0xB0, 0x50)
            if extra:
                for k, v in enumerate(extra):
                    run = t.cell(5, k).paragraphs[0].add_run(v)
                    run.font.color.rgb = RGBColor(0x00, 0xB0, 0x50)
            d.save(TMP / name)
            return TMP / name
        was = ['КП 5447 обр СпН', '', '56 км', 'НШ гв п/п-к Залупа В.А.', '12188 4444\n18197 4400\n11741 4444', '27/2',
               'с-в окраина ЗАЛУПИНСК', 'Заброшенное помещение в промышленной зоне, 1 запасной район', '4 сут. с 19.10.2026']
        now = was[:]; now[2] = '43 км'; now[5] = '27/4'; now[6] = 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК'
        template = build('ПУ_образец.docx', was)
        new_kp = ['КП 101 мсп', '', '30 км', 'НШ м-р Иванов И.И.', '11111 2222', '12/3', 'южнее ЛИСИЧАНСК', 'палатки', '2 сут.']
        sent = build('ПУ_рота.docx', now, green={(0, -1), (2, -1), (5, -1), (6, 1)}, extra=new_kp)
        out = TMP / 'ПУ_итог.docx'
        rep = H.merge(template, [sent], out)
        t = Document(str(out)).tables[0]
        self.assertEqual(t.cell(4, 2).text, '43 км')
        self.assertEqual(t.cell(4, 5).text, '27/4')
        self.assertEqual(t.cell(4, 6).text, 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК')
        self.assertEqual(t.cell(4, 0).text, 'КП 5447 обр СпН')            # отмечено, но не менялось — без изменений
        self.assertEqual(t.cell(2, 2).text, '77 км')                      # заливка образца — не изменение
        self.assertEqual(len(t.rows), 9)                                   # новые строки не добавлены лишние
        self.assertEqual(t.cell(5, 0).text, 'КП 101 мсп')                 # новая — в первую пустую строку раздела
        self.assertEqual(t.cell(5, 3).text, 'НШ м-р Иванов И.И.')
        self.assertEqual(rep.unplaced, [])
        self.assertEqual(len(rep.placed), 3)
        self.assertEqual(len(rep.added_rows), 1)
        self.assertIn('СЕВЕРОДОНЕЦКОЕ', rep.added_rows[0])

    def test_full_table_many_sections_no_empty_rows(self):
        """Реальный документ: всё заполнено, несколько направлений, одинаковые старшие/телефоны в разных строках."""
        from docx.shared import RGBColor
        heads = ['Наименование ПУ', 'Удаление от линии фронта', 'Старший на ПУ', 'Количество ОС/ВВСТ', 'Положение']
        sections = {'СЕВЕРОДОНЕЦКОЕ НАПРАВЛЕНИЕ': [['КП 5447', '56 км', 'НШ Залупа В.А.', '27/2', 'ЗАЛУПИНСК'],
                                                  ['КП 5448', '61 км', 'НШ Залупа В.А.', '12/1', 'ЛИСИЧАНСК'],
                                                  ['ЗКП 5447', '80 км', 'ЗНШ Петров П.П.', '9/0', 'КРЕМЕННАЯ']],
                    'ЛИМАНСКОЕ НАПРАВЛЕНИЕ': [['КП 7001', '40 км', 'НШ Сидоров С.С.', '30/5', 'ЛИМАН'],
                                              ['КП 7002', '45 км', 'НШ Сидоров С.С.', '18/2', 'ЯМПОЛЬ']]}

        def build(name, changes=(), extra=None):
            d = Document()
            t = d.add_table(rows=1, cols=5)
            for k, h in enumerate(heads):
                t.cell(0, k).text = h
            for sec, rows in sections.items():
                r = t.add_row(); c = r.cells[0].merge(r.cells[4]); c.text = sec
                for row in rows + ([extra[1]] if extra and extra[0] == sec else []):
                    cells = t.add_row().cells
                    for k, v in enumerate(row):
                        new = dict(changes).get((row[0], k))
                        run = cells[k].paragraphs[0].add_run(new or v)
                        if new or (extra and row is extra[1]):
                            run.font.color.rgb = RGBColor(0x00, 0xB0, 0x50)
            d.save(TMP / name)
            return TMP / name
        template = build('полный_образец.docx')
        a = build('полный_1.docx', changes={('КП 5448', 1): '58 км', ('КП 7002', 4): 'ЯМПОЛЬ, СЕВЕРСК'})
        b = build('полный_2.docx', changes={('КП 5447', 3): '27/4'},
                  extra=('ЛИМАНСКОЕ НАПРАВЛЕНИЕ', ['КП 7003', '50 км', 'НШ Орлов О.О.', '5/1', 'ДРОБЫШЕВО']))
        out = TMP / 'полный_итог.docx'
        rep = H.merge(template, [a, b], out)
        rows = [[c.text for c in r.cells] for r in Document(str(out)).tables[0].rows]
        by = {r[0]: r for r in rows}
        self.assertEqual(by['КП 5448'][1], '58 км')
        self.assertEqual(by['КП 5447'][1], '56 км')                     # тот же старший — но не та строка
        self.assertEqual(by['КП 5447'][3], '27/4')
        self.assertEqual(by['КП 7002'][4], 'ЯМПОЛЬ, СЕВЕРСК')
        names = [r[0] for r in rows]
        self.assertEqual(names.index('КП 7003'), names.index('КП 7002') + 1)   # новая — в конце своего раздела
        self.assertEqual(rep.unplaced, [])
        self.assertEqual(len(rep.placed), 3)

    def test_colors(self):
        self.assertTrue(H._green_hex('92D050'))
        self.assertTrue(H._green_hex('00FF00'))
        self.assertTrue(H._green_hex('C6EFCE'))
        self.assertFalse(H._green_hex('FFFF00'))
        self.assertFalse(H._green_hex('D9D9D9'))


if __name__ == '__main__':
    unittest.main()
