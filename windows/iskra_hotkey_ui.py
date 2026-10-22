"""Окно горячей клавиши: выделенный в другой программе текст → действие → вставка на место выделенного."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import iskra_ai as ai
import iskra_hotkey as hk
from iskra_spell import fix_typical

# (кнопка, что делать, вставлять ли результат вместо выделенного)
ACTIONS = [
    ('Исправить ошибки', 'Исправить ошибки', True),
    ('Деловой стиль', 'Официальный стиль', True),
    ('Сократить', 'Сократить', True),
    ('Оформить телеграммой', 'telegram', True),
    ('Ответ на это', 'reply', False),
    ('О чём это (кратко)', 'brief', False),
]


class HotkeyMixin:
    def start_hotkey(self):
        self.hotkey = hk.Hotkey(lambda hwnd, text: self.events.put(('call', lambda: self.hotkey_window(hwnd, text))))
        if hk.supported():
            if self.hotkey.start():
                self.say(f'В любой программе (Word, почта, браузер): выделите текст и нажмите {hk.HOTKEY_TEXT} — '
                         'Искра исправит, сократит, оформит или ответит.', 'proof')
            else:
                self.say(f'Сочетание {hk.HOTKEY_TEXT} уже занято другой программой — помощь в Word по клавише недоступна.', 'proof')

    def stop_hotkey(self):
        if getattr(self, 'hotkey', None):
            self.hotkey.stop()

    def hotkey_window(self, hwnd, text):
        if not text:
            self.root.bell()
            self.say(f'{hk.HOTKEY_TEXT}: сначала выделите текст в документе или письме.', 'proof')
            return
        win = tk.Toplevel(self.root)
        win.title('Искра · выделенный текст')
        win.attributes('-topmost', True)
        x, y = self.root.winfo_pointerxy()
        win.geometry(f'640x460+{max(0, x - 320)}+{max(0, y - 60)}')
        top = ttk.Frame(win, padding=8); top.pack(fill='x')
        preview = text if len(text) < 240 else text[:240] + '…'
        ttk.Label(top, text='Выделено: ' + preview.replace('\n', ' '), wraplength=610, style='Muted.TLabel').pack(anchor='w')
        buttons = ttk.Frame(win, padding=(8, 0)); buttons.pack(fill='x')
        out = tk.Text(win, wrap='word', font=('Segoe UI', 11), height=12, undo=True)
        out.pack(fill='both', expand=True, padx=8, pady=6)
        status = tk.StringVar(value='Выберите действие. Результат можно поправить здесь перед вставкой.')
        ttk.Label(win, textvariable=status, style='Muted.TLabel', wraplength=610).pack(anchor='w', padx=8)
        bottom = ttk.Frame(win, padding=8); bottom.pack(fill='x')
        state = {'cancel': None, 'insert': True}

        def show(value):
            def put():
                if win.winfo_exists() and value and not value.startswith('…'):
                    out.delete('1.0', 'end'); out.insert('1.0', value)
            self.events.put(('call', put))

        def run(how, insert):
            if state['cancel'] is not None:
                state['cancel'].set()
            state['insert'] = insert
            paste_btn.state(['!disabled'] if insert else ['disabled'])
            if not self.ai_ready:
                if how == 'Исправить ошибки':
                    fixed, n = fix_typical(text)
                    out.delete('1.0', 'end'); out.insert('1.0', fixed)
                    status.set(f'Без нейросети: исправлено типовых ошибок — {n}. Орфографию проверьте в «Редакторе телеграмм».')
                else:
                    status.set(ai_status)
                return
            cancel = threading.Event()
            state['cancel'] = cancel
            status.set('Нейросеть пишет… (закройте окно — остановится)')
            me = self.my_details()

            def work():
                try:
                    if how == 'telegram':
                        result = ai.write('Оформи этот текст как служебную телеграмму, не добавляя новых фактов',
                                          [('выделенный текст', text)], me=me, on_text=show, cancel=cancel)[0]
                    elif how == 'reply':
                        result = ai.reply(text, 'выделенный текст', me=me, on_text=show, cancel=cancel)[0]
                    elif how == 'brief':
                        result = ai.brief(text, on_text=show, cancel=cancel)
                    else:
                        result = ai.edit(text, how, on_text=show, cancel=cancel)
                    result = result if isinstance(result, str) else str(result)
                    doubtful = ai.unverified(result, [('выделенный текст', text)])
                    note = ('Готово. Проверьте — этих чисел/дат не было в тексте: ' + ', '.join(doubtful[:8])) if doubtful \
                        else 'Готово. Все числа и даты — из выделенного текста.'
                    self.events.put(('call', lambda: win.winfo_exists() and (show(result), status.set(note))))
                except ai.AIError as exc:
                    msg = str(exc)
                    self.events.put(('call', lambda: win.winfo_exists() and status.set(msg)))
            threading.Thread(target=work, daemon=True).start()

        ai_status = self.ai_status_line()
        for i, (label, how, insert) in enumerate(ACTIONS):
            ttk.Button(buttons, text=label, command=lambda h=how, ins=insert: run(h, ins)).grid(
                row=i // 3, column=i % 3, sticky='ew', padx=2, pady=2)
        for c in range(3):
            buttons.columnconfigure(c, weight=1)

        def paste():
            value = out.get('1.0', 'end-1c').strip()
            if not value:
                return
            close()
            threading.Thread(target=hk.paste_into, args=(hwnd, value), daemon=True).start()

        def copy():
            value = out.get('1.0', 'end-1c').strip()
            if value:
                self.root.clipboard_clear(); self.root.clipboard_append(value)
                status.set('Скопировано в буфер обмена.')

        def close():
            if state['cancel'] is not None:
                state['cancel'].set()
            win.destroy()

        paste_btn = ttk.Button(bottom, text='Вставить вместо выделенного', command=paste)
        paste_btn.pack(side='left')
        ttk.Button(bottom, text='Копировать', command=copy).pack(side='left', padx=6)
        ttk.Button(bottom, text='Закрыть', command=close).pack(side='right')
        win.protocol('WM_DELETE_WINDOW', close)
        win.bind('<Escape>', lambda _: close())
        win.focus_force()
