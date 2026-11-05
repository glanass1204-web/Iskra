"""Документы как у пользователя: таблица ПУ, разделы, заливка, многострочные ячейки, зелёные отметки."""
import sys
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

HEADS = ['Наименование ПУ', 'Подчиненные в/ч', 'Удаление от линии фронта', 'Старший на ПУ', 'Телефоны',
         'Количество ОС/ВВСТ', 'Положение', 'Характер ПУ, количество запасных районов', 'Время нахождения в районе']


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    tcPr.append(shd)


def build(path, rows, green=(), how='font', font='Times New Roman', size=10, title=True):
    d = Document()
    d.styles['Normal'].font.name, d.styles['Normal'].font.size = font, Pt(size)
    if title:
        p = d.add_paragraph(); r = p.add_run('СВЕДЕНИЯ о пунктах управления'); r.bold = True
    t = d.add_table(rows=2 + len(rows) + 3, cols=9)
    t.style = 'Table Grid'
    for k, h in enumerate(HEADS):
        c = t.cell(0, k); c.text = ''; r = c.paragraphs[0].add_run(h); r.bold = True
    sec = t.cell(1, 0).merge(t.cell(1, 8)); sec.text = ''; sec.paragraphs[0].add_run('СЕВЕРОДОНЕЦКОЕ НАПРАВЛЕНИЕ').bold = True
    for r_i, values in enumerate(rows, 2):
        for k, v in enumerate(values):
            c = t.cell(r_i, k)
            for i, line in enumerate(v.split('\n')):
                par = c.paragraphs[0] if i == 0 else c.add_paragraph()
                run = par.add_run(line)
                if (r_i - 2, k, i) in green or (r_i - 2, k, -1) in green:
                    if how == 'font':
                        run.font.color.rgb = RGBColor(0x00, 0xB0, 0x50)
                    elif how == 'marker':
                        run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
                    else:
                        shade(c, '92D050')
            if r_i < 4:
                shade(c, 'C2D69B' if k % 2 else '9BBB59')
    d.add_paragraph('Начальник штаба')
    d.save(path)


if __name__ == '__main__':
    pass
