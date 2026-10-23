"""Телеграмма по задаче: сколько просили пунктов — столько и будет; документы — по теме и из своих папок."""
import unittest

import iskra_ai as ai


class Points(unittest.TestCase):
    def test_wanted_count(self):
        self.assertEqual(ai.wanted_count('составь телеграмму о повышении живучести ПУ, 15 пунктов'), 15)
        self.assertEqual(ai.wanted_count('указание из десяти мероприятий'), 0)          # «десяти» — косвенный падеж
        self.assertEqual(ai.wanted_count('пятнадцать пунктов по связи'), 15)
        self.assertEqual(ai.wanted_count('на 3 пунктах управления'), 0)
        self.assertEqual(ai.wanted_count('телеграмма о готовности'), 0)

    def test_plan_then_text_then_missing_points_added(self):
        calls = []
        plan = '\n'.join(f'{i}. {w}' for i, w in enumerate([
            'Провести маскировку пункта управления', 'Оборудовать запасные позиции', 'Организовать охранение',
            'Рассредоточить средства связи', 'Создать резерв питания', 'Подготовить укрытия личного состава',
            'Организовать дежурство расчётов', 'Отработать перемещение пункта управления'], 1))
        short = ('1. Провести маскировку пункта управления.\n2. Оборудовать запасные позиции.\n3. Организовать охранение:\n'
                 '– круглосуточно.\nО выполнении доложить.')
        more = '4. Рассредоточить средства связи.\n5. Провести маскировку пункта управления.\n6. Создать резерв питания.'

        def fake(prompt, **kw):
            calls.append(prompt)
            return [plan, short, more][min(len(calls) - 1, 2)]
        old = ai.run
        ai.run = fake
        try:
            out, _ = ai.write('составь телеграмму о повышении живучести ПУ, 8 пунктов', [])
        finally:
            ai.run = old
        self.assertIn('ровно из 8', calls[0])                    # сначала разбор задачи
        self.assertIn('НУЖНО РОВНО 8 ПУНКТОВ', calls[1])
        self.assertIn('Подготовить укрытия личного состава', calls[1])      # план — в задании на текст
        self.assertIn('Допиши пункты с 4 по 8', calls[2])
        points = ai.numbered(out)
        self.assertEqual(len(points), 8)
        self.assertEqual([p.split('.')[0] for p in points], [str(i) for i in range(1, 9)])
        self.assertEqual(sum('маскировку' in p for p in points), 1)   # повтор не дописан
        self.assertIn('Рассредоточить средства связи', out)
        self.assertTrue(out.rstrip().endswith('О выполнении доложить.'))
        self.assertIn('– круглосуточно.\n4. ', out)


class Documents(unittest.TestCase):
    def test_abbreviation_is_a_keyword(self):
        self.assertIn('ПУ', ai.keywords('составь телеграмму о повышении живучести ПУ'))
        self.assertNotIn('по', ai.keywords('по на в'))

    def test_one_common_word_is_not_enough(self):
        docs = {'старая.txt': 'О повышении классной квалификации водителей подразделений 1 мсб.',
                'живучесть.txt': 'Мероприятия по повышению живучести ПУ: маскировка, рассредоточение.',
                'пу.txt': 'Живучесть пунктов управления (ПУ) обеспечивается маскировкой.'}

        def search(q, any_word):
            return [(p, '') for p, t in docs.items() if all(w.lower()[:5] in t.lower() for w in q.split())]
        found = [p for p, _, _ in ai.rank_documents(ai.keywords('повышении живучести ПУ'), search)]
        self.assertIn('живучесть.txt', found)
        self.assertNotIn('старая.txt', found)                     # только «повышении» — не по теме

    def test_only_search_folders_and_named_folder(self):
        docs = {r'D:\Штаб\ПУ\живучесть.docx': 'живучесть ПУ', r'D:\Штаб\Связь\живучесть связи.docx': 'живучесть ПУ',
                r'C:\Users\u\Desktop\живучесть.docx': 'живучесть ПУ'}

        def search(q, any_word):
            return [(p, '') for p in docs]
        stats = {}
        _, paths = ai.retrieve('телеграмма о живучести ПУ', search, docs.get, folders=[r'D:\Штаб'], stats=stats)
        self.assertEqual(len(paths), 2)                           # рабочий стол — не папка поиска
        _, paths = ai.retrieve('телеграмма о живучести по документам из папки ПУ', search, docs.get,
                               folders=[r'D:\Штаб'], stats=stats)
        self.assertEqual(paths, [r'D:\Штаб\ПУ\живучесть.docx'])
        self.assertEqual(stats['folder'], 'пу')

    def test_unit_numbers_not_asked_removed(self):
        out, removed = ai.strip_unasked('1. Командиру войсковой части 54321 обеспечить маскировку.', 'телеграмма о живучести ПУ')
        self.assertEqual(out, '1. Командиру войсковой части обеспечить маскировку.')
        self.assertIn('номер части: 54321', removed)


if __name__ == '__main__':
    unittest.main()
