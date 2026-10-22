"""Offline VBA macro builder: turns a task in plain Russian into a ready Excel or Word macro made of
tested building blocks, checks VBA code for typical mistakes and explains/fixes runtime errors.
No AI: only the operations below are understood, and the user is told what was not."""
import re
from dataclasses import dataclass, field
from datetime import date

CYR_TO_LAT = str.maketrans('АВСЕНКМОРТХ', 'ABCEHKMOPTX')
COLORS = {
    'красн': 'RGB(255, 199, 206)', 'зелен': 'RGB(198, 239, 206)', 'желт': 'RGB(255, 235, 156)',
    'син': 'RGB(189, 215, 238)', 'голуб': 'RGB(189, 215, 238)', 'оранж': 'RGB(252, 213, 180)',
    'сер': 'RGB(217, 217, 217)', 'фиолет': 'RGB(225, 211, 242)',
}


def vba_str(s):
    return '"' + str(s).replace('"', '""') + '"'


@dataclass
class Params:
    text: str
    col: str = 'A'
    col_given: bool = False
    quoted: list = field(default_factory=list)
    numbers: list = field(default_factory=list)
    color: str = 'RGB(255, 235, 156)'
    all_sheets: bool = False
    desc: bool = False


def parse_params(clause):
    t = clause.lower().replace('ё', 'е')
    p = Params(clause)
    m = re.search(r'(?:столбц\w*|столбе\w*|колонк\w*|графе|графы)\s+([A-Za-zА-Яа-я]{1,2})\b', clause, re.IGNORECASE) \
        or re.search(r'\b(?:в|по|из)\s+([A-Za-z])\b', clause)
    if m:
        p.col, p.col_given = m.group(1).upper().translate(CYR_TO_LAT), True
    p.quoted = re.findall(r'[«"„“]([^»"”]*)[»"”]', clause)
    p.numbers = [float(x.replace(',', '.')) for x in re.findall(r'(?<![\w.])(\d+(?:[.,]\d+)?)', re.sub(r'[«"„“][^»"”]*[»"”]', '', clause))]
    for stem, rgb in COLORS.items():
        if stem in t:
            p.color = rgb
            break
    p.all_sheets = bool(re.search(r'(на|во|по) всех лист|каждом лист|все листы', t))
    p.desc = bool(re.search(r'убыв|от большего|от я|по убыв|сначала больш|z-a|я-а', t))
    return p


@dataclass(frozen=True)
class Op:
    key: str
    app: str            # 'excel' | 'word'
    title: str
    pattern: str        # regex over the lowercased clause
    scope: str          # 'sheet' (Sub(ws)), 'book' (no args), 'doc' (Sub(doc)), 'app' (no args)
    build: object       # Params -> (title detail, [vba lines])
    needs: str = ''     # what parameters must be present: 'quoted', 'two_quoted'


def _last_row(col):
    return f'lastRow = ws.Cells(ws.Rows.Count, "{col}").End(xlUp).Row'


# ---------- Excel ----------

def x_delete_empty_rows(p):
    return 'Удалить пустые строки', [
        'Dim r As Long, lastRow As Long',
        'lastRow = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1',
        'For r = lastRow To 1 Step -1',
        '    If Application.WorksheetFunction.CountA(ws.Rows(r)) = 0 Then ws.Rows(r).Delete',
        'Next r']


def x_highlight_dups(p):
    return f'Выделить повторы в столбце {p.col}', [
        'Dim r As Long, lastRow As Long, rng As Range',
        _last_row(p.col),
        'If lastRow < 2 Then Exit Sub',
        f'Set rng = ws.Range(ws.Cells(2, "{p.col}"), ws.Cells(lastRow, "{p.col}"))',
        'For r = 2 To lastRow',
        f'    If Len(CStr(ws.Cells(r, "{p.col}").Value)) > 0 Then',
        f'        If Application.WorksheetFunction.CountIf(rng, ws.Cells(r, "{p.col}").Value) > 1 Then ws.Cells(r, "{p.col}").Interior.Color = {p.color}',
        '    End If',
        'Next r']


def x_remove_dups(p):
    return f'Удалить строки-повторы по столбцу {p.col}', [
        'Dim colIndex As Long',
        f'colIndex = ws.Range("{p.col}1").Column - ws.UsedRange.Column + 1',
        'If colIndex < 1 Then Exit Sub',
        'ws.UsedRange.RemoveDuplicates Columns:=colIndex, Header:=xlYes']


def x_sort(p):
    order = 'xlDescending' if p.desc else 'xlAscending'
    return f'Сортировать по столбцу {p.col} ' + ('по убыванию' if p.desc else 'по возрастанию'), [
        'Dim rng As Range',
        'Set rng = ws.UsedRange',
        f'rng.Sort Key1:=ws.Range("{p.col}" & rng.Row), Order1:={order}, Header:=xlYes']


def x_autofit(p):
    return 'Подогнать ширину столбцов', ['ws.UsedRange.Columns.AutoFit']


def _cells_loop(p, action):
    target = f'ws.Range(ws.Cells(1, "{p.col}"), ws.Cells(lastRow, "{p.col}"))' if p.col_given else 'ws.UsedRange'
    lines = ['Dim c As Range, lastRow As Long']
    if p.col_given:
        lines.append(_last_row(p.col))
    lines += [f'For Each c In {target}.Cells',
              '    If Not c.HasFormula And Not IsError(c.Value) Then',
              '        If VarType(c.Value) = vbString Then ' + action,
              '    End If',
              'Next c']
    return lines


def x_trim(p):
    where = f'в столбце {p.col}' if p.col_given else 'на листе'
    return f'Убрать лишние пробелы {where}', _cells_loop(p, 'c.Value = Application.WorksheetFunction.Trim(c.Value)')


def x_case(p):
    t = p.text.lower()
    if 'заглавн' in t and 'кажд' in t or 'с большой' in t:
        fn, name = 'StrConv(c.Value, vbProperCase)', 'Каждое Слово С Заглавной'
    elif 'строчн' in t or 'маленьк' in t:
        fn, name = 'LCase(c.Value)', 'строчные буквы'
    else:
        fn, name = 'UCase(c.Value)', 'ПРОПИСНЫЕ буквы'
    where = f'в столбце {p.col}' if p.col_given else 'на листе'
    return f'{name} {where}', _cells_loop(p, f'c.Value = {fn}')


def x_values(p):
    return 'Заменить формулы значениями', [
        'Dim c As Range',
        'For Each c In ws.UsedRange.Cells',
        '    If c.HasFormula And Not c.MergeCells Then c.Value = c.Value',
        'Next c']


def x_replace(p):
    a, b = (p.quoted + ['', ''])[:2]
    return f'Заменить «{a}» на «{b}»', [
        f'ws.Cells.Replace What:={vba_str(a)}, Replacement:={vba_str(b)}, LookAt:=xlPart, MatchCase:=False']


