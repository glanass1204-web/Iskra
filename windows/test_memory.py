import os
import tempfile
import unittest

os.environ['ISKRA_DATA_DIR'] = tempfile.mkdtemp()

import iskra_memory as M  # noqa: E402

TECH = ('ТЕЛЕГРАММА\n\nКому: Командиру войсковой части 12345\n\nТекст:\nВо исполнение указания № 15/3 от 01.10.2026 '
        'прошу представить сведения о наличии и техническом состоянии автомобильной техники до 10.10.2026.\n\n'
        'Подпись:\nНачальник штаба\nполковник И.И. Иванов')
FOOD = ('ТЕЛЕГРАММА\n\nКому: Начальнику продовольственной службы\n\nТекст:\nПрошу организовать доставку '
        'продовольствия и питьевой воды на полигон к 05.10.2026.\n\nПодпись:\nНачальник штаба')


class Sent(unittest.TestCase):
    def setUp(self):
        M.forget('sent')

    def test_remembers_and_finds_similar(self):
        self.assertTrue(M.remember_sent(TECH + '\n\n--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---\n1. x.docx', 'C:/a/t.docx'))
        self.assertTrue(M.remember_sent(FOOD))
        self.assertFalse(M.remember_sent('ТЕЛЕГРАММА\nКому: [УТОЧНИТЬ]'))          # пустой бланк — не образец
        self.assertEqual(M.stats()['sent'], 2)
        found = M.similar_sent('телеграмма: запросить сведения о техническом состоянии автомобильной техники')
        self.assertIn('техническом', found[0][1]['text'])
        self.assertEqual(M.similar_sent('отпуск сотрудников бухгалтерии'), [])

    def test_last_time_uses_addressee_and_masks_facts(self):
        M.remember_sent(TECH)
        M.remember_sent(FOOD)
        block = M.prompt_block('телеграмма командиру в/ч 12345 как в прошлый раз, срок 30.10.2026')
        self.assertIn('как в прошлый раз', block)
        self.assertIn('Командиру войсковой части 12345', block)            # адресат сохранён
        self.assertNotIn('01.10.2026', block)
        self.assertNotIn('15/3', block)
        self.assertIn('[ДАТА]', block)
        self.assertIn('НЕ переносить', M.prompt_block('сведения о техническом состоянии автомобильной техники'))

    def test_duplicate_saved_once(self):
        M.remember_sent(TECH); M.remember_sent(TECH)
        self.assertEqual(M.stats()['sent'], 1)


class Search(unittest.TestCase):
    def setUp(self):
        M.forget('search')

    def test_opened_documents_rise(self):
        rows = [('a.docx', ''), ('b.docx', ''), ('отчёт техника.docx', ''), ('d.docx', '')]
        self.assertEqual(M.rerank('техника', rows), (rows, 0))
        M.opened('техника', 'отчёт техника.docx')
        new, raised = M.rerank('Техника отчёт', rows)
        self.assertEqual(raised, 1)
        self.assertEqual(new[0][0], 'отчёт техника.docx')
        self.assertEqual([r[0] for r in new[1:]], ['a.docx', 'b.docx', 'd.docx'])   # остальной порядок прежний
        self.assertEqual(M.rerank('продовольствие', rows)[1], 0)                      # другие слова — без изменений


if __name__ == '__main__':
    unittest.main()
