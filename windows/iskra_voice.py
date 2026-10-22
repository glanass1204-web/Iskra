"""Голосовые команды без интернета: запись с микрофона средствами Windows (winmm) и распознавание речи
whisper.cpp (папка voice рядом с программой, дополнительный архив Iskra-dop-golos.zip).
Запись и распознанный текст остаются на этом компьютере; файл записи удаляется сразу после распознавания."""
import ctypes
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

RATE = 16000
MAX_SECONDS = 30
PROMPT = ('Телеграмма, приказ, распоряжение, свод, поручения, сроки, доклад, личный состав, на лицо, по списку, '
          'госпиталь, полигон, начальнику штаба.')
BASE = None              # для тестов


def base_dir():
    if BASE:
        return Path(BASE)
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def _voice_dir():
    return base_dir() / 'voice'


def _exe():
    d = _voice_dir()
    for name in ('whisper-cli.exe', 'whisper-cli', 'main.exe'):
        if (d / name).is_file():
            return d / name
    return None


def _model():
    models = sorted(_voice_dir().glob('ggml-*.bin'))
    return models[0] if models else None


def available():
    return _exe() is not None and _model() is not None


def transcribe(wav, lang='ru', timeout=180):
    """Текст из записи. Пути — относительные от папки voice: русские буквы в пути не попадают в командную строку."""
    home = _voice_dir()

    def rel(p):
        try:
            return os.path.relpath(p, home)
        except ValueError:
            return str(p)
    threads = str(max(2, min(8, (os.cpu_count() or 4) - 1)))
    cmd = [str(_exe()), '-m', rel(_model()), '-f', rel(wav), '-l', lang, '-nt', '-np', '-t', threads]
    if lang == 'ru':
        cmd += ['--prompt', PROMPT]
    out = subprocess.run(cmd, cwd=str(home), capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if out.returncode != 0:
        raise RuntimeError('распознавание речи не удалось: ' + out.stderr.decode('utf-8', 'replace')[-300:])
    text = out.stdout.decode('utf-8', 'replace')
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('[')]
    return ' '.join(lines).strip()


def work_dir():
    d = Path(os.environ.get('ISKRA_DATA_DIR', str(base_dir() / 'data'))) / 'voice_tmp'
    try:
        d.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix='rec_', dir=d))
    except OSError:
        return Path(tempfile.mkdtemp(prefix='iskra_rec_'))


# ---------- запись с микрофона (Windows, winmm) ----------

class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [('wFormatTag', ctypes.c_ushort), ('nChannels', ctypes.c_ushort), ('nSamplesPerSec', ctypes.c_uint32),
                ('nAvgBytesPerSec', ctypes.c_uint32), ('nBlockAlign', ctypes.c_ushort), ('wBitsPerSample', ctypes.c_ushort),
                ('cbSize', ctypes.c_ushort)]


class _WAVEHDR(ctypes.Structure):
    pass


_WAVEHDR._fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', ctypes.c_uint32), ('dwBytesRecorded', ctypes.c_uint32),
                     ('dwUser', ctypes.c_size_t), ('dwFlags', ctypes.c_uint32), ('dwLoops', ctypes.c_uint32),
                     ('lpNext', ctypes.c_void_p), ('reserved', ctypes.c_size_t)]
WHDR_DONE = 1


class Recorder:
    """start() → stop() → путь к WAV (16 кГц, моно). Без сторонних библиотек: функции записи звука самой Windows."""

    def __init__(self):
        self.frames = []
        self.stopped = threading.Event()
        self.thread = None
        self.error = None

    def start(self):
        if sys.platform != 'win32':
            raise RuntimeError('запись звука — только в Windows')
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        winmm = ctypes.WinDLL('winmm')
        fmt = _WAVEFORMATEX(1, 1, RATE, RATE * 2, 2, 16, 0)
        handle = ctypes.c_void_p()
        res = winmm.waveInOpen(ctypes.byref(handle), ctypes.c_uint(0xFFFFFFFF), ctypes.byref(fmt), ctypes.c_size_t(0),
                               ctypes.c_size_t(0), ctypes.c_uint(0))   # WAVE_MAPPER: микрофон по умолчанию
        if res != 0:
            self.error = 'не удалось открыть микрофон (код %d). Проверьте, что микрофон подключён и разрешён.' % res
            self.stopped.set()
            return
        size = RATE // 5 * 2                               # буферы по 0,2 секунды
        bufs = [ctypes.create_string_buffer(size) for _ in range(6)]
        hdrs = [_WAVEHDR(ctypes.cast(b, ctypes.c_void_p), size, 0, 0, 0, 0, None, 0) for b in bufs]
        hs = ctypes.sizeof(_WAVEHDR)
        for h in hdrs:
            winmm.waveInPrepareHeader(handle, ctypes.byref(h), hs)
            winmm.waveInAddBuffer(handle, ctypes.byref(h), hs)
        winmm.waveInStart(handle)
        started = time.monotonic()
        try:
            while not self.stopped.is_set() and time.monotonic() - started < MAX_SECONDS:
                for h, b in zip(hdrs, bufs):
                    if h.dwFlags & WHDR_DONE:
                        self.frames.append(b.raw[:h.dwBytesRecorded])
                        h.dwFlags &= ~WHDR_DONE
                        winmm.waveInUnprepareHeader(handle, ctypes.byref(h), hs)
                        winmm.waveInPrepareHeader(handle, ctypes.byref(h), hs)
                        winmm.waveInAddBuffer(handle, ctypes.byref(h), hs)
                time.sleep(0.02)
        finally:
            winmm.waveInStop(handle)
            winmm.waveInReset(handle)
            for h, b in zip(hdrs, bufs):
                if h.dwFlags & WHDR_DONE and h.dwBytesRecorded:
                    self.frames.append(b.raw[:h.dwBytesRecorded])
                winmm.waveInUnprepareHeader(handle, ctypes.byref(h), hs)
            winmm.waveInClose(handle)
            self.stopped.set()

    def stop(self):
        """Остановить и сохранить. Возвращает путь к WAV или None, если записи нет."""
        self.stopped.set()
        if self.thread:
            self.thread.join(3)
        if self.error:
            raise RuntimeError(self.error)
        data = b''.join(self.frames)
        if len(data) < RATE // 2:                          # меньше четверти секунды
            return None
        path = work_dir() / 'rec.wav'
        write_wav(path, data)
        return path


def write_wav(path, pcm16):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm16)


def cleanup(path):
    try:
        Path(path).unlink()
        Path(path).parent.rmdir()
    except OSError:
        pass
