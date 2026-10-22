import sys
import unittest

import iskra_trial as t
import iskra_vba as v


class Prepare(unittest.TestCase):
    def test_msgbox_replaced_outside_strings_only(self):
        code = 'Sub Iskra_Macro()\n    MsgBox "Нажмите MsgBox", vbInformation\n    If MsgBox("Да?", vbYesNo) = vbYes Then x = 1 \' MsgBox тут\nEnd Sub\n'
        test, entry, refuse = t.prepare(code)
        self.assertEqual((entry, refuse), ('Iskra_Macro', ''))
        self.assertIn('IskraTrialMsg "Нажмите MsgBox"', test)
        self.assertIn('If IskraTrialMsg("Да?"', test)
        self.assertIn("' MsgBox тут", test)

    def test_entry_skips_private_and_parametrized(self):
        code = 'Private Sub A()\nEnd Sub\nSub B(x As Long)\nEnd Sub\nPublic Sub Main()\nEnd Sub\n'
        self.assertEqual(t.entry_point(code), 'Main')

    def test_dialog_macros_are_not_run(self):
        code, _, _ = v.generate('во всех документах папки заменить «т.е.» на «то есть»', 'word')
        _, _, refuse = t.prepare(code)
        self.assertIn('окно выбора', refuse)

    def test_generated_macros_prepare(self):
        code, _, _ = v.generate('удалить пустые строки, отсортировать по столбцу A', 'excel')
        test, entry, refuse = t.prepare(code)
        self.assertEqual(refuse, '')
        self.assertNotRegex(test.split("' ")[0], r'\bMsgBox\b')
        self.assertIn(f'Call {entry}', t.harness(entry))

    def test_parse_results(self):
        self.assertTrue(t.parse('OK\nMSG Готово. Выполнено шагов: 2.\n').ok)
        r = t.parse('OK\n!ERR 1004 Метод Range завершился ошибкой\nMSG Ошибка на шаге «1. Сортировка»\n')
        self.assertFalse(r.ok)
        self.assertIn('1004', r.error)
        self.assertIn('Ошибка на шаге', r.summary())
        r = t.parse('ERR\n!ERR 91 Object variable not set\n')
        self.assertFalse(r.ok)
        self.assertIn('91', r.error)

    def test_decode(self):
        self.assertIn('не найден', t._decode('noapp', 'class not registered').unavailable)
        self.assertIn('запрещают', t._decode('novbom', 'x').unavailable)
        self.assertIn('компиляции', t._decode('error', 'Compile error in hidden module').error)


@unittest.skipUnless(sys.platform == 'win32', 'только Windows')
class RealScript(unittest.TestCase):
    def test_powershell_script_runs(self):
        """На сервере сборки Office нет: сценарий должен честно сказать об этом, а не упасть."""
        code, _, _ = v.generate('удалить пустые строки', 'excel')
        r = t.run(code, 'excel', timeout=90)
        print('trial:', r)
        self.assertFalse(r.ok)
        self.assertTrue(r.unavailable or r.error)
        self.assertNotIn('PowerShell не выполнил', r.unavailable)


if __name__ == '__main__':
    unittest.main()
