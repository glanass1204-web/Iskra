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
elif mode == 'slow':
    say('Очень долгий ответ ' * 200, 0.05)
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


if __name__ == '__main__':
    unittest.main()
