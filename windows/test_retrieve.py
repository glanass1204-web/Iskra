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
        self.assertNotIn('Дата:', out)                               # дату не просили — и в шапке её нет
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

    def test_proofread_fixes_typos_keeps_names(self):
        text = ('Текст:\n**Прошу** предаставить сведенья согласно приказа № 7 в течении суток. '
                'Ответсвенный — майор Кузнецов 完成.\nПодпись:\nполковник И.И. Сидорчук')
        out, fixes = ai.proofread(text, [('a', 'майор Кузнецов, полковник Сидорчук')], 'телеграмма')
        if ai._speller() is not None:
            self.assertIn('Прошу представить сведения согласно приказу № 7 в течение суток.', out)
            self.assertIn('Ответственный — майор Кузнецов.', out)
        self.assertIn('Сидорчук', out)
        self.assertNotIn('**', out)
        self.assertNotIn('完', out)
        self.assertTrue(fixes)

    def test_short_draft_is_expanded(self):
        calls = []
        short = 'ТЕЛЕГРАММА\nКому: Командирам\nТекст:\nПроверить технику.\nПодпись:\nНШ'
        full = ('ТЕЛЕГРАММА\nКому: Командирам\nТекст:\n' + '1. Провести проверку технического состояния техники '
                'подразделений с составлением актов. ' * 12 + '\nПодпись:\nНШ')
        old = ai.run
        ai.run = lambda prompt, **kw: calls.append(prompt) or (short if len(calls) == 1 else full)
        try:
            facts = [('сведения.docx', 'КамАЗ-4310 — 6 ед., неисправно 2, требуется замена двигателя. Урал — 3 ед. '
                                         'Ответственный — капитан Орлов. Акты проверки представить в отдел. ' * 4)]
            out, _ = ai.write('составь телеграмму командирам: проверить технику', facts)
            self.assertEqual(len(calls), 2)                              # коротко — второй круг
            self.assertIn('РАЗВЁРНУТО', calls[1])
            self.assertGreater(len(ai.body_of(out)), 450)
            calls.clear()
            ai.run = lambda prompt, **kw: calls.append(prompt) or full
            ai.write('составь телеграмму командирам: проверить технику', facts)
            self.assertEqual(len(calls), 1)                              # и так полно — без лишнего круга
            calls.clear()
            ai.run = lambda prompt, **kw: calls.append(prompt) or short
            ai.write('составь телеграмму командирам: проверить технику', [('сведения.docx', 'КамАЗ 6 ед.')])
            self.assertEqual(len(calls), 1)                              # материалов почти нет — не раздувать «водой»
            self.assertIn('РАЗВЁРНУТО', calls[0])                        # требование полноты в задании
        finally:
            ai.run = old

    def test_sample_of_other_kind_not_used_and_copy_redone(self):
        import tempfile
        sample = ('ТЕЛЕГРАММА\n\nКомандирам подразделений\n\nВо исполнение указаний штаба округа ПРИКАЗЫВАЮ:\n'
                  '1. Провести проверку наличия и технического состояния автомобильной техники подразделений.\n'
                  '2. Неисправную технику выявить, принять меры к её восстановлению силами ремонтных подразделений.\n'
                  '3. О выполнении доложить.\n\nНачальник штаба\nполковник А.А. Смирнов')
        d = Path(tempfile.mkdtemp())
        (d / 'Телеграмма о проверке техники.txt').write_text(sample, encoding='utf-8')
        old_dir, old_run = ai.STYLE_DIR, ai.run
        ai.STYLE_DIR = d
        calls = []
        try:
            other = ai.best_sample('Составь телеграмму-ответ: сведения о технике направляем, техника готова')
            self.assertEqual(other[0], 'типовой образец Искры')       # приказ отдела к ответу не подходит
            self.assertIsNotNone(ai.best_sample('Составь телеграмму командирам: провести проверку техники к зиме'))
            # нейросеть переписала образец, а задачу (учения, полигон) не раскрыла — второй раз без образца
            answers = [sample, 'ТЕЛЕГРАММА\nТекст:\n' + '1. Организовать выход подразделений на полигон для учений '
                       'с техникой, проверить готовность техники к учениям. ' * 6]
            ai.run = lambda prompt, **kw: calls.append(prompt) or answers[min(len(calls) - 1, 1)]
            out, _ = ai.write('Составь телеграмму командирам: организовать выход на полигон для учений с проверкой техники',
                              [('план.docx', 'Учения на полигоне, техника')])
            self.assertEqual(len(calls), 2)
            self.assertIn('ОБРАЗЕЦ', calls[0])
            self.assertNotIn('ОБРАЗЕЦ', calls[1])
            self.assertIn('полигон', out)
        finally:
            ai.STYLE_DIR, ai.run = old_dir, old_run

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
