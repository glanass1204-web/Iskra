import unittest
import iskra_vba as v


class Builder(unittest.TestCase):
    def test_every_example_builds_clean_code(self):
        for task in v.EXAMPLES:
            code, steps, unknown = v.generate(task)
            self.assertEqual(unknown, [], task)
            self.assertEqual(v.lint(code), [], task + '\n' + code)

    def test_multi_step_excel_task(self):
        code, steps, unknown = v.generate('удалить пустые строки, выделить повторы в столбце B красным, отсортировать по столбцу A по убыванию')
        self.assertEqual([s.op.key for s in steps], ['x_delete_empty', 'x_highlight_dups', 'x_sort'])
        self.assertIn('ws.Cells(r, "B").Interior.Color = RGB(255, 199, 206)', code)
        self.assertIn('Order1:=xlDescending', code)
        self.assertIn('Call Iskra_Step3(ActiveSheet)', code)

    def test_word_folder_mode_and_params(self):
        code, steps, _ = v.generate('во всех документах папки заменить "в/ч" на "войсковая часть" и поставить шрифт Times New Roman 14')
        self.assertIn('msoFileDialogFolderPicker', code)
        self.assertIn('.Text = "в/ч"', code)
        self.assertIn('.Replacement.Text = "войсковая часть"', code)
        self.assertIn('doc.Content.Font.Size = 14', code)
        self.assertIn('Call Iskra_Step1(doc)', code)

    def test_reports_what_was_not_understood(self):
        _, steps, unknown = v.generate('удалить пустые строки и сварить кофе')
        self.assertEqual(len(steps), 1)
        self.assertEqual(unknown, ['сварить кофе'])
        with self.assertRaises(ValueError):
            v.generate('сварить кофе')

    def test_warns_about_missing_parameters(self):
        _, steps, _ = v.generate('заменить текст')
        self.assertIn('кавычках', steps[0].warning)
        _, steps, _ = v.generate('выделить повторы')
        self.assertIn('взяла A', steps[0].warning)

    def test_quotes_in_text_are_escaped(self):
        code, _, _ = v.generate('Excel: заменить "ООО «Ромашка»" на "АО ""Р"""')
        self.assertEqual(v.lint(code), [])

    def test_all_sheets(self):
        code, _, _ = v.generate('подогнать ширину столбцов на всех листах')
        self.assertIn('For Each ws In ActiveWorkbook.Worksheets', code)
        self.assertEqual(v.lint(code), [])


class Export(unittest.TestCase):
    def test_bas_is_windows_1251_with_module_name(self):
        data = v.bas_bytes('Sub A()\n    MsgBox "Готово → да"\nEnd Sub\n')
        text = data.decode('cp1251')
        self.assertTrue(text.startswith('Attribute VB_Name = "Iskra"\r\n'))
        self.assertIn('MsgBox "Готово -> да"', text)

    def test_library_export(self):
        import tempfile, os
        from iskra_macros import MACROS, export_macro
        path = os.path.join(tempfile.mkdtemp(), 'm.bas')
        export_macro(MACROS[0], path)
        self.assertIn('Attribute VB_Name', open(path, encoding='cp1251').read())


class Fixing(unittest.TestCase):
    BROKEN = '''Sub Test()
    Dim i As Integer
    For i = 1 To 10
        If Cells(i, 1).Value = “x” Then
            total = total + 1
    Next i
End Sub
'''

    def test_lint_finds_problems(self):
        msgs = ' | '.join(m for _, m in v.lint('Option Explicit\n' + self.BROKEN))
        self.assertIn('кавычки', msgs)
        self.assertIn('As Integer', msgs)
        self.assertIn('End If', msgs)
        self.assertIn('«total» не объявлена', msgs)

    def test_auto_fix(self):
        fixed, changes = v.auto_fix(self.BROKEN)
        self.assertIn('As Long', fixed)
        self.assertIn('= "x"', fixed)
        self.assertIn('Dim total As Variant', fixed)
        self.assertTrue(fixed.startswith('Option Explicit'))
        self.assertEqual(len(changes), 4)
        # End If программа не выдумывает — об этом сообщает проверка.
        self.assertTrue(any('End If' in m for _, m in v.lint(fixed)))

    def test_explains_errors_in_russian_and_english(self):
        self.assertIn('9', v.explain_error('Ошибка выполнения 9: Индекс за пределами допустимого диапазона')[0])
        self.assertIn('1004', v.explain_error("Run-time error '1004': Application-defined or object-defined error")[0])
        self.assertIn('переполнение', v.explain_error('Ошибка на шаге «2»: 6 — Переполнение')[0].lower())
        self.assertIn('Макросы отключены', v.explain_error('Невозможно выполнить макрос')[0])
        self.assertIn('не из моего справочника', v.explain_error('что-то странное')[0])


if __name__ == '__main__':
    unittest.main()
