import unittest
from iskra_formula import build_formula, explain_formula


class Formulas(unittest.TestCase):
    def check(self, request, expected):
        self.assertEqual(build_formula(request)[0], expected, request)

    def test_fills_columns_and_conditions(self):
        self.check('сумма столбца C где в столбце A "Москва"', '=СУММЕСЛИ(A:A;"Москва";C:C)')
        self.check('количество где в B больше 100', '=СЧЁТЕСЛИ(B:B;">100")')
        self.check('среднее по столбцу D если в колонке B равно Готово', '=СРЗНАЧЕСЛИ(B:B;"Готово";D:D)')
        self.check('сумма столбца С', '=СУММ(C:C)')  # русская «С» в имени столбца
        self.check('количество заполненных в столбце F', '=СЧЁТЗ(F:F)')
        self.check('если в A больше 5', '=ЕСЛИ(A2>5;"Да";"Нет")')
        self.check('найти повторы в столбце A', '=ЕСЛИ(СЧЁТЕСЛИ(A:A;A2)>1;"Повтор";"")')

    def test_tells_what_it_assumed(self):
        formula, note = build_formula('сумма по условию')
        self.assertEqual(formula, '=СУММЕСЛИ(B:B;"значение";A:A)')
        self.assertIn('Предположила', note)

    def test_unknown_request(self):
        self.assertIsNone(build_formula('погода')[0])

    def test_explain(self):
        text = explain_formula('=ЕСЛИОШИБКА(ВПР(E2,A:B,2,ЛОЖЬ),"нет")')
        self.assertIn('ВПР — поиск', text)
        self.assertIn('«;»', text)


if __name__ == '__main__':
    unittest.main()