def x_sheets_to_files(p):
    return 'Сохранить каждый лист отдельным файлом', [
        'Dim sh As Worksheet, folder As String',
        'folder = ActiveWorkbook.Path',
        'If folder = "" Then',
        '    MsgBox "Сначала сохраните книгу: файлы листов будут рядом с ней.", vbExclamation, "Искра"',
        '    Exit Sub',
        'End If',
        'Application.DisplayAlerts = False',
        'For Each sh In ActiveWorkbook.Worksheets',
        '    sh.Copy',
        '    ActiveWorkbook.SaveAs Filename:=folder & "\\" & sh.Name & ".xlsx", FileFormat:=xlOpenXMLWorkbook',
        '    ActiveWorkbook.Close SaveChanges:=False',
        'Next sh',
        'Application.DisplayAlerts = True']


def x_combine_sheets(p):
    return 'Собрать все листы на один лист «Сводная»', [
        'Dim wb As Workbook, sh As Worksheet, target As Worksheet',
        'Dim nextRow As Long, lastRow As Long, lastCol As Long',
        'Set wb = ActiveWorkbook',
        'Application.DisplayAlerts = False',
        'On Error Resume Next',
        'wb.Worksheets("Сводная").Delete',
        'On Error GoTo 0',
        'Application.DisplayAlerts = True',
        'Set target = wb.Worksheets.Add(Before:=wb.Worksheets(1))',
        'target.Name = "Сводная"',
        'nextRow = 1',
        'For Each sh In wb.Worksheets',
        '    If sh.Name <> target.Name And Application.WorksheetFunction.CountA(sh.Cells) > 0 Then',
        '        lastRow = sh.Cells.Find("*", SearchOrder:=xlByRows, SearchDirection:=xlPrevious).Row',
        '        lastCol = sh.Cells.Find("*", SearchOrder:=xlByColumns, SearchDirection:=xlPrevious).Column',
        '        If nextRow = 1 Then',
        '            sh.Range(sh.Cells(1, 1), sh.Cells(lastRow, lastCol)).Copy target.Cells(1, 1)',
        '            nextRow = lastRow + 1',
        '        ElseIf lastRow >= 2 Then',
        '            sh.Range(sh.Cells(2, 1), sh.Cells(lastRow, lastCol)).Copy target.Cells(nextRow, 1)',
        '            nextRow = nextRow + lastRow - 1',
        '        End If',
        '    End If',
        'Next sh']


def x_combine_files(p):
    return 'Собрать первые листы всех файлов Excel из папки на один лист', [
        'Dim folder As String, f As String, src As Workbook, target As Worksheet',
        'Dim nextRow As Long, lastRow As Long, lastCol As Long',
        'With Application.FileDialog(msoFileDialogFolderPicker)',
        '    .Title = "Папка с файлами Excel"',
        '    If .Show <> -1 Then Exit Sub',
        '    folder = .SelectedItems(1) & "\\"',
        'End With',
        'Set target = ActiveWorkbook.Worksheets.Add(After:=ActiveWorkbook.Worksheets(ActiveWorkbook.Worksheets.Count))',
        'nextRow = 1',
        'Application.DisplayAlerts = False',
        'f = Dir(folder & "*.xls*")',
        'Do While f <> ""',
        '    If folder & f <> ActiveWorkbook.FullName Then',
        '        Set src = Workbooks.Open(folder & f, ReadOnly:=True)',
        '        With src.Worksheets(1)',
        '            If Application.WorksheetFunction.CountA(.Cells) > 0 Then',
        '                lastRow = .Cells.Find("*", SearchOrder:=xlByRows, SearchDirection:=xlPrevious).Row',
        '                lastCol = .Cells.Find("*", SearchOrder:=xlByColumns, SearchDirection:=xlPrevious).Column',
        '                If nextRow = 1 Then',
        '                    .Range(.Cells(1, 1), .Cells(lastRow, lastCol)).Copy target.Cells(1, 1)',
        '                    target.Cells(1, lastCol + 1).Value = "Файл"',
        '                    nextRow = 2',
        '                End If',
        '                If lastRow >= 2 Then',
        '                    .Range(.Cells(2, 1), .Cells(lastRow, lastCol)).Copy target.Cells(nextRow, 1)',
        '                    target.Range(target.Cells(nextRow, lastCol + 1), target.Cells(nextRow + lastRow - 2, lastCol + 1)).Value = f',
        '                    nextRow = nextRow + lastRow - 1',
        '                End If',
        '            End If',
        '        End With',
        '        src.Close SaveChanges:=False',
        '    End If',
        '    f = Dir()',
        'Loop',
        'Application.DisplayAlerts = True']


def x_split_by_column(p):
    return f'Разнести строки по листам по значениям столбца {p.col}', [
        'Dim dict As Object, key As Variant, sh As Worksheet',
        'Dim r As Long, lastRow As Long, nextRow As Long, sheetName As String',
        'Set dict = CreateObject("Scripting.Dictionary")',
        _last_row(p.col),
        'For r = 2 To lastRow',
        f'    If Len(CStr(ws.Cells(r, "{p.col}").Value)) > 0 Then dict(CStr(ws.Cells(r, "{p.col}").Value)) = 1',
        'Next r',
        'For Each key In dict.Keys',
        '    sheetName = key',
        '    sheetName = Replace(Replace(Replace(Replace(sheetName, "/", "-"), "\\", "-"), ":", "-"), "?", "")',
        '    sheetName = Left(Replace(Replace(Replace(sheetName, "*", ""), "[", "("), "]", ")"), 31)',
        '    Set sh = ActiveWorkbook.Worksheets.Add(After:=ActiveWorkbook.Worksheets(ActiveWorkbook.Worksheets.Count))',
        '    On Error Resume Next',
        '    sh.Name = sheetName',
        '    On Error GoTo 0',
        '    ws.Rows(1).Copy sh.Rows(1)',
        '    nextRow = 2',
        '    For r = 2 To lastRow',
        f'        If CStr(ws.Cells(r, "{p.col}").Value) = key Then',
        '            ws.Rows(r).Copy sh.Rows(nextRow)',
        '            nextRow = nextRow + 1',
        '        End If',
        '    Next r',
        'Next key',
        'ws.Activate']


def x_highlight_compare(p):
    t = p.text.lower()
    op = '<' if re.search(r'меньше|ниже|менее', t) else ('=' if re.search(r'равн', t) else '>')
    n = p.numbers[-1] if p.numbers else 0
    num = str(int(n)) if float(n).is_integer() else str(n)
    return f'Выделить в столбце {p.col} значения {op} {num}', [
        'Dim r As Long, lastRow As Long, v As Variant',
        _last_row(p.col),
        'For r = 2 To lastRow',
        f'    v = ws.Cells(r, "{p.col}").Value',
        '    If Not IsEmpty(v) And IsNumeric(v) Then',
        f'        If v {op} {num} Then ws.Cells(r, "{p.col}").Interior.Color = {p.color}',
        '    End If',
        'Next r']


