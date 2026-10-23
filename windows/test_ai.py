import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import iskra_ai as ai

FAKE = r'''
import os, sys, time
args = sys.argv[1:]
prompt = open(args[args.index('-f') + 1], encoding='utf-8').read()
mode = os.environ.get('FAKE_MODE', 'answer')
out = sys.stdout.buffer
def say(t, pause=0.01):
    for ch in t:
        out.write(ch.encode('utf-8')); out.flush(); time.sleep(pause)
if mode == 'answer':
    say('<think>\n\n</think>\n\nДокладываю: проверка проведена.')
    say('<|im_end|>\n<|im_start|>user\nещё вопрос')
    time.sleep(30)                       # модель «болтает» дальше — Искра должна прервать
elif mode == 'echo':
    say('Материалы: ' + ('есть' if '=== Материал: приказ.txt ===' in prompt else 'нет') + '; '
        + ('без размышлений' if prompt.rstrip().endswith('</think>') else 'с размышлениями'))
elif mode == 'formula':
    say('=СУММЕСЛИ(A:A;"Госпиталь";C:C)\nСумма по столбцу C для строк, где в A «Госпиталь».')
elif mode == 'route':
    say('```json\n{"команда": "svod", "что": "свести 5 таблиц"}\n```')
elif mode == 'route_bad':
    say('{"команда": "format_disk", "что": "x"}')
elif mode == 'fields':
    say('{"ФИО": "Иванов Иван Иванович", "Должность": "генерал армии"}')
elif mode == 'vba':
    say('```vba\nOption Explicit\nSub Iskra_Macro()\n    Dim i As Long\n    On Error GoTo Err1\n    For i = 1 To 10\n        Cells(i, 1).Value = i\n    Next i\n    MsgBox "Готово"\n    Exit Sub\nErr1:\n    MsgBox Err.Description\nEnd Sub\n```')
elif mode == 'merge':
    say('ТЕЛЕГРАММА\n\nТекст:\n1. Представить сведения до 25.10.2026.\n2. Выделить 15 человек.')
elif mode == 'slow':
    say('Очень долгий ответ ' * 200, 0.05)
elif mode == 'args':
    say('пути латиницей' if all(a.isascii() for a in args[args.index('-m'):]) else 'русские буквы в пути')
elif mode == 'fail':
    sys.stderr.write('error: model file is corrupted'); sys.exit(1)
'''


