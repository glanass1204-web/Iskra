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

    def test_colors(self):
        self.assertTrue(H._green_hex('92D050'))
        self.assertTrue(H._green_hex('00FF00'))
        self.assertTrue(H._green_hex('C6EFCE'))
        self.assertFalse(H._green_hex('FFFF00'))
        self.assertFalse(H._green_hex('D9D9D9'))


if __name__ == '__main__':
    unittest.main()
