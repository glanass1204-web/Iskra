"""Auditable offline VBA templates. Export only; never execute or install macros."""
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Macro:
    key: str
    app: str
    title: str
    description: str
    code: str

MACROS = [
    Macro('word_spaces','Word','Убрать двойные пробелы','Работает с активным документом; сначала сохраните копию.', '''Option Explicit
Sub Iskra_RemoveDoubleSpaces()
    Dim rng As Range
    Set rng = ActiveDocument.Content
    With rng.Find
        .ClearFormatting
        .Replacement.ClearFormatting
        .Text = "  "
        .Replacement.Text = " "
        .Forward = True
        .Wrap = wdFindStop
        .Format = False
        .MatchWildcards = False
        .Execute Replace:=wdReplaceAll
    End With
    MsgBox "Проверка двойных пробелов завершена.", vbInformation
End Sub
'''),
    Macro('word_days','Word','Увеличить «N сут.» на 1','Меняет только числа перед «сут.» в основном тексте документа; дата остаётся прежней. Проверьте копию.', '''Option Explicit
Sub Iskra_AddOneDay()
    Dim r As Range
    Dim n As Long
    Set r = ActiveDocument.Content
    With r.Find
        .ClearFormatting
        .Text = "[0-9]{1,} сут."
        .MatchWildcards = True
        .Wrap = wdFindStop
        .Forward = True
    End With
    Do While r.Find.Execute
        n = CLng(Split(r.Text, " ")(0))
        If n < 2147483647 Then
            r.Text = CStr(n + 1) & " сут."
        End If
        r.Collapse wdCollapseEnd
    Loop
    MsgBox "Готово. Проверьте изменения.", vbInformation
End Sub
'''),
    Macro('word_lastcol','Word','Сутки +1 в последнем столбце таблиц','Обходит таблицы Word; объединённые ячейки могут требовать ручной проверки. Даты не изменяет.', '''Option Explicit
Sub Iskra_AddDayLastColumn()
    Dim tbl As Table, rw As Row, cel As Cell
    Dim re As Object, matches As Object
    Dim s As String, value As Long
    Set re = CreateObject("VBScript.RegExp")
    re.Pattern = "(^|[^0-9])([0-9]+)([ ]+сут\\.)"
    re.Global = False
    For Each tbl In ActiveDocument.Tables
        For Each rw In tbl.Rows
            On Error Resume Next
            Set cel = rw.Cells(rw.Cells.Count)
            If Err.Number <> 0 Then Err.Clear: GoTo NextRow
            s = Left$(cel.Range.Text, Len(cel.Range.Text) - 2)
            If re.Test(s) Then
                Set matches = re.Execute(s)
                value = CLng(matches(0).SubMatches(1))
                If value < 2147483647 Then
                    s = Left$(s, matches(0).FirstIndex) & matches(0).SubMatches(0) & _
                        CStr(value + 1) & matches(0).SubMatches(2) & _
                        Mid$(s, matches(0).FirstIndex + matches(0).Length + 1)
                    cel.Range.Text = s
                End If
            End If
NextRow:
            On Error GoTo 0
        Next rw
    Next tbl
    MsgBox "Проверьте результат, особенно объединённые ячейки.", vbInformation
End Sub
'''),
    Macro('excel_fill','Excel','Заполнить формулу вниз','Копирует формулу из активной ячейки до последней заполненной строки соседнего столбца слева.', '''Option Explicit
Sub Iskra_FillFormulaDown()
    Dim ws As Worksheet, startCell As Range
    Dim lastRow As Long
    Set startCell = ActiveCell
    Set ws = startCell.Worksheet
    If startCell.Column = 1 Then
        MsgBox "Выберите ячейку правее столбца A.", vbExclamation
        Exit Sub
    End If
    If Not startCell.HasFormula Then
        MsgBox "В выбранной ячейке должна быть формула.", vbExclamation
        Exit Sub
    End If
    lastRow = ws.Cells(ws.Rows.Count, startCell.Column - 1).End(xlUp).Row
    If lastRow < startCell.Row Then Exit Sub
    ws.Range(startCell, ws.Cells(lastRow, startCell.Column)).FillDown
    MsgBox "Формула заполнена до строки " & lastRow, vbInformation
End Sub
'''),
    Macro('excel_highlight','Excel','Подсветить пустые ячейки','Подсвечивает пустые ячейки только внутри выделенного диапазона.', '''Option Explicit
Sub Iskra_HighlightBlanks()
    Dim rng As Range
    On Error Resume Next
    Set rng = Selection.SpecialCells(xlCellTypeBlanks)
    On Error GoTo 0
    If rng Is Nothing Then
        MsgBox "Пустых ячеек в выделении нет.", vbInformation
        Exit Sub
    End If
    rng.Interior.Color = RGB(255, 235, 156)
    MsgBox "Пустые ячейки отмечены.", vbInformation
End Sub
'''),
]

def export_macro(macro, destination):
    p = Path(destination)
    if p.suffix.lower() != '.bas':
        raise ValueError('Для VBA требуется файл .bas')
    p.write_text(macro.code, encoding='utf-8-sig')
    return p
