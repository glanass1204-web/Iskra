"""Поручения (контроль исполнения), утренняя сводка и автосвод с динамикой — окна и фоновые проверки."""
import json
import threading
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import iskra_ai as ai
import iskra_morning as morning
from iskra_autosvod import AutoSvod, describe_change
from iskra_control import Control, DATE_FMT, _d
from iskra_index import ROOT, extract, iter_documents
from iskra_tools_ui import _window, _open_path
from iskra_workflows import save_history

MORNING = ROOT / 'morning.json'
TASK_KINDS = ('Телеграмма', 'Приказ', 'Распоряжение', 'Указание', 'Письмо', 'Документ')


class PlanMixin:
    control = None
    autosvod = None

    def start_planning(self):
        self.control = Control(ROOT)
        self.autosvod = AutoSvod(ROOT)
        self.root.after(20000, self._plan_tick)

    def _plan_tick(self):
        """Раз в минуту: автосвод (если пришли новые таблицы) и напоминания о сроках поручений."""
        def work():
            result, reminders = None, []
            try:
                result = self.autosvod.check()
            except Exception as exc:
                msg = f'Автосвод: не удалось собрать — {exc}'
                self.events.put(('call', lambda: self.say(msg, 'proof')))
            if datetime.now().minute % 30 == 0 or not getattr(self, '_reminded_once', False):
                self._reminded_once = True
                reminders = self.control.to_remind()
            self.events.put(('call', lambda: self._plan_results(result, reminders)))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(60000, self._plan_tick)

    def _plan_results(self, result, reminders):
        if result and result.get('output'):
            lines = self.autosvod.summary_lines(result)
            self.say('Автосвод обновлён: ' + ' '.join(lines))
            self.toast_lines('Искра: свод обновлён', lines, self.autosvod_window)
        if reminders:
            today = date.today()
            lines = []
            for t in reminders:
                d = _d(t['deadline'])
                when = ('просрочено' if d < today else 'сегодня' if d == today else f'до {t["deadline"]}')
                lines.append(f'{when}: {t["text"]}')
            self.say('Напоминание о сроках поручений:')
            for line in lines[:10]:
                self.say('• ' + line, 'proof')
            self.toast_lines(f'Искра: сроки поручений — {len(reminders)}', lines, lambda: self.tabs.select(self.control_tab))
            self.refresh_control()

    def toast_lines(self, title, lines, on_click=None):
        """Уведомление в правом нижнем углу на 15 секунд."""
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            frame = tk.Frame(win, background='#24518A', padx=2, pady=2); frame.pack(fill='both', expand=True)
            inner = tk.Frame(frame, background='white', padx=12, pady=8); inner.pack(fill='both', expand=True)
            tk.Label(inner, text=title, font=('Segoe UI', 11, 'bold'), background='white', foreground='#24518A').pack(anchor='w')
            for line in lines[:4]:
                tk.Label(inner, text=line[:90], background='white', anchor='w').pack(anchor='w')

            def click(_=None):
                win.destroy()
                self.root.deiconify(); self.root.lift()
                if on_click:
                    on_click()
            for w in (win, frame, inner) + tuple(inner.winfo_children()):
                w.bind('<Button-1>', click)
            win.update_idletasks()
            win.geometry(f'+{win.winfo_screenwidth() - win.winfo_reqwidth() - 24}+{win.winfo_screenheight() - win.winfo_reqheight() - 72}')
            win.after(15000, win.destroy)
            self.root.bell()
        except tk.TclError:
            pass

    # ---------- поручения ----------

    def _control_tab(self):
        tab = ttk.Frame(self.tabs, padding=8); self.tabs.add(tab, text='Поручения')
        self.control_tab = tab
        top = ttk.Frame(tab); top.pack(fill='x')
        self.control_info = tk.StringVar()
        ttk.Label(top, textvariable=self.control_info, style='Muted.TLabel').pack(side='left')
        self.control_done = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='показывать выполненные', variable=self.control_done, command=self.refresh_control).pack(side='right')
        cols = ('deadline', 'text', 'responsible', 'source', 'state')
        tf = ttk.Frame(tab); tf.pack(fill='both', expand=True, pady=6)
        tree = ttk.Treeview(tf, columns=cols, show='headings', selectmode='extended')
        for c, h, w in zip(cols, ('Срок', 'Поручение', 'Ответственный', 'Документ', 'Состояние'), (90, 420, 170, 170, 130)):
            tree.heading(c, text=h); tree.column(c, width=w, stretch=c in ('text', 'responsible'))
        sc = ttk.Scrollbar(tf, command=tree.yview); tree.configure(yscrollcommand=sc.set)
        tree.pack(side='left', fill='both', expand=True); sc.pack(side='right', fill='y')
        tree.tag_configure('late', foreground='#C00000')
        tree.tag_configure('soon', foreground='#B26B00')
        tree.tag_configure('done', foreground='#888888')
        tree.bind('<Double-Button-1>', lambda e: self.control_edit())
        self.control_tree = tree
        b = ttk.Frame(tab); b.pack(fill='x')
        for label, cmd in (('Добавить…', self.control_add), ('Из документа…', self.control_from_file),
                           ('Изменить…', self.control_edit), ('Открыть документ', self.control_open)):
            ttk.Button(b, text=label, command=cmd).pack(side='left', padx=(0, 4))
        for label, cmd in (('Удалить', self.control_delete), ('В работу', lambda: self.control_status('в работе')),
                           ('Выполнено', lambda: self.control_status('выполнено'))):
            ttk.Button(b, text=label, command=cmd).pack(side='right', padx=(4, 0))
        r = ttk.Frame(tab); r.pack(fill='x', pady=(6, 0))
        ttk.Label(r, text='Отчёт для начальника:').pack(side='left')
        ttk.Button(r, text='Word', command=lambda: self.control_report('docx')).pack(side='left', padx=4)
        ttk.Button(r, text='Excel', command=lambda: self.control_report('xlsx')).pack(side='left')
        self.refresh_control()

    def refresh_control(self):
        if not hasattr(self, 'control_tree'):
            return
        tree = self.control_tree
        keep = set(tree.selection())
        tree.delete(*tree.get_children())
        today = date.today()
        items = self.control.all() if self.control_done.get() else self.control.open_items()
        items.sort(key=lambda i: (i['status'] == 'выполнено', _d(i['deadline']) or date.max))
        late = 0
        for i in items:
            d = _d(i['deadline'])
            if i['status'] == 'выполнено':
                state, tag = f'выполнено {i["done"]}', 'done'
            elif d and d < today:
                state, tag = f'просрочено {(today - d).days} дн.', 'late'
                late += 1
            elif d and (d - today).days <= 2:
                state, tag = ('сегодня' if d == today else f'через {(d - today).days} дн.'), 'soon'
            else:
                state, tag = ('в работе' if d else 'без срока'), ''
            src = i['source'] + (f' № {i["number"]}' if i['number'] else '')
            tree.insert('', 'end', iid=i['id'], tags=(tag,),
                        values=(i['deadline'] or '—', ('✦ ' if i.get('ai') else '') + i['text'], i['responsible'] or '—', src or '—', state))
        for iid in keep:
            if tree.exists(iid):
                tree.selection_add(iid)
        open_n = len(self.control.open_items())
        self.control_info.set(f'На контроле: {open_n}, просрочено: {late}.  ✦ — найдено нейросетью, проверьте.')
        self.tabs.tab(self.control_tab, text=f'Поручения ({late}!)' if late else 'Поручения')

    def _control_selected(self, many=False):
        sel = list(self.control_tree.selection())
        if not sel:
            messagebox.showinfo('Поручения', 'Выберите поручение в списке.')
        return sel if many else (sel[0] if sel else None)

    def control_status(self, status):
        for iid in self._control_selected(many=True):
            self.control.update(iid, status=status)
        self.refresh_control()

    def control_delete(self):
        sel = self._control_selected(many=True)
        if sel and messagebox.askyesno('Поручения', f'Удалить из контроля: {len(sel)}?'):
            for iid in sel:
                self.control.remove(iid)
            self.refresh_control()

    def control_open(self):
        iid = self._control_selected()
        item = next((i for i in self.control.all() if i['id'] == iid), None)
        if item and item.get('path') and Path(item['path']).exists():
            _open_path(item['path'])
        elif item:
            messagebox.showinfo('Документ', 'Поручение добавлено вручную или документ перемещён.')

    def _control_dialog(self, title, item=None, on_save=None):
        win = _window(self, title, '640x300')
        form = ttk.Frame(win, padding=12); form.pack(fill='both', expand=True)
        form.columnconfigure(1, weight=1)
        v = {k: tk.StringVar(value=(item or {}).get(k, '')) for k in ('deadline', 'responsible', 'source')}
        ttk.Label(form, text='Поручение:').grid(row=0, column=0, sticky='nw')
        text = tk.Text(form, height=4, wrap='word', font=('Segoe UI', 10)); text.grid(row=0, column=1, sticky='we', pady=3)
        text.insert('1.0', (item or {}).get('text', ''))
        for row, (key, label) in enumerate((('deadline', 'Срок (ДД.ММ.ГГГГ):'), ('responsible', 'Ответственный:'),
                                            ('source', 'Документ:')), 1):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=3, padx=(0, 8))
            ttk.Entry(form, textvariable=v[key]).grid(row=row, column=1, sticky='we', pady=3)

        def save():
            what = text.get('1.0', 'end').strip()
            dl = v['deadline'].get().strip()
            if not what:
                messagebox.showinfo('Поручение', 'Напишите, что нужно сделать.', parent=win); return
            if dl and not _d(dl):
                messagebox.showinfo('Срок', 'Срок — в виде 25.10.2026.', parent=win); return
            on_save(what, dl, v['responsible'].get().strip(), v['source'].get().strip())
            win.destroy()
            self.refresh_control()
        ttk.Button(win, text='Сохранить', style='Accent.TButton', command=save).pack(side='right', padx=12, pady=10)

    def control_add(self):
        self._control_dialog('новое поручение', on_save=lambda t, d, r, s: self.control.add(t, d, r, s or 'вручную'))

    def control_edit(self):
        iid = self._control_selected()
        item = next((i for i in self.control.all() if i['id'] == iid), None)
        if item:
            self._control_dialog('поручение', item, lambda t, d, r, s: self.control.update(iid, text=t, deadline=d, responsible=r, source=s))

    def control_from_file(self, path=None):
        path = path or filedialog.askopenfilename(filetypes=[('Документы', '*.docx *.txt *.pdf'), ('Все файлы', '*.*')])
        if path:
            self.control_from_paths([path], announce=True)

    def control_from_paths(self, paths, announce=False):
        """Поручения из документов: по правилам сразу, нейросеть дополняет в фоне."""
        def work():
            total = []
            for p in paths:
                try:
                    text = extract(Path(p))
                except Exception:
                    continue
                total += self.control.add_from_document(text, Path(p).name, str(p))
                if self.ai_ready:
                    def ai_job(cancel, text=text, p=p):
                        return self.control.add_from_document(text, Path(p).name, str(p), ai_tasks=ai.tasks(text, cancel=cancel))
                    self.events.put(('call', lambda job=ai_job: self._control_ai(job)))
            self.events.put(('call', lambda: self._control_added(total, announce)))
        threading.Thread(target=work, daemon=True).start()

    def _control_ai(self, job):
        if self.ai_cancel is not None:
            return                                  # нейросеть занята задачей пользователя — хватит найденного правилами
        self.ai_background(job, lambda added: added and self._control_added(added, False, ai_found=True))

    def _control_added(self, added, announce, ai_found=False):
        self.refresh_control()
        if added:
            self.say(f'{"Нейросеть добавила" if ai_found else "Добавлено"} на контроль поручений: {len(added)}.')
            for t in added[:6]:
                self.say(f'• {t["deadline"] or "без срока"} — {t["text"]}', 'proof')
        elif announce:
            self.say('Новых поручений в документе не нашла (или они уже на контроле).')

    def control_report(self, kind):
        path = filedialog.asksaveasfilename(defaultextension='.' + kind, initialdir=str(ROOT),
                                            initialfile=f'Контроль исполнения {date.today().strftime(DATE_FMT)}.{kind}',
                                            filetypes=[('Word', '*.docx')] if kind == 'docx' else [('Excel', '*.xlsx')])
        if not path:
            return
        try:
            (self.control.report_docx if kind == 'docx' else self.control.report_xlsx)(path)
        except Exception as exc:
            messagebox.showerror('Отчёт', str(exc)); return
        save_history(ROOT, 'Отчёт по поручениям', Path(path).name)
        if messagebox.askyesno('Отчёт', f'Сохранено:\n{path}\n\nОткрыть?'):
            _open_path(path)

    # ---------- утренняя сводка ----------

    def maybe_morning(self):
        try:
            last = json.loads(MORNING.read_text(encoding='utf-8')).get('shown', '')
        except (OSError, ValueError):
            last = ''
        if last != date.today().isoformat():
            self.morning_window(first=True)

    def morning_window(self, first=False):
        win = _window(self, 'сводка на ' + date.today().strftime(DATE_FMT), '900x640')
        text = tk.Text(win, wrap='word', font=('Segoe UI', 10), padx=12, pady=10, relief='flat', background='#FAFAFA')
        sc = ttk.Scrollbar(win, command=text.yview); text.configure(yscrollcommand=sc.set)
        buttons = ttk.Frame(win, padding=(10, 6)); buttons.pack(side='bottom', fill='x')
        sc.pack(side='right', fill='y'); text.pack(fill='both', expand=True)
        text.tag_configure('head', font=('Segoe UI', 11, 'bold'), foreground='#24518A', spacing1=8)
        text.tag_configure('late', foreground='#C00000')
        text.tag_configure('ai', background='#EEF3FA', lmargin1=8, lmargin2=8)
        text.insert('1.0', 'Собираю сводку…')
        state = {}

        def show(sections):
            if not win.winfo_exists():
                return
            state['text'] = morning.text(sections)
            text.configure(state='normal'); text.delete('1.0', 'end')
            text.insert('end', f'СВОДКА НА {date.today().strftime(DATE_FMT)}\n', 'head')
            for title, lines in sections:
                text.insert('end', f'\n{title}: {len(lines) if lines else "нет"}\n', 'head')
                for line in lines[:40]:
                    text.insert('end', f'• {line}\n', 'late' if title == 'ПРОСРОЧЕНО' else '')
            text.configure(state='disabled')
            try:
                MORNING.write_text(json.dumps({'shown': date.today().isoformat()}), encoding='utf-8')
            except OSError:
                pass

        def work():
            try:
                docs = list(iter_documents(30000))
                doc_deadlines = morning.upcoming_from_docs(docs)
            except Exception:
                doc_deadlines = []
            lines = self.autosvod.summary_lines() if self.autosvod.last else []
            sections = morning.build(self.inbox.items(), self.control, doc_deadlines, lines)
            self.events.put(('call', lambda: show(sections)))
        threading.Thread(target=work, daemon=True).start()

        def ai_main():
            if 'text' not in state:
                return

            def done(result):
                if win.winfo_exists():
                    text.configure(state='normal')
                    text.insert('1.0', 'ГЛАВНОЕ (нейросеть):\n' + result + '\n\n', 'ai')
                    text.configure(state='disabled')
            self.ai_background(lambda cancel: ai.morning(state['text'], cancel=cancel), done)

        def to_word():
            if 'text' not in state:
                return
            path = filedialog.asksaveasfilename(parent=win, defaultextension='.docx', initialdir=str(ROOT),
                                                initialfile=f'Сводка {date.today().strftime(DATE_FMT)}.docx', filetypes=[('Word', '*.docx')])
            if path:
                from docx import Document
                doc = Document()
                for line in state['text'].split('\n'):
                    doc.add_paragraph(line)
                doc.save(path)
                _open_path(path)
        ttk.Button(buttons, text='Поручения', command=lambda: (win.destroy(), self.tabs.select(self.control_tab))).pack(side='left')
        ttk.Button(buttons, text='Входящие', command=lambda: (win.destroy(), self.tabs.select(self.inbox_tab))).pack(side='left', padx=6)
        ttk.Button(buttons, text='Сохранить в Word', command=to_word).pack(side='left')
        ai_btn = ttk.Button(buttons, text='Главное — нейросеть', command=ai_main)
        ai_btn.pack(side='left', padx=6)
        if not self.ai_ready:
            ai_btn.state(['disabled'])
        show_var = tk.BooleanVar(value=self._morning_enabled())
        ttk.Checkbutton(buttons, text='показывать при запуске', variable=show_var,
                        command=lambda: self._morning_enable(show_var.get())).pack(side='right')
        ttk.Button(buttons, text='Закрыть', style='Accent.TButton', command=win.destroy).pack(side='right', padx=6)

    def _morning_enabled(self):
        try:
            return json.loads(MORNING.read_text(encoding='utf-8')).get('enabled', True)
        except (OSError, ValueError):
            return True

    def _morning_enable(self, on):
        try:
            data = json.loads(MORNING.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        data['enabled'] = bool(on)
        MORNING.write_text(json.dumps(data), encoding='utf-8')

    # ---------- автосвод ----------

    def autosvod_window(self):
        win = _window(self, 'автосвод', '860x640')
        s = self.autosvod.settings
        from iskra_work_ui import SVOD_SETTINGS, _load
        order_default = s.get('order') or _load(SVOD_SETTINGS).get('order', [])
        ttk.Label(win, text='Автосвод: таблицы подразделений → свод за день', font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=12, pady=(10, 2))
        ttk.Label(win, style='Muted.TLabel', wraplength=820, text=(
            'Укажите папку, куда подразделения кладут таблицы Excel. Искра проверяет её каждую минуту: как только приходит новый '
            'или исправленный файл за сегодня, свод пересобирается. Видно, кто ещё не прислал и что изменилось со вчера. '
            'Если подразделение прислало исправленный файл, берутся последние цифры.')).pack(anchor='w', padx=12)
        form = ttk.Frame(win, padding=12); form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        folder, out = tk.StringVar(value=s.get('folder', '')), tk.StringVar(value=s.get('out', ''))
        for row, (label, var) in enumerate((('Папка с таблицами:', folder), ('Куда класть своды:', out))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=3, padx=(0, 8))
            ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky='we', pady=3)
            ttk.Button(form, text='Выбрать…', command=lambda v=var: v.set(filedialog.askdirectory(parent=win) or v.get())).grid(row=row, column=2, padx=(6, 0))
        enabled = tk.BooleanVar(value=s.get('enabled', True))
        ttk.Checkbutton(form, text='Собирать автоматически при поступлении таблиц', variable=enabled).grid(row=2, column=1, sticky='w', pady=4)
        ttk.Label(form, text='Перечень организаций\n(кого ждём):').grid(row=3, column=0, sticky='nw', pady=3)
        order = tk.Text(form, height=7, font=('Segoe UI', 10)); order.grid(row=3, column=1, columnspan=2, sticky='we', pady=3)
        order.insert('1.0', '\n'.join(order_default))
        status = tk.Text(win, height=10, wrap='word', font=('Segoe UI', 10), background='#FAFAFA', relief='flat')
        status.pack(fill='both', expand=True, padx=12)
        state = {'r': self.autosvod.last}

        def show(r):
            status.configure(state='normal'); status.delete('1.0', 'end')
            if r:
                status.insert('end', '\n'.join(self.autosvod.summary_lines(r)) + (f'\n\nФайл: {r["output"]}' if r.get('output') else ''))
                if r.get('failed'):
                    status.insert('end', '\nНе прочитано: ' + '; '.join(r['failed']))
            else:
                status.insert('end', f'Последняя сборка: {s.get("last_build", "ещё не было")}.')
            status.configure(state='disabled')
        show(state['r'])

        def save_settings():
            if not folder.get().strip() or not Path(folder.get()).is_dir():
                messagebox.showinfo('Автосвод', 'Выберите папку с таблицами.', parent=win); return False
            self.autosvod.configure(folder.get().strip(), out.get().strip() or folder.get().strip(), enabled.get(),
                                    [x.strip() for x in order.get('1.0', 'end').splitlines() if x.strip()])
            return True

        def build_now():
            if not save_settings():
                return
            status.configure(state='normal'); status.delete('1.0', 'end'); status.insert('end', 'Собираю…'); status.configure(state='disabled')

            def work():
                try:
                    r = self.autosvod.build()
                    self.events.put(('call', lambda: (state.__setitem__('r', r), show(r) if win.winfo_exists() else None)))
                except Exception as exc:
                    msg = str(exc)
                    self.events.put(('call', lambda: messagebox.showerror('Автосвод', msg, parent=win) if win.winfo_exists() else None))
            threading.Thread(target=work, daemon=True).start()

        def report():
            r = state.get('r')
            if not r or not r.get('svod'):
                messagebox.showinfo('Автосвод', 'Сначала соберите свод.', parent=win); return
            import iskra_compose as compose
            from iskra_work_ui import svod_table_text
            me = self.my_details()
            text = compose.svod_report(r['svod'], me)
            extra = []
            if r['changes']:
                extra.append(f'Изменения к {r["prev_date"]}: ' + '; '.join(describe_change(c) for c in r['changes']) + '.')
            if r['missing']:
                extra.append('Не представили сведения: ' + ', '.join(r['missing']) + '.')
            if extra:
                text = text.replace('\n\nПодпись:', '\n' + '\n'.join(extra) + '\n\nПодпись:', 1)
            ed = self.telegrams(initial=text, note='Доклад по автосводу (с изменениями к прошлому дню). Проверьте цифры.')
            if self.ai_ready:
                table = svod_table_text(r['svod']) + ('\n' + '\n'.join(extra) if extra else '')
                self.ai_into_editor(ed, lambda cancel, update: ai.svod_report(table, me=me, on_text=update, cancel=cancel)[0],
                                    [('свод', table)], 'Доклад по автосводу от нейросети')
        b = ttk.Frame(win, padding=(12, 8)); b.pack(fill='x')
        ttk.Button(b, text='Сохранить настройки', command=lambda: save_settings() and messagebox.showinfo(
            'Автосвод', 'Сохранено. Искра проверяет папку каждую минуту.', parent=win)).pack(side='left')
        ttk.Button(b, text='Открыть свод', command=lambda: state.get('r') and state['r'].get('output') and _open_path(state['r']['output'])).pack(side='left', padx=6)
        ttk.Button(b, text='Доклад телеграммой', command=report).pack(side='left')
        ttk.Button(b, text='Собрать сейчас', style='Accent.TButton', command=build_now).pack(side='right')
