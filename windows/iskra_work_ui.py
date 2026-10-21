"""Окна для ежедневной работы: «Входящие» (слежение за новыми файлами), свод таблиц Excel по организациям,
составление телеграмм по видам и реквизиты отправителя."""
import json
import threading
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import iskra_assistant as assistant
import iskra_compose as compose
from iskra_inbox import Inbox
from iskra_index import ROOT, extract
from iskra_svod import read_tables, svod_files, describe
from iskra_tools_ui import _window, _open_path
from iskra_workflows import save_history

SVOD_SETTINGS = ROOT / 'svod.json'


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _store(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _days_left(value):
    try:
        return (datetime.strptime(value, '%d.%m.%Y').date() - date.today()).days
    except (TypeError, ValueError):
        return None


class WorkMixin:
    inbox = None

    # ---------- реквизиты для телеграмм ----------

    def my_details(self):
        return self.telegram_settings().get('me', {})

    def my_details_window(self, parent=None, then=None):
        win = _window(self, 'мои реквизиты для телеграмм', '560x330')
        me = self.my_details()
        ttk.Label(win, text='Подставляются во все черновики телеграмм. Хранятся только на этом компьютере.',
                  style='Muted.TLabel').pack(anchor='w', padx=12, pady=(10, 6))
        ttk.Label(win, text='От кого (организация, подразделение):').pack(anchor='w', padx=12)
        frm = tk.StringVar(value=me.get('from', ''))
        ttk.Entry(win, textvariable=frm, font=('Segoe UI', 11)).pack(fill='x', padx=12, pady=(2, 8))
        ttk.Label(win, text='Подпись (каждая часть с новой строки: должность, звание и И.О. Фамилия):').pack(anchor='w', padx=12)
        sig = tk.Text(win, height=4, font=('Segoe UI', 11))
        sig.pack(fill='both', expand=True, padx=12, pady=(2, 8))
        sig.insert('1.0', me.get('signature', ''))

        def save():
            data = self.telegram_settings()
            data['me'] = {'from': frm.get().strip(), 'signature': sig.get('1.0', 'end-1c').strip()}
            _store(ROOT / 'telegram.json', data)
            win.destroy()
            if then:
                then()

        ttk.Button(win, text='Сохранить', style='Accent.TButton', command=save).pack(side='right', padx=12, pady=10)

    # ---------- составить телеграмму ----------

    def compose_window(self, kind=None, source=None):
        win = _window(self, 'составить телеграмму', '760x620')
        ttk.Label(win, text='Новая телеграмма по виду', font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=12, pady=(10, 2))
        ttk.Label(win, text='Заполните, что знаете, — остальное будет помечено [УТОЧНИТЬ] в черновике. '
                            'Шапка, нумерация пунктов, стандартные фразы и подпись — автоматически.',
                  style='Muted.TLabel', wraplength=720).pack(anchor='w', padx=12)
        form = ttk.Frame(win, padding=12); form.pack(fill='both', expand=True)
        form.columnconfigure(1, weight=1)
        v = {k: tk.StringVar() for k in ('kind', 'to', 'basis', 'subject', 'deadline', 'source')}
        v['kind'].set(kind or compose.KINDS[1])
        v['source'].set(source or '')
        ttk.Label(form, text='Вид:').grid(row=0, column=0, sticky='w', pady=3)
        ttk.Combobox(form, textvariable=v['kind'], values=compose.KINDS, state='readonly').grid(row=0, column=1, sticky='we', pady=3)
        src_label = ttk.Label(form, text='Входящая:')
        src_row = ttk.Frame(form)
        ttk.Entry(src_row, textvariable=v['source']).pack(side='left', fill='x', expand=True)

        def pick_source():
            p = filedialog.askopenfilename(parent=win, filetypes=[('Документы', '*.docx *.txt *.pdf'), ('Все файлы', '*.*')])
            if p:
                v['source'].set(p)
        ttk.Button(src_row, text='Выбрать…', command=pick_source).pack(side='left', padx=(6, 0))
        rows = [('Кому:', 'to'), ('Основание (Во исполнение …):', 'basis'), ('Тема:', 'subject'), ('Срок:', 'deadline')]
        widgets = []
        for i, (label, key) in enumerate(rows, 2):
            lw = ttk.Label(form, text=label)
            ew = ttk.Entry(form, textvariable=v[key])
            lw.grid(row=i, column=0, sticky='w', pady=3, padx=(0, 8)); ew.grid(row=i, column=1, sticky='we', pady=3)
            widgets.append((lw, ew))
        pts_label = ttk.Label(form, text='Пункты (каждый с новой строки):')
        pts_label.grid(row=6, column=0, sticky='nw', pady=3)
        points = tk.Text(form, height=8, font=('Segoe UI', 11), wrap='word')
        points.grid(row=6, column=1, sticky='nsew', pady=3)
        form.rowconfigure(6, weight=1)
        me_info = tk.StringVar()

        def show_me():
            me = self.my_details()
            me_info.set('От кого: ' + (me.get('from') or 'не указано') + ' · подпись: ' +
                        (' '.join(me.get('signature', '').splitlines()) or 'не указана'))
        show_me()
        ttk.Label(form, textvariable=me_info, style='Muted.TLabel', wraplength=560).grid(row=7, column=1, sticky='w', pady=(6, 0))
        ttk.Button(form, text='Мои реквизиты…', command=lambda: self.my_details_window(win, show_me)).grid(row=7, column=0, sticky='w', pady=(6, 0))

        def switch(*_):
            is_reply = v['kind'].get() == 'Ответ на входящую'
            if is_reply:
                src_label.grid(row=1, column=0, sticky='w', pady=3); src_row.grid(row=1, column=1, sticky='we', pady=3)
            else:
                src_label.grid_remove(); src_row.grid_remove()
            for lw, ew in widgets:
                (lw.grid_remove(), ew.grid_remove()) if is_reply else (lw.grid(), ew.grid())
            (pts_label.grid_remove(), points.grid_remove()) if is_reply else (pts_label.grid(), points.grid())
        v['kind'].trace_add('write', switch)
        switch()

        def make():
            me = self.my_details()
            kind = v['kind'].get()
            if kind == 'Ответ на входящую':
                path = v['source'].get().strip()
                if not path or not Path(path).is_file():
                    messagebox.showinfo('Входящая', 'Выберите файл входящей телеграммы.', parent=win); return
                try:
                    text = compose.reply(extract(Path(path)), me, Path(path).name)
                except Exception as exc:
                    messagebox.showerror('Ошибка', str(exc), parent=win); return
            else:
                text = compose.compose(kind, me, to=v['to'].get().strip(), basis=v['basis'].get().strip(),
                                       subject=v['subject'].get().strip(), deadline=v['deadline'].get().strip(),
                                       points=points.get('1.0', 'end-1c').splitlines())
            save_history(ROOT, 'Черновик телеграммы', kind)
            left = compose.unfilled(text)
            win.destroy()
            self.telegrams(initial=text, note=(f'Черновик готов. Впишите места [УТОЧНИТЬ…] — их {len(left)}. ' if left else 'Черновик готов. ')
                           + 'Затем «Орфография» и «Сохранить в Word».')

        ttk.Button(win, text='Сделать черновик', style='Accent.TButton', command=make).pack(side='right', padx=12, pady=10)

    # ---------- свод таблиц Excel ----------

    def svod_window(self, files=None):
        win = _window(self, 'свод таблиц Excel по организациям', '900x700')
        settings = _load(SVOD_SETTINGS)
        ttk.Label(win, text='Свод нескольких таблиц Excel в одну', font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=12, pady=(10, 2))
        ttk.Label(win, text='Искра сама находит в каждой таблице столбец с наименованием организации и шапку (даже в две строки), '
                            'сопоставляет организации по названию («Модуль №1» = «модуль 1») и складывает числа. '
                            'Исходные файлы не изменяются.', style='Muted.TLabel', wraplength=860).pack(anchor='w', padx=12)
        body = ttk.Frame(win, padding=12); body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1); body.columnconfigure(1, weight=1); body.rowconfigure(1, weight=1)

        ttk.Label(body, text='1. Таблицы (сколько угодно):').grid(row=0, column=0, sticky='w')
        lf = ttk.Frame(body); lf.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
        box = tk.Listbox(lf, font=('Segoe UI', 10), selectmode='extended')
        box.pack(fill='both', expand=True)
        paths = []

        def add(new):
            for p in new:
                if p not in paths:
                    paths.append(p); box.insert('end', Path(p).name)
            count.set(f'Файлов: {len(paths)}')

        def choose():
            add(filedialog.askopenfilenames(parent=win, filetypes=[('Excel', '*.xlsx *.xlsm')]))

        def remove():
            for i in reversed(box.curselection()):
                box.delete(i); paths.pop(i)
            count.set(f'Файлов: {len(paths)}')
        count = tk.StringVar(value='Файлов: 0')
        fb = ttk.Frame(body); fb.grid(row=2, column=0, sticky='we', pady=4)
        ttk.Button(fb, text='Добавить файлы…', command=choose).pack(side='left')
        ttk.Button(fb, text='Убрать', command=remove).pack(side='left', padx=4)
        ttk.Label(fb, textvariable=count, style='Muted.TLabel').pack(side='left', padx=6)

        ttk.Label(body, text='2. Перечень организаций по порядку (необязательно):').grid(row=0, column=1, sticky='w')
        order = tk.Text(body, font=('Segoe UI', 10), wrap='none', height=10)
        order.grid(row=1, column=1, sticky='nsew')
        order.insert('1.0', '\n'.join(settings.get('order', [])))
        ob = ttk.Frame(body); ob.grid(row=2, column=1, sticky='we', pady=4)

        def order_from_file():
            p = filedialog.askopenfilename(parent=win, filetypes=[('Excel', '*.xlsx *.xlsm')])
            if not p:
                return
            try:
                names = [r[0] for t in read_tables(p) for r in t.rows]
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win); return
            order.delete('1.0', 'end'); order.insert('1.0', '\n'.join(dict.fromkeys(names)))
        ttk.Button(ob, text='Взять из таблицы…', command=order_from_file).pack(side='left')
        ttk.Button(ob, text='Очистить', command=lambda: order.delete('1.0', 'end')).pack(side='left', padx=4)
        ttk.Label(ob, text='порядок строк в своде; кого нет — будет видно', style='Muted.TLabel').pack(side='left', padx=6)

        opts = ttk.Frame(body); opts.grid(row=3, column=0, columnspan=2, sticky='we', pady=(8, 0))
        mode = tk.StringVar(value=settings.get('mode', 'sum'))
        ttk.Label(opts, text='3. Если организация есть в нескольких таблицах:').pack(anchor='w')
        ttk.Radiobutton(opts, text='сложить числа (свод от разных подразделений)', variable=mode, value='sum').pack(anchor='w', padx=12)
        ttk.Radiobutton(opts, text='не складывать — взять последнее и показать расхождения (одни и те же сведения из разных источников)',
                        variable=mode, value='check').pack(anchor='w', padx=12)
        form = tk.StringVar(value=settings.get('form', ''))
        fr = ttk.Frame(opts); fr.pack(fill='x', pady=(6, 0))
        ttk.Label(fr, text='4. Заполнить готовую форму (необязательно):').pack(side='left')
        ttk.Entry(fr, textvariable=form).pack(side='left', fill='x', expand=True, padx=6)

        def pick_form():
            p = filedialog.askopenfilename(parent=win, filetypes=[('Excel', '*.xlsx *.xlsm')])
            if p:
                form.set(p)
        ttk.Button(fr, text='Выбрать…', command=pick_form).pack(side='left')
        ttk.Button(fr, text='×', width=3, command=lambda: form.set('')).pack(side='left', padx=(4, 0))

        out_box = tk.Text(body, height=7, wrap='word', font=('Segoe UI', 10), background='#FAFAFA', relief='flat')
        out_box.grid(row=4, column=0, columnspan=2, sticky='nsew', pady=(8, 0))
        body.rowconfigure(4, weight=1)
        buttons = ttk.Frame(win, padding=(12, 0, 12, 10)); buttons.pack(fill='x')
        state = {}

        def show(text):
            out_box.delete('1.0', 'end'); out_box.insert('1.0', text)

        def run():
            if len(paths) < 1:
                messagebox.showinfo('Свод', 'Добавьте таблицы Excel.', parent=win); return
            out = filedialog.asksaveasfilename(parent=win, defaultextension='.xlsx', filetypes=[('Excel', '*.xlsx')],
                                               initialfile=f'Свод {date.today().strftime("%d.%m.%Y")}.xlsx',
                                               initialdir=str(Path(paths[0]).parent))
            if not out:
                return
            if Path(out).resolve() in [Path(p).resolve() for p in paths]:
                messagebox.showerror('Свод', 'Нельзя сохранять поверх исходной таблицы.', parent=win); return
            names = [n.strip() for n in order.get('1.0', 'end-1c').splitlines() if n.strip()]
            _store(SVOD_SETTINGS, {'order': names, 'mode': mode.get(), 'form': form.get().strip()})
            show('Собираю…')
            go.state(['disabled'])

            def work():
                try:
                    r = svod_files(list(paths), out, names, mode.get(), form.get().strip() or None)
                    save_history(ROOT, 'Свод Excel', f'{len(paths)} файлов → {Path(out).name}')
                    self.events.put(('call', lambda: done(r)))
                except Exception as exc:
                    msg = str(exc)
                    self.events.put(('call', lambda: (show('Не получилось: ' + msg), go.state(['!disabled']))))
            threading.Thread(target=work, daemon=True).start()

        def done(r):
            state['r'] = r
            go.state(['!disabled'])
            show('Готово: ' + r['output'] + '\n' + describe(r))
            for b in after:
                b.state(['!disabled'])
            if 'form_output' not in r:
                form_btn.state(['disabled'])

        def report():
            r = state.get('r')
            if r:
                self.telegrams(initial=compose.svod_report(r['svod'], self.my_details()),
                               note='Доклад по своду. Проверьте цифры и впишите места [УТОЧНИТЬ…].')

        go = ttk.Button(buttons, text='Собрать свод', style='Accent.TButton', command=run)
        go.pack(side='right')
        open_btn = ttk.Button(buttons, text='Открыть свод', command=lambda: _open_path(state['r']['output']))
        form_btn = ttk.Button(buttons, text='Открыть форму', command=lambda: _open_path(state['r'].get('form_output', '')))
        tg_btn = ttk.Button(buttons, text='Доклад телеграммой', command=report)
        after = (open_btn, form_btn, tg_btn)
        for b in after:
            b.pack(side='left', padx=(0, 6)); b.state(['disabled'])
        add(files or [])

    # ---------- входящие ----------

    def start_inbox(self):
        self.inbox = Inbox(ROOT, notify=lambda items: self.events.put(('call', lambda: self.on_new_files(items))))
        self.inbox.start()

    def _inbox_tab(self):
        tab = ttk.Frame(self.tabs, padding=8); self.tabs.add(tab, text='Входящие')
        self.inbox_tab = tab
        top = ttk.Frame(tab); top.pack(fill='x')
        self.inbox_info = tk.StringVar()
        ttk.Label(top, textvariable=self.inbox_info, style='Muted.TLabel').pack(side='left')
        ttk.Button(top, text='Папки входящих…', command=self.inbox_folders_window).pack(side='right')
        ttk.Button(top, text='Проверить сейчас', command=lambda: self.inbox.check_now()).pack(side='right', padx=6)
        cols = ('added', 'name', 'kind', 'number', 'date', 'sender', 'deadline', 'status')
        heads = ('Поступил', 'Файл', 'Вид', 'Номер', 'Дата', 'От кого', 'Срок', 'Статус')
        widths = (110, 220, 100, 80, 80, 150, 120, 80)
        tf = ttk.Frame(tab); tf.pack(fill='both', expand=True, pady=6)
        tree = ttk.Treeview(tf, columns=cols, show='headings', selectmode='extended')
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h); tree.column(c, width=w, stretch=c in ('name', 'sender'))
        sc = ttk.Scrollbar(tf, command=tree.yview); tree.configure(yscrollcommand=sc.set)
        tree.pack(side='left', fill='both', expand=True); sc.pack(side='right', fill='y')
        tree.tag_configure('new', font=('Segoe UI', 10, 'bold'))
        tree.tag_configure('late', foreground='#C00000')
        tree.tag_configure('soon', foreground='#B26B00')
        tree.tag_configure('done', foreground='#888888')
        self.inbox_tree = tree
        self.inbox_detail = tk.Text(tab, height=5, wrap='word', font=('Segoe UI', 10), background='#FAFAFA', relief='flat', state='disabled')
        self.inbox_detail.pack(fill='x')
        b = ttk.Frame(tab); b.pack(fill='x', pady=(6, 0))
        for label, cmd in (('Открыть', self.inbox_open), ('Ответ телеграммой', self.inbox_reply),
                           ('Напоминание', self.inbox_reminder), ('Объединить телеграммы', self.inbox_merge),
                           ('В свод Excel', self.inbox_svod)):
            ttk.Button(b, text=label, command=cmd).pack(side='left', padx=(0, 4))
        for label, status in (('Выполнено', 'выполнен'), ('В работу', 'в работе')):
            ttk.Button(b, text=label, command=lambda s=status: self.inbox_status(s)).pack(side='right', padx=(4, 0))
        tree.bind('<<TreeviewSelect>>', lambda e: self.inbox_show())
        tree.bind('<Double-Button-1>', lambda e: self.inbox_open())
        self.refresh_inbox()

    def refresh_inbox(self):
        tree = self.inbox_tree
        keep = set(tree.selection())
        tree.delete(*tree.get_children())
        for it in self.inbox.items():
            days = _days_left(it.get('deadline'))
            deadline = it.get('deadline', '')
            if deadline and days is not None and it['status'] != 'выполнен':
                deadline += f' ({assistant.deadline_status(datetime.strptime(it["deadline"], "%d.%m.%Y").date())})'
            tags = []
            if it['status'] == 'новый':
                tags.append('new')
            if it['status'] == 'выполнен':
                tags.append('done')
            elif days is not None and days < 0:
                tags.append('late')
            elif days is not None and days <= 3:
                tags.append('soon')
            tree.insert('', 'end', iid=it['path'], tags=tags, values=(
                it['added'], it['name'], it['kind'], it['number'].replace('№ ', ''), it['date'], it['sender'], deadline, it['status']))
        for iid in keep:
            if tree.exists(iid):
                tree.selection_add(iid)
        new, work = self.inbox.counts()
        folders = self.inbox.folders()
        self.inbox_info.set((f'Слежу за папками: {len(folders)} · проверка каждые {self.inbox.interval} с' if folders
                             else 'Папка входящих не выбрана — нажмите «Папки входящих…»') + f' · новых: {new}, в работе: {work}')
        self.tabs.tab(self.inbox_tab, text=f'Входящие ({new})' if new else 'Входящие')

    def inbox_selected(self, many=False):
        sel = list(self.inbox_tree.selection())
        if not sel:
            messagebox.showinfo('Входящие', 'Выберите файл в списке входящих.')
            return [] if many else None
        items = {i['path']: i for i in self.inbox.items()}
        chosen = [items[p] for p in sel if p in items]
        return chosen if many else (chosen[0] if chosen else None)

    def inbox_show(self):
        sel = self.inbox_tree.selection()
        items = {i['path']: i for i in self.inbox.items()}
        it = items.get(sel[0]) if sel else None
        text = ''
        if it:
            text = f'{it["kind"]} «{it["name"]}»'
            if it['number'] or it['date']:
                text += f' · {it["number"]} от {it["date"]}'.replace(' от ', ' от ' if it['date'] else '')
            if it['sender']:
                text += f'\nОт кого: {it["sender"]}'
            if it['deadline']:
                text += f'\nСрок {it["deadline"]}: {it["deadline_text"]}'
            if it['summary']:
                text += f'\nКратко: {it["summary"]}'
            if it.get('note'):
                text += f'\n{it["note"]}'
            text += f'\nПуть: {it["path"]}'
        self.inbox_detail.configure(state='normal'); self.inbox_detail.delete('1.0', 'end')
        self.inbox_detail.insert('1.0', text); self.inbox_detail.configure(state='disabled')

    def inbox_open(self):
        it = self.inbox_selected()
        if it:
            if it['status'] == 'новый':
                self.inbox.set_status(it['path'], 'в работе'); self.refresh_inbox()
            _open_path(it['path'])

    def inbox_status(self, status):
        for it in self.inbox_selected(many=True):
            self.inbox.set_status(it['path'], status)
        self.refresh_inbox()

    def inbox_reply(self):
        it = self.inbox_selected()
        if not it:
            return

        def make(text):
            draft = compose.reply(text, self.my_details(), it['name'])
            left = compose.unfilled(draft)
            self.telegrams(initial=draft, note=f'Ответ на «{it["name"]}» по пунктам. Впишите, что сделано, — мест [УТОЧНИТЬ…]: {len(left)}.')
            self.inbox.set_status(it['path'], 'в работе'); self.refresh_inbox()
        self.with_text(it['path'], make)

    def inbox_reminder(self):
        it = self.inbox_selected()
        if it:
            self.telegrams(initial=compose.reminder(it, self.my_details()), note='Напоминание о сроке. Проверьте адресата.')

    def inbox_merge(self):
        items = [i for i in self.inbox_selected(many=True) if i['kind'] != 'Таблица Excel']
        if len(items) < 2:
            messagebox.showinfo('Объединить', 'Выделите в списке 2–5 телеграмм (Ctrl + щелчок).'); return
        self.merge_telegrams_window(files=[i['path'] for i in items])

    def inbox_svod(self):
        items = [i for i in self.inbox_selected(many=True) if i['kind'] == 'Таблица Excel']
        if not items:
            messagebox.showinfo('Свод', 'Выделите в списке таблицы Excel (Ctrl + щелчок).'); return
        self.svod_window(files=[i['path'] for i in items])

    def on_new_files(self, items):
        self.refresh_inbox()
        for it in items:
            line = f'Новый файл: {it["kind"].lower()} «{it["name"]}»'
            if it['number']:
                line += f' {it["number"]}'
            if it['sender']:
                line += f' от: {it["sender"]}'
            self.say(line)
            if it['deadline']:
                d = datetime.strptime(it['deadline'], '%d.%m.%Y').date()
                self.say(f'Срок: {it["deadline"]} — {assistant.deadline_status(d)}. {it["deadline_text"]}', 'proof')
            if it.get('svod'):
                self.say('Это таблица по организациям — можно добавить в свод: вкладка «Входящие» → «В свод Excel».', 'proof')
        self.toast(items)

    def toast(self, items):
        """Всплывающее уведомление в правом нижнем углу на 15 секунд."""
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            frame = tk.Frame(win, background='#24518A', padx=2, pady=2); frame.pack(fill='both', expand=True)
            inner = tk.Frame(frame, background='white', padx=12, pady=8); inner.pack(fill='both', expand=True)
            tk.Label(inner, text=f'Искра: новых файлов — {len(items)}', font=('Segoe UI', 11, 'bold'),
                     background='white', foreground='#24518A').pack(anchor='w')
            for it in items[:4]:
                extra = f', срок {it["deadline"]}' if it['deadline'] else ''
                tk.Label(inner, text=f'{it["kind"]}: {it["name"]}{extra}'[:80], background='white', anchor='w').pack(anchor='w')

            def show(_=None):
                win.destroy()
                self.root.deiconify(); self.root.lift()
                self.tabs.select(self.inbox_tab)
            for w in (win, frame, inner) + tuple(inner.winfo_children()):
                w.bind('<Button-1>', show)
            win.update_idletasks()
            x = win.winfo_screenwidth() - win.winfo_reqwidth() - 24
            y = win.winfo_screenheight() - win.winfo_reqheight() - 72
            win.geometry(f'+{x}+{y}')
            win.after(15000, win.destroy)
            self.root.bell()
        except tk.TclError:
            pass

    def inbox_folders_window(self):
        win = _window(self, 'папки входящих', '720x360')
        ttk.Label(win, text='Искра проверяет эти папки каждые 30 секунд и разбирает каждый новый файл. '
                            'Файлы не перемещаются и не изменяются.', wraplength=690).pack(anchor='w', padx=12, pady=8)
        box = tk.Listbox(win, font=('Segoe UI', 10)); box.pack(fill='both', expand=True, padx=12)

        def fill():
            box.delete(0, 'end')
            for f in self.inbox.folders():
                box.insert('end', f + ('' if Path(f).is_dir() else '   (сейчас недоступна)'))
        fill()

        def add():
            folder = filedialog.askdirectory(parent=win)
            if not folder:
                return
            take = messagebox.askyesno('Папка входящих', 'Разобрать и файлы, которые уже лежат в папке?\n'
                                       '«Нет» — следить только за новыми.', parent=win)
            self.inbox.add_folder(folder, take_existing=take)
            if folder not in self.indexer.folders():
                self.indexer.add_folder(folder)      # чтобы сроки и поиск видели входящие
            fill(); self.refresh_inbox()

        def remove():
            sel = box.curselection()
            if sel:
                self.inbox.remove_folder(self.inbox.folders()[sel[0]]); fill(); self.refresh_inbox()
        b = ttk.Frame(win); b.pack(fill='x', padx=12, pady=8)
        ttk.Button(b, text='Добавить папку…', style='Accent.TButton', command=add).pack(side='left')
        ttk.Button(b, text='Убрать', command=remove).pack(side='left', padx=6)