def x_delete_rows_where(p):
    value = p.quoted[0] if p.quoted else ''
    contains = bool(re.search(r'содерж|есть', p.text.lower()))
    test = (f'InStr(1, CStr(ws.Cells(r, "{p.col}").Value), {vba_str(value)}, vbTextCompare) > 0' if contains
            else f'CStr(ws.Cells(r, "{p.col}").Value) = {vba_str(value)}')
    return f'Удалить строки, где в столбце {p.col} ' + ('есть' if contains else 'равно') + f' «{value}»', [
        'Dim r As Long, lastRow As Long',
        _last_row(p.col),
        'For r = lastRow To 2 Step -1',
        f'    If {test} Then ws.Rows(r).Delete',
        'Next r']


def x_number_rows(p):
    return 'Добавить столбец «№» с нумерацией', [
        'Dim r As Long, lastRow As Long',
        'lastRow = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1',
        'ws.Columns(1).Insert',
        'ws.Cells(1, 1).Value = "№"',
        'For r = 2 To lastRow',
        '    ws.Cells(r, 1).Value = r - 1',
        'Next r']


def x_header(p):
    return 'Оформить шапку: жирный, закрепить, фильтр', [
        'ws.Rows(1).Font.Bold = True',
        'ws.Activate',
        'ActiveWindow.FreezePanes = False',
        'ws.Range("A2").Select',
        'ActiveWindow.FreezePanes = True',
        'If Not ws.AutoFilterMode Then ws.UsedRange.AutoFilter']


def x_pdf(p):
    return 'Сохранить лист в PDF', [
        'If ActiveWorkbook.Path = "" Then',
        '    MsgBox "Сначала сохраните книгу: PDF будет рядом с ней.", vbExclamation, "Искра"',
        '    Exit Sub',
        'End If',
        'ws.ExportAsFixedFormat Type:=xlTypePDF, Filename:=ActiveWorkbook.Path & "\\" & ws.Name & ".pdf"']


def x_toc(p):
    return 'Лист «Оглавление» со ссылками на все листы', [
        'Dim toc As Worksheet, sh As Worksheet, i As Long',
        'Application.DisplayAlerts = False',
        'On Error Resume Next',
        'ActiveWorkbook.Worksheets("Оглавление").Delete',
        'On Error GoTo 0',
        'Application.DisplayAlerts = True',
        'Set toc = ActiveWorkbook.Worksheets.Add(Before:=ActiveWorkbook.Worksheets(1))',
        'toc.Name = "Оглавление"',
        'toc.Cells(1, 1).Value = "Листы книги"',
        'toc.Cells(1, 1).Font.Bold = True',
        'i = 2',
        'For Each sh In ActiveWorkbook.Worksheets',
        '    If sh.Name <> toc.Name Then',
        '        toc.Hyperlinks.Add Anchor:=toc.Cells(i, 1), Address:="", SubAddress:="\'" & sh.Name & "\'!A1", TextToDisplay:=sh.Name',
        '        i = i + 1',
        '    End If',
        'Next sh']


def x_unmerge(p):
    return 'Разъединить объединённые ячейки и заполнить значением', [
        'Dim c As Range, m As Range, v As Variant',
        'For Each c In ws.UsedRange.Cells',
        '    If c.MergeCells Then',
        '        Set m = c.MergeArea',
        '        v = m.Cells(1, 1).Value',
        '        m.UnMerge',
        '        m.Value = v',
        '    End If',
        'Next c']


def x_overdue(p):
    return f'Выделить просроченные даты в столбце {p.col}', [
        'Dim r As Long, lastRow As Long, v As Variant',
        _last_row(p.col),
        'For r = 2 To lastRow',
        f'    v = ws.Cells(r, "{p.col}").Value',
        '    If IsDate(v) Then',
        f'        If CDate(v) < Date Then ws.Cells(r, "{p.col}").Interior.Color = RGB(255, 199, 206)',
        '    End If',
        'Next r']


def x_total(p):
    return f'Строка «Итого» с суммой столбца {p.col}', [
        'Dim lastRow As Long',
        _last_row(p.col),
        'If lastRow < 2 Then Exit Sub',
        f'ws.Cells(lastRow + 1, "{p.col}").Formula = "=SUM({p.col}2:{p.col}" & lastRow & ")"',
        f'ws.Cells(lastRow + 1, "{p.col}").Font.Bold = True',
        f'If ws.Range("{p.col}1").Column > 1 Then',
        '    If IsEmpty(ws.Cells(lastRow + 1, 1).Value) Then ws.Cells(lastRow + 1, 1).Value = "Итого"',
        '    ws.Cells(lastRow + 1, 1).Font.Bold = True',
        'End If']


def x_protect(p):
    pw = p.quoted[0] if p.quoted else ''
    off = bool(re.search(r'снять|убрать|раз', p.text.lower()))
    return ('Снять защиту со всех листов' if off else 'Поставить защиту на все листы'), [
        'Dim sh As Worksheet',
        'For Each sh In ActiveWorkbook.Worksheets',
        f'    sh.{"Unprotect" if off else "Protect"} Password:={vba_str(pw)}',
        'Next sh']


def x_fill_down(p):
    return 'Протянуть формулу из активной ячейки вниз', [
        'Dim startCell As Range, lastRow As Long',
        'Set startCell = ActiveCell',
        'If Not startCell.HasFormula Then',
        '    MsgBox "Встаньте на ячейку с формулой.", vbExclamation, "Искра"',
        '    Exit Sub',
        'End If',
        'If startCell.Column = 1 Then Exit Sub',
        'lastRow = startCell.Worksheet.Cells(startCell.Worksheet.Rows.Count, startCell.Column - 1).End(xlUp).Row',
        'If lastRow > startCell.Row Then startCell.Worksheet.Range(startCell, startCell.Worksheet.Cells(lastRow, startCell.Column)).FillDown']


def x_blanks(p):
    return 'Подсветить пустые ячейки в выделенном диапазоне', [
        'Dim rng As Range',
        'On Error Resume Next',
        'Set rng = Selection.SpecialCells(xlCellTypeBlanks)',
        'On Error GoTo 0',
        f'If Not rng Is Nothing Then rng.Interior.Color = {p.color}']


# ---------- Word ----------

def w_replace(p):
    a, b = (p.quoted + ['', ''])[:2]
    return f'Заменить «{a}» на «{b}»', _w_find(vba_str(a), vba_str(b))


def _w_find(what, repl, extra=()):
    return ['With doc.Content.Find',
            '    .ClearFormatting',
            '    .Replacement.ClearFormatting',
            f'    .Text = {what}',
            f'    .Replacement.Text = {repl}',
            '    .Forward = True',
            '    .Wrap = wdFindStop',
            '    .MatchCase = False',
            '    .MatchWildcards = False',
            *['    ' + e for e in extra],
            '    .Execute Replace:=wdReplaceAll',
            'End With']


