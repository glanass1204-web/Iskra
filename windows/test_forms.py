import os
import tempfile
import unittest
from datetime import date

import iskra_forms as f


class LeaveTicket(unittest.TestCase):
    def test_days_words(self):
        self.assertEqual(f.days_words(30), 'тридцать суток')
        self.assertEqual(f.days_words(21), 'двадцать одни сутки')
        self.assertEqual(f.days_words(2), 'двое суток')
        self.assertEqual(f.days_words(11), 'одиннадцать суток')
        self.assertEqual(f.days_words(45), 'сорок пять суток')

    def test_dates_and_text(self):
        end, back = f.leave_dates(date(2026, 11, 1), 30)
        self.assertEqual((end, back), (date(2026, 11, 30), date(2026, 12, 1)))
        text = f.leave_ticket_text({'who': 'капитан Иванов Иван Иванович', 'kind_place': 'в основной отпуск в г. Курск',
                                    'days': '30', 'start': date(2026, 11, 1), 'end': end, 'back_name': 'Иванов И.И.',
                                    'unit': 'войсковую часть 12345', 'back_date': back})
        self.assertIn('сроком на тридцать суток', text)
        self.assertIn('с "01" ноября 2026 г. по "30" ноября 2026 г.', text)
        self.assertIn('явиться к месту военной службы в войсковую часть 12345 "01" декабря 2026 г.', text)
        self.assertNotIn('[УТОЧНИТЬ', text)
        self.assertIn('[УТОЧНИТЬ', f.leave_ticket_text({}))

    def test_word_a5(self):
        from docx import Document
        path = os.path.join(tempfile.mkdtemp(), 'b.docx')
        f.save_leave_ticket({'who': 'капитан Иванов Иван Иванович', 'days': '10'}, path)
        doc = Document(path)
        self.assertAlmostEqual(doc.sections[0].page_width.cm, 14.8, places=1)
        self.assertIn('ОТПУСКНОЙ БИЛЕТ', [p.text for p in doc.paragraphs])

    def test_short_name(self):
        import importlib.util
        if importlib.util.find_spec('tkinter') is None:
            self.skipTest('нет tkinter')
        from iskra_forms_ui import short_name
        self.assertEqual(short_name('капитан Иванов Иван Иванович'), 'Иванов И.И.')


if __name__ == '__main__':
    unittest.main()