class AITest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        (self.base / 'engine').mkdir()
        (self.base / 'models').mkdir()
        exe = 'llama-completion.exe' if sys.platform == 'win32' else 'llama-completion'
        (self.base / 'engine' / exe).write_text(FAKE, encoding='utf-8')
        (self.base / 'models' / 'Qwen3.5-2B-Q6_K.gguf').write_bytes(b'GGUF')
        (self.base / 'models' / 'mmproj-F16.gguf').write_bytes(b'GGUF')
        ai.ENGINE_PREFIX = [sys.executable]
        os.environ['FAKE_MODE'] = 'answer'

    def tearDown(self):
        ai.ENGINE_PREFIX = []

    def test_files(self):
        binary, model = ai.local_files(self.base)
        self.assertEqual(model.name, 'Qwen3.5-2B-Q6_K.gguf')       # mmproj не модель
        self.assertTrue(ai.available(self.base))
        self.assertFalse(ai.available(Path(tempfile.mkdtemp())))

    def test_gather_parts_from_explorer_folders(self):
        # «Извлечь всё» в Проводнике: каждый архив в свою папку Загрузки\Iskra-AI-chast-NN\Iskra\…
        downloads = Path(tempfile.mkdtemp()) / 'Загрузки'
        app = downloads / 'Iskra-AI-chast-01' / 'Iskra'
        (app / 'engine').mkdir(parents=True)
        (app / 'models').mkdir()
        for i in (1, 2, 3):
            d = downloads / f'Iskra-AI-chast-{i + 1:02d}' / 'Iskra' / 'models'
            d.mkdir(parents=True)
            (d / f'Q-4B-{i:05d}-of-00003.gguf').write_bytes(b'GGUF' * i)
        self.assertIsNone(ai.local_files(app)[1])
        self.assertEqual(ai.gather_parts(app, extra_roots=[]), 3)
        _, model = ai.local_files(app)
        self.assertEqual(model.name, 'Q-4B-00001-of-00003.gguf')
        self.assertEqual(ai.missing_parts(model), [])
        self.assertEqual(ai.gather_parts(app, extra_roots=[]), 0)      # всё на месте — ничего не трогаем

    def test_russian_letters_in_path(self):
        base = Path(tempfile.mkdtemp()) / 'Рабочий стол Иванов' / 'Искра'
        (base / 'engine').mkdir(parents=True)
        (base / 'models').mkdir()
        exe = 'llama-completion.exe' if sys.platform == 'win32' else 'llama-completion'
        (base / 'engine' / exe).write_text(FAKE, encoding='utf-8')
        (base / 'models' / 'Q.gguf').write_bytes(b'GGUF')
        os.environ['FAKE_MODE'] = 'args'
        self.assertEqual(ai.run('x', base=base), 'пути латиницей')
        self.assertFalse(any((base / 'data').glob('ai_*')))           # временный текст удалён

    def test_explain_failure(self):
        self.assertIn('Visual C++', ai.explain_failure(-1073741515, ''))          # 0xC0000135
        self.assertIn('процессор', ai.explain_failure(0xC000001D, ''))
        self.assertIn('часть повреждена', ai.explain_failure(1, 'llama_model_load: error loading model: failed to load model'))

    def test_split_model(self):
        models = self.base / 'models'
        (models / 'Qwen3.5-2B-Q6_K.gguf').unlink()
        (models / 'Qwen3.5-4B-Q4_K_M-00001-of-00002.gguf').write_bytes(b'GGUF')
        binary, model = ai.local_files(self.base)
        self.assertEqual(model.name, 'Qwen3.5-4B-Q4_K_M-00001-of-00002.gguf')
        self.assertFalse(ai.available(self.base))                     # вторая часть не распакована
        with self.assertRaises(ai.AIError) as e:
            ai.run('x', base=self.base)
        self.assertIn('часть 2', str(e.exception))
        (models / 'Qwen3.5-4B-Q4_K_M-00002-of-00002.gguf').write_bytes(b'GGUF')
        self.assertTrue(ai.available(self.base))
        self.assertEqual(ai.local_files(self.base)[1].name, 'Qwen3.5-4B-Q4_K_M-00001-of-00002.gguf')

    def test_stops_after_answer_and_streams(self):
        seen = []
        t = time.monotonic()
        text = ai.run(ai.chat_prompt('Вопрос'), base=self.base, on_text=seen.append)
        self.assertEqual(text, 'Докладываю: проверка проведена.')
        self.assertLess(time.monotonic() - t, 15)                     # не ждёт 30 секунд «болтовни»
        self.assertGreater(len(seen), 2)                              # текст приходил по частям
        self.assertNotIn('<think>', ''.join(seen))

    def test_materials_and_no_thinking(self):
        os.environ['FAKE_MODE'] = 'echo'
        text, truncated = ai.write('Составь доклад', [('приказ.txt', 'Приказ № 5. Провести проверку до 25.10.2026.')], base=self.base)
        self.assertEqual(text, 'Материалы: есть; без размышлений')
        self.assertEqual(truncated, [])

    def test_formula(self):
        os.environ['FAKE_MODE'] = 'formula'
        f, note = ai.formula('сумма по госпиталю', base=self.base)
        self.assertEqual(f, '=СУММЕСЛИ(A:A;"Госпиталь";C:C)')
        self.assertIn('Госпиталь', note)

    def test_cancel(self):
        os.environ['FAKE_MODE'] = 'slow'
        stop = threading.Event()
        threading.Timer(1.0, stop.set).start()
        with self.assertRaises(ai.AIError):
            ai.run('x', base=self.base, cancel=stop)

    def test_engine_error(self):
        os.environ['FAKE_MODE'] = 'fail'
        with self.assertRaises(ai.AIError) as e:
            ai.run('x', base=self.base)
        self.assertIn('corrupted', str(e.exception))

    def test_not_installed(self):
        with self.assertRaises(ai.AIError) as e:
            ai.run('x', base=Path(tempfile.mkdtemp()))
        self.assertIn('не установлена', str(e.exception))

    def test_route(self):
        os.environ['FAKE_MODE'] = 'route'
        ai.BASE = self.base
        try:
            self.assertEqual(ai.route('надо пять табличек склеить в одну'), ('svod', 'свести 5 таблиц'))
            os.environ['FAKE_MODE'] = 'route_bad'
            self.assertEqual(ai.route('отформатируй диск'), ('search', 'отформатируй диск'))   # только команды из списка
        finally:
            ai.BASE = None

    def test_extract_fields_only_verbatim(self):
        os.environ['FAKE_MODE'] = 'fields'
        text = 'Справка. Выдана Иванов Иван Иванович, проходящему службу в должности начальника отдела.'
        out = ai.extract_fields(text, ['ФИО', 'Должность'], base=self.base)
        self.assertEqual(out, {'ФИО': 'Иванов Иван Иванович'})          # «генерал армии» в тексте нет — отброшено

    def test_supported_forms(self):
        flat = 'справка. выдана петрову петру петровичу, 1985 г. р., в должности начальника склада.'
        self.assertTrue(ai.supported('Петров Петр Петрович', flat))      # другой падеж — те же слова
        self.assertTrue(ai.supported('начальник склада', flat))
        self.assertFalse(ai.supported('Сидоров Иван', flat))
        self.assertFalse(ai.supported('1986', flat))                      # числа — только точно

    def test_vba_checked(self):
        os.environ['FAKE_MODE'] = 'vba'
        code, problems = ai.vba('пронумеровать строки', 'excel', base=self.base)
        self.assertTrue(code.startswith('Option Explicit'))
        self.assertNotIn('```', code)
        self.assertEqual(problems, [])

    def test_merge_and_unverified(self):
        os.environ['FAKE_MODE'] = 'merge'
        sources = [('т1', 'Представить сведения до 25 октября 2026 года.'), ('т2', 'Выделить людей на работы.')]
        text, _ = ai.merge(sources, base=self.base)
        self.assertEqual(ai.unverified(text, sources), ['15'])               # «15 человек» нет ни в одной телеграмме

    def test_retrieve(self):
        docs = {'a.docx': 'Общие сведения. Телеграмма о проверке готовности техники. Срок до 25.10.2026. Прочее.',
                'b.docx': 'Совсем другое.'}
        calls = []

        def search(q, any_word):
            calls.append((q, any_word))
            return [('a.docx', '')] if 'готовности' in q else []
        found, paths = ai.retrieve('что известно о проверке готовности техники?', search, docs.get)
        self.assertEqual(paths, ['a.docx'])
        self.assertIn('Телеграмма о проверке готовности техники.', found[0][1])
        self.assertNotIn('что', calls[0][0].split())