def w_double_spaces(p):
    return 'Убрать двойные пробелы', [
        'Dim i As Long',
        'For i = 1 To 10',
        '    With doc.Content.Find',
        '        .ClearFormatting',
        '        .Replacement.ClearFormatting',
        '        .Text = "  "',
        '        .Replacement.Text = " "',
        '        .Forward = True',
        '        .Wrap = wdFindStop',
        '        .MatchWildcards = False',
        '        .Execute Replace:=wdReplaceAll',
        '    End With',
        'Next i']


def w_empty_paragraphs(p):
    return 'Удалить пустые абзацы', [
        'Dim i As Long, t As String',
        'For i = doc.Paragraphs.Count To 1 Step -1',
        '    t = Replace(Replace(doc.Paragraphs(i).Range.Text, vbCr, ""), Chr(7), "")',
        '    If Len(Trim(t)) = 0 And doc.Paragraphs(i).Range.Information(wdWithInTable) = False Then',
        '        On Error Resume Next',
        '        doc.Paragraphs(i).Range.Delete',
        '        On Error GoTo 0',
        '    End If',
        'Next i']


FONTS = ['Times New Roman', 'Arial', 'Calibri', 'PT Astra Serif', 'PT Serif', 'Liberation Serif', 'Cambria', 'Verdana']


def w_font(p):
    name = next((f for f in FONTS if f.lower() in p.text.lower()), None) or (p.quoted[0] if p.quoted else 'Times New Roman')
    size = next((n for n in p.numbers if 6 <= n <= 72), 14)
    size_s = str(int(size)) if float(size).is_integer() else str(size)
    return f'Шрифт {name}, {size_s} пт во всём документе', [
        f'doc.Content.Font.Name = {vba_str(name)}',
        f'doc.Content.Font.Size = {size_s}']


def w_margins(p):
    # ГОСТ Р 7.0.97-2016: левое 20 мм, правое 10, верхнее 20, нижнее 20.
    n = [x for x in p.numbers if 0 < x < 10]
    left, right, top, bottom = (n + [2, 1, 2, 2][len(n):])[:4] if n else (2, 1, 2, 2)
    fmt = lambda x: str(x).replace('.0', '')
    return f'Поля: левое {fmt(left)} см, правое {fmt(right)}, верхнее {fmt(top)}, нижнее {fmt(bottom)}', [
        'Dim s As Section',
        'For Each s In doc.Sections',
        f'    s.PageSetup.LeftMargin = CentimetersToPoints({fmt(left)})',
        f'    s.PageSetup.RightMargin = CentimetersToPoints({fmt(right)})',
        f'    s.PageSetup.TopMargin = CentimetersToPoints({fmt(top)})',
        f'    s.PageSetup.BottomMargin = CentimetersToPoints({fmt(bottom)})',
        'Next s']


def w_spacing(p):
    t = p.text.lower()
    rule, name = ('wdLineSpace1pt5', 'полуторный') if re.search(r'1[.,]5|полутор', t) else (
        ('wdLineSpaceDouble', 'двойной') if 'двой' in t else ('wdLineSpaceSingle', 'одинарный'))
    return f'Межстрочный интервал: {name}', [f'doc.Content.ParagraphFormat.LineSpacingRule = {rule}']


def w_page_numbers(p):
    return 'Номера страниц внизу по центру', [
        'Dim s As Section',
        'For Each s In doc.Sections',
        '    s.Footers(wdHeaderFooterPrimary).PageNumbers.Add PageNumberAlignment:=wdAlignPageNumberCenter, FirstPage:=True',
        'Next s']


def w_tables(p):
    return 'Оформить все таблицы: рамки, жирная шапка, по ширине', [
        'Dim tbl As Table',
        'For Each tbl In doc.Tables',
        '    tbl.Borders.Enable = True',
        '    tbl.Rows(1).Range.Font.Bold = True',
        '    tbl.AutoFitBehavior wdAutoFitWindow',
        'Next tbl']


def w_highlight(p):
    what = p.quoted[0] if p.quoted else ''
    return f'Выделить маркером «{what}»', [
        'Options.DefaultHighlightColorIndex = wdYellow',
        *_w_find(vba_str(what), '"^&"', ('.Replacement.Highlight = True', '.Format = True'))]


def w_unhighlight(p):
    return 'Убрать выделение маркером', ['doc.Content.HighlightColorIndex = wdNoHighlight']


def w_accept(p):
    return 'Принять все исправления и удалить примечания', [
        'doc.TrackRevisions = False',
        'If doc.Revisions.Count > 0 Then doc.Revisions.AcceptAll',
        'If doc.Comments.Count > 0 Then doc.DeleteAllComments']


def w_pdf(p):
    return 'Сохранить в PDF рядом с документом', [
        'Dim pdfName As String',
        'If doc.Path = "" Then',
        '    MsgBox "Сначала сохраните документ.", vbExclamation, "Искра"',
        '    Exit Sub',
        'End If',
        'pdfName = doc.Path & "\\" & Left(doc.Name, InStrRev(doc.Name, ".") - 1) & ".pdf"',
        'doc.ExportAsFixedFormat OutputFileName:=pdfName, ExportFormat:=wdExportFormatPDF']


def w_days_plus(p):
    n = int(p.numbers[0]) if p.numbers and p.numbers[0] < 1000 else 1
    return f'Увеличить «N сут.» на {n}', [
        'Dim r As Range, k As Long',
        'Set r = doc.Content',
        'With r.Find',
        '    .ClearFormatting',
        '    .Text = "[0-9]{1,} сут."',
        '    .MatchWildcards = True',
        '    .Forward = True',
        '    .Wrap = wdFindStop',
        'End With',
        'Do While r.Find.Execute',
        '    k = CLng(Split(r.Text, " ")(0))',
        f'    r.Text = CStr(k + {n}) & " сут."',
        '    r.Collapse wdCollapseEnd',
        'Loop']


def w_date(p):
    return 'Вставить сегодняшнюю дату в место курсора', ['Selection.InsertAfter Format(Date, "dd.mm.yyyy")']


def w_upper_selection(p):
    return 'Выделенный текст — прописными', ['Selection.Range.Case = wdUpperCase']


