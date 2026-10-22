import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import iskra_ai as ai
from iskra_ai_server import SERVER

FAKE_SERVER = r'''
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
args = sys.argv[1:]
if os.environ.get('FAKE_SERVER') == 'crash':
    sys.exit(3)
port, key = int(args[args.index('--port') + 1]), args[args.index('--api-key') + 1]
assert args[args.index('--host') + 1] == '127.0.0.1'
assert all(a.isascii() for a in args[args.index('-m'):]), 'русские буквы в командной строке'
time.sleep(0.5)                                     # «загрузка модели»
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def ok(self):
        if self.headers.get('Authorization') != 'Bearer ' + key:
            self.send_response(401); self.end_headers(); return False
        return True
    def do_GET(self):
        if self.ok():
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
    def do_POST(self):
        if not self.ok(): return
        req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
        words = ('pid ' + str(os.getpid()) + ' ' + ('долгий ответ ' * 300 if 'долго' in req['prompt'] else 'Докладываю: готово.')).split(' ')
        for i, w in enumerate(words):
            last = i == len(words) - 1
            self.wfile.write(b'data: ' + json.dumps({'content': w + ('' if last else ' '), 'stop': last}).encode() + b'\n\n')
            self.wfile.flush(); time.sleep(0.01)
ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
'''

FAKE_COMPLETION = 'import sys; sys.stdout.write("обычный способ")'


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp()) / 'Мои документы' / 'Искра'
        (self.base / 'engine').mkdir(parents=True)
        (self.base / 'models').mkdir()
        ext = '.exe' if sys.platform == 'win32' else ''
        (self.base / 'engine' / ('llama-completion' + ext)).write_text(FAKE_COMPLETION, encoding='utf-8')
        (self.base / 'engine' / ('llama-server' + ext)).write_text(FAKE_SERVER, encoding='utf-8')
        (self.base / 'models' / 'Q.gguf').write_bytes(b'GGUF')
        ai.ENGINE_PREFIX = [sys.executable]
        os.environ.pop('FAKE_SERVER', None)
        SERVER.failed_for = None

    def tearDown(self):
        ai.shutdown()
        ai.ENGINE_PREFIX = []

    def test_model_stays_loaded(self):
        first = ai.run('вопрос', base=self.base)
        self.assertIn('Докладываю: готово.', first)
        self.assertEqual(ai.mode(), 'быстрый (модель в памяти)')
        second = ai.run('ещё вопрос', base=self.base)
        self.assertEqual(first.split()[1], second.split()[1])          # тот же процесс — модель не перезагружалась

    def test_stream_and_cancel(self):
        cancel, seen = threading.Event(), []

        def on_text(t):
            seen.append(t)
            if 'долгий' in t:
                cancel.set()
        t = time.time()
        with self.assertRaises(ai.AIError):
            ai.run('долго', base=self.base, on_text=on_text, cancel=cancel)
        self.assertLess(time.time() - t, 5)
        self.assertTrue(any('загружаю' in s for s in seen))
        self.assertIn('Докладываю', ai.run('вопрос', base=self.base))     # после остановки работает дальше

    def test_falls_back_when_server_fails(self):
        os.environ['FAKE_SERVER'] = 'crash'
        self.assertEqual(ai.run('вопрос', base=self.base), 'обычный способ')
        self.assertEqual(ai.mode(), 'обычный')

    def test_rejects_without_key(self):
        import http.client
        ai.warm(self.base)
        conn = http.client.HTTPConnection('127.0.0.1', SERVER.port, timeout=5)
        conn.request('POST', '/completion', body=b'{"prompt":"x"}')
        self.assertEqual(conn.getresponse().status, 401)


if __name__ == '__main__':
    unittest.main()
