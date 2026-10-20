import tempfile
import unittest
from pathlib import Path
from iskra_giga import make_prompt, generate, GigaError

class Tests(unittest.TestCase):
    def test_missing_source(self):
        with self.assertRaises(ValueError):make_prompt('ответ',[])
    def test_no_fabrication_instruction(self):
        p=make_prompt('сводка',[('telegram.docx','Численность: 5')])
        self.assertIn('НЕ НАЙДЕНО',p)
        self.assertIn('telegram.docx',p)
    def test_missing_binary(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(GigaError):generate('ответ',[('a','текст')],base=td)
if __name__=='__main__':unittest.main()
