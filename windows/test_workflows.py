import tempfile
import unittest
from pathlib import Path
from iskra_workflows import compare_texts, normalize_layout, draft_from_sources, save_history, read_history

class WorkflowTests(unittest.TestCase):
    def test_compare(self):
        self.assertIn('+новая строка', compare_texts('старая строка','новая строка'))
        self.assertEqual('Отличий не найдено.',compare_texts('одинаково','одинаково'))
    def test_layout(self):
        self.assertEqual('Первое\n\nВторое', normalize_layout('  Первое   \n\n\n  Второе  '))
    def test_draft(self):
        result=draft_from_sources('Проверка',[('пример.docx','Исходные сведения')])
        self.assertIn('пример.docx',result)
        self.assertIn('[УТОЧНИТЬ]',result)
        self.assertIn('НЕ ЧАСТЬ ТЕЛЕГРАММЫ',result)
    def test_empty_draft(self):
        with self.assertRaises(ValueError):draft_from_sources('Тема',[])
    def test_history(self):
        with tempfile.TemporaryDirectory() as d:
            save_history(d,'Поиск','документ')
            self.assertEqual(read_history(d)[0]['action'],'Поиск')
if __name__=='__main__':unittest.main()
