import os
import tempfile
import unittest
from pathlib import Path

os.environ['ISKRA_DATA_DIR'] = tempfile.mkdtemp()
import iskra_index  # noqa: E402
import iskra_smartsearch as ss  # noqa: E402


class SmartSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = Path(tempfile.mkdtemp())
        (d / 'Сведения госпиталь.txt').write_text('Численность личного состава госпиталя: по списку 120, на лицо 112.', encoding='utf-8')
        (d / 'Топливо.txt').write_text('Остатки ГСМ на складе: дизельное топливо 12 т.', encoding='utf-8')
        (d / 'Отпуска.txt').write_text('График отпусков на 2027 год.', encoding='utf-8')
        iskra_index.index_folder(str(d), lambda *_: None)

    def names(self, rows):
        return {Path(p).name for p, _ in rows}

    def test_plain_search_still_works(self):
        rows, how = ss.search('ГСМ')
        self.assertEqual(self.names(rows), {'Топливо.txt'})
        self.assertEqual(how, '')

    def test_by_meaning(self):
        rows, how = ss.search('сколько людей в госпитале')
        self.assertEqual(self.names(rows), {'Сведения госпиталь.txt'})
        self.assertTrue(how.startswith('по смыслу'))
        rows, _ = ss.search('остатки горючего')
        self.assertEqual(self.names(rows), {'Топливо.txt'})
        rows, _ = ss.search('когда увольнения')
        self.assertEqual(self.names(rows), {'Отпуска.txt'})

    def test_ai_expansion(self):
        rows, how = ss.search('планы отдыха сотрудников летом', ai_expand=lambda q: ['отпусков', 'график'])
        self.assertIn('Отпуска.txt', self.names(rows))

    def test_user_synonyms(self):
        root = Path(tempfile.mkdtemp())
        (root / 'sinonimy.txt').write_text('ГСМ, соляра\n', encoding='utf-8')
        rows, _ = ss.smart_search('соляра', root=root)
        self.assertEqual(self.names(rows), {'Топливо.txt'})


if __name__ == '__main__':
    unittest.main()
