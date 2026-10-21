import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('ISKRA_DATA_DIR', tempfile.mkdtemp())
from iskra_spell import SpellChecker, DICT_DIR, summary

CHECKER = SpellChecker(DICT_DIR, Path(tempfile.mkdtemp()) / 'words.txt')


class Spell(unittest.TestCase):
    def test_finds_misspellings_but_not_names(self):
        text = ('Начальнику отдела кадров Иванову И.И. подготоветь сводный отчот до 25 октября. '
                'Телиграму направить в штаб.')
        found = [(i.text, i.kind) for i in CHECKER.check(text) if i.kind == 'spelling']
        self.assertEqual(found, [('подготоветь', 'spelling'), ('отчот', 'spelling'), ('Телиграму', 'spelling')])

    def test_suggestions(self):
        self.assertIn('отчёт', [s.replace('е', 'ё') if s == 'отчет' else s for s in CHECKER.suggest('отчот')] + CHECKER.suggest('отчот'))
        self.assertIn('подготовить', CHECKER.suggest('подготоветь'))

    def test_office_style_rules(self):
        text = 'Согласно приказа командира, в течении недели оплатить за услуги и и по приезду доложить.'
        kinds = {(i.text.lower(), i.fix) for i in CHECKER.check(text) if i.kind != 'spelling'}
        self.assertIn(('согласно приказа', ''), kinds)
        self.assertIn(('в течении', 'в течение'), kinds)
        self.assertIn(('оплатить за', 'оплатить'), kinds)
        self.assertIn(('и и', 'и'), kinds)
        self.assertIn(('по приезду', 'по приезде'), kinds)

    def test_user_dictionary(self):
        self.assertFalse(CHECKER.known('Гвардейскстрой'.lower()))
        CHECKER.add_word('гвардейскстрой')
        self.assertTrue(CHECKER.known('гвардейскстрой'))

    def test_clean_text(self):
        issues = CHECKER.check('Прошу представить отчёт о выполнении работ в установленный срок.')
        self.assertEqual(summary(issues), 'Ошибок не найдено.', issues)


if __name__ == '__main__':
    unittest.main()
