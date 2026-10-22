import os
import tempfile
import unittest

os.environ['ISKRA_DATA_DIR'] = tempfile.mkdtemp()

import iskra_learn as L  # noqa: E402

AI1 = ('ТЕЛЕГРАММА\n\nКому: Командиру в/ч 12345\n\nТекст:\nПрошу в кратчайшие сроки представить сведения о '
       'наличии техники до 25.10.2026.\n\nПодпись:\nНачальник штаба')
FIN1 = ('ТЕЛЕГРАММА\n\nКому: Командиру в/ч 12345\n\nТекст:\nТребую представить сведения о '
        'наличии техники до 27.10.2026.\n\nПодпись:\nНачальник штаба')
AI2 = 'Прошу в кратчайшие сроки доложить о выполнении мероприятий по № 15/3 от 01.10.2026. Ответственный — Петров.'
FIN2 = 'Требую доложить о выполнении мероприятий по № 15/3 от 01.10.2026. Ответственный — Петров.'


class Learn(unittest.TestCase):
    def setUp(self):
        L.forget()

    def test_learns_repeated_edits_and_masks_facts(self):
        self.assertTrue(L.remember(AI1, FIN1 + '\n\n--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---\n1. a.docx'))
        self.assertEqual(L.rules(), [])                       # одна правка — ещё не привычка
        self.assertTrue(L.remember(AI2, FIN2))
        rules = L.rules()
        self.assertIn('вместо «прошу в кратчайшие сроки» пишите «требую»', rules)
        block = L.prompt_block()
        self.assertIn('НЕ переносить', block)
        self.assertNotIn('01.10.2026', block)                  # старые даты и номера замаскированы
        self.assertNotIn('15/3', block)
        self.assertNotIn('ИСТОЧНИКИ', block)

    def test_ignores_no_edit_rewrite_and_fact_only(self):
        self.assertFalse(L.remember(AI1, AI1))
        self.assertFalse(L.remember(AI1, 'Совсем другой документ про отпуск и командировку сотрудников отдела.'))
        self.assertFalse(L.remember(AI1, AI1.replace('25.10.2026', '28.10.2026')))   # поменяли только срок
        self.assertEqual(L.count(), 0)
        self.assertEqual(L.prompt_block(), '')

    def test_same_document_saved_twice_is_one_pair(self):
        L.remember(AI1, FIN1)
        L.remember(AI1, FIN1.replace('Начальник штаба', 'Начальник штаба полковник'))
        self.assertEqual(L.count(), 1)

    def test_forget(self):
        L.remember(AI1, FIN1)
        L.forget()
        self.assertEqual(L.count(), 0)


if __name__ == '__main__':
    unittest.main()
