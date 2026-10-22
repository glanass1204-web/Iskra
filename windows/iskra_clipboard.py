"""Копирование и вставка во всех окнах Искры.
- Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A / Ctrl+Z работают и при РУССКОЙ раскладке (Tk по умолчанию понимает их
  только в английской — нажатие «Ctrl+С» с русской «с» ничего не делало).
- Текст «только для чтения» (чат, ответы, отчёты) можно выделить мышью и скопировать: щелчок даёт ему фокус.
- Правая кнопка мыши — меню «Копировать / Вырезать / Вставить / Выделить всё».
- В списках (входящие, поручения, журнал, справочник) Ctrl+C копирует выделенные строки — их можно вставить в Excel.
- show_text — окно с длинным сообщением, из которого всё можно скопировать (вместо обычного окна сообщения)."""
import tkinter as tk
from tkinter import ttk

# Код клавиши не зависит от раскладки: 67 — C, 86 — V, 88 — X, 65 — A, 90 — Z, 89 — Y.
KEYCODES = {67: '<<Copy>>', 86: '<<Paste>>', 88: '<<Cut>>', 65: '<<SelectAll>>', 90: '<<Undo>>', 89: '<<Redo>>'}
LATIN = {'c', 'v', 'x', 'a', 'z', 'y'}


def _is_editable(w):
    try:
        return str(w.cget('state')) not in ('disabled', 'readonly')
    except tk.TclError:
        return False


def _select_all(w):
    if isinstance(w, tk.Text):
        w.tag_add('sel', '1.0', 'end-1c')
    else:
        try:
            w.selection_range(0, 'end')
            w.icursor('end')
        except tk.TclError:
            pass


def _copy_tree(tree):
    """Выделенные строки списка — в буфер обмена, столбцы через табуляцию (вставляется в Excel по ячейкам)."""
    rows = []
    cols = tree['columns']
    if cols:
        rows.append('\t'.join(str(tree.heading(c, 'text')) for c in cols))
    for iid in tree.selection():
        rows.append('\t'.join(str(v) for v in tree.item(iid, 'values')))
    if len(rows) > 1:
        tree.clipboard_clear()
        tree.clipboard_append('\n'.join(rows))


def _menu(event):
    w = event.widget
    editable = _is_editable(w)
    menu = tk.Menu(w, tearoff=False)
    menu.add_command(label='Копировать', command=lambda: w.event_generate('<<Copy>>'))
    if editable:
        menu.add_command(label='Вырезать', command=lambda: w.event_generate('<<Cut>>'))
        menu.add_command(label='Вставить', command=lambda: w.event_generate('<<Paste>>'))
    menu.add_separator()
    menu.add_command(label='Выделить всё', command=lambda: (w.focus_set(), _select_all(w)))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def install(root):
    def on_ctrl(event):
        w = event.widget
        if isinstance(w, ttk.Treeview) and event.keycode == 67:
            _copy_tree(w)
            return 'break'
        virtual = KEYCODES.get(event.keycode)
        if not virtual or event.keysym.lower() in LATIN:
            return None                                   # английская раскладка — Tk справится сам
        if virtual == '<<SelectAll>>':
            _select_all(w)
        elif virtual in ('<<Paste>>', '<<Cut>>', '<<Undo>>', '<<Redo>>') and not _is_editable(w):
            return 'break'
        else:
            try:
                w.event_generate(virtual)
            except tk.TclError:
                pass
        return 'break'

    root.bind_all('<Control-KeyPress>', on_ctrl, add='+')
    # Текст «только для чтения»: щелчок даёт фокус — тогда выделение копируется по Ctrl+C.
    root.bind_class('Text', '<Button-1>', lambda e: e.widget.focus_set(), add='+')
    for cls in ('Text', 'Entry', 'TEntry', 'TCombobox'):
        root.bind_class(cls, '<Button-3>', _menu, add='+')
    root.bind_class('Treeview', '<Control-Insert>', lambda e: _copy_tree(e.widget), add='+')


def show_text(parent, title, text, warn=False):
    """Сообщение, из которого можно выделить и скопировать любую часть (обычное окно сообщения этого не умеет)."""
    win = tk.Toplevel(parent)
    win.title('Искра · ' + title)
    win.transient(parent)
    lines = text.count('\n') + 1
    win.geometry(f'640x{min(560, 140 + lines * 22)}')
    box = tk.Text(win, wrap='word', font=('Segoe UI', 10), padx=10, pady=8, relief='flat',
                  background='#FFF8E1' if warn else '#FAFAFA')
    box.insert('1.0', text)
    box.configure(state='disabled')
    bar = ttk.Frame(win, padding=8); bar.pack(side='bottom', fill='x')
    box.pack(fill='both', expand=True)

    def copy_all():
        win.clipboard_clear()
        win.clipboard_append(text)
        note.set('Скопировано.')
    note = tk.StringVar(value='Выделите мышью нужное и Ctrl+C — или «Копировать всё».')
    ttk.Label(bar, textvariable=note, style='Muted.TLabel').pack(side='left')
    ttk.Button(bar, text='Закрыть', command=win.destroy).pack(side='right')
    ttk.Button(bar, text='Копировать всё', command=copy_all).pack(side='right', padx=6)
    win.bind('<Escape>', lambda _e: win.destroy())
    box.focus_set()
    return win
