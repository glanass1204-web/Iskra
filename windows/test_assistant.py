import unittest
from datetime import date

import iskra_assistant as a
from iskra_services import excel_formula

DOC = '''ПРИКАЗ № 15-к от 20.10.2026
О подготовке годового отчёта

В целях своевременной подготовки отчётности приказываю:
1. Начальнику отдела кадров Иванову И.И. подготовить сводный отчёт до 25 октября 2026 года.
2. Главному бухгалтеру Петровой А.С. представить расчёт фонда оплаты труда не позднее 01.11.2026.
3. Выделить на подготовку 150 000 руб. из резервного фонда.
4. Контроль за исполнением возложить на С.П. Сидорова, тел. 8 (495) 123-45-67, sidorov@example.ru.
Совещание состоялось 15.10.2026.'''

TODAY = date(2026, 10, 21)


class Extraction(unittest.TestCase):
    def test_deadlines_only_where_a_deadline_word_precedes(self):
        found = a.deadlines(DOC, TODAY)
        self.assertEqual([f.value for f in found], ['25.10.2026', '01.11.2026'])
        self.assertIn('Иванову', found[0].context)

    def test_all_dates(self):
        self.assertEqual([f.value for f in a.all_dates(DOC, TODAY)], ['15.10.2026', '20.10.2026', '25.10.2026', '01.11.2026'])

    def test_word_dates_without_year_use_current_year(self):
        self.assertEqual(a.deadlines('Сдать отчёт до 3 марта.', TODAY)[0].value, '03.03.2026')

    def test_people(self):
        self.assertEqual([f.value for f in a.people(DOC)], ['Иванову И.И.', 'Петровой А.С.', 'Сидорова С.П.'])

    def test_numbers_money_contacts(self):
        self.assertEqual([f.value for f in a.numbers(DOC)], ['№ 15-к'])
        self.assertEqual([f.value for f in a.money(DOC)], ['150000 руб.'])
        self.assertEqual([f.value for f in a.contacts(DOC)], ['8 (495) 123-45-67', 'sidorov@example.ru'])

    def test_summary_keeps_original_sentences_in_order(self):
        s = a.summary(DOC, limit=3)
        self.assertEqual(len(s), 3)
        for sentence in s:
            self.assertIn(sentence, ' '.join(a.sentences(DOC)))
        self.assertTrue(s[0].startswith('ПРИКАЗ') or s[0].startswith('О подготовке'))

    def test_upcoming_across_documents(self):
        rows = a.upcoming([('a.docx', DOC), ('b.docx', 'Направить ответ до 18.10.2026. Старое: до 01.01.2020.')], TODAY)
        self.assertEqual([(r[0].isoformat(), r[1], r[2]) for r in rows], [
            ('2026-10-18', 'просрочено на 3 дн.', 'b.docx'),
            ('2026-10-25', 'через 4 дн.', 'a.docx'),
            ('2026-11-01', 'через 11 дн.', 'a.docx'),
        ])

    def test_invalid_dates_are_ignored(self):
        self.assertEqual(a.all_dates('Версия 1.2.3 и дата 31.02.2026', TODAY), [])


class Commands(unittest.TestCase):
    def test_intents(self):
        cases = {
            'что ты умеешь?': ('help', ''),
            'кратко': ('summary', ''),
            'О чём документ': ('summary', ''),
            'сроки': ('deadlines', ''),
            'ближайшие сроки': ('upcoming', ''),
            'что просрочено': ('upcoming', ''),
            'кто исполнитель': ('people', ''),
            'суммы': ('money', ''),
            'формула сумма по условию': ('formula', 'сумма по условию'),
            'найди приказ о премировании': ('search', 'приказ о премировании'),
            'отпуск Иванова': ('search', 'отпуск иванова'),
            'сколько документов': ('stats', ''),
            'проверь орфографию': ('spell', ''),
            'объедини три телеграммы': ('merge', ''),
            'собери из word в excel': ('word2excel', ''),
            'из excel в word по образцу': ('excel2word', ''),
            'формула сумма столбца C где в A "Москва"': ('formula', 'сумма столбца C где в A "Москва"'),
            '=ВПР(E2;A:B;2;ЛОЖЬ)': ('explain', '=ВПР(E2;A:B;2;ЛОЖЬ)'),
            'объясни =СУММ(A1:A5)': ('explain', '=СУММ(A1:A5)'),
        }
        for text, expected in cases.items():
            self.assertEqual(a.intent(text), expected, text)

    def test_formulas(self):
        self.assertTrue(excel_formula('сумма по условию')[0].startswith('=СУММЕСЛИ('))
        self.assertTrue(excel_formula('рабочие дни между датами')[0].startswith('=ЧИСТРАБДНИ('))
        self.assertTrue(excel_formula('подтянуть данные с другого листа')[0].startswith('=ЕСЛИОШИБКА(ВПР('))
        self.assertTrue(excel_formula('просто сумма')[0].startswith('=СУММ('))
        self.assertIsNone(excel_formula('погода')[0])


if __name__ == '__main__':
    unittest.main()
