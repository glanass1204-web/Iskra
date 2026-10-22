import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ['ISKRA_DATA_DIR'] = TMP

import iskra_bugreport as br  # noqa: E402
from iskra_workflows import save_history  # noqa: E402


class Report(unittest.TestCase):
    def test_report_has_facts_but_no_private_text(self):
        save_history(TMP, 'Телеграмма', 'СЕКРЕТНЫЙ ТЕКСТ ТЕЛЕГРАММЫ про Иванова')
        try:
            raise ValueError('проверка')
        except ValueError:
            br.log_crash('Ошибка в окне', *sys.exc_info())
        text = br.build('нажал Свод — зависло', '9.9.9')
        self.assertIn('9.9.9', text)
        self.assertIn('нажал Свод', text)
        self.assertIn('Телеграмма', text)                     # действие видно…
        self.assertNotIn('СЕКРЕТНЫЙ', text)                   # …а его текст — нет
        self.assertIn('ValueError: проверка', text)
        self.assertIn('Движок:', text)
        home = str(Path.home())
        if len(home) > 3:
            self.assertNotIn(home, text)

    def test_crash_log_is_capped(self):
        old = br.LOG_LIMIT
        br.LOG_LIMIT = 2000
        try:
            for _ in range(50):
                try:
                    raise RuntimeError('x' * 100)
                except RuntimeError:
                    br.log_crash('тест', *sys.exc_info())
            self.assertLessEqual(len(br.errors_log().read_text(encoding='utf-8')), 2000)
        finally:
            br.LOG_LIMIT = old

    def test_save(self):
        path = br.save('отчёт', TMP)
        self.assertTrue(path.read_text(encoding='utf-8-sig').startswith('отчёт'))


if __name__ == '__main__':
    unittest.main()