OPS = [
    # Excel
    Op('x_split', 'excel', 'Разнести по листам', r'(разнес|раздел|разбит|распредел)\w*.*(лист|по значени)', 'sheet', x_split_by_column),
    Op('x_sheets_files', 'excel', 'Листы в файлы', r'(кажд\w* лист|все листы|листы).*(отдельн|файл)|(сохран|разбит).*(лист\w*) .*(файл)', 'book', x_sheets_to_files),
    Op('x_combine_files', 'excel', 'Файлы папки в один лист', r'(собр|собер|объедин|свест|склей)\w*.*(файл\w*|книг\w*).*(папк|в один)|(из|все) (файл|книг)\w* (из )?папк', 'book', x_combine_files),
    Op('x_combine_sheets', 'excel', 'Листы в один', r'(собр|собер|объедин|свест|склей)\w*.*(лист)', 'book', x_combine_sheets),
    Op('x_toc', 'excel', 'Оглавление', r'оглавлен|содержан\w* (лист|книг)|ссылк\w* на (все )?лист', 'book', x_toc),
    Op('x_protect', 'excel', 'Защита листов', r'(защит|пароль)', 'book', x_protect),
    Op('x_remove_dups', 'excel', 'Удалить повторы', r'(удал|убр)\w*.*(повтор|дубл)', 'sheet', x_remove_dups),
    Op('x_highlight_dups', 'excel', 'Выделить повторы', r'(повтор|дубл)', 'sheet', x_highlight_dups),
    Op('x_delete_rows_where', 'excel', 'Удалить строки по условию', r'(удал|убр)\w* строк\w*.*(где|если|котор|со? значени|содерж)', 'sheet', x_delete_rows_where, 'quoted'),
    Op('x_delete_empty', 'excel', 'Удалить пустые строки', r'(удал|убр)\w*.*пуст\w* строк', 'sheet', x_delete_empty_rows),
    Op('x_blanks', 'excel', 'Пустые ячейки', r'(подсвет|выдел|покраси|отмет)\w*.*пуст\w* ячейк', 'app', x_blanks),
    Op('x_overdue', 'excel', 'Просроченные даты', r'просроч|(дат)\w*.*(прош|раньше сегодн)', 'sheet', x_overdue),
    Op('x_compare', 'excel', 'Выделить больше/меньше', r'(выдел|подсвет|покрас|отмет)\w*.*(больше|меньше|выше|ниже|более|менее|равн\w* \d)', 'sheet', x_highlight_compare),
    Op('x_sort', 'excel', 'Сортировка', r'сортир|упорядоч|по алфавиту', 'sheet', x_sort),
    Op('x_total', 'excel', 'Итого', r'итог|сумм\w* (внизу|в конце|под)', 'sheet', x_total),
    Op('x_number', 'excel', 'Нумерация', r'(пронумер|нумерац|номер\w* строк|столбец с номер|столбец №)', 'sheet', x_number_rows),
    Op('x_header', 'excel', 'Шапка', r'(шапк|заголов\w* (жирн|закреп)|закреп\w* (шапк|перв|заголов|строк)|автофильтр|фильтр\w* на шапк)', 'sheet', x_header),
    Op('x_autofit', 'excel', 'Ширина столбцов', r'ширин|автоподбор|подогн', 'sheet', x_autofit),
    Op('x_trim', 'excel', 'Пробелы', r'пробел', 'sheet', x_trim),
    Op('x_case', 'excel', 'Регистр', r'прописн|заглавн|строчн|регистр|большими букв|маленьк\w* букв', 'sheet', x_case),
    Op('x_values', 'excel', 'Формулы в значения', r'формул\w* (в|на) значени|значени\w* вместо формул|убр\w* формул|только значени', 'sheet', x_values),
    Op('x_fill_down', 'excel', 'Протянуть формулу', r'протян|заполн\w* формул|формул\w* вниз', 'app', x_fill_down),
    Op('x_pdf', 'excel', 'Лист в PDF', r'pdf|пдф', 'sheet', x_pdf),
    Op('x_replace', 'excel', 'Замена', r'замен', 'sheet', x_replace, 'two_quoted'),
    # Word
    Op('w_days', 'word', 'Сутки +N', r'сут', 'doc', w_days_plus),
    Op('w_empty', 'word', 'Пустые абзацы', r'пуст\w* (абзац|строк)', 'doc', w_empty_paragraphs),
    Op('w_spaces', 'word', 'Двойные пробелы', r'пробел', 'doc', w_double_spaces),
    Op('w_font', 'word', 'Шрифт', r'шрифт|кегл|размер\w* текст', 'doc', w_font),
    Op('w_margins', 'word', 'Поля страницы', r'пол[яей]\b|поля страниц|отступ\w* страниц', 'doc', w_margins),
    Op('w_spacing', 'word', 'Интервал', r'интервал|междустроч|межстроч', 'doc', w_spacing),
    Op('w_pages', 'word', 'Номера страниц', r'номер\w* страниц|пронумеровать страниц|нумерац\w* страниц', 'doc', w_page_numbers),
    Op('w_tables', 'word', 'Таблицы', r'(оформ|рамк|границ|выровн)\w*.*таблиц|таблиц\w*.*(рамк|границ|оформ)', 'doc', w_tables),
    Op('w_unhighlight', 'word', 'Снять маркер', r'(убр|снять|удал)\w*.*(маркер|выделени\w* цвет|подсветк)', 'doc', w_unhighlight),
    Op('w_highlight', 'word', 'Маркер', r'(выдел|подсвет|отмет)\w*.*(маркер|желт|цвет)|маркер', 'doc', w_highlight, 'quoted'),
    Op('w_accept', 'word', 'Исправления и примечания', r'исправлен|рецензир|примечан|комментар', 'doc', w_accept),
    Op('w_pdf', 'word', 'В PDF', r'pdf|пдф', 'doc', w_pdf),
    Op('w_date', 'word', 'Дата', r'(встав|постав)\w*.*(дат|сегодн)', 'app', w_date),
    Op('w_upper', 'word', 'Прописные', r'прописн|заглавн|большими букв', 'app', w_upper_selection),
    Op('w_replace', 'word', 'Замена', r'замен', 'doc', w_replace, 'two_quoted'),
]

EXCEL_WORDS = re.compile(r'excel|эксел|лист|столб|колонк|ячейк|строк\w* таблиц|книг|xlsx|формул')
WORD_WORDS = re.compile(r'word|ворд|документ|абзац|шрифт|страниц|телеграм|docx|текст|сут\.?|маркер|примечан|интервал')


def detect_app(task):
    t = task.lower()
    x, w = len(EXCEL_WORDS.findall(t)), len(WORD_WORDS.findall(t))
    return 'word' if w > x else 'excel'


def split_task(task):
    # Шаги разделяются и перед словами-действиями («интервал 1,5, номера страниц»), но не после «сут.», «шт.», «г.».
    parts = re.split(r'[\n;]+|(?<!сут)(?<!шт)(?<!\bг)(?<!\bч)(?<!мин)\.\s+|,\s*(?=(?:потом|затем|и|а также)?\s*[а-яё]+(?:ть|ти|чь|й|и)\b)'
                     r'|,\s*(?=(?:интервал|междустроч|номер\w* страниц|нумерац|шрифт|поля|отступ|выравнив|колонтитул|абзац|заголов|переносы)\w*)'
                     r'|\s+(?:потом|затем|после этого|а также)\s+|\s+и\s+(?=[а-яё]+(?:ть|ти|й|и)\b)',
                     task.strip(), flags=re.IGNORECASE)
    return [p.strip(' ,.') for p in parts if p and p.strip(' ,.')]


