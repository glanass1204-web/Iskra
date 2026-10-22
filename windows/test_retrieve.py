import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

import iskra_ai as ai


class RetrieveTest(unittest.TestCase):
    def test_collects_many_documents(self):
        docs = {f'тлг {i}.txt': f'Телеграмма {i}. Представить сведения о технике подразделения {i} до {10 + i}.11.2026.' for i in range(1, 9)}
        docs['приказ.txt'] = 'Приказ о готовности техники к зиме.'

        def search(q, any_word):
            words = q.lower().split()
            hit = [p for p, t in docs.items() if (any if any_word else all)(w[:5] in t.lower() for w in words)]
            return [(p, '') for p in hit]
        sources, paths = ai.retrieve('напиши доклад о готовности техники по телеграммам о сведениях', search, docs.get)
        self.assertGreaterEqual(len(paths), 8)                  # раньше — не больше 4, обычно 1–2

    def test_file_date_in_name(self):
        d = Path(tempfile.mkdtemp())
        f = d / 'старая.txt'
        f.write_text('Сведения о технике', encoding='utf-8')
        old = time.mktime((2024, 3, 1, 12, 0, 0, 0, 0, -1))
        os.utime(f, (old, old))
        sources, _ = ai.retrieve('сведения о технике', lambda q, a: [(str(f), '')], lambda p: Path(p).read_text(encoding='utf-8'))
        self.assertIn('файл от 01.03.2024', sources[0][0])

    def test_condense_reads_every_document(self):
        calls = []
        old = ai.notes
        ai.notes = lambda task, name, text, **kw: calls.append(name) or ('НЕТ' if name == 'пусто' else f'выписка {name}')
        try:
            sources = [(f'док {i}', 'х' * 3000) for i in range(6)] + [('пусто', 'у' * 3000)]
            out = ai.condense('задача', sources)
            self.assertEqual(len(calls), 7)
            self.assertEqual(len(out), 6)
            self.assertTrue(all(n.endswith('выписка') for n, _ in out))
            small = [('a', 'короткий'), ('b', 'текст')]
            self.assertEqual(ai.condense('задача', small), small)        # помещается — без лишнего шага
        finally:
            ai.notes = old

    def test_past_dates_not_used_as_deadlines(self):
        text = 'Дата: 12.03.2025\nНа № 7 от 01.02.2025 представить сведения до 15.10.2025, доложить до 30.11.2026.'
        fixed, changed = ai.fix_dates(text, '', date(2026, 10, 22))
        self.assertIn('Дата: 22.10.2026', fixed)
        self.assertIn('от 01.02.2025', fixed)                    # ссылка на старый документ — можно
        self.assertIn('[УТОЧНИТЬ: срок', fixed)
        self.assertNotIn('до 15.10.2025', fixed)
        self.assertIn('30.11.2026', fixed)
        self.assertEqual(len(changed), 2)
        self.assertIn('Сегодня', ai.DATE_RULES())


if __name__ == '__main__':
    unittest.main()
