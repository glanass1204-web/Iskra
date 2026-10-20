import stat
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from iskra_giga import make_prompt, generate, local_files, GigaError, MAX_SOURCE_CHARS


def fake_engine(base, name, body):
    """Stand-in for llama.cpp: a script that reads the prompt file passed with -f."""
    engine = Path(base) / 'engine'
    engine.mkdir(exist_ok=True)
    (Path(base) / 'models').mkdir(exist_ok=True)
    (Path(base) / 'models' / 'giga-q4_K_M.gguf').write_bytes(b'')
    if sys.platform == 'win32':
        script = engine / (name + '.py')
        script.write_text(body, encoding='utf-8')
        exe = engine / (name + '.cmd')
        exe.write_text(f'@"{sys.executable}" "{script}" %*', encoding='utf-8')
        return exe
    exe = engine / name
    exe.write_text(f'#!{sys.executable}\n' + body, encoding='utf-8')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


ECHO = textwrap.dedent('''
    import sys
    args = sys.argv[1:]
    assert '-p' not in args, 'запрос не должен идти через командную строку'
    prompt = open(args[args.index('-f') + 1], encoding='utf-8').read()
    print('Проект: ' + ('НЕ НАЙДЕНО' if 'Численность' not in prompt else 'Численность 5') + ' [end of text]')
''')


class Tests(unittest.TestCase):
    def test_missing_source(self):
        with self.assertRaises(ValueError):
            make_prompt('ответ', [])

    def test_no_fabrication_instruction(self):
        p, truncated = make_prompt('сводка', [('telegram.docx', 'Численность: 5')])
        self.assertIn('НЕ НАЙДЕНО', p)
        self.assertIn('telegram.docx', p)
        self.assertEqual(truncated, [])

    def test_reports_truncated_sources(self):
        _, truncated = make_prompt('сводка', [('big.docx', 'я' * (MAX_SOURCE_CHARS + 5)), ('small.docx', 'текст')])
        self.assertEqual(truncated, ['big.docx', 'small.docx'])

    def test_missing_binary(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(GigaError):
                generate('ответ', [('a', 'текст')], base=td)

    @unittest.skipIf(sys.platform == 'win32', 'фиктивный движок собран как скрипт для Linux/macOS')
    def test_runs_engine_with_prompt_file(self):
        with tempfile.TemporaryDirectory() as td:
            fake_engine(td, 'llama-completion', ECHO)
            answer, _ = generate('сводка', [('a.docx', 'Численность: 5')], base=td)
            self.assertEqual(answer, 'Проект: Численность 5')
            self.assertEqual([p.name for p in Path(tempfile.gettempdir()).glob('iskra_*/prompt.txt')], [])

    @unittest.skipIf(sys.platform == 'win32', 'фиктивный движок собран как скрипт для Linux/macOS')
    def test_prefers_completion_over_chat_cli(self):
        with tempfile.TemporaryDirectory() as td:
            fake_engine(td, 'llama-cli', ECHO)
            self.assertEqual(local_files(td)[0].name, 'llama-cli')
            fake_engine(td, 'llama-completion', ECHO)
            self.assertEqual(local_files(td)[0].name, 'llama-completion')

    def test_cuts_runaway_generation(self):
        from iskra_giga import clean_answer
        raw = (' Срок — до 25 октября, исполнитель Иванов (приказ. txt).\n\nРЕЗУЛЬТАТ: повтор\n'
               'ЗАДАЧА: Какая информация\nИСТОЧНИКИ:\n')
        self.assertEqual(clean_answer(raw), 'Срок — до 25 октября, исполнитель Иванов (приказ.txt).')

    @unittest.skipIf(sys.platform == 'win32', 'фиктивный движок собран как скрипт для Linux/macOS')
    def test_stops_engine_once_answer_is_done(self):
        rambling = 'import sys, time\nprint("Ответ готов.\\nЗАДАЧА: ещё", flush=True)\ntime.sleep(30)\n'
        with tempfile.TemporaryDirectory() as td:
            fake_engine(td, 'llama-completion', rambling)
            started = __import__('time').monotonic()
            answer, _ = generate('сводка', [('a', 'текст')], base=td)
            self.assertEqual(answer, 'Ответ готов.')
            self.assertLess(__import__('time').monotonic() - started, 10)

    @unittest.skipIf(sys.platform == 'win32', 'фиктивный движок собран как скрипт для Linux/macOS')
    def test_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as td:
            fake_engine(td, 'llama-completion', 'import time\ntime.sleep(30)\n')
            cancel = threading.Event()
            threading.Timer(0.5, cancel.set).start()
            with self.assertRaisesRegex(GigaError, 'остановлена'):
                generate('сводка', [('a', 'текст')], base=td, cancel=cancel)


if __name__ == '__main__':
    unittest.main()