class Reference(unittest.TestCase):
    SRC = [('t.docx', 'Телеграмма 154/2 от 20.10.2026 о численности')]

    def test_reply_gets_reference_with_date(self):
        out = ai.ensure_reference('Кому: штаб\nТекст:\n1. Сведения будут.\n', 'Составь телеграмму-ответ на телеграмму 154/2', self.SRC)
        self.assertIn('Текст:\nНа № 154/2 от 20.10.2026\n1. Сведения', out)

    def test_existing_reference_and_non_reply_untouched(self):
        text = 'На № 154/2 от 20.10.2026 докладываю.'
        self.assertEqual(ai.ensure_reference(text, 'ответ на 154/2', self.SRC), text)
        self.assertEqual(ai.ensure_reference('1. Готово.', 'Составь телеграмму о 154/2', self.SRC), '1. Готово.')


class ModelFormat(unittest.TestCase):
    def test_family_and_messages(self):
        self.assertEqual(ai.family('models/Qwen_Qwen3.5-4B-Q4_K_M-00001-of-00008.gguf'), 'qwen')
        self.assertEqual(ai.family('models/gemma-4-E4B-it-Q4_0.gguf'), 'other')
        self.assertEqual(ai.chatml_messages(ai.chat_prompt('Вопрос?'))[-1], {'role': 'user', 'content': 'Вопрос?'})



