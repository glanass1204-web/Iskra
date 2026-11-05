"""Несколько шаблонов: свой для каждого вида документа; «напиши рапорт…» — сам берётся шаблон рапорта."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from docx import Document

import iskra_ai as ai
import iskra_forms as forms

TMP = Path(tempfile.mkdtemp())


def template(name, lines):
    d = Document()
    for line in lines:
        d.add_paragraph(line)
    d.save(TMP / name)
    return str(TMP / name)


class Choose(unittest.TestCase):
    def setUp(self):
        self.old = dict(ai.TEMPLATES), ai.TELEGRAM_TEMPLATE
        self.tlg = template('тлг.docx', ['ТЕЛЕГРАММА', 'Командирам подразделений',
                                         'Во исполнение указаний штаба округа и в целях поддержания готовности ПРИКАЗЫВАЮ '
                                         'провести проверку подразделений в установленный срок.', 'Начальник штаба',
                                         'полковник П.П. Сидоров'])
        self.rap = template('рапорт.docx', ['Командиру войсковой части 12345', 'РАПОРТ',
                                            'Прошу Вашего ходатайства о предоставлении мне основного отпуска за текущий год '
                                            'с выездом в город Тверь.', 'капитан И.И. Иванов'])
        self.spr = template('справка.docx', ['СПРАВКА-ДОКЛАД', 'Текст.'])
        ai.TEMPLATES = {'Телеграмма': self.tlg, 'Рапорт': self.rap, 'Справка-доклад': self.spr}

    def tearDown(self):
        ai.TEMPLATES, ai.TELEGRAM_TEMPLATE = self.old

    def test_kind_and_template_by_task(self):
        self.assertEqual(ai.template_for('напиши рапорт на отпуск'), self.rap)
        self.assertEqual(ai.template_for('составь указание командирам о проверке техники'), self.tlg)   # указание — по тлг
        self.assertEqual(ai.template_for('подготовь справку-доклад о технике'), self.spr)               # свой вид
        self.assertIsNone(ai.template_for('подготовь отпускной билет'))       # своего бланка нет — стандартный

    def test_write_uses_kind_template(self):
        prompts = []
        old = ai.run
        ai.run = lambda prompt, **kw: prompts.append(prompt) or 'Командиру войсковой части 12345\nРАПОРТ\nПрошу предоставить отпуск.'
        try:
            out, _ = ai.write('напиши рапорт на отпуск', [])
            first = prompts[0]
            self.assertIn('Прошу Вашего ходатайства', first)          # образец текста — из шаблона рапорта
            self.assertNotIn('Командиру войсковой части 12345', first)  # шапку нейросеть не переписывает
            self.assertNotIn('РАПОРТ', out)                           # только текст — шапка встанет из шаблона
            prompts.clear()
            ai.write('напиши телеграмму командирам о проверке', [])
            self.assertIn('Во исполнение указаний штаба округа', prompts[0])
            self.assertNotIn('Сидоров', prompts[0])
        finally:
            ai.run = old
        self.assertEqual(ai.TELEGRAM_TEMPLATE, self.old[1])         # после работы — как было

    def test_combat_order_not_written(self):
        with self.assertRaises(ai.AIError):
            ai.write('напиши боевое распоряжение', [])


class BodyIntoTemplate(unittest.TestCase):
    def test_body_goes_between_header_and_signature(self):
        """Жалоба «шаблоны не работают»: раньше шапка и подпись шаблона без меток пропадали. Теперь текст
        встаёт между ними, оформление — как у текста шаблона."""
        import iskra_telegram as tg
        from docx.shared import Pt
        d = Document()
        d.add_paragraph('ТЕЛЕГРАММА')
        d.add_paragraph('Командирам подразделений')
        p = d.add_paragraph(); r = p.add_run('Во исполнение указаний штаба округа ПРИКАЗЫВАЮ провести проверку '
                                              'подразделений в установленный срок и доложить.')
        r.font.size = Pt(13); r.font.name = 'Times New Roman'
        d.add_paragraph('1. Старый пункт шаблона.')
        d.add_paragraph('Начальник штаба')
        d.add_paragraph('полковник П.П. Сидоров')
        d.save(TMP / 'тлг_без_меток.docx')
        out = TMP / 'тлг_итог.docx'
        tg.save_docx('В целях повышения живучести ПУ ПРИКАЗЫВАЮ:\n1. Провести маскировку.\n2. Доложить.', str(out),
                     str(TMP / 'тлг_без_меток.docx'))
        res = Document(str(out)).paragraphs
        self.assertEqual([p.text for p in res], ['ТЕЛЕГРАММА', 'Командирам подразделений',
                                                 'В целях повышения живучести ПУ ПРИКАЗЫВАЮ:', '1. Провести маскировку.',
                                                 '2. Доложить.', 'Начальник штаба', 'полковник П.П. Сидоров'])
        self.assertEqual(res[3].runs[0].font.size, Pt(13))       # вид текста — как в шаблоне

    def test_filled_full_blank_not_doubled(self):
        """Бланк открыт по шаблону и заполнен целиком — шапка не должна задвоиться."""
        import iskra_telegram as tg
        tpl = template('бланк.docx', ['БОЕВОЕ РАСПОРЯЖЕНИЕ № ___', 'Штаб', 'Текст.', 'Начальник штаба', 'полковник П.П. Сидоров'])
        out = TMP / 'бланк_итог.docx'
        tg.save_docx('БОЕВОЕ РАСПОРЯЖЕНИЕ № ___\nШтаб\nСвой текст человека.\nНачальник штаба\nполковник П.П. Сидоров',
                     str(out), tpl)
        texts = [p.text for p in Document(str(out)).paragraphs]
        self.assertEqual(texts.count('БОЕВОЕ РАСПОРЯЖЕНИЕ № ___'), 1)
        self.assertIn('Свой текст человека.', texts)


class LeaveTicket(unittest.TestCase):
    def test_own_blank_with_labels(self):
        blank = template('отпускной.docx', ['{Штамп}', 'ОТПУСКНОЙ БИЛЕТ', '{ФИО} убыл {Вид отпуска}',
                                             'сроком на {Сроком на} с {С} по {По}', 'Командир {Командир}'])
        f = {'stamp': 'в/ч 12345', 'who': 'капитан Иванов Иван Иванович', 'kind_place': 'в основной отпуск в г. Тверь',
             'days': '15', 'start': date(2026, 11, 1), 'end': date(2026, 11, 15), 'commander': 'полковник Петров'}
        out = TMP / 'билет.docx'
        forms.save_leave_ticket(f, out, blank)
        text = [p.text for p in Document(str(out)).paragraphs]
        self.assertEqual(text[0], 'в/ч 12345')
        self.assertEqual(text[2], 'капитан Иванов Иван Иванович убыл в основной отпуск в г. Тверь')
        self.assertEqual(text[3], 'сроком на пятнадцать суток с "01" ноября 2026 г. по "15" ноября 2026 г.')
        self.assertNotIn('{', ' '.join(text))


if __name__ == '__main__':
    unittest.main()
