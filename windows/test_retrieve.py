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

    def test_every_document_fits_no_truncation(self):
        """Раньше документы по 1800 знаков — после 5-го кончалось место, остальные отрезались."""
        docs = {f'тлг {i}.txt': ('Вступление. ' * 200) + f'Представить сведения о технике в/ч {1000 + i}: {i} ед. '
                                + ('Окончание. ' * 200) for i in range(1, 19)}

        def search(q, any_word):
            words = q.lower().split()
            return [(p, '') for p, t in docs.items() if (any if any_word else all)(w[:5] in t.lower() for w in words)]
        sources, paths = ai.retrieve('доклад о сведениях о технике', search, docs.get)
        self.assertEqual(len(paths), 18)
        block, truncated = ai.materials(sources)
        self.assertEqual(truncated, [])                                  # ни один не обрезан
        for i in range(1, 19):
            self.assertIn(f'в/ч {1000 + i}', block)                       # из каждого — нужное место

    def test_rank_by_matched_words(self):
        docs = {'общий.txt': 'сведения сведения сведения о готовности',
                'точный.txt': 'КП 5447 переместился в Лисичанск, сведения о готовности',
                'шум.txt': 'прочее'}

        def search(q, any_word):
            words = q.lower().split()
            return [(p, '') for p, t in docs.items() if (any if any_word else all)(w[:4] in t.lower() for w in words)]
        stats = {}
        _, paths = ai.retrieve('где сейчас КП 5447, Лисичанск, сведения', search, docs.get, stats=stats)
        self.assertEqual(paths[0] if len(paths) == 1 else sorted(paths, key=lambda p: p != 'точный.txt')[0], 'точный.txt')
        ranked = ai.rank_documents(ai.keywords('КП 5447 Лисичанск сведения'), search)
        self.assertEqual(ranked[0][0], 'точный.txt')
        self.assertNotIn('шум.txt', [r[0] for r in ranked])
        self.assertGreaterEqual(stats['found'], 1)

    def test_unasked_dates_times_numbers_removed(self):
        src = [('тлг_техника_5.docx (файл от 21.10.2026)', 'x')]
        text = ('ТЕЛЕГРАММА\nКому: Командиру войсковой части 12345\nДата: 22.10.2026\nТекст:\n'
                'Согласно телеграмме «тлг_техника_5» от 21.10.2026 № 154/2 прошу представить сведения о технике '
                'по состоянию на 20.10.2026. Совещание в 14:00 в штабе.\nПодпись:\nНачальник штаба\nполковник И.И. Иванов')
        out, removed = ai.strip_unasked(text, 'составь телеграмму командиру войсковой части 12345: запросить сведения о технике', '', src)
        self.assertIn('Прошу представить сведения о технике.', out)
        self.assertIn('Совещание в штабе.', out)
        for gone in ('21.10.2026', '154/2', '20.10.2026', '14:00', 'тлг_техника'):
            self.assertNotIn(gone, out)
        self.assertIn('Дата: 22.10.2026', out)                       # шапка остаётся
        self.assertIn('войсковой части 12345', out)                  # не дата и не номер документа
        self.assertIn('И.И. Иванов', out)
        self.assertGreaterEqual(len(removed), 5)

    def test_asked_dates_and_refs_stay(self):
        text = 'Текст:\nНа № 154/2 от 20.10.2026 докладываю: сведения будут представлены до 25.10.2026, совещание в 14:00.'
        out, removed = ai.strip_unasked(text, 'ответ на телеграмму 154/2: сведения представим в срок, совещание в 14:00')
        self.assertEqual(out, text)
        self.assertEqual(removed, [])
        own, _ = ai.strip_unasked('Текст:\nПрибыть 27.10.2026.', 'оформи телеграммой', keep='прибыть 27.10.2026')
        self.assertIn('27.10.2026', own)                              # дату написал сам человек

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
