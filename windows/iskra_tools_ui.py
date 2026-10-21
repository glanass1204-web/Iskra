"""Windows for batch Word ↔ Excel, telegram merging, spelling and the Excel formula helper."""
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from iskra_batch import discover_fields, collect_tables, mail_merge, template_fields
from iskra_crossformat import merge_crossformat
from iskra_formula import build_formula, explain_formula
from iskra_index import ROOT, extract
from iskra_services import telegram_check, telegram_template
from iskra_spell import SpellChecker, summary as spell_summary
from iskra_telegram import merge_telegrams
from iskra_workflows import normalize_layout, draft_from_sources, save_history

DOC_TYPES = [('Word и текст', '*.docx *.txt'), ('Все документы', '*.docx *.xlsx *.pptx *.pdf *.txt *.md *.csv')]


def _window(app, title, size):
    win = tk.Toplevel(app.root)
    win.title('Искра · ' + title)
    win.geometry(size)
    win.transient(app.root)
    return win


def _open_path(path):
    try:
        os.startfile(path)
    except (OSError, AttributeError):
        pass


class ToolsMixin:
    spell = None

    def spellchecker(self):
        if self.spell is None:
            self.spell = SpellChecker()
            if self.spell.available:
                self.spell.preload()
        return self.spell

    # ---------- Word → Excel ----------

    def word_to_excel(self):
        files = filedialog.askopenfilenames(title='Выберите документы Word (можно сразу 20 и больше)', filetypes=[('Word', '*.docx')])
        if not files:
            return
        win = _window(self, 'Word → Excel', '760x560')
        ttk.Label(win, text=f'Выбрано документов: {len(files)}. Что собрать в таблицу?', font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=12, pady=(12, 6))
        mode = tk.StringVar(value='fields')
        ttk.Radiobutton(win, text='Поля вида «Название: значение» (анкеты, карточки, справки) — одна строка на документ',
                        variable=mode, value='fields').pack(anchor='w', padx=12)
        ttk.Radiobutton(win, text='Таблицы из документов — все строки всех таблиц в одну таблицу Excel',
                        variable=mode, value='tables').pack(anchor='w', padx=12)
        ttk.Label(win, text='Найденные поля (отмечены те, что есть хотя бы в половине документов). Ctrl+щелчок — выбрать/снять:',
                  wraplength=720).pack(anchor='w', padx=12, pady=(10, 4))
        frame = ttk.Frame(win); frame.pack(fill='both', expand=True, padx=12)
        box = tk.Listbox(frame, selectmode='extended', font=('Segoe UI', 10), exportselection=False)
        box.pack(side='left', fill='both', expand=True)
        sc = ttk.Scrollbar(frame, command=box.yview); sc.pack(side='right', fill='y'); box.config(yscrollcommand=sc.set)
        ttk.Label(win, text='Своё поле (если его нет в списке) — точная подпись из документов:').pack(anchor='w', padx=12, pady=(8, 2))
        extra = tk.StringVar(); ttk.Entry(win, textvariable=extra).pack(fill='x', padx=12)
        status = tk.StringVar(value='Ищу поля в документах…')
        ttk.Label(win, textvariable=status, wraplength=720).pack(anchor='w', padx=12, pady=6)
        labels = []

        def found(fields):
            labels.clear()
            for label, n in fields:
                labels.append(label)
                box.insert('end', f'{label}   —   в {n} из {len(files)}')
                if n * 2 >= len(files):
                    box.selection_set('end')
            status.set(f'Найдено полей: {len(fields)}.' if fields else 'Поля вида «Название: значение» не найдены — выберите «Таблицы» или впишите поле.')

        def work():
            fields = discover_fields(files)
            self.events.put(('call', lambda: found(fields) if win.winfo_exists() else None))
        threading.Thread(target=work, daemon=True).start()

        def run():
            output = filedialog.asksaveasfilename(parent=win, title='Сохранить таблицу Excel', defaultextension='.xlsx',
                                                  initialdir=str(ROOT), filetypes=[('Excel', '*.xlsx')])
            if not output:
                return
            try:
                if mode.get() == 'tables':
                    r = collect_tables(files, output)
                    msg = f"Строк: {r['rows']}, листов: {r['sheets']}.\nНе прочитано файлов: {len(r['failed'])}."
                else:
                    chosen = [labels[i] for i in box.curselection()] + [x.strip() for x in extra.get().split(';') if x.strip()]
                    if not chosen:
                        messagebox.showwarning('Поля', 'Отметьте хотя бы одно поле.', parent=win); return
                    r = merge_crossformat(files, chosen, output, 'xlsx')
                    msg = f"Записей: {r['rows']}, замечаний: {r['issues']}.\nПустые и противоречивые значения — «НЕ НАЙДЕНО», подробности на листе «Проверка»."
                save_history(ROOT, 'Word → Excel', f'{len(files)} файлов → {Path(output).name}')
                if messagebox.askyesno('Готово', msg + f'\n\n{output}\n\nОткрыть файл?', parent=win):
                    _open_path(output)
                win.destroy()
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
        ttk.Button(win, text='Собрать в Excel', style='Accent.TButton', command=run).pack(pady=(0, 12))

    # ---------- Excel → Word ----------

    def excel_to_word(self):
        win = _window(self, 'Excel → Word', '760x470')
        ttk.Label(win, text='Excel → Word', font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=12, pady=(12, 4))
        mode = tk.StringVar(value='merge')
        ttk.Radiobutton(win, text='Документы по образцу: каждая строка Excel — отдельный документ Word (справки, письма, телеграммы)',
                        variable=mode, value='merge').pack(anchor='w', padx=12)
        ttk.Radiobutton(win, text='Одна таблица Word из нескольких файлов Excel',
                        variable=mode, value='table').pack(anchor='w', padx=12)
        ttk.Label(win, wraplength=720, style='Muted.TLabel', text=(
            'Как подготовить образец: напишите документ в Word и вместо данных впишите названия столбцов Excel '
            'в фигурных скобках, например: «Выдана {ФИО} в том, что он проходит службу в {Подразделение}». '
            'Первая строка Excel — заголовки.')).pack(anchor='w', padx=12, pady=8)
        paths = {'xlsx': tk.StringVar(), 'tpl': tk.StringVar(), 'out': tk.StringVar()}
        name_field = tk.StringVar()
        grid = ttk.Frame(win); grid.pack(fill='x', padx=12)

        def pick(key, kind):
            if kind == 'dir':
                p = filedialog.askdirectory(parent=win, title='Папка для новых документов')
            else:
                types = [('Excel', '*.xlsx *.xlsm')] if kind == 'xlsx' else [('Word', '*.docx')]
                p = filedialog.askopenfilename(parent=win, filetypes=types)
            if p:
                paths[key].set(p)
                if key == 'tpl':
                    try:
                        fields = template_fields(p)
                        names.configure(values=fields)
                        status.set('Поля образца: ' + (', '.join(fields) if fields else 'не найдены — впишите {Поле}'))
                        if fields and not name_field.get():
                            name_field.set(fields[0])
                    except Exception as exc:
                        status.set(f'Не удалось прочитать образец: {exc}')

        rows = [('Таблица Excel:', 'xlsx', 'xlsx'), ('Образец Word:', 'tpl', 'docx'), ('Куда сохранить:', 'out', 'dir')]
        for r, (label, key, kind) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky='w', pady=3)
            ttk.Entry(grid, textvariable=paths[key], width=70).grid(row=r, column=1, sticky='we', padx=6)
            ttk.Button(grid, text='Выбрать…', command=lambda k=key, t=kind: pick(k, t)).grid(row=r, column=2)
        ttk.Label(grid, text='Имя файлов из поля:').grid(row=3, column=0, sticky='w', pady=3)
        names = ttk.Combobox(grid, textvariable=name_field, width=30); names.grid(row=3, column=1, sticky='w', padx=6)
        grid.columnconfigure(1, weight=1)
        status = tk.StringVar(value='')
        ttk.Label(win, textvariable=status, wraplength=720).pack(anchor='w', padx=12, pady=8)

        def run():
            try:
                if mode.get() == 'table':
                    files = filedialog.askopenfilenames(parent=win, title='Файлы Excel', filetypes=[('Excel', '*.xlsx *.xlsm')])
                    if not files:
                        return
                    from openpyxl import load_workbook
                    wb = load_workbook(files[0], read_only=True)
                    header = [str(c) for c in next(wb.active.iter_rows(values_only=True)) if c is not None]
                    wb.close()
                    output = filedialog.asksaveasfilename(parent=win, defaultextension='.docx', filetypes=[('Word', '*.docx')], initialdir=str(ROOT))
                    if not output:
                        return
                    r = merge_crossformat(files, header, output, 'docx')
                    messagebox.showinfo('Готово', f"Строк в таблице Word: {r['rows']}\n{output}", parent=win)
                    _open_path(output)
                    return
                if not (paths['xlsx'].get() and paths['tpl'].get() and paths['out'].get()):
                    messagebox.showwarning('Не всё выбрано', 'Выберите таблицу Excel, образец Word и папку.', parent=win); return
                r = mail_merge(paths['xlsx'].get(), paths['tpl'].get(), paths['out'].get(), name_field.get().strip() or None)
                save_history(ROOT, 'Excel → Word', f"{r['created']} документов в {r['output']}")
                if messagebox.askyesno('Готово', f"Создано документов: {r['created']}\nПапка: {r['output']}\n\nОткрыть папку?", parent=win):
                    _open_path(r['output'])
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
        ttk.Button(win, text='Создать', style='Accent.TButton', command=run).pack(pady=(0, 12))

    # ---------- Телеграммы ----------

    def telegrams(self, initial=None, note=None):
        win = _window(self, 'редактор телеграмм', '860x680')
        ttk.Label(win, text='Проект телеграммы · исходные документы не изменяются', font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=12, pady=8)
        buttons = ttk.Frame(win); buttons.pack(side='bottom', fill='x', padx=12, pady=8)
        status = tk.StringVar(value=note or 'Используйте утверждённый образец организации. Шаблон здесь — пример.')
        ttk.Label(win, textvariable=status, wraplength=820).pack(side='bottom', anchor='w', padx=12, pady=6)
        t = tk.Text(win, wrap='word', font=('Segoe UI', 11), undo=True)
        t.pack(fill='both', expand=True, padx=12)
        t.insert('1.0', initial or telegram_template())

        def check():
            issues = telegram_check(t.get('1.0', 'end-1c'))
            issues = [i for i in issues if not i.startswith('Орфография и фактическая точность')]
            messagebox.showinfo('Проверка перед отправкой', '\n'.join('• ' + x for x in issues) or 'Замечаний по оформлению нет.', parent=win)

        def save():
            from docx import Document
            path = filedialog.asksaveasfilename(parent=win, defaultextension='.docx', filetypes=[('Word', '*.docx')], initialdir=str(ROOT))
            if path:
                d = Document()
                for line in t.get('1.0', 'end-1c').split('--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---')[0].rstrip().splitlines():
                    d.add_paragraph(line)
                d.save(path); status.set('Проект сохранён: ' + path)

        def tidy():
            t.replace('1.0', 'end', normalize_layout(t.get('1.0', 'end-1c')))
            status.set('Пробелы и пустые строки приведены к единому виду.')

        def prepare():
            ix = self.selected()
            if ix is None:
                messagebox.showinfo('Источник', 'Сначала найдите и выберите документ в главном окне.', parent=win); return
            path = self.results[ix][0]
            try:
                t.replace('1.0', 'end', draft_from_sources('По выбранному документу', [(path, extract(Path(path)))]))
                save_history(ROOT, 'Проект телеграммы', Path(path).name)
                status.set('Создан черновик с выдержками из источника.')
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)

        ttk.Button(buttons, text='Орфография', style='Accent.TButton', command=lambda: self.spell_window(target=t)).pack(side='left')
        ttk.Button(buttons, text='Проверить оформление', command=check).pack(side='left', padx=6)
        ttk.Button(buttons, text='Убрать лишние пробелы', command=tidy).pack(side='left')
        ttk.Button(buttons, text='Черновик по выбранному файлу', command=prepare).pack(side='left', padx=6)
        ttk.Button(buttons, text='Сохранить в Word', command=save).pack(side='right')

    def merge_telegrams_window(self):
        files = filedialog.askopenfilenames(title='Выберите телеграммы для объединения (две и больше)', filetypes=DOC_TYPES)
        if not files:
            return
        if len(files) < 2:
            messagebox.showinfo('Объединение', 'Выберите хотя бы две телеграммы (Ctrl+щелчок).'); return
        try:
            text, report = merge_telegrams([(Path(p).name, extract(Path(p))) for p in files])
        except Exception as exc:
            messagebox.showerror('Ошибка', str(exc)); return
        save_history(ROOT, 'Объединение телеграмм', ', '.join(Path(p).name for p in files)[:400])
        self.telegrams(text, ' '.join(report) + ' Проверьте пометки [УТОЧНИТЬ], [ДАТА], [НОМЕР].')

    # ---------- Орфография ----------

    def spell_window(self, target=None):
        checker = self.spellchecker()
        if not checker.available:
            messagebox.showerror('Орфография', 'Не найден словарь (папка dict рядом с программой).'); return
        win = _window(self, 'проверка орфографии', '980x620')
        top = ttk.Frame(win); top.pack(fill='x', padx=12, pady=8)
        status = tk.StringVar(value='Вставьте текст или откройте документ и нажмите «Проверить».')
        ttk.Label(top, textvariable=status).pack(side='left')
        pane = ttk.Panedwindow(win, orient='horizontal'); pane.pack(fill='both', expand=True, padx=12)
        if target is None:
            t = tk.Text(pane, wrap='word', font=('Segoe UI', 11), undo=True)
        else:
            t = target  # проверяем текст прямо в редакторе телеграммы
        if target is None:
            pane.add(t, weight=3)
        right = ttk.Frame(pane); pane.add(right, weight=2)
        for tag, color in (('spelling', '#C62828'), ('style', '#1565C0'), ('typo', '#8A5300')):
            t.tag_configure(tag, underline=True, foreground=color)
        t.tag_configure('current', background='#FFE58F')
        issues_box = tk.Listbox(right, font=('Segoe UI', 10), exportselection=False)
        issues_box.pack(fill='both', expand=True)
        ttk.Label(right, text='Варианты:').pack(anchor='w', pady=(6, 0))
        sugg = tk.Listbox(right, height=6, font=('Segoe UI', 10), exportselection=False); sugg.pack(fill='x')
        actions = ttk.Frame(right); actions.pack(fill='x', pady=6)
        state = {'issues': []}

        def run_check():
            text = t.get('1.0', 'end-1c')
            status.set('Проверяю…')

            def work():
                issues = checker.check(text)
                self.events.put(('call', lambda: show(issues) if win.winfo_exists() else None))
            threading.Thread(target=work, daemon=True).start()

        def show(issues):
            state['issues'] = issues
            for tag in ('spelling', 'style', 'typo', 'current'):
                t.tag_remove(tag, '1.0', 'end')
            issues_box.delete(0, 'end'); sugg.delete(0, 'end')
            for i in issues:
                t.tag_add(i.kind, f'1.0+{i.start}c', f'1.0+{i.end}c')
                kind = {'spelling': 'Орфография', 'style': 'Стиль', 'typo': 'Опечатка'}[i.kind]
                issues_box.insert('end', f'{kind}: «{i.text}» — {i.message}')
            status.set(spell_summary(issues) + ('  Красным — орфография, синим — стиль, коричневым — опечатки.' if issues else ''))

        def current():
            ix = issues_box.curselection()
            return state['issues'][ix[0]] if ix else None

        def select(event=None):
            i = current()
            if not i:
                return
            t.tag_remove('current', '1.0', 'end')
            t.tag_add('current', f'1.0+{i.start}c', f'1.0+{i.end}c'); t.see(f'1.0+{i.start}c')
            sugg.delete(0, 'end')
            if i.fix:
                sugg.insert('end', i.fix)
            elif i.kind == 'spelling':
                for s in checker.suggest(i.text):
                    sugg.insert('end', s)
            if sugg.size():
                sugg.selection_set(0)

        def apply():
            i = current()
            ix = sugg.curselection()
            if not i or not ix:
                return
            replacement = sugg.get(ix[0])
            if i.text[:1].isupper() and replacement[:1].islower():
                replacement = replacement[:1].upper() + replacement[1:]
            t.delete(f'1.0+{i.start}c', f'1.0+{i.end}c'); t.insert(f'1.0+{i.start}c', replacement)
            run_check()

        def learn():
            i = current()
            if i and i.kind == 'spelling':
                checker.add_word(i.text); run_check()

        def open_doc():
            p = filedialog.askopenfilename(parent=win, filetypes=DOC_TYPES)
            if p:
                t.delete('1.0', 'end'); t.insert('1.0', extract(Path(p))); run_check()

        issues_box.bind('<<ListboxSelect>>', select)
        sugg.bind('<Double-Button-1>', lambda e: apply())
        ttk.Button(actions, text='Исправить', style='Accent.TButton', command=apply).pack(side='left')
        ttk.Button(actions, text='Добавить в словарь', command=learn).pack(side='left', padx=6)
        ttk.Button(top, text='Проверить', style='Accent.TButton', command=run_check).pack(side='right')
        if target is None:
            ttk.Button(top, text='Открыть документ…', command=open_doc).pack(side='right', padx=6)
        else:
            win.title('Искра · орфография телеграммы')

            def close():
                for tag in ('spelling', 'style', 'typo', 'current'):
                    t.tag_remove(tag, '1.0', 'end')
                win.destroy()
            win.protocol('WM_DELETE_WINDOW', close)
            run_check()

    # ---------- Формулы Excel ----------

    def formulas(self, request=''):
        win = _window(self, 'формулы Excel', '800x520')
        ttk.Label(win, text='Опишите задачу обычными словами или вставьте формулу, чтобы её объяснить',
                  font=('Segoe UI', 12, 'bold')).pack(anchor='w', padx=12, pady=8)
        q = tk.StringVar(value=request)
        entry = ttk.Entry(win, textvariable=q, font=('Segoe UI', 11)); entry.pack(fill='x', padx=12)
        result = tk.Text(win, wrap='word', font=('Segoe UI', 11), height=12); result.pack(fill='both', expand=True, padx=12, pady=10)
        examples = ('Примеры:\n• сумма столбца C где в столбце A "Москва"\n• количество где в B больше 100\n'
                    '• среднее по столбцу D если в колонке B равно Готово\n• подтянуть с другого листа\n'
                    '• рабочие дни между датами • стаж • найти повторы в столбце A • просрочено\n'
                    '• =ЕСЛИОШИБКА(ВПР(E2;A:B;2;ЛОЖЬ);"нет") — объяснить формулу')
        result.insert('1.0', examples)
        formula = {'value': ''}

        def go(event=None):
            text = q.get().strip()
            result.delete('1.0', 'end')
            if text.startswith('='):
                formula['value'] = ''
                result.insert('1.0', 'Что делает формула:\n' + explain_formula(text))
                return
            f, note = build_formula(text)
            formula['value'] = f or ''
            if f:
                result.insert('1.0', f + '\n\n' + note + '\n\nИз чего состоит:\n' + explain_formula(f))
            else:
                result.insert('1.0', note + '\n\n' + examples)

        def copy():
            if formula['value']:
                win.clipboard_clear(); win.clipboard_append(formula['value'])
                messagebox.showinfo('Скопировано', 'Формула в буфере обмена — вставьте её в ячейку Excel (Ctrl+V).', parent=win)

        entry.bind('<Return>', go)
        buttons = ttk.Frame(win); buttons.pack(pady=(0, 12))
        ttk.Button(buttons, text='Подобрать / объяснить', style='Accent.TButton', command=go).pack(side='left')
        ttk.Button(buttons, text='Копировать формулу', command=copy).pack(side='left', padx=8)
        if request:
            go()
        entry.focus_set()
