import tempfile
import unittest
from datetime import date
from pathlib import Path

from docx import Document

import iskra_journal as jr
import iskra_report as rp


class JournalTest(unittest.TestCase):
    def test_numbers_and_replies(self):
        j = jr.Journal(Path(tempfile.mkdtemp()))
        j.configure(fmt='{n}/шт')
        a = j.register('Начальнику госпиталя', 'О представлении сведений', reply_by='25.10.2026', today=date(2026, 10, 20))
        b = j.register('Командиру в/ч 12345', 'О проверке', today=date(2026, 10, 21))
        self.assertEqual((a['number'], b['number']), ('1/шт', '2/шт'))
        self.assertEqual(j.lines_for_morning(date(2026, 10, 26))[0][-11:], '(ПРОСРОЧЕН)')
        done = j.match_reply('На Ваш № 1/шт от 20.10.2026 докладываю: сведения прилагаются.', 'ответ.docx')
        self.assertEqual([d['number'] for d in done], ['1/шт'])
        self.assertEqual(j.waiting(date(2026, 10, 26)), [])
        c = j.register('x', 'y', today=date(2027, 1, 10))                 # новый год — нумерация заново
        self.assertEqual(c['number'], '1/шт')
        again = jr.Journal(j.path.parent)
        self.assertEqual(len(again.items), 3)

    def test_text_helpers(self):
        text = 'ТЕЛЕГРАММА\n\nКому: Начальнику госпиталя\nДата: [ДАТА]\nНомер: [НОМЕР]\n\nТекст: Представить сведения о численности.'
        self.assertEqual(jr.addressee_from_text(text), 'Начальнику госпиталя')
        self.assertTrue(jr.subject_from_text(text).startswith('Представить сведения'))
        filled, placed = jr.put_number(text, '17/шт', '22.10.2026')
        self.assertTrue(placed)
        self.assertIn('№ 5/шт', jr.put_number('Исх. [УТОЧНИТЬ: номер] от [УТОЧНИТЬ: дата]', '5/шт', '22.10.2026')[0])
        self.assertFalse(jr.put_number('Просто текст', '5', '22.10.2026')[1])
        self.assertIn('Номер: 17/шт', filled)
        self.assertIn('Дата: 22.10.2026', filled)
        self.assertEqual(jr.addressee_from_text('Начальнику госпиталя\nполковнику\nИванову И.И.\n\nПрошу...'),
                         'Начальнику госпиталя полковнику Иванову И.И.')


class ReportTest(unittest.TestCase):
    def test_build_from_template(self):
        root = Path(tempfile.mkdtemp())
        sections = [('ПРИШЛО', ['Телеграмма «154»', 'Приказ «12»']), ('СРОКИ СЕГОДНЯ И ЗАВТРА', []),
                    ('ПРОСРОЧЕНО', ['25.10.2026 — сведения']), ('СВОД ЗА ДЕНЬ', ['Свод: 5 файлов'])]
        out = rp.build(root, sections, ['№ 1/шт — ответ до 25.10.2026'], main='Всё по плану.', today=date(2026, 10, 22))
        text = '\n'.join(p.text for p in Document(out).paragraphs)
        self.assertIn('на 22.10.2026', text)
        self.assertIn('— Телеграмма «154»', text)
        self.assertIn('— Приказ «12»', text)
        self.assertIn('Всё по плану.', text)
        self.assertIn('№ 1/шт', text)
        self.assertNotIn('{{', text)
        self.assertTrue(out.name.startswith('Доклад 22.10.2026'))


if __name__ == '__main__':
    unittest.main()
