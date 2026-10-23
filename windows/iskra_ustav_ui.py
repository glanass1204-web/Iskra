"""Окно «Уставы» и вопросы по уставам в чате: статьи из файлов пользователя, ответ нейросети со ссылками."""
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import iskra_ai as ai
import iskra_ustav as ustav
from iskra_tools_ui import _window

NONE_LOADED = ('Уставы ещё не загружены. Меню «Инструменты → Уставы…» → «Добавить файлы уставов» '
               '(Word, PDF или текст: БУ ч.1, ч.2, УВС, ДУ, УГиКС, СУ). После этого спрашивайте: '
               '«по уставу: обязанности командира взвода в обороне», «статья 45 БУ ч.2».')


class UstavMixin:
    def ustav_ask(self, question):
        """Вопрос по уставам: «статья N …» — текст статьи как есть; иначе — ответ по найденным статьям."""
        def job(cancel):
            lib = ustav.library()
            if not lib.articles:
                return 'none', None
            direct = ustav.direct_ref(question)
            if direct:
                a = lib.get(*direct)
                if a:
                    return 'article', a
            found = lib.search(question, k=6)
            if not found:
                return 'notfound', None
            if not self.ai_ready:
                return 'found', found
            self.events.put(('call', lambda: self.say(
                'Статьи: ' + '; '.join(ustav.ref(a) for _, a in found), 'proof')))
            update = self._stream_to_chat('Ответ по уставам (нейросеть):')
            return 'answer', (ai.ustav_answer(question, ustav.materials(found), on_text=update, cancel=cancel), found)

        def done(result):
            kind, value = result
            if kind == 'none':
                self.say(NONE_LOADED, 'proof')
            elif kind == 'article':
                self.say(f'{ustav.ref(value)}' + (f' — {value["chapter"]}' if value['chapter'] else '') + ':', 'proof')
                self.say(value['text'])
            elif kind == 'notfound':
                self.say('В загруженных уставах подходящих статей не нашла — переформулируйте другими словами.', 'proof')
            elif kind == 'found':
                self.say('Нейросеть не установлена — вот ближайшие статьи:', 'proof')
                for _, a in value[:3]:
                    self.say(f'{ustav.ref(a)}:', 'proof')
                    self.say(a['text'][:1500])
            else:
                text, found = value
                self.remember('ask', question, text, ustav.materials(found))
        self.tabs.select(0)
        self.ai_background(job, done, label='ответ по уставам')

    def ustav_window(self):
        win = _window(self, 'уставы', '1000x600')
        ttk.Label(win, text='Искра отвечает по уставам из папки «Уставы»: находит нужные статьи и даёт ответ со ссылкой '
                            '(БУ ч.2, ст. 45). Добавьте файлы уставов (Word, PDF, текст) — один раз.',
                  wraplength=960).pack(anchor='w', padx=12, pady=(10, 4))
        bar = ttk.Frame(win, padding=(12, 0)); bar.pack(fill='x')
        docs_var = tk.StringVar(value='Загружаю уставы…')
        ttk.Label(win, textvariable=docs_var, style='Muted.TLabel', wraplength=960).pack(anchor='w', padx=12, pady=4)
        top = ttk.Frame(win, padding=(12, 4)); top.pack(fill='x')
        ttk.Label(top, text='Найти в уставах:').pack(side='left')
        q = tk.StringVar()
        entry = ttk.Entry(top, textvariable=q); entry.pack(side='left', fill='x', expand=True, padx=6)
        body = ttk.Panedwindow(win, orient='horizontal'); body.pack(fill='both', expand=True, padx=12, pady=(4, 10))
        tree = ttk.Treeview(body, columns=('ref', 'chapter'), show='headings')
        tree.heading('ref', text='Статья'); tree.column('ref', width=120)
        tree.heading('chapter', text='Глава / начало'); tree.column('chapter', width=260)
        body.add(tree, weight=1)
        text = tk.Text(body, wrap='word', font=('Segoe UI', 10)); body.add(text, weight=2)
        shown = {}

        def describe(lib):
            if not lib.docs:
                docs_var.set(f'Уставов пока нет. Папка: {ustav.folder()}')
            else:
                docs_var.set('Загружено: ' + '; '.join(f'{d} — статей {n} ({name})' for name, (d, n) in lib.docs.items())
                             + '. Если статей 0 — файл не разобрался (скан без распознавания?).')

        def load(reload=False):
            def work():
                lib = ustav.library(reload=reload)
                self.events.put(('call', lambda: win.winfo_exists() and describe(lib)))
            threading.Thread(target=work, daemon=True, name='уставы').start()

        def find(_=None):
            tree.delete(*tree.get_children()); shown.clear()
            lib = ustav.library()
            d = ustav.direct_ref(q.get())
            found = [(1, lib.get(*d))] if d and lib.get(*d) else lib.search(q.get(), k=40)
            for _, a in found:
                iid = tree.insert('', 'end', values=(ustav.ref(a), (a['chapter'] or a['text'])[:80]))
                shown[iid] = a
            if found:
                tree.selection_set(tree.get_children()[0])

        def select(_=None):
            sel = tree.selection()
            if sel and sel[0] in shown:
                a = shown[sel[0]]
                text.delete('1.0', 'end')
                text.insert('end', f'{ustav.ref(a)}\n' + (a['chapter'] + '\n' if a['chapter'] else '') + '\n' + a['text'])

        def add():
            paths = filedialog.askopenfilenames(parent=win, title='Файлы уставов',
                                                filetypes=[('Документы', '*.docx *.pdf *.txt *.md'), ('Все файлы', '*.*')])
            if paths:
                n = ustav.add_files(paths)
                docs_var.set(f'Добавлено файлов: {n}. Разбираю на статьи…')
                load(reload=True)

        def open_folder():
            ustav.folder().mkdir(parents=True, exist_ok=True)
            try:
                os.startfile(str(ustav.folder()))          # noqa: S606 — только Windows
            except (AttributeError, OSError):
                messagebox.showinfo('Уставы', str(ustav.folder()), parent=win)

        def ask():
            if q.get().strip():
                self.ustav_ask(q.get().strip())

        ttk.Button(bar, text='Добавить файлы уставов…', command=add).pack(side='left')
        ttk.Button(bar, text='Открыть папку уставов', command=open_folder).pack(side='left', padx=6)
        ttk.Button(bar, text='Обновить', command=lambda: load(reload=True)).pack(side='left')
        ttk.Button(top, text='Найти', command=find).pack(side='left')
        ttk.Button(top, text='Спросить Искру по уставам', command=ask).pack(side='left', padx=6)
        entry.bind('<Return>', find)
        tree.bind('<<TreeviewSelect>>', select)
        load()
        return win
