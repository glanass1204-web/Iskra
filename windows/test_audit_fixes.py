"""Ошибки, найденные проверкой кода, — чтобы не вернулись."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import iskra_ai as ai
import iskra_assistant as a
import iskra_control as c


class AuditFixes(unittest.TestCase):
    TODAY = date(2026, 10, 22)

    def test_fix_dates_does_not_touch_words_or_facts(self):
        t = 'Приложение: список 01.10.2026. Утверждён график 15.09.2026. Сведения представлены до 15.10.2026.'
        self.assertEqual(ai.fix_dates(t, '', self.TODAY)[0], t)

    def test_keep_unasked_keeps_additions_and_asked_addressee(self):
        prev = 'Кому: Штаб округа\n\nТекст: сведения.\n\nПодпись:\nНачальник штаба\nП.П. Сидоров'
        res = 'Кому: Штаб округа\n\nТекст: сведения.\n\nПодпись:\nНачальник штаба\nП.П. Сидоров\n\nИсполнитель: Петров, тел. 12-34'
        self.assertIn('Исполнитель: Петров', ai.keep_unasked(prev, res, 'добавь исполнителя Петров, тел. 12-34'))
        res2 = res.replace('Кому: Штаб округа', 'Кому: Начальнику штаба округа')
        self.assertIn('Кому: Начальнику штаба округа', ai.keep_unasked(prev, res2, 'отправь начальнику штаба округа'))

    def test_control_deadline_not_reference_date(self):
        t = 'Начальнику госпиталя представить копию приказа от 01.09.2026 № 12 в срок до 30.10.2026.'
        self.assertEqual([x['deadline'] for x in c.extract(t, 'x', today=self.TODAY)], ['30.10.2026'])
        got = c.merge_ai([], [{'что': 'представить копию', 'срок': '01.09.2026'}], t)
        self.assertEqual(got[0]['deadline'], '')

    def test_year_rolls_over_at_new_year(self):
        self.assertEqual(a.deadlines('представить до 15 января', date(2026, 12, 20))[0].value, '15.01.2027')

    def test_questions_on_new_topic(self):
        self.assertFalse(a.related('Кто подписал приказ № 7?', 'какой срок сведений о численности'))
        self.assertTrue(a.related('а кто подписал телеграмму 154?', 'какой срок по телеграмме 154'))

    def test_keywords_keep_numbers(self):
        self.assertIn('7', ai.keywords('Напиши справку о выполнении приказа № 7'))
        self.assertIn('ГСМ', ai.keywords('Найди телеграмму № 45 от 12.10 про ГСМ'))
        self.assertNotIn('справку', ai.keywords('Напиши справку о выполнении приказа № 7'))

    def test_telegram_words(self):
        self.assertTrue(ai.TELEGRAM_WORDS.search('напиши тлг начальнику'))
        self.assertFalse(ai.TELEGRAM_WORDS.search('напиши доклад'))

    def test_revise_answer_not_document(self):
        seen = {}
        old = ai.run
        ai.run = lambda p, **kw: seen.setdefault('p', p) and 'ok'
        try:
            ai.revise('до какого числа сведения?', 'До 15.10.2025. Источник: тлг.docx', 'сделай по пунктам', kind='ask')
            self.assertNotIn('Дата нового документа', seen['p'])
        finally:
            ai.run = old

    def test_autosvod_restore_without_writing(self):
        from openpyxl import Workbook
        import iskra_autosvod as asv
        d = Path(tempfile.mkdtemp())
        wb = Workbook(); ws = wb.active
        ws.append(['Организация', 'По списку', 'На лицо']); ws.append(['Госпиталь', 120, 112])
        wb.save(d / 'госпиталь.xlsx')
        s = asv.AutoSvod(Path(tempfile.mkdtemp()))
        s.configure(d, d, order=['Госпиталь', 'Полигон'])
        r = s.build(write=False)
        self.assertEqual(r['missing'], ['Полигон'])
        self.assertFalse(list(d.glob('Свод *.xlsx')))           # файлы свода не тронуты


if __name__ == '__main__':
    unittest.main()
