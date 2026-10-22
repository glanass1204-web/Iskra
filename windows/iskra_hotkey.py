"""Помощь в любой программе: выделили текст в Word, почте или браузере → Ctrl+Alt+Пробел → окно Искры
с действиями (исправить, сократить, деловой стиль, телеграмма, ответ). Результат вставляется на место выделенного.
Только Windows; клавиши и буфер обмена — средствами самой Windows (ctypes), без сторонних программ."""
import ctypes
import sys
import threading
import time

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_SPACE, VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN = 0x20, 0x11, 0x12, 0x10, 0x5B
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
CF_UNICODETEXT = 13
HOTKEY_TEXT = 'Ctrl+Alt+Пробел'


def supported():
    return sys.platform == 'win32'


if supported():
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('pad', ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('u', _U)]


def _keys(*seq):
    """seq: (vk, up) — нажатия клавиш в активной программе."""
    arr = (INPUT * len(seq))()
    for i, (vk, up) in enumerate(seq):
        arr[i].type = 1
        arr[i].u.ki = KEYBDINPUT(vk, 0, 2 if up else 0, 0, 0)
    user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def _ctrl(letter):
    vk = ord(letter)
    _keys((VK_CONTROL, False), (vk, False), (vk, True), (VK_CONTROL, True))


def _wait_modifiers_released(limit=2.0):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if not any(user32.GetAsyncKeyState(k) & 0x8000 for k in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN)):
            return
        time.sleep(0.02)


def _open_clipboard():
    for _ in range(20):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.03)
    return False


def get_clipboard():
    if not _open_clipboard():
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard(text):
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0042, size)            # GMEM_MOVEABLE | GMEM_ZEROINIT
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, size)
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        user32.CloseClipboard()


def copy_selection():
    """(окно, выделенный текст). Старый буфер обмена возвращается на место."""
    hwnd = user32.GetForegroundWindow()
    _wait_modifiers_released()
    before = get_clipboard()
    marker = '⁣iskra⁣'
    set_clipboard(marker)
    _ctrl('C')
    text = None
    for _ in range(40):
        time.sleep(0.03)
        now = get_clipboard()
        if now is not None and now != marker:
            text = now
            break
    set_clipboard(before or '')
    return hwnd, (text or '').strip()


def paste_into(hwnd, text):
    """Вставить text в окно hwnd на место выделенного; буфер обмена потом восстанавливается."""
    before = get_clipboard()
    set_clipboard(text)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.25)
    _ctrl('V')
    time.sleep(0.4)
    set_clipboard(before or '')


class Hotkey:
    """Ctrl+Alt+Пробел в любой программе → callback(hwnd, text) в потоке горячей клавиши."""

    def __init__(self, callback):
        self.callback = callback
        self.thread = None
        self.thread_id = None
        self.ok = None

    def start(self):
        if not supported():
            self.ok = False
            return False
        ready = threading.Event()

        def loop():
            self.thread_id = kernel32.GetCurrentThreadId()
            self.ok = bool(user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE))
            ready.set()
            if not self.ok:
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        hwnd, text = copy_selection()
                        self.callback(hwnd, text)
                    except Exception:
                        pass
            user32.UnregisterHotKey(None, 1)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()
        ready.wait(3)
        return bool(self.ok)

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
