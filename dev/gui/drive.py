"""Прогон самой программы: меню, окна, кнопки — с подставленными ответами на диалоги."""
import os, sys, tempfile, time, traceback, threading
from pathlib import Path
DATA = tempfile.mkdtemp(); os.environ['ISKRA_DATA_DIR'] = DATA
sys.path.insert(0, '/home/user/iskra/windows'); sys.path.insert(0, '/home/user/iskra/windows/../windows')
import tkinter as tk
os.startfile = lambda *a, **k: None
from tkinter import ttk, filedialog, messagebox, simpledialog

ANS = {'open': '', 'opens': (), 'save': '', 'yesno': False, 'string': None}
LOG = []
filedialog.askopenfilename = lambda *a, **k: ANS['open']
filedialog.askopenfilenames = lambda *a, **k: ANS['opens']
filedialog.asksaveasfilename = lambda *a, **k: ANS['save']
filedialog.askdirectory = lambda *a, **k: ''
for name in ('showinfo', 'showwarning', 'showerror'):
    setattr(messagebox, name, lambda *a, n=name, **k: LOG.append((n, a[:2])))
messagebox.askyesno = lambda *a, **k: ANS['yesno']
messagebox.askokcancel = lambda *a, **k: ANS['yesno']
messagebox.askyesnocancel = lambda *a, **k: None
simpledialog.askstring = lambda *a, **k: ANS['string']

ERRORS = []
root = tk.Tk()
root.report_callback_exception = lambda et, ev, tb: ERRORS.append(''.join(traceback.format_exception(et, ev, tb)))
import iskra
app = iskra.App(root)
import iskra_bugreport
orig_log = iskra_bugreport.log_crash
iskra_bugreport.log_crash = lambda where, et, ev, tb: (ERRORS.append(f'{where}: ' + ''.join(traceback.format_exception(et, ev, tb))), orig_log(where, et, ev, tb))
th_old = threading.excepthook
threading.excepthook = lambda a: ERRORS.append('поток: ' + ''.join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.02)


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def button(win, text):
    for w in walk(win):
        if isinstance(w, (ttk.Button, tk.Button)) and w.cget('text') == text:
            return w
    raise LookupError(f'нет кнопки «{text}» в {win.title() if hasattr(win, "title") else win}')


def toplevels():
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def close_new(before):
    for w in toplevels():
        if w not in before:
            try: w.destroy()
            except tk.TclError: pass