@dataclass
class Step:
    op: Op
    params: Params
    title: str
    lines: list
    warning: str = ''


def understand(task, app=None):
    """Splits the task into steps. Returns (app, steps, not_understood)."""
    app = app or detect_app(task)
    folder = bool(re.search(r'(во? )?все\w* (документ|файл)\w*.*папк|в папке|из папки|каждом документе', task.lower())) and app == 'word'
    steps, unknown = [], []
    for clause in split_task(task):
        c = clause.lower().replace('ё', 'е')
        op = next((o for o in OPS if o.app == app and re.search(o.pattern, c)), None)
        if op is None:
            if not re.fullmatch(r'(во? )?все\w* (документ|файл)\w*( в| из)? папк\w*|в excel|в word', c):
                unknown.append(clause)
            continue
        p = parse_params(clause)
        warning = ''
        if op.needs == 'two_quoted' and len(p.quoted) < 2:
            warning = 'Не вижу, что на что заменить: напишите оба текста в кавычках — заменить "старое" на "новое".'
        elif op.needs == 'quoted' and not p.quoted:
            warning = 'Укажите текст в кавычках, например "Москва".'
        if op.scope == 'sheet' and not p.col_given and op.build in (x_highlight_dups, x_remove_dups, x_sort, x_split_by_column,
                                                                    x_highlight_compare, x_delete_rows_where, x_overdue, x_total):
            warning = (warning + ' ' if warning else '') + 'Столбец не указан — взяла A. Напишите, например, «в столбце C».'
        title, lines = op.build(p)
        steps.append(Step(op, p, title, lines, warning.strip()))
    return app, steps, unknown, folder


def generate(task, app=None, name='Iskra_Macro'):
    """Returns (vba_code, steps, not_understood). Raises ValueError if nothing was understood."""
    app, steps, unknown, folder = understand(task, app)
    if not steps:
        raise ValueError('Не поняла ни одного действия. Посмотрите список «Что я умею» и опишите задачу теми же словами.')
    one_line_task = ' '.join(task.split())[:300]
    out = ['Option Explicit', '',
           f"' Создано программой «Искра» {date.today():%d.%m.%Y} для {'Excel' if app == 'excel' else 'Word'}.",
           f"' Задача: {one_line_task}",
           "' ПЕРЕД ЗАПУСКОМ сохраните копию файла: действия макроса нельзя отменить через Ctrl+Z.",
           "' Подключение: Alt+F11 -> Insert -> Module (Вставка -> Модуль) -> вставить этот текст -> F5.", '']
    for i, s in enumerate(steps, 1):
        out.append(f"' Шаг {i}. {s.title}")
    out += ['', f'Sub {name}()', '    Dim stepName As String']
    if app == 'excel' and any(s.op.scope == 'sheet' and s.params.all_sheets for s in steps):
        out.append('    Dim ws As Worksheet')
    if folder:
        out += ['    Dim folder As String, outDir As String, f As String, doc As Document, n As Long']
    out += ['    On Error GoTo Failed', '    Application.ScreenUpdating = False']
    body = []
    for i, s in enumerate(steps, 1):
        call = f'Iskra_Step{i}'
        body.append(f'stepName = "{i}. {s.title.replace(chr(34), chr(39))}"')
        if s.op.scope == 'sheet':
            if s.params.all_sheets:
                body += ['For Each ws In ActiveWorkbook.Worksheets', f'    Call {call}(ws)', 'Next ws']
            else:
                body.append(f'Call {call}(ActiveSheet)')
        elif s.op.scope == 'doc':
            body.append(f'Call {call}({"doc" if folder else "ActiveDocument"})')
        else:
            body.append(f'Call {call}')
    if folder:
        out += ['    With Application.FileDialog(msoFileDialogFolderPicker)',
                '        .Title = "Папка с документами Word"',
                '        If .Show <> -1 Then Exit Sub',
                '        folder = .SelectedItems(1) & "\\"',
                '    End With',
                '    outDir = folder & "Обработано Искрой\\"',
                '    If Dir(outDir, vbDirectory) = "" Then MkDir outDir',
                '    f = Dir(folder & "*.docx")',
                '    Do While f <> ""',
                '        If Left(f, 2) <> "~$" Then',
                '            Set doc = Documents.Open(FileName:=folder & f, Visible:=False)']
        out += ['            ' + b for b in body]
        out += ['            doc.SaveAs2 FileName:=outDir & f',
                '            doc.Close SaveChanges:=False',
                '            n = n + 1',
                '        End If',
                '        f = Dir()',
                '    Loop',
                '    Application.ScreenUpdating = True',
                '    MsgBox "Готово. Обработано документов: " & n & vbCrLf & "Копии сохранены в папке: " & outDir, vbInformation, "Искра"']
    else:
        out += ['    ' + b for b in body]
        out += ['    Application.ScreenUpdating = True',
                f'    MsgBox "Готово. Выполнено шагов: {len(steps)}.", vbInformation, "Искра"']
    out += ['    Exit Sub', 'Failed:', '    Application.ScreenUpdating = True',
            '    Application.DisplayAlerts = True',          # шаг мог выключить предупреждения — вернуть
            '    MsgBox "Ошибка на шаге «" & stepName & "»:" & vbCrLf & Err.Number & " — " & Err.Description & vbCrLf & vbCrLf & _',
            '        "Скопируйте этот текст в Искру: «Исправить ошибку».", vbExclamation, "Искра"',
            'End Sub']
    for i, s in enumerate(steps, 1):
        arg = '(ws As Worksheet)' if s.op.scope == 'sheet' else ('(doc As Document)' if s.op.scope == 'doc' else '()')
        out += ['', f"' {s.title}", f'Private Sub Iskra_Step{i}{arg}']
        out += ['    ' + line for line in s.lines]
        out.append('End Sub')
    return '\n'.join(out) + '\n', steps, unknown


def capabilities():
    excel = sorted({o.title for o in OPS if o.app == 'excel'})
    word = sorted({o.title for o in OPS if o.app == 'word'})
    return excel, word


EXAMPLES = [
    'Excel: удалить пустые строки, выделить повторы в столбце B красным, отсортировать по столбцу A',
    'Excel: разнести строки по листам по значениям столбца C',
    'Excel: сохранить каждый лист отдельным файлом',
    'Excel: собрать все файлы из папки в один лист',
    'Excel: выделить в столбце D значения больше 1000 и добавить итог по столбцу D',
    'Excel: удалить строки где в столбце B "уволен"',
    'Word: во всех документах папки заменить "в/ч" на "войсковая часть" и поставить шрифт Times New Roman 14',
    'Word: удалить пустые абзацы, убрать двойные пробелы, оформить таблицы, сохранить в PDF',
    'Word: поля по ГОСТ, интервал 1,5, номера страниц',
]


