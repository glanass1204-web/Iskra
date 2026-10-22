import tempfile
import unittest
from datetime import date
from pathlib import Path

import iskra_people as pp
import iskra_precheck as pc


class PeopleTest(unittest.TestCase):
    def test_addressee_cases(self):
        person = {'fio': 'Иванов И.И.', 'rank': 'полковник медицинской службы', 'position': 'начальник госпиталя'}
        self.assertEqual(pp.addressee(person), ['Начальнику госпиталя', 'полковнику медицинской службы', 'Иванову И.И.'])
        self.assertEqual(pp.inflect_phrase('старший помощник начальника штаба'), 'старшему помощнику начальника штаба')
        self.assertEqual(pp.inflect_phrase('генерал-майор'), 'генерал-майору')
        self.assertEqual(pp.inflect_surname('Петрова', 'datv', 'ж'), 'Петровой')
        self.assertEqual(pp.inflect_surname('Шевченко', 'datv'), 'Шевченко')
        self.assertEqual(pp.signature({'fio': 'Сидоров П.П.', 'rank': 'полковник', 'position': 'начальник штаба'}),
                         'Начальник штаба\nполковник\nП.П. Сидоров')

    def test_store_find_excel(self):
        root = Path(tempfile.mkdtemp())
        people = pp.People(root)
        people.add(fio='Иванов И.И.', rank='полковник', position='начальник госпиталя', org='Госпиталь')
        people.add(fio='Петрова А.С.', rank='', position='начальник отдела кадров', sex='ж')
        self.assertEqual([p['fio'] for p in people.find('доложить Иванову И.И. до пятницы')], ['Иванов И.И.'])
        self.assertTrue(people.context('госпиталь'))
        x = root / 'люди.xlsx'
        people.to_xlsx(x)
        other = pp.People(Path(tempfile.mkdtemp()))
        self.assertEqual(other.from_xlsx(x), 2)
        self.assertEqual(other.items[1]['sex'], 'ж')

    def test_rank_mismatch(self):
        people = pp.People(Path(tempfile.mkdtemp()))
        people.add(fio='Иванов И.И.', rank='полковник', position='начальник госпиталя')
        people.add(fio='Сидоров П.П.', rank='майор', position='начальник штаба')
        self.assertTrue(pp.mismatches('Начальнику госпиталя\nмайору\nИванову И.И.', people))
        self.assertFalse(pp.mismatches('Начальнику госпиталя\nполковнику\nИванову И.И.', people))


class PrecheckTest(unittest.TestCase):
    def test_finds_problems(self):
        text = ('ТЕЛЕГРАММА\n\nКому: [УТОЧНИТЬ]\n\n1. Представить сведения до 15.10.2026.\n3. Выделить 15 человек '
                'не позднее 31.02.2026.\n2. Доложить до 24.10.2026.')
        issues = pc.check(text, today=date(2026, 10, 22), sources=[('тлг', 'Выделить 12 человек')])
        msgs = ' '.join(m for _, m in issues)
        self.assertIn('Не заполнено', msgs)
        self.assertIn('15.10.2026 уже прошёл', msgs)
        self.assertIn('Такой даты не бывает: 31.02.2026', msgs)
        self.assertIn('субботу', msgs)                       # 24.10.2026 — суббота
        self.assertIn('Нумерация', msgs)
        self.assertIn('подписи', msgs)
        self.assertIn('15', msgs)                            # 15 человек — нет в источнике

    def test_clean_text(self):
        text = ('Начальнику госпиталя\n\n1. Представить сведения до 28.10.2026.\n2. Доложить до 30.10.2026.\n\n'
                'Начальник штаба\nполковник\nП.П. Сидоров')
        self.assertEqual([i for i in pc.check(text, today=date(2026, 10, 22)) if i[0] == 'ошибка'], [])


if __name__ == '__main__':
    unittest.main()
