"""Перенос изменений в Excel — те же правила, что в Word: шаблон + документ + присланные; зелёное переносится
и пишется зелёным шрифтом; строка — по названию ПУ (без задвоения); новый пункт снизу в той же ячейке;
сутки при переезде — заново; шрифт и ширина столбцов — как в шаблоне."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font, PatternFill

import iskra_highlight as H
import iskra_highlight_xlsx as X

TMP = Path(tempfile.mkdtemp())
HEADS = ['Наименование ПУ', 'Удаление от линии фронта', 'Старший на ПУ', 'Количество ОС/ВВСТ', 'Положение',
         'Время нахождения в районе']
WAS = [['КП 5447 обр СпН', '56 км', 'НШ п/п-к Залупа В.А.', '27/2', 'с-в окраина ЗАЛУПИНСК', '4 сут. с 19.10.2026'],
       ['КП 7001', '40 км', 'НШ м-р Иванов И.И.', '30/5', 'ЛИМАН', '2 сут. с 21.10.2026'],
       ['КП 7002', '45 км', 'НШ м-р Сидоров С.С.', '18/2', 'ЯМПОЛЬ', '3 сут. с 20.10.2026']]
G = 'FF00B050'


def book(name, rows, font=('Calibri', 11), green=None, extra=(), widths=None):
    """green: {(строка, столбец): 'all' | 'second_line' | 'fill'}."""
    wb = Workbook(); ws = wb.active; ws.title = 'ПУ'
    ws.append(['СВЕДЕНИЯ о пунктах управления'])
    ws.append(HEADS)
    ws.append(['СЕВЕРОДОНЕЦКОЕ НАПРАВЛЕНИЕ'])
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=6)
    for r in list(rows) + list(extra):
        ws.append(r)
    ws.append([None] * 6)
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name=font[0], size=font[1])
    for (r, k), how in (green or {}).items():
        cell = ws.cell(4 + r, 1 + k)
        if how == 'all':
            cell.font = Font(name=font[0], size=font[1], color=G)
        elif how == 'fill':
            cell.fill = PatternFill('solid', fgColor='92D050')
        elif how == 'second_line':
            old, new = str(cell.value).split('\n')
            cell.value = CellRichText([TextBlock(InlineFont(rFont=font[0], sz=font[1]), old + '\n'),
                                       TextBlock(InlineFont(rFont=font[0], sz=font[1], color=G), new)])
    for col, w in (widths or {}).items():
        ws.column_dimensions[col].width = w
    wb.save(TMP / name)
    return TMP / name


class ExcelTransfer(unittest.TestCase):
    def test_three_units(self):
        template = book('шаблон.xlsx', WAS, font=('Times New Roman', 12), widths={'A': 22, 'E': 30})
        doc = book('документ.xlsx', WAS, font=('Arial', 9))
        moved = [r[:] for r in WAS]
        moved[0] = ['КП 5447 обр СпН', '43 км', 'НШ м-р Петров П.П.', '27/4', 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК', '4 сут. с 19.10.2026']
        s1 = book('рота1.xlsx', moved, green={(0, 0): 'all', (0, 1): 'all', (0, 2): 'all', (0, 3): 'all', (0, 4): 'second_line'})
        km = [r[:] for r in WAS]; km[1][1] = '35 км'
        s2 = book('рота2.xlsx', km, green={(1, 1): 'fill'})
        s3 = book('рота3.xlsx', WAS, extra=[['КП 9001', '30 км', 'НШ к-н Орлов О.О.', '5/1', 'МИРНОГРАД', '1 сут. с 24.10.2026']],
                  green={(3, k): 'all' for k in range(6)})
        out = TMP / 'итог.xlsx'
        rep = X.merge(template, [s1, s2, s3], out, mark=H.FONT, base=doc, today=date(2026, 10, 24))
        ws = load_workbook(out, rich_text=True).active
        col = {h: i + 1 for i, h in enumerate(HEADS)}

        def text(r, h):
            return X._text(ws.cell(r, col[h]).value)

        names = [text(r, 'Наименование ПУ') for r in range(4, ws.max_row + 1)]
        self.assertEqual(names.count('КП 5447 обр СпН'), 1, names)                  # без задвоения
        self.assertEqual(text(4, 'Удаление от линии фронта'), '43 км')
        self.assertEqual(text(4, 'Положение'), 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК')    # новый пункт снизу
        place = ws.cell(4, col['Положение']).value
        self.assertIsInstance(place, CellRichText)                                   # старое — чёрным, новое — зелёным
        self.assertEqual([(b.text.strip(), X._rgb(b.font.color) == 'B050' or (b.font.color is not None and X._rgb(b.font.color) == '00B050'))
                          for b in place], [('с-в окраина ЗАЛУПИНСК', False), ('ПЕЧОРИНСК', True)])
        self.assertEqual(text(4, 'Время нахождения в районе'), '1 сут. с 24.10.2026')   # переезд — сутки заново
        self.assertTrue(X._font_green(ws.cell(4, col['Время нахождения в районе']).font))
        self.assertEqual(text(5, 'Удаление от линии фронта'), '35 км')                 # отмечено заливкой
        self.assertTrue(X._font_green(ws.cell(5, col['Удаление от линии фронта']).font))
        self.assertEqual(text(5, 'Время нахождения в районе'), '4 сут. с 21.10.2026')  # без переезда — пересчёт
        self.assertFalse(X._font_green(ws.cell(5, col['Время нахождения в районе']).font))
        self.assertFalse(X._font_green(ws.cell(6, col['Удаление от линии фронта']).font))   # не менялось — чёрным
        self.assertIn('КП 9001', names)                                              # новый ПУ — в пустую строку
        r9 = 4 + names.index('КП 9001')
        self.assertTrue(X._font_green(ws.cell(r9, 1).font))
        # строго по шаблону: шрифт и размер везде, ширина столбцов
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if c.value not in (None, ''):
                    self.assertEqual((c.font.name, c.font.sz), ('Times New Roman', 12), c.coordinate)
        self.assertEqual(ws.column_dimensions['A'].width, 22)
        self.assertEqual(ws.column_dimensions['E'].width, 30)
        self.assertEqual(rep.unplaced, [])
        self.assertEqual(rep.conflicts, [])

    def test_next_day_old_green_becomes_black(self):
        doc = book('вчера.xlsx', WAS, green={(0, 1): 'all'})
        out = TMP / 'сегодня.xlsx'
        X.merge(doc, [book('рота_сегодня.xlsx', WAS)], out, mark=H.FONT, base=doc, today=date(2026, 10, 25))
        ws = load_workbook(out, rich_text=True).active
        self.assertFalse(X._font_green(ws.cell(4, 2).font))
        self.assertEqual(X._text(ws.cell(4, 6).value), '7 сут. с 19.10.2026')

    def test_conflict_between_units(self):
        doc = book('док_к.xlsx', WAS)
        a = [r[:] for r in WAS]; a[0][1] = '43 км'
        b = [r[:] for r in WAS]; b[0][1] = '44 км'
        out = TMP / 'конфликт.xlsx'
        rep = X.merge(doc, [book('a.xlsx', a, green={(0, 1): 'all'}), book('b.xlsx', b, green={(0, 1): 'all'})], out,
                      mark=H.FONT, base=doc, today=date(2026, 10, 24))
        self.assertEqual(len(rep.conflicts), 1)
        self.assertIn('УТОЧНИТЬ', X._text(load_workbook(out).active.cell(4, 2).value))


class Colours(unittest.TestCase):
    def test_theme_and_palette_greens(self):
        """Зелёный из верхних рядов палитры Excel (цвет темы «акцент 6», светлее/темнее) и из старой палитры."""
        from openpyxl.styles.colors import Color
        for color in (Color(theme=9), Color(theme=9, tint=0.4), Color(theme=9, tint=-0.25), Color(indexed=17), Color(rgb='FF92D050')):
            with self.subTest(color=color):
                self.assertTrue(X._font_green(Font(color=color)))
        for color in (Color(theme=1), Color(theme=4), Color(rgb='FFFF0000'), Color(indexed=8)):
            with self.subTest(color=color):
                self.assertFalse(X._font_green(Font(color=color)))


if __name__ == '__main__':
    unittest.main()
