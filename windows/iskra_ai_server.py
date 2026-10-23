"""Быстрый режим нейросети: модель загружается один раз и остаётся в памяти, пока Искра открыта.
Движок (llama-server) слушает только адрес 127.0.0.1 этого компьютера — снаружи к нему не подключиться,
а без ключа, известного только Искре, он не отвечает и местным программам. Интернет не нужен и не используется.
После 20 минут без работы модель выгружается, чтобы не занимать память; следующий вопрос загрузит её снова."""
import http.client
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

IDLE_SECONDS = 20 * 60
LOAD_TIMEOUT = 300


class ServerError(RuntimeError):
    """Быстрый режим не поднялся — Искра отвечает обычным способом (запуск модели на каждый вопрос)."""


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _job_kill_on_close(proc):
    """Windows: движок закрывается вместе с Искрой, даже если она завершилась аварийно."""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        job = k32.CreateJobObjectW(None, None)

        class LIMIT(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]

        class EXT(ctypes.Structure):
            _fields_ = [('Basic', LIMIT), ('Io', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]
        info = EXT()
        info.Basic.LimitFlags = 0x2000                     # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle))
        return job                                         # держим ссылку: закрытие = завершение движка
    except Exception:
        return None


class Server:
    def __init__(self):
        self.proc = None
        self.port = None
        self.key = None
        self.model = None
        self.job = None
        self.last_used = 0.0
        self.failed_for = None          # модель, на которой быстрый режим не поднялся — второй раз не пробуем
        self.lock = threading.Lock()
        self._watch = None
        self.last_cut = False           # последний ответ упёрся в предел длины
        self.loading = False            # модель грузится в память

    # ---------- запуск ----------

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def ensure(self, prefix, binary, model, home, context, cancel=None, on_text=None, log=None):
        with self.lock:
            if self.alive() and self.model == model:
                return
            self.stop()
            if self.failed_for == model:
                raise ServerError('быстрый режим уже не запустился')
            self.port, self.key, self.model = _free_port(), secrets.token_hex(16), model
            try:
                rel = str(Path(model).relative_to(home))
            except ValueError:
                rel = str(model)
            command = prefix + [str(binary), '-m', rel, '-c', str(context), '--host', '127.0.0.1',
                                '--port', str(self.port), '--api-key', self.key, '-ngl', '0', '-np', '1']
            if log:
                Path(log).parent.mkdir(parents=True, exist_ok=True)
            out = open(log, 'ab') if log else subprocess.DEVNULL
            try:
                self.proc = subprocess.Popen(command, stdout=out, stderr=out, stdin=subprocess.DEVNULL, cwd=str(home),
                                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError as exc:
                self.failed_for = model
                raise ServerError(str(exc)) from exc
            finally:
                if log:
                    out.close()
            self.job = _job_kill_on_close(self.proc)
            if on_text:
                on_text('… загружаю нейросеть в память (один раз за сеанс, до минуты)')
            started = time.monotonic()
            self.loading = True
            try:
                self._wait_loaded(model, cancel, started)
            finally:
                self.loading = False
            self.last_used = time.monotonic()
            if self._watch is None:
                self._watch = threading.Thread(target=self._idle_watch, daemon=True)
                self._watch.start()

    def _wait_loaded(self, model, cancel, started):
        """Ждать, пока движок загрузит модель и ответит на /health."""
        while True:
            if self.proc.poll() is not None:
                self.proc, self.failed_for = None, model
                raise ServerError('движок закрылся при загрузке')
            if cancel is not None and cancel.is_set():
                self.stop()
                raise ServerError('остановлено')
            if self._health():
                break
            if time.monotonic() - started > LOAD_TIMEOUT:
                self.stop()
                self.failed_for = model
                raise ServerError('модель не загрузилась за 5 минут')
            time.sleep(0.5)

    def _health(self):
        try:
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
            conn.request('GET', '/health', headers={'Authorization': 'Bearer ' + self.key})
            ok = conn.getresponse().status == 200
            conn.close()
            return ok
        except OSError:
            return False

    def _idle_watch(self):
        while True:
            time.sleep(30)
            if self.alive() and time.monotonic() - self.last_used > IDLE_SECONDS and self.lock.acquire(blocking=False):
                try:
                    if time.monotonic() - self.last_used > IDLE_SECONDS:
                        self.stop()
                finally:
                    self.lock.release()

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.job = None

    # ---------- ответ ----------

    def complete(self, prompt, max_tokens, temperature, on_text, cancel, timeout, clean):
        """Текст ответа по мере написания. Остановка — закрытием соединения: движок сразу бросает задачу."""
        body = json.dumps({'prompt': prompt, 'n_predict': max_tokens, 'temperature': temperature, 'top_p': 0.9,
                           'repeat_penalty': 1.05, 'stream': True, 'cache_prompt': True,
                           'stop': ['<|im_end|>', '<|im_start|>', '<|message_sep|>', '</s>']}, ensure_ascii=False).encode('utf-8')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        started, text, shown = time.monotonic(), '', ''
        self.last_cut = False
        try:
            conn.request('POST', '/completion', body=body, headers={
                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
            sock = conn.sock                  # после ответа соединение может отпустить сокет — держим свою ссылку
            resp = conn.getresponse()
            if resp.status != 200:
                raise ServerError(f'ответ движка {resp.status}: ' + resp.read(300).decode('utf-8', 'replace'))
            stopped = threading.Event()
            why = {}

            def watch():
                # Чтение блокирующее; остановку и предел времени обеспечивает закрытие соединения из этого потока.
                while not stopped.wait(0.2):
                    if cancel is not None and cancel.is_set():
                        why['cancel'] = True
                    elif time.monotonic() - started > timeout:
                        why['timeout'] = True
                    else:
                        continue
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except (OSError, AttributeError):
                        pass
                    return
            threading.Thread(target=watch, daemon=True).start()
            try:
                lines = iter(resp.readline, b'')
                for line in lines:
                    line = line.strip()
                    if not line.startswith(b'data:'):
                        continue
                    try:
                        data = json.loads(line[5:].decode('utf-8'))
                    except ValueError:
                        continue
                    text += data.get('content', '')
                    if on_text:
                        now = clean(text)
                        if now != shown:
                            shown = now
                            on_text(now)
                    if data.get('stop'):
                        self.last_cut = bool(data.get('stopped_limit') or data.get('truncated'))
                        break
            except (OSError, http.client.HTTPException):
                if not why:
                    raise
            finally:
                stopped.set()
            if why.get('cancel'):
                return None
            if why.get('timeout'):
                raise TimeoutError
            return text
        finally:
            conn.close()
            self.last_used = time.monotonic()


SERVER = Server()
