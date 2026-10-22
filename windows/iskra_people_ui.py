"""Окна справочника людей, папки образцов отдела и проверки перед отправкой."""
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

import iskra_ai as ai
import iskra_people as pp
import iskra_precheck as pc
from iskra_index import ROOT, extract
from iskra_tools_ui import _window

SAMPLES_README = ('Положите сюда 10–20 удачных документов отдела (Word или .txt): телеграммы, доклады, ответы.\n'
                  'Нейросеть берёт из самых похожих оформление, порядок частей и обороты — но не факты.\n'
                  'Имя файла помогает выбрать образец: «Телеграмма о представлении сведений.docx», «Доклад о проверке.docx».\n')


class PeopleMixin:
    def start_people(self):
        self.people = pp.People(ROOT)
        ai.PEOPLE = self.people
        samples = ROOT / 'obrazcy'
        samples.mkdir(parents=True, exist_ok=True)
        readme = samples / 'ПРОЧТИТЕ.txt'
        if not readme.exists():
            readme.write_text(SAMPLES_README, encoding='utf-8')
        ai.STYLE_DIR = samples

    def samples_folder(self):
        os.startfile(str(ROOT / 'obrazcy'))

    # ---------- справочник ----------

    def people_window(self):
        win = _window(self, 'справочник людей', '980x520')
        ttk.Label(win, text='Справочник: звания, должности и организации. Искра ставит их в нужный падеж '
                            'и подсказывает нейросети.', wraplength=940).pack(anchor='w', padx=12, pady=8)
        cols = pp.FIELDS
        tree = ttk.Treeview(win, columns=cols, show='headings', height=14)
        for c, w in zip(cols, (170, 190, 260, 170, 60, 160)):
            tree.heading(c, text=pp.TITLES[c]); tree.column(c, width=w)
        tree.pack(fill='both', expand=True, padx=12)
        status = tk.StringVar(value='Двойной щелчок — изменить. Можно загрузить список из Excel.')
        ttk.Label(win, textvariable=status, wraplength=940).pack(anchor='w', padx=12, pady=4)
        buttons = ttk.Frame(win); buttons.pack(fill='x', padx=12, pady=8)

        def refresh():
            tree.delete(*tree.get_children())
            for p in self.people.items:
                tree.insert('', 'end', iid=p['fio'], values=[p.get(c, '') for c in cols])

        def edit(person=None):
            d = tk.Toplevel(win); d.title('Человек'); d.transient(win); d.grab_set()
            entries = {}
            for i, c in enumerate(cols):
                ttk.Label(d, text=pp.TITLES[c]).grid(row=i, column=0, sticky='w', padx=8, pady=3)
                e = ttk.Entry(d, width=50); e.grid(row=i, column=1, padx=8, pady=3)
                e.insert(0, (person or {}).get(c, '') or ('м' if c == 'sex' else ''))
                entries[c] = e
            preview = tk.StringVar()
            ttk.Label(d, textvariable=preview, foreground='#24518A', wraplength=420).grid(row=len(cols), column=0, columnspan=2, padx=8, pady=6, sticky='w')

            def show(_=None):
                p = {c: entries[c].get() for c in cols}
                preview.set('Кому: ' + ' '.join(pp.addressee(p)) + '\nПодпись: ' + pp.signature(p).replace('\n', ' · '))
            for e in entries.values():
                e.bind('<KeyRelease>', show)
            show()

            def ok():
                if person and person['fio'] != entries['fio'].get().strip():
                    self.people.remove(person['fio'])
                if not self.people.add(**{c: entries[c].get() for c in cols}):
                    messagebox.showwarning('Справочник', 'Укажите фамилию и инициалы.', parent=d); return
                d.destroy(); refresh()
            ttk.Button(d, text='Сохранить', command=ok).grid(row=len(cols) + 1, column=1, sticky='e', padx=8, pady=8)

        def chosen():
            sel = tree.selection()
            return next((p for p in self.people.items if sel and p['fio'] == sel[0]), None)

        def remove():
            p = chosen()
            if p and messagebox.askyesno('Справочник', f'Удалить {p["fio"]}?', parent=win):
                self.people.remove(p['fio']); refresh()

        def load():
            path = filedialog.askopenfilename(parent=win, filetypes=[('Excel', '*.xlsx')])
            if path:
                try:
                    n = self.people.from_xlsx(path)
                except Exception as exc:
                    messagebox.showerror('Справочник', str(exc), parent=win); return
                refresh(); status.set(f'Загружено из Excel: {n}.')

        def unload():
            path = filedialog.asksaveasfilename(parent=win, defaultextension='.xlsx', initialfile='Справочник.xlsx',
                                                filetypes=[('Excel', '*.xlsx')])
            if path:
                self.people.to_xlsx(path); status.set('Выгружено: ' + path)

        tree.bind('<Double-1>', lambda _: chosen() and edit(chosen()))
        ttk.Button(buttons, text='Добавить', style='Accent.TButton', command=edit).pack(side='left')
        ttk.Button(buttons, text='Изменить', command=lambda: chosen() and edit(chosen())).pack(side='left', padx=6)
        ttk.Button(buttons, text='Удалить', command=remove).pack(side='left')
        ttk.Button(buttons, text='Выгрузить в Excel', command=unload).pack(side='right')
        ttk.Button(buttons, text='Загрузить из Excel…', command=load).pack(side='right', padx=6)
        refresh()

    # ---------- в редакторе телеграмм ----------

    def people_menu(self, parent, t):
        """Кнопка «Из справочника»: адресат в дательном падеже или подпись — в место курсора."""
        mb = ttk.Menubutton(parent, text='Из справочника')
        menu = tk.Menu(mb, tearoff=False)
        mb['menu'] = menu

        def fill():
            menu.delete(0, 'end')
            if not self.people.items:
                menu.add_command(label='Справочник пуст — открыть…', command=self.people_window)
                return
            to = tk.Menu(menu, tearoff=False); sign = tk.Menu(menu, tearoff=False)
            for p in self.people.items:
                label = f'{p["fio"]} — {p["position"]}'[:70]
                to.add_command(label=label, command=lambda p=p: getattr(t, 'iskra_busy', False) or t.insert('insert', '\n'.join(pp.addressee(p))))
                sign.add_command(label=label, command=lambda p=p: getattr(t, 'iskra_busy', False) or t.insert('insert', pp.signature(p)))
            menu.add_cascade(label='Кому (адресат)', menu=to)
            menu.add_cascade(label='Подпись', menu=sign)
            menu.add_separator()
            menu.add_command(label='Открыть справочник…', command=self.people_window)
        menu.configure(postcommand=fill)
        return mb

    def precheck(self, win, t, source_paths=(), source_texts=()):
        """Проверка перед отправкой. Исходные документы читаются в фоне — окно не замирает."""
        text = t.get('1.0', 'end-1c')
        people = self.people

        def work():
            sources = list(source_texts or ())        # уже известные тексты (таблица свода и т. п.)
            for p in source_paths or ():
                try:
                    sources.append((Path(p).name, extract(Path(p))))
                except Exception:
                    pass
            issues = pc.check(text, sources=sources, people=people)
            from iskra_services import telegram_check
            issues += [('внимание', x) for x in telegram_check(pc.body(text))
                       if not x.startswith(('Орфография и фактическая', 'Не заполнено', 'Документ пуст'))]

            def show():
                if not win.winfo_exists():
                    return
                from iskra_clipboard import show_text
                show_text(win, 'Проверка перед отправкой', pc.report(issues), warn=any(lvl == 'ошибка' for lvl, _ in issues))
            self.events.put(('call', show))
        threading.Thread(target=work, daemon=True).start()