# ---------- Проверка и исправление кода ----------

BLOCKS = [
    (r'^\s*(Private\s+|Public\s+)?Sub\s+\w+', r'^\s*End\s+Sub\b', 'Sub', 'End Sub'),
    (r'^\s*(Private\s+|Public\s+)?Function\s+\w+', r'^\s*End\s+Function\b', 'Function', 'End Function'),
    (r'^\s*If\b.*\bThen\s*(\'.*)?$', r'^\s*End\s+If\b', 'If … Then', 'End If'),
    (r'^\s*For\b', r'^\s*Next\b', 'For', 'Next'),
    (r'^\s*Do\b', r'^\s*Loop\b', 'Do', 'Loop'),
    (r'^\s*With\b', r'^\s*End\s+With\b', 'With', 'End With'),
    (r'^\s*Select\s+Case\b', r'^\s*End\s+Select\b', 'Select Case', 'End Select'),
]
KEYWORDS = set('''if then else elseif end for next each to step do loop while until wend with select case sub function
dim as set let call exit on error goto resume new nothing true false and or not mod is like private public option
explicit const redim preserve byval byref optional me debug msgbox'''.split())


def _strip_strings(line):
    line = re.sub(r'"(?:[^"]|"")*"', '""', line)
    return re.sub(r"'.*$", '', line)


def lint(code):
    """Typical mistakes that stop a macro from running. Returns [(line_no, message)]."""
    issues = []
    lines = code.replace('\r\n', '\n').split('\n')
    for n, raw in enumerate(lines, 1):
        if re.search('[“”„«»]', _strip_strings(raw)) or re.search(r'[“”„]', raw):
            issues.append((n, 'Типографские кавычки “ ” « » — в VBA нужны прямые кавычки "'))
        if re.search(r'^\s*[A-Za-zА-Яа-я_]\w*\s+As\s+Integer\b', raw) or re.search(r'\bAs\s+Integer\b', raw):
            issues.append((n, 'As Integer переполняется после 32 767 строк — лучше As Long'))
    # Блоки
    for open_re, close_re, open_name, close_name in BLOCKS:
        depth = 0
        for n, raw in enumerate(lines, 1):
            line = _strip_strings(raw)
            if re.search(open_re, line, re.IGNORECASE) and not (open_name == 'If … Then' and re.search(r'\bThen\s+\S', line)):
                depth += 1
            if re.search(close_re, line, re.IGNORECASE):
                depth -= 1
                if depth < 0:
                    issues.append((n, f'Лишний «{close_name}» без «{open_name}»'))
                    depth = 0
        if depth > 0:
            issues.append((len(lines), f'Не хватает «{close_name}»: открыто «{open_name}» больше, чем закрыто ({depth})'))
    # Повтор имени процедуры
    names = [m.group(1).lower() for m in re.finditer(r'^\s*(?:Private\s+|Public\s+)?(?:Sub|Function)\s+(\w+)', code, re.IGNORECASE | re.MULTILINE)]
    for name in sorted({x for x in names if names.count(x) > 1}):
        issues.append((0, f'Процедура «{name}» объявлена несколько раз (Ambiguous name)'))
    # Необъявленные переменные при Option Explicit
    if re.search(r'^\s*Option\s+Explicit', code, re.IGNORECASE | re.MULTILINE):
        for n, var in undeclared(code):
            issues.append((n, f'Переменная «{var}» не объявлена (Variable not defined) — нужна строка Dim {var} As Variant'))
    return sorted(issues)


def undeclared(code):
    declared = set()
    for m in re.finditer(r'\b(?:Dim|ReDim|Const|Static|Private|Public)\s+(?!Sub|Function)([^\n\'=]+)', code, re.IGNORECASE):
        for part in m.group(1).split(','):
            name = re.match(r'\s*(?:Preserve\s+)?(\w+)', part)
            if name:
                declared.add(name.group(1).lower())
    for m in re.finditer(r'(?:Sub|Function)\s+\w+\s*\(([^)]*)\)', code, re.IGNORECASE):
        for part in m.group(1).split(','):
            name = re.match(r'\s*(?:Optional\s+)?(?:ByVal\s+|ByRef\s+)?(\w+)', part)
            if name:
                declared.add(name.group(1).lower())
    for m in re.finditer(r'(?:Sub|Function)\s+(\w+)', code, re.IGNORECASE):
        declared.add(m.group(1).lower())
    found, seen = [], set()
    for n, raw in enumerate(code.split('\n'), 1):
        line = _strip_strings(raw)
        for m in re.finditer(r'(?:^|:)\s*(?:Set\s+)?([A-Za-zА-Яа-я_]\w*)\s*=(?!=)', line):
            var = m.group(1)
            if var.lower() in declared or var.lower() in KEYWORDS or var.lower() in seen:
                continue
            seen.add(var.lower())
            found.append((n, var))
        for m in re.finditer(r'^\s*For\s+(?:Each\s+)?([A-Za-zА-Яа-я_]\w*)\b', line, re.IGNORECASE):
            var = m.group(1)
            if var.lower() not in declared and var.lower() not in seen:
                seen.add(var.lower())
                found.append((n, var))
    return found


def auto_fix(code):
    """Fixes what can be fixed safely. Returns (code, [what was changed])."""
    changes = []
    fixed = code
    if re.search(r'[“”„]', fixed):
        fixed = re.sub(r'[“”„]', '"', fixed)
        changes.append('Типографские кавычки заменены на прямые.')
    if re.search(r'\bAs\s+Integer\b', fixed):
        fixed = re.sub(r'\bAs\s+Integer\b', 'As Long', fixed)
        changes.append('As Integer заменено на As Long (нет переполнения на больших таблицах).')
    if not re.search(r'^\s*Option\s+Explicit', fixed, re.IGNORECASE | re.MULTILINE):
        fixed = 'Option Explicit\n' + fixed
        changes.append('Добавлено Option Explicit — опечатки в именах переменных будут видны сразу.')
    missing = undeclared(fixed)
    if missing:
        lines = fixed.split('\n')
        by_proc = {}
        for n, var in missing:
            start = max((i for i in range(n - 1, -1, -1) if re.match(r'\s*(?:Private\s+|Public\s+)?(?:Sub|Function)\s+\w+', lines[i], re.IGNORECASE)), default=None)
            if start is not None:
                by_proc.setdefault(start, []).append(var)
        for start in sorted(by_proc, reverse=True):
            lines.insert(start + 1, '    Dim ' + ', '.join(f'{v} As Variant' for v in by_proc[start]))
        fixed = '\n'.join(lines)
        changes.append('Объявлены переменные: ' + ', '.join(v for _, v in missing) + '.')
    names = [m.group(1) for m in re.finditer(r'^\s*(?:Private\s+|Public\s+)?Sub\s+(\w+)', fixed, re.IGNORECASE | re.MULTILINE)]
    for name in {x for x in names if names.count(x) > 1}:
        k = 0

        def rename(m):
            nonlocal k
            k += 1
            return m.group(0) if k == 1 else m.group(0).replace(name, f'{name}_{k}')
        fixed = re.sub(rf'^(\s*(?:Private\s+|Public\s+)?Sub\s+){name}\b', rename, fixed, flags=re.IGNORECASE | re.MULTILINE)
        changes.append(f'Повторяющаяся процедура «{name}» переименована.')
    return fixed, changes


