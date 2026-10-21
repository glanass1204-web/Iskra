"""Окна и команды: первый запуск (какие папки собрать), обзор папок, локальная нейросеть в чате и в редакторе."""
import json
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import iskra_ai as ai
from iskra_index import ROOT, extract, iter_documents, search_docs
from iskra_overview import candidate_folders, folder_overview, folders_summary, render
from iskra_tools_ui import _window, _open_path
from iskra_workflows import save_history

SETUP = ROOT / 'setup.json'
OVERVIEW_CHARS = 30000
SELECTED_DOC = ('по этому документ', 'по выбранному', 'по нему', 'на него', 'на эту', 'на этот', 'этого документ')


class AIMixin:
    ai_ready = False
    ai_cancel = None
    ai_cancel_all = threading.Event()      # Esc: остановить и фоновые задачи (поиск полей в Word → Excel)
    _brief_queue = None

    # ---------- первый запуск ----------

    def maybe_first_run(self):
        if SETUP.exists():
            return
        if self.indexer.folders():
            SETUP.write_text(json.dumps({'done': True}), encoding='utf-8')
            return
        self.first_run_window()

    def first_run_window(self):
        win = _window(self, 'первый запуск', '640x460')
        ttk.Label(win, text='Где лежат ваши документы?', font=('Segoe UI', 13, 'bold')).pack(anchor='w', padx=14, pady=(12, 4))
        ttk.Label(win, wraplength=600, style='Muted.TLabel', text=(
            'Искра прочитает Word, Excel, PowerPoint, PDF и текстовые файлы в отмеченных папках и будет искать по ним, '
            'следить за сроками и делать обзор. Всё остаётся на этом компьютере, файлы не изменяются. '
            'Первый раз чтение может занять от нескольких минут до получаса — работать можно сразу.')).pack(anchor='w', padx=14)
        box = ttk.Frame(win, padding=(14, 10)); box.pack(fill='both', expand=True)
        choices = []

        def add_row(label, path, on=True):
            var = tk.BooleanVar(value=on)
            ttk.Checkbutton(box, text=f'{label}: {path}', variable=var).pack(anchor='w', pady=2)
            choices.append((var, path))
        for label, path in candidate_folders():
            add_row(label, path, not label.startswith('Загрузки'))
        if not choices:
            ttk.Label(box, text='Стандартные папки не найдены — добавьте свою.').pack(anchor='w')

        def other():
            folder = filedialog.askdirectory(parent=win)
            if folder:
                add_row('Папка', str(Path(folder).resolve()))

        def start():
            chosen = [p for v, p in choices if v.get()]
            for p in chosen:
                self.indexer.add_folder(p)
            SETUP.write_text(json.dumps({'done': True, 'folders': chosen}, ensure_ascii=False), encoding='utf-8')
            win.destroy()
            if chosen:
                self.say(f'Собираю документы из папок: {len(chosen)}. Пока идёт чтение, поиск уже работает по готовым. '
                         'Когда закончу — спросите «обзор папок».')
        b = ttk.Frame(win, padding=(14, 0, 14, 12)); b.pack(fill='x')
        ttk.Button(b, text='Другая папка…', command=other).pack(side='left')
        ttk.Button(b, text='Начать', style='Accent.TButton', command=start).pack(side='right')
        ttk.Button(b, text='Позже', command=lambda: (SETUP.write_text('{"done": true}', encoding='utf-8'), win.destroy())).pack(side='right', padx=6)

    # ---------- обзор папок ----------

    def overview_window(self, folder=None):
        win = _window(self, 'обзор папок', '1040x680')
        pane = ttk.Panedwindow(win, orient='horizontal'); pane.pack(fill='both', expand=True, padx=10, pady=10)
        left = ttk.Frame(pane); pane.add(left, weight=1)
        ttk.Label(left, text='Папки (число документов):').pack(anchor='w')
        tree = ttk.Treeview(left, show='tree', selectmode='browse')
        tree.pack(fill='both', expand=True, pady=(4, 0))
        right = ttk.Frame(pane); pane.add(right, weight=3)
        text = tk.Text(right, wrap='word', font=('Segoe UI', 10), relief='flat', background='#FAFAFA', padx=10, pady=8)
        sc = ttk.Scrollbar(right, command=text.yview); text.configure(yscrollcommand=sc.set)
        sc.pack(side='right', fill='y'); text.pack(fill='both', expand=True)
        buttons = ttk.Frame(win, padding=(10, 0, 10, 10)); buttons.pack(fill='x')
        state = {'docs': None, 'folder': None, 'overview': ''}

        def show(value):
            text.configure(state='normal'); text.delete('1.0', 'end'); text.insert('1.0', value)

        def load():
            show('Читаю индекс документов…')

            def work():
                docs = list(iter_documents(OVERVIEW_CHARS))
                self.events.put(('call', lambda: fill(docs)))
            threading.Thread(target=work, daemon=True).start()

        def fill(docs):
            if not win.winfo_exists():
                return
            state['docs'] = docs
            tree.delete(*tree.get_children())
            roots = self.indexer.folders()
            if not roots:
                show('Папки для поиска не выбраны. Нажмите «Папки…» в главном окне.'); return
            counts = {}
            for path, _ in docs:
                for parent in Path(path).parents:
                    counts[str(parent)] = counts.get(str(parent), 0) + 1
            for root in roots:
                rid = tree.insert('', 'end', iid=root, text=f'{root} ({counts.get(str(Path(root)), 0)})', open=True)
                subs = set()
                for p, _ in docs:
                    parts = _parts(p, root)
                    if parts and len(parts) > 1:
                        subs.add(str(Path(root) / parts[0]))
                subs = sorted(subs)
                for s in subs[:200]:
                    if not tree.exists(s):
                        tree.insert(rid, 'end', iid=s, text=f'{Path(s).name} ({counts.get(s, 0)})')
            target = folder if folder and tree.exists(folder) else roots[0]
            tree.selection_set(target); tree.see(target)

        def select(_=None):
            sel = tree.selection()
            if not sel or state['docs'] is None:
                return
            chosen = sel[0]
            state['folder'] = chosen
            show('Составляю обзор…')

            def work():
                ov = render(folder_overview(chosen, state['docs']))
                self.events.put(('call', lambda: (state.__setitem__('overview', ov), show(ov)) if state['folder'] == chosen and win.winfo_exists() else None))
            threading.Thread(target=work, daemon=True).start()

        def summarize():
            if not state['overview']:
                return
            chosen = state['folder']
            docs = [(p, t) for p, t in state['docs'] if _under(p, chosen)][:40]
            heads = '\n'.join(f'— {Path(p).name}: ' + ' '.join(t.split('\n', 1)[-1].split())[:300] for p, t in docs)
            material = state['overview'] + '\n\nНАЧАЛО ДОКУМЕНТОВ:\n' + heads
            text.configure(state='normal'); text.insert('1.0', 'ОБОБЩЕНИЕ НЕЙРОСЕТИ (проверьте по документам):\n…\n\n' + '—' * 40 + '\n\n')
            text.mark_set('ai_end', '2.0'); text.mark_gravity('ai_end', 'left')

            def update(value):
                def put():
                    if win.winfo_exists():
                        text.delete('2.0', 'ai_end'); text.insert('2.0', value + '\n')
                self.events.put(('call', put))
            self.ai_background(lambda cancel: ai.summarize(f'Обзор папки {chosen}', material, on_text=update, cancel=cancel),
                               lambda result: save_history(ROOT, 'Обобщение папки', chosen))

        tree.bind('<<TreeviewSelect>>', select)
        ttk.Button(buttons, text='Открыть папку', command=lambda: state['folder'] and _open_path(state['folder'])).pack(side='left')
        ttk.Button(buttons, text='Обновить', command=load).pack(side='left', padx=6)
        ai_btn = ttk.Button(buttons, text='Обобщить нейросетью', style='Accent.TButton', command=summarize)
        ai_btn.pack(side='right')
        if not self.ai_ready:
            ai_btn.state(['disabled'])
            ttk.Label(buttons, text='нейросеть не установлена', style='Muted.TLabel').pack(side='right', padx=6)
        load()

    def chat_overview(self):
        roots = self.indexer.folders()
        if not roots:
            self.say('Папки для поиска не выбраны: кнопка «Папки…» вверху справа.'); return
        self.say('Смотрю, что лежит в папках…')

        def work():
            lines = folders_summary(roots, iter_documents(OVERVIEW_CHARS))
            self.events.put(('call', lambda: (self.say('Обзор папок:'), [self.say(x) for x in lines],
                                              self.say('Подробно по любой папке и вложенным — окно «Обзор папок».', 'proof'),
                                              self.overview_window())))
        threading.Thread(target=work, daemon=True).start()

    # ---------- нейросеть ----------

    def ai_status_line(self):
        if self.ai_ready:
            return f'Нейросеть: {ai.model_name()} — работает на этом компьютере, без интернета.'
        _, model = ai.local_files()
        if model is not None and ai.missing_parts(model):
            return ('Нейросеть: не хватает второй части модели — распакуйте Iskra-Windows-AI-chast-2.zip '
                    'в ту же папку, что и первую часть, и перезапустите Искру.')
        return 'Нейросеть не установлена (версия без модели): работают поиск, сроки, свод, шаблоны телеграмм и формулы.'

    def ai_background(self, job, done=None):
        """Запуск модели в фоне: одна задача за раз, Esc или «Стоп» — остановить."""
        if not self.ai_ready:
            messagebox.showinfo('Нейросеть', 'Нейросеть не установлена. Скачайте версию Искры «с нейросетью» (Iskra-Windows-AI.zip).')
            return
        if self.ai_cancel is not None:
            messagebox.showinfo('Нейросеть', 'Нейросеть ещё пишет предыдущий ответ. Подождите или нажмите «Стоп».')
            return
        cancel = threading.Event()
        self.ai_cancel = cancel
        self.status.set('Нейросеть пишет… (Esc — остановить)')
        if getattr(self, 'stop_btn', None):
            self.stop_btn.state(['!disabled'])

        def finish(result=None, error=None):
            self.ai_cancel = None
            self.status.set('Готов к работе')
            if getattr(self, 'stop_btn', None):
                self.stop_btn.state(['disabled'])
            if error:
                self.say('Нейросеть: ' + error)
            elif done:
                done(result)

        def work():
            try:
                result = job(cancel)
                self.events.put(('call', lambda: finish(result)))
            except ai.AIError as exc:
                msg = str(exc)
                self.events.put(('call', lambda: finish(error=msg)))
            except Exception as exc:
                msg = f'ошибка: {exc}'
                self.events.put(('call', lambda: finish(error=msg)))
        threading.Thread(target=work, daemon=True).start()

    def ai_stop(self, _=None):
        if self.ai_cancel is not None:
            self.ai_cancel.set()
        self.ai_cancel_all.set()

    # ---------- нейросеть пишет прямо в редактор ----------

    def ai_into_editor(self, editor, job, sources, title):
        """editor = (окно, поле текста, строка состояния) из telegrams(). Пока нейросеть пишет, в редакторе черновик по правилам;
        затем он заменяется её текстом. Числа и даты, которых нет в источниках, подсвечиваются."""
        if not editor or not self.ai_ready:
            return
        win, t, status = editor
        original = t.get('1.0', 'end-1c')
        tail = original[original.find('--- ИСТОЧНИКИ'):] if '--- ИСТОЧНИКИ' in original else ''
        t.tag_configure('unverified', background='#FFE0B2')
        status.set(f'{title}: нейросеть пишет… (пока здесь черновик по шаблону; Esc в главном окне — остановить)')
        state = {'started': False}

        def update(value):
            def put():
                if not win.winfo_exists() or not value or value.startswith('…'):
                    return
                if not state['started']:
                    state['started'] = True
                    t.edit_separator()
                t.delete('1.0', 'end'); t.insert('1.0', value)
            self.events.put(('call', put))

        def done(result):
            if not win.winfo_exists():
                return
            t.delete('1.0', 'end'); t.insert('1.0', result + ('\n\n' + tail if tail else ''))
            doubtful = ai.unverified(result, sources)
            for start, end in ai.fact_spans(result, doubtful):
                t.tag_add('unverified', f'1.0+{start}c', f'1.0+{end}c')
            msg = f'{title}: готово. Отменить — Ctrl+Z (вернётся черновик по шаблону).'
            if doubtful:
                msg += ' ПРОВЕРЬТЕ — этих чисел/дат нет в документах (подсвечены): ' + ', '.join(doubtful[:10])
            else:
                msg += ' Все числа и даты есть в документах.'
            status.set(msg)
            save_history(ROOT, title, (sources[0][0] if sources else '')[:200])

        def job_with_errors(cancel):
            try:
                return job(cancel, update)
            except ai.AIError:
                self.events.put(('call', lambda: win.winfo_exists() and (
                    t.delete('1.0', 'end'), t.insert('1.0', original))))
                raise
        self.ai_background(job_with_errors, done)

    # ---------- входящие: краткая справка нейросети в фоне ----------

    def inbox_briefs(self, items):
        """Каждый новый документ нейросеть кратко описывает в фоне (по одному, не мешая работе)."""
        import queue as _queue
        if self._brief_queue is None:
            self._brief_queue = _queue.Queue()

            def worker():
                while True:
                    it = self._brief_queue.get()
                    try:
                        text = extract(Path(it['path']))
                        result = ai.brief(text)
                        self.inbox.update(it['path'], ai_brief=' '.join(result.split())[:600])
                        self.events.put(('call', lambda: (self.refresh_inbox(), self.inbox_show())))
                    except Exception:
                        pass
            threading.Thread(target=worker, daemon=True).start()
        for it in items:
            self._brief_queue.put(it)

    # ---------- понимание свободной фразы ----------

    def ai_route(self, text):
        """Фраза не похожа ни на одну команду — нейросеть решает, что сделать."""
        self.say('Понимаю, что нужно…', 'proof')

        def job(cancel):
            return ai.route(text, cancel=cancel)

        def done(result):
            cmd, what = result
            if cmd in ai.NEEDS_DOC and self.selected() is None:
                cmd, what = 'ask', text                 # документ не выбран — ищем ответ по всем документам
            if cmd == 'chat':
                self.ai_chat(text)
            elif cmd == 'search':
                self.query.set(what or text); self.find(report=True)
            else:
                self.say(f'Поняла так: {ai.COMMANDS.get(cmd, cmd)}.', 'proof')
                self.ask(what if cmd in ('ask', 'write', 'formula', 'macro') and what else text, routed=cmd)
        self.ai_background(job, done)

    def ai_chat(self, text):
        def job(cancel):
            self.events.put(('call', lambda: self.tabs.select(0)))
            update = self._stream_to_chat('Нейросеть:')
            return ai.chat(text, on_text=update, cancel=cancel)
        self.ai_background(job, lambda result: self.say('(ответ нейросети без документов — проверьте важное)', 'proof'))

    def _stream_to_chat(self, title):
        """Функция для фонового потока: показывает текст нейросети в чате по мере написания.
        Окно меняется только в главном потоке — через очередь событий."""
        state = {'started': False}

        def put(value):
            self.chat.configure(state='normal')
            if not state['started']:
                state['started'] = True
                self.chat.insert('end', title + '\n', 'value')
                self.chat.mark_set('ai_start', 'end-1c'); self.chat.mark_gravity('ai_start', 'left')
            self.chat.delete('ai_start', 'end-1c')
            self.chat.insert('ai_start', (value or '…') + '\n', 'iskra')
            self.chat.configure(state='disabled'); self.chat.see('end')

        def update(value):
            self.events.put(('call', lambda v=value: put(v)))
        update('…')
        return update

    def _chosen_doc(self, text):
        """Выбранный в списке документ, если в задаче сказано «по этому документу». Только в главном потоке."""
        i = self.selected()
        if i is not None and any(k in text.lower() for k in SELECTED_DOC):
            return [self.results[i][0]]
        return []

    @staticmethod
    def _sources_for(text, extra):
        return ai.retrieve(text, lambda q, any_word: search_docs(q, 6, any_word), lambda p: extract(Path(p)), extra=extra)

    def ai_write(self, task):
        if not self.ai_ready:
            self.say('Свободный текст пишет нейросеть, а она не установлена. Открываю шаблоны телеграмм.')
            self.compose_window(); return

        extra = self._chosen_doc(task)
        me = self.my_details()

        def job(cancel):
            sources, paths = self._sources_for(task, extra)
            self.events.put(('call', lambda: self.say(
                ('Взяла материалы из: ' + ', '.join(Path(p).name for p in paths)) if paths else
                'Подходящих документов не нашла — пишу по задаче, факты помечу [УТОЧНИТЬ].', 'proof')))
            self.events.put(('call', lambda: self.tabs.select(0)))
            update = self._stream_to_chat('Черновик (нейросеть):')
            text, _ = ai.write(task, sources, me=me, on_text=update, cancel=cancel)
            return text, paths

        def done(result):
            text, paths = result
            save_history(ROOT, 'Нейросеть: текст', task[:200])
            self.telegrams(initial=text + ('\n\n--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---\n' +
                                           '\n'.join(f'{i}. {Path(p).name}' for i, p in enumerate(paths, 1)) if paths else ''),
                           note='Черновик нейросети. Проверьте факты по источникам, впишите [УТОЧНИТЬ…], затем «Орфография».')
        self.ai_background(job, done)

    def ai_ask(self, question):
        extra = self._chosen_doc(question)

        def job(cancel):
            sources, paths = self._sources_for(question, extra)
            if not sources:
                raise ai.AIError('по вопросу не нашла документов. Попробуйте другие слова или «найди …».')
            self.events.put(('call', lambda: self.tabs.select(0)))
            update = self._stream_to_chat('Ответ по документам (нейросеть):')
            text, _ = ai.answer(question, sources, on_text=update, cancel=cancel)
            return paths

        def done(paths):
            self.say('Проверить: ' + ', '.join(Path(p).name for p in paths), 'proof')
            self.results = [(p, '') for p in paths]
            self.listbox.delete(0, 'end')
            for p in paths:
                self.listbox.insert('end', Path(p).name)
            self.found_label.set(f'Документы для ответа: {len(paths)} — двойной щелчок откроет')
        self.ai_background(job, done)

    def ai_formula(self, task):
        def job(cancel):
            return ai.formula(task, cancel=cancel)

        def done(result):
            f, note = result
            from iskra_formula import explain_formula
            self.say('Формула от нейросети (проверьте диапазоны):')
            self.say(f, 'value')
            if note:
                self.say(note, 'proof')
            self.say('Из чего состоит:\n' + explain_formula(f))
        self.say('Готовой формулы в справочнике нет — спрашиваю нейросеть…', 'proof')
        self.ai_background(job, done)

    def editor_ai(self, parent, text_widget, status):
        """Кнопка «Нейросеть ▾» в редакторе телеграмм."""
        mb = ttk.Menubutton(parent, text='Нейросеть ▾')
        menu = tk.Menu(mb, tearoff=False)
        mb['menu'] = menu

        def run(how):
            original = text_widget.get('1.0', 'end-1c')
            if not original.strip():
                return
            body, sep, tail = original.partition('--- ИСТОЧНИКИ')
            status.set(f'Нейросеть: «{how}»… (Esc в главном окне — остановить)')

            def update(value):
                def put():
                    if text_widget.winfo_exists():
                        text_widget.delete('1.0', 'end'); text_widget.insert('1.0', value)
                self.events.put(('call', put))

            def done(result):
                if text_widget.winfo_exists():
                    text_widget.delete('1.0', 'end')
                    text_widget.insert('1.0', result + ('\n\n' + sep + tail if sep else ''))
                    status.set(f'Готово: «{how}». Отменить — Ctrl+Z.')
            text_widget.edit_separator()
            self.ai_background(lambda cancel: ai.edit(body, how, on_text=update, cancel=cancel), done)
        for how in ai.EDITS:
            menu.add_command(label=how, command=lambda h=how: run(h))
        if not self.ai_ready:
            mb.state(['disabled'])
        return mb


def _parts(path, folder):
    """Части пути внутри папки (без учёта регистра на Windows) или None."""
    a, b = os.path.normcase(str(Path(path))), os.path.normcase(str(Path(folder)))
    if not a.startswith(b.rstrip(os.sep) + os.sep):
        return None
    return Path(str(path)[len(str(Path(folder)).rstrip(os.sep)) + 1:]).parts


def _under(path, folder):
    return _parts(path, folder) is not None