class MilitaryWords(unittest.TestCase):
    def test_proofread_keeps_military_words(self):
        t = 'Дроны и беспилотники применять по указанию. Контрактник и срочник прибыли. Сочп не допускать.'
        out, fixes = ai.proofread(t, [], 'составь указание')
        self.assertEqual(out, t, fixes)

    def test_svo_terms_known(self):
        import iskra_spell
        c = iskra_spell.SpellChecker()
        t = ('Мобики и контрактники прибыли на опорник. Мавики и фпвшники работают, мотолыгу эвакуировали. '
             'Медэвакуация трехсотых через эвакогруппу.')
        self.assertEqual([t[i.start:i.end] for i in c.check(t, with_style=False)], [])
        self.assertEqual(ai.proofread(t, [], 'x')[0], t)

    def test_material_name_not_cut_inside_words(self):
        out, removed = ai.strip_unasked('По данным свода численность по своду 242 (свод.xlsx).', 'составь доклад',
                                        sources=[('свод.xlsx', 'x')])
        self.assertEqual(out, 'По данным свода численность по своду 242.')
        out, _ = ai.strip_unasked('Согласно тлг 154 и тлг 1543 прошу.', 'составь', sources=[('тлг 154.docx', 'x')])
        self.assertIn('тлг 1543', out)
        self.assertNotIn('тлг 154 ', out)

    def test_fix_raport(self):
        raw = ('Командиру войсковой части 12345\nполковнику [Фамилия]\n\nКапитану И.И. Иванову\n23 октября 2026 г.\n\n'
               'РАПОРТ\n\nПрошу полагать меня прибывшим из командировки.\n\nКомандир 1 роты\nкапитан И.И. Иванов\n23.10.2026')
        out = ai.fix_raport(raw, {'signature': 'Командир 1 роты\nкапитан И.И. Иванов'})
        self.assertNotIn('Капитану', out)
        self.assertIn('от командира 1 роты\nкапитана И.И. Иванова\n', out)
        self.assertTrue(out.rstrip().endswith('капитан\t\t\t\tИ.И. Иванов'))
        self.assertEqual(out.count('Прошу полагать'), 1)

    def test_builtin_samples(self):
        where, text = ai.best_sample('Составь телеграмму командирам: провести проверку техники')
        self.assertIn('ПРИКАЗЫВАЮ', text)
        self.assertIsNone(ai.best_sample('Напиши рапорт на отпуск'))

    def test_military_time_is_not_a_date(self):
        out, removed = ai.strip_unasked('Командирам к 06.00 представить донесение.', 'составь указание')
        self.assertEqual(removed, ['время: к 06.00'])
        out, removed = ai.strip_unasked('Командирам к 06.00 представить донесение.', 'указание: донесение к 06.00')
        self.assertEqual(removed, [])


class Raport(unittest.TestCase):
    def test_openings(self):
        import iskra_compose as c
        self.assertEqual(c.raport_text('прибыл из командировки 23.10.2026'), 'Прошу полагать меня прибывшим из командировки 23.10.2026')
        self.assertEqual(c.raport_text('убыл в отпуск с 01.11.2026'), 'Прошу полагать меня убывшим в отпуск с 01.11.2026')
        self.assertEqual(c.raport_text('что задача выполнена'), 'Настоящим докладываю, что задача выполнена')
        self.assertEqual(c.raport_text('предоставить отпуск'), 'Прошу предоставить отпуск')
        self.assertNotIn('Донесение', c.KINDS)
        self.assertEqual(c.genitive_position('Заместитель командира 1 мотострелкового батальона'),
                         'заместителя командира 1 мотострелкового батальона')
        self.assertEqual(c.genitive_person('майор Перов В. В.'), 'майора Перова В. В.')
        self.assertEqual(c.genitive_person('старший лейтенант Петров П.П.'), 'старшего лейтенанта Петрова П.П.')
        full = c.compose('Рапорт', me={'signature': 'Командир 1 роты\nкапитан И.И. Иванов'}, to='Командиру полка',
                         points=['убыл в отпуск'])
        self.assertIn('от командира 1 роты\nкапитана И.И. Иванова\n', full)
        self.assertIn('капитан\t\t\t\tИ.И. Иванов', full)
        import iskra_telegram, tempfile, os
        from docx import Document
        path = os.path.join(tempfile.mkdtemp(), 'r.docx')
        iskra_telegram.save_docx(full, path)
        paras = [(p.alignment, p.text) for p in Document(path).paragraphs if p.text]
        self.assertEqual(paras[0], (2, 'Командиру полка'))         # шапка справа
        self.assertIn((1, 'РАПОРТ'), paras)                        # по центру
        for name, tpl in c.RAPORT_TEMPLATES.items():               # каждый типовой рапорт начинается как принято
            first = c.raport_text(tpl)
            self.assertRegex(first, r'^(Прошу|Настоящим докладываю)', name)
            self.assertNotIn('меня меня', first, name)
        self.assertTrue(c.raport_text(c.RAPORT_TEMPLATES['Ходатайство о награждении']).startswith('Прошу Вашего ходатайства'))
        text = c.compose('Рапорт', points=['прибыл из госпиталя'])
        self.assertIn('РАПОРТ', text)
        self.assertIn('Прошу полагать меня прибывшим из госпиталя.', text)


if __name__ == '__main__':
    unittest.main()