ERRORS = [
    (r'\b1004\b|ошибка, определяемая приложением|application-defined|метод .* не выполнен|method .* failed',
     'Ошибка 1004 — Excel не смог выполнить действие.',
     'Частые причины: лист защищён; лист с таким именем уже есть; книга не сохранена (пустой путь); '
     'слишком длинное или недопустимое имя листа/файла; объединённые ячейки в диапазоне.',
     'Снимите защиту листа, сохраните книгу, разъедините ячейки и запустите снова.'),
    (r'\b9\b.*(индекс|subscript)|индекс за пределами|subscript out of range',
     'Ошибка 9 — нет такого листа, книги или элемента.',
     'В макросе указано имя листа или книги, которого нет (опечатка, лишний пробел, другой язык).',
     'Проверьте точное имя листа на ярлыке и в тексте макроса — оно должно совпадать буква в букву.'),
    (r'\b13\b|несоответствие типа|type mismatch',
     'Ошибка 13 — несоответствие типа.',
     'В ячейке оказался текст вместо числа или даты, либо значение ошибки (#Н/Д, #ДЕЛ/0!).',
     'Проверьте данные в указанном столбце; уберите ошибки в ячейках или пропишите проверку IsNumeric/IsDate.'),
    (r'\b91\b|переменная объекта|object variable',
     'Ошибка 91 — объект не найден.',
     'Поиск ничего не нашёл, нет выделения или нет активного документа/листа.',
     'Откройте нужный файл, выделите диапазон (если макрос работает с выделением) и запустите снова.'),
    (r'\b424\b|требуется объект|object required',
     'Ошибка 424 — требуется объект.', 'Опечатка в имени объекта или переменной.', 'Нажмите «Проверить код» — Искра покажет строку.'),
    (r'\b438\b|не поддерживает это свойство|doesn.t support this property',
     'Ошибка 438 — у объекта нет такого свойства.',
     'Чаще всего макрос для Word запущен в Excel (или наоборот), либо версия Office старая.',
     'Запустите макрос в той программе, для которой он создан (указано в первой строке).'),
    (r'\b6\b.*(переполнение|overflow)|переполнение|overflow',
     'Ошибка 6 — переполнение.', 'Переменная As Integer не вмещает номер строки больше 32 767.',
     'Нажмите «Исправить автоматически» — Integer будет заменён на Long.'),
    (r'\b11\b|деление на ноль|division by zero', 'Ошибка 11 — деление на ноль.', 'В данных есть пустая ячейка или 0 в знаменателе.', 'Заполните пустые ячейки или добавьте проверку на 0.'),
    (r'\b53\b|файл не найден|file not found', 'Ошибка 53 — файл не найден.', 'Неверный путь или имя файла.', 'Проверьте путь; сохраните книгу/документ перед запуском.'),
    (r'\b7[056]\b|отказано в доступе|permission denied|path not found|путь не найден',
     'Ошибка доступа к файлу или папке.', 'Файл открыт в другой программе, папка только для чтения или не существует.',
     'Закройте файл, выберите папку, куда разрешена запись.'),
    (r'\b4605\b|команда недоступна|command is not available', 'Word: команда недоступна.', 'Документ защищён, открыт только для чтения или в режиме чтения.', 'Снимите защиту (Рецензирование → Ограничить редактирование) и откройте документ для правки.'),
    (r'\b5941\b|элемент семейства|requested member of the collection', 'Word: нет такого элемента (таблицы, раздела, закладки).', 'В документе меньше таблиц или разделов, чем ожидает макрос.', 'Проверьте документ или уберите шаг из задачи.'),
    (r'variable not defined|переменная не определена', 'Переменная не объявлена.', 'В модуле включено Option Explicit, а переменная без Dim.', 'Нажмите «Исправить автоматически» — объявления добавятся.'),
    (r'sub or function not defined|подпрограмма или функция не определена', 'Нет такой процедуры или функции.', 'Опечатка в имени, функция из надстройки или неверная версия Office.', 'Нажмите «Проверить код»; убедитесь, что весь текст вставлен целиком.'),
    (r'ambiguous name|неоднозначное имя', 'Две процедуры с одинаковым именем.', 'Макрос вставлен дважды или в модуле уже есть Iskra_Macro.', 'Удалите старый модуль или нажмите «Исправить автоматически».'),
    (r'expected:? end|ожидается:? end|block if without end if|if без end if|next without for|for без next',
     'Незакрытый блок (If/For/With/Sub).', 'Текст вставлен не полностью или удалена строка.', 'Вставьте макрос заново целиком; «Проверить код» покажет, какого End не хватает.'),
    (r'макрос\w* отключ|macros (have been )?disabled|невозможно выполнить макрос|cannot run the macro',
     'Макросы отключены.', 'Файл сохранён без поддержки макросов или их запрещают настройки.',
     'Сохраните файл как .xlsm/.docm и разрешите макросы (Файл → Параметры → Центр управления безопасностью), если это разрешено в организации.'),
    (r"can.t find project or library|не удается найти проект или библиотеку", 'Нет нужной библиотеки.', 'В Tools → References отмечена отсутствующая библиотека.', 'Alt+F11 → Tools → References: снимите галочку с пункта MISSING.'),
]


def explain_error(message):
    """(title, cause, what to do) for a VBA error text in Russian or English."""
    t = message.lower()
    for pattern, title, cause, fix in ERRORS:
        if re.search(pattern, t):
            return title, cause, fix
    return ('Ошибка не из моего справочника.', 'Причину по тексту ошибки определить не удалось.',
            'Нажмите «Проверить код». Проверьте, что макрос запущен в нужной программе и файл сохранён. '
            'Если ошибка на конкретном шаге — уберите этот шаг из задачи и создайте макрос заново.')


def bas_bytes(code, module='Iskra'):
    """A .bas file the VBA editor imports correctly: Windows-1251 (as on Russian Windows) and a module name line."""
    text = code.replace('→', '->').replace('\r\n', '\n')
    if not text.startswith('Attribute VB_Name'):
        text = f'Attribute VB_Name = "{module}"\n' + text
    return text.replace('\n', '\r\n').encode('cp1251', errors='replace')
