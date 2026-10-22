"""Окна и команды: первый запуск (какие папки собрать), обзор папок, локальная нейросеть в чате и в редакторе."""
import json
import os
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import iskra_addons
from iskra_errors import friendly_error  # noqa: F401  (и для других окон)
import iskra_assistant as assistant
import iskra_ai as ai
from iskra_index import ROOT, extract, iter_documents, search_docs
from iskra_overview import candidate_folders, folder_overview, folders_summary, render
from iskra_tools_ui import _window, _open_path
from iskra_workflows import save_history

SETUP = ROOT / 'setup.json'
OVERVIEW_CHARS = 30000
SELECTED_DOC = ('по этому документ', 'по выбранному', 'по нему', 'на него', 'на эту', 'на этот', 'этого документ')
# «по найденным», «по всем этим» — взять все документы из списка результатов слева.
ALL_LISTED = ('по найденн', 'по всем найденн', 'по всем этим', 'по этим документ', 'по списку слева', 'по всем документам из списка',
              'из найденн', 'все найденн')


def editor_busy(t, status=None):
    """Нейросеть сейчас пишет в этот редактор — другие действия с ним подождут (иначе правка потеряется)."""
    if getattr(t, 'iskra_busy', False):
        if status is not None:
            status.set('Подождите: нейросеть ещё пишет в этот текст (Esc — остановить).')
        return True
    return False


class EditorStream:
    """Нейросеть пишет в редактор. Пока пишет — поле только для чтения (набранное человеком не затрётся) и без
    сотен шагов в истории отмены; в конце одна замена — Ctrl+Z возвращает прежний текст одним нажатием."""

    def __init__(self, app, win, t, status=None):
        self.app, self.win, self.t, self.status = app, win, t, status
        self.original = t.get('1.0', 'end-1c')
        self._versions('до нейросети', self.original)
        self.t.iskra_busy = True                     # кнопки редактора ждут, пока нейросеть допишет
        self.t.configure(undo=False, state='disabled')

    def _versions(self, why, text):
        save = getattr(self.t, 'iskra_on_replace', None)      # редактор с автосохранением — отложить версию
        if save is not None:
            try:
                save(text, why)
            except Exception:                              # noqa: BLE001 — версия не должна мешать нейросети
                pass

    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _set(self, value):
        self.t.configure(state='normal')
        self.t.delete('1.0', 'end'); self.t.insert('1.0', value)

    def update(self, value):
        """Для фонового потока: показать текст по мере написания."""
        def put():
            if self.alive() and value and not value.startswith('…'):
                self._set(value)
                self.t.configure(state='disabled')
            elif self.alive() and value and value.startswith('…') and self.status is not None:
                self.status.set(value.strip('… '))
        self.app.events.put(('call', put))

    def finish(self, final):
        self.t.iskra_busy = False
        if not self.alive():
            return False
        self._set(self.original)                     # история отмены — от прежнего текста
        self.t.configure(undo=True, autoseparators=False)
        self.t.edit_separator()
        self.t.delete('1.0', 'end'); self.t.insert('1.0', final)
        self.t.edit_separator()
        self.t.iskra_ai_text = final                 # с чем сравнить при сохранении: так Искра учится на правках
        self._versions('текст нейросети', final)
        self.t.configure(autoseparators=True)
        try:
            self.win.lift()
        except tk.TclError:
            pass
        return True

    def fail(self, message):
        self.t.iskra_busy = False
        if not self.alive():
            return
        self._set(self.original)
        self.t.configure(undo=True)
        if self.status is not None:
            self.status.set('Нейросеть: ' + message + ' Текст остался прежним.')


class AIMixin:
    ai_ready = False
    ai_cancel = None
    ai_cancel_all = threading.Event()      # Esc: остановить и фоновые задачи (поиск полей в Word → Excel)
    _ai_queue = None                       # задачи человека, ждущие очереди
    _bg_jobs = None                        # фоновые задачи (входящие, поручения)
    _bg_running = False
    _bg_yield = None                       # установлен — фоновая задача уступает модель человеку
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
            line = f'Нейросеть: {ai.model_name()} — работает на этом компьютере, без интернета.'
            ram = ai.ram_gb()
            if 0 < ram < 7:
                line += (f' Оперативной памяти {ram:.0f} ГБ — модели нужно около 4 ГБ свободной памяти: '
                         'перед работой с нейросетью закройте лишние программы.')
            return line
        binary, model = ai.local_files()
        if model is not None and not binary.is_file():
            return ('Нейросеть: нет папки engine с llama-completion.exe — распакуйте часть 1 (Iskra-AI-chast-01) заново. '
                    'Если файл пропадает сразу после распаковки — его удаляет антивирус: добавьте папку Искры в исключения.')
        if model is not None and ai.missing_parts(model):
            return ('Нейросеть: не хватает частей модели (' + ', '.join(ai.missing_parts(model)) + '). Распакуйте все архивы '
                    'Iskra-AI-chast-… в одну папку и перезапустите Искру.')
        if binary.is_file():
            return ('Нейросеть: программа есть, а модели нет — распакуйте архивы Iskra-AI-chast-02 … chast-10 '
                    'в ту же папку, что и часть 1, и перезапустите Искру.')
        return 'Нейросеть не установлена (версия без модели): работают поиск, сроки, свод, шаблоны телеграмм и формулы.'

    def addons_status_line(self):
        scans = ('Сканы и фото документов: распознаются (без интернета).' if iskra_addons.installed('ocr') else
                 'Сканы не распознаются — нужен дополнительный архив Iskra-dop-skany.zip.')
        voice = ('Голосовые команды: кнопка «Сказать».' if iskra_addons.installed('voice') else
                 'Голосовые команды — дополнительный архив Iskra-dop-golos.zip.')
        return scans + ' ' + voice

    def ai_gather(self):
        """Части модели, распакованные в отдельные папки, переносятся к программе (в фоне: с другого диска — копирование)."""
        def work():
            try:
                addons = iskra_addons.gather()
            except Exception:
                addons = []
            try:
                moved = 0 if self.ai_ready else ai.gather_parts()
            except Exception:
                moved = 0
            if moved:
                def done():
                    self.ai_ready = ai.available()
                    self.say(f'Нашла {moved} част(ей) модели в соседних папках и перенесла их к программе.', 'proof')
                    self.say(self.ai_status_line(), 'proof')
                self.events.put(('call', done))
            if addons:
                def enable():
                    self.say('Нашла дополнения в соседних папках и подключила их.', 'proof')
                    self.say(self.addons_status_line(), 'proof')
                    if 'voice' in addons and getattr(self, 'voice_btn', None):
                        self.voice_btn.state(['!disabled'])
                self.events.put(('call', enable))
        threading.Thread(target=work, daemon=True).start()

    def ai_check(self):
        """Меню «Файл → Проверить нейросеть»: короткий настоящий ответ модели или понятная причина сбоя."""
        self.ai_ready = ai.available()
        if not self.ai_ready:
            messagebox.showwarning('Нейросеть', self.ai_status_line())
            return
        self.say('Проверяю нейросеть: короткий ответ, обычно 10–60 секунд…', 'proof')

        def work():
            import time
            t = time.time()
            try:
                text = ai.run(ai.chat_prompt('Ответь одним словом по-русски: готово.'), max_tokens=16, timeout=300)
                msg = f'Нейросеть работает: ответила «{text[:60]}» за {time.time() - t:.0f} с. Интернет не использовался.'
                self.events.put(('call', lambda: (self.say(msg, 'proof'), messagebox.showinfo('Нейросеть', msg))))
            except ai.AIError as exc:
                msg = str(exc) + '\n\nЖурнал: папка данных → ai_log.txt'
                from iskra_clipboard import show_text
                self.events.put(('call', lambda: (self.say(msg), show_text(self.root, 'Нейросеть', msg, warn=True))))
        threading.Thread(target=work, daemon=True).start()

    def ai_background(self, job, done=None, on_error=None, background=False, label=''):
        """Задача нейросети в фоне. Задачи человека идут по очереди (вторая не отклоняется, а ждёт первую)
        и всегда раньше фоновых (справки о входящих, поручения): фоновая уступает, а потом продолжается.
        on_error(текст) — чтобы окно, откуда пришла задача, не осталось с надписью «пишет…»."""
        if not self.ai_ready:
            if on_error:
                on_error(self.ai_status_line())
            else:
                messagebox.showinfo('Нейросеть', self.ai_status_line())
            return
        if background:
            self._bg_jobs.append((job, done))
            self._bg_next()
            return
        if self.ai_cancel is not None:
            self._ai_queue.append((job, done, on_error, label))
            self.say(f'Поставила в очередь{": " + label if label else ""} — начну сразу после текущего ответа.', 'proof')
            return
        self._ai_start(job, done, on_error)

    def _ai_start(self, job, done, on_error):
        cancel = threading.Event()
        self.ai_cancel = cancel
        self._bg_yield.set()                       # фоновая задача уступает модель человеку
        self.status.set('Нейросеть пишет… (Esc — остановить)')
        if getattr(self, 'stop_btn', None):
            self.stop_btn.state(['!disabled'])

        def finish(result=None, error=None):
            self.ai_cancel = None
            if getattr(self, 'stop_btn', None):
                self.stop_btn.state(['disabled'])
            try:
                if error:
                    self.say('Нейросеть: ' + error)
                    if on_error:
                        on_error(error)
                elif done:
                    done(result)
            finally:
                if self.ai_cancel is not None:
                    pass                                   # done() уже запустил следующую задачу (уточнение)
                elif self._ai_queue:
                    job2, done2, err2, _ = self._ai_queue.pop(0)
                    self._ai_start(job2, done2, err2)
                else:
                    self.status.set('Готов к работе')
                    self._bg_yield.clear()
                    self._bg_next()

        def work():
            try:
                result = job(cancel)
                self.events.put(('call', lambda: finish(result)))
            except ai.AIError as exc:
                msg = str(exc)
                self.events.put(('call', lambda: finish(error=msg)))
            except Exception as exc:
                msg = friendly_error(exc)
                ai.write_log('Ошибка задачи нейросети: ' + repr(exc))
                self.events.put(('call', lambda: finish(error=msg)))
        threading.Thread(target=work, daemon=True).start()

    def _bg_next(self):
        """Следующая фоновая задача — только когда человек ничего не ждёт."""
        if self._bg_running or self.ai_cancel is not None or not self._bg_jobs:
            return
        job, done = self._bg_jobs.pop(0)
        self._bg_running = True

        def work():
            yielded = False
            try:
                result = job(self._bg_yield)
                yielded = self._bg_yield.is_set()
                ok = not yielded
            except ai.AIError:
                yielded = self._bg_yield.is_set()     # запомнить сейчас: к разбору итога флаг может уже сброситься
                result, ok = None, False
            except Exception as exc:
                ai.write_log('Фоновая задача: ' + repr(exc))
                result, ok = None, True                # ошибка — не повторяем
            def after():
                self._bg_running = False
                if ok:
                    if done and result is not None:
                        try:
                            done(result)
                        except Exception as exc:
                            ai.write_log('Фоновая задача (итог): ' + repr(exc))
                elif yielded:
                    self._bg_jobs.insert(0, (job, done))   # уступила человеку — повторим потом
                self._bg_next()
            self.events.put(('call', after))
        threading.Thread(target=work, daemon=True).start()

    def ai_busy(self):
        return self.ai_cancel is not None

    def ai_stop(self, _=None):
        if self.ai_cancel is not None:
            self.ai_cancel.set()
            if self._ai_queue:
                self.say(f'Остановила. В очереди ещё: {len(self._ai_queue)}.', 'proof')
        else:
            self.ai_cancel_all.set()               # нет задачи в чате — остановить подбор полей Word → Excel

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
        status.set(f'{title}: нейросеть пишет… (пока здесь черновик по шаблону; Esc — остановить)')
        stream = EditorStream(self, win, t, status)

        def done(result):
            final = result + ('\n\n' + tail if tail else '')
            if not stream.finish(final):
                return
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
            # Запомнить, чтобы «сделай короче» в чате правило этот черновик.
            self.remember('write', title, result, sources, [], editor)

        self.ai_background(lambda cancel: job(cancel, stream.update), done, on_error=stream.fail, label=title)

    # ---------- входящие: краткая справка нейросети в фоне ----------

    def inbox_briefs(self, items):
        """Каждый новый документ нейросеть кратко описывает в фоне — уступая задачам человека."""
        for it in items:
            def job(cancel, it=it):
                text = extract(Path(it['path']))
                return it, ai.brief(text, cancel=cancel)

            def done(result):
                it, brief = result
                self.inbox.update(it['path'], ai_brief=' '.join(brief.split())[:600])
                self.refresh_inbox()
                self.inbox_show()
            self.ai_background(job, done, background=True)

    # ---------- понимание свободной фразы ----------

    # ---------- память разговора: уточнения правят прошлый ответ ----------

    def remember(self, kind, request, answer, sources=(), paths=(), editor=None):
        prev = getattr(self, 'last_ai', None)
        history = (prev['history'] if prev and kind in ('ask', 'chat') and prev['kind'] == kind else []) + [(request, answer)]
        self.last_ai = {'kind': kind, 'request': request, 'answer': answer, 'sources': list(sources), 'paths': list(paths),
                        'editor': editor, 'history': history[-4:], 'time': time.monotonic()}
        hints = {'write': '«сделай короче», «поменяй срок на 30.10», «добавь пункт о …», «адресат — начальник штаба»',
                 'ask': '«а кто подписал?», «а срок какой?», «ответь списком»',
                 'chat': '«подробнее», «а если …», «приведи пример»',
                 'formula': '«а если по столбцу D», «только для полигона», «без пустых»'}
        self.say(f'Можно уточнить — поправлю этот же ответ: {hints[kind]}. Начать заново: «новое: …».', 'proof')

    def check_facts(self, answer, sources):
        """Числа и даты ответа, которых нет в документах, — сказать сразу (нейросеть могла выдумать)."""
        if not sources:
            return
        doubtful = ai.unverified(answer, sources)
        if doubtful:
            self.say('Проверьте: этих чисел/дат нет в документах — ' + ', '.join(doubtful[:10]), 'proof')

    def _editor_alive(self, editor):
        try:
            return bool(editor) and editor[0].winfo_exists()
        except tk.TclError:
            return False

    def ai_followup(self, text):
        last = getattr(self, 'last_ai', None)
        if not last:
            # Прошлый ответ не сохранился (ошибка, «Стоп» или окно без памяти) — выполняем как обычную просьбу.
            cmd, _ = assistant.intent(text)
            self.ask(text, routed='ask' if cmd in ('search', 'ask') else cmd)
            return
        kind = last['kind']
        me = self.my_details()
        if kind in ('ask', 'chat') and assistant.is_question(text):
            self.say('Продолжаю разговор (те же документы).' if last['sources'] else 'Продолжаю разговор.', 'proof')

            def job(cancel):
                update = self._stream_to_chat('Ответ (продолжение):')
                return ai.followup(last['history'], text, last['sources'], on_text=update, cancel=cancel)

            def done(answer):
                self.check_facts(answer, last['sources'])
                self.remember(kind, text, answer, last['sources'], last['paths'])
            self.ai_background(job, done)
            return
        if kind == 'formula':
            self.say('Поправляю формулу.', 'proof')
            task = f'{last["request"]}. Уточнение: {text}. Предыдущий вариант формулы: {last["answer"]}'

            def done_formula(result):
                f, note = result
                from iskra_formula import explain_formula
                self.say('Исправленная формула (проверьте диапазоны):')
                self.say(f, 'value')
                if note:
                    self.say(note, 'proof')
                self.say('Из чего состоит:\n' + explain_formula(f))
                self.remember('formula', task, f)
            self.ai_background(lambda cancel: ai.formula(task, cancel=cancel), done_formula)
            return
        editor = last.get('editor')
        if kind == 'write' and self._editor_alive(editor):
            win, t, status = editor
            whole = t.get('1.0', 'end-1c')
            previous, sep, tail = whole.partition('--- ИСТОЧНИКИ')
            self.say('Поправляю черновик в открытом редакторе (Ctrl+Z — вернуть как было).', 'proof')
            status.set(f'Нейросеть правит: «{text}»… (Esc — остановить)')
            stream = EditorStream(self, win, t, status)

            def done_edit(result):
                if stream.finish(result + ('\n\n' + sep + tail if sep else '')):
                    doubtful = ai.unverified(result, last['sources'] + [('просьба', text), ('прошлый текст', previous)])
                    status.set(f'Поправлено: «{text}». Отменить — Ctrl+Z.' +
                               (' Проверьте — этого не было ни в документах, ни в просьбе: ' + ', '.join(doubtful[:8]) if doubtful else ''))
                last['answer'], last['time'] = result, time.monotonic()
                self.say('Готово — черновик в редакторе исправлен. Можно уточнять дальше.', 'proof')
            self.ai_background(lambda cancel: ai.revise(last['request'], previous.strip(), text, last['sources'], me=me,
                                                        on_text=stream.update, cancel=cancel), done_edit,
                               on_error=stream.fail, label=f'«{text}»')
            return
        self.say('Поправляю предыдущий ответ.', 'proof')

        def job(cancel):
            update = self._stream_to_chat('Исправленный вариант:')
            return ai.revise(last['request'], last['answer'], text, last['sources'], me=me, kind=kind,
                             on_text=update, cancel=cancel)

        def done(result):
            if kind == 'write':
                editor = self.telegrams(initial=result, note='Исправленный черновик нейросети. Проверьте факты.',
                                        source_paths=last['paths'], source_texts=[] if last['paths'] else last['sources'])
                self.remember('write', last['request'], result, last['sources'], last['paths'], editor)
            else:
                self.remember(kind, last['request'], result, last['sources'], last['paths'])
        self.ai_background(job, done, label=f'«{text}»')

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
                # Для текста и вопроса — слова человека как есть («по найденным», «тлг» не теряются).
                self.ask(what if cmd in ('formula', 'macro') and what else text, routed=cmd)
        self.ai_background(job, done)

    def ai_chat(self, text):
        def job(cancel):
            self.events.put(('call', lambda: self.tabs.select(0)))
            update = self._stream_to_chat('Нейросеть:')
            return ai.chat(text, on_text=update, cancel=cancel)

        def done(result):
            self.say('(ответ нейросети без документов — проверьте важное)', 'proof')
            self.remember('chat', text, result)
        self.ai_background(job, done)

    def _stream_to_chat(self, title):
        """Функция для фонового потока: показывает текст нейросети в чате по мере написания.
        Окно меняется только в главном потоке — через очередь событий."""
        AIMixin._streams = getattr(AIMixin, '_streams', 0) + 1
        a, b = f'ai_s{AIMixin._streams}', f'ai_e{AIMixin._streams}'
        state = {'started': False}

        def put(value):
            # Меняется только свой кусок чата (между метками a и b): сообщения, пришедшие во время ответа
            # («Беру документы…», «Новый файл…»), остаются на месте.
            self.chat.configure(state='normal')
            if not state['started']:
                state['started'] = True
                self.chat.insert('end', title + '\n', 'value')
                self.chat.mark_set(a, 'end-1c'); self.chat.mark_gravity(a, 'left')
                self.chat.mark_set(b, 'end-1c'); self.chat.mark_gravity(b, 'left')
            piece = (value or '…') + '\n'
            self.chat.delete(a, b)
            self.chat.insert(a, piece, 'iskra')
            self.chat.mark_set(b, f'{a} + {len(piece)} chars')
            self.chat.configure(state='disabled'); self.chat.see('end')

        def update(value):
            self.events.put(('call', lambda v=value: put(v)))
        update('…')
        return update

    def _chosen_doc(self, text):
        """Документы, которые пользователь явно указал: выбранный в списке («по этому документу») или все найденные
        («по найденным»). Только в главном потоке."""
        low = text.lower()
        if self.results and any(k in low for k in ALL_LISTED):
            return [p for p, _ in self.results[:30]]
        i = self.selected()
        if i is not None and any(k in low for k in SELECTED_DOC):
            return [self.results[i][0]]
        return []

    @staticmethod
    def _sources_for(text, extra):
        import iskra_smartsearch
        return ai.retrieve(text, lambda q, any_word: search_docs(q, 20, any_word), lambda p: extract(Path(p)), extra=extra,
                           smart_fn=lambda q: iskra_smartsearch.smart_search(q, 20, ROOT)[0])

    def _gather(self, task, extra, cancel, update):
        """Найти документы, показать какие, и если их много — выписать нужное из каждого."""
        sources, paths = self._sources_for(task, extra)
        names = [Path(p).name for p in paths]
        self.events.put(('call', lambda: self.say(
            (f'Беру документы ({len(names)}): ' + ', '.join(names)) if names else
            'Подходящих документов не нашла — пишу по задаче, факты помечу [УТОЧНИТЬ]. '
            'Чтобы писать по своим документам: «найди …», затем «напиши … по найденным».', 'proof')))
        full = list(sources)
        if len(sources) > 1:
            sources = ai.condense(task, sources, on_progress=update, cancel=cancel)
        return sources, full, paths

    def ai_write(self, task):
        if not self.ai_ready:
            self.say('Свободный текст пишет нейросеть, а она не установлена. Открываю шаблоны телеграмм.')
            self.compose_window(); return

        extra = self._chosen_doc(task)
        me = self.my_details()

        def job(cancel):
            self.events.put(('call', lambda: self.tabs.select(0)))
            update = self._stream_to_chat('Черновик (нейросеть):')
            sources, full, paths = self._gather(task, extra, cancel, update)
            text, cut = ai.write(task, sources, me=me, on_text=update, cancel=cancel)
            if cut:
                self.events.put(('call', lambda: self.say('Не поместились целиком: ' + ', '.join(cut) +
                                                          ' — проверьте, всё ли учтено.', 'proof')))
            return text, paths, full

        def done(result):
            text, paths, sources = result
            save_history(ROOT, 'Нейросеть: текст', task[:200])
            editor = self.telegrams(initial=text + ('\n\n--- ИСТОЧНИКИ (НЕ ЧАСТЬ ТЕЛЕГРАММЫ) ---\n' +
                                           '\n'.join(f'{i}. {Path(p).name}' for i, p in enumerate(paths, 1)) if paths else ''),
                           note='Черновик нейросети. Проверьте факты по источникам, впишите [УТОЧНИТЬ…], затем «Проверить перед отправкой».',
                           source_paths=paths)
            self.remember('write', task, text, sources, paths, editor)
        self.ai_background(job, done, label='черновик')

    def ai_ask(self, question):
        extra = self._chosen_doc(question)

        def job(cancel):
            self.events.put(('call', lambda: self.tabs.select(0)))
            update = self._stream_to_chat('Ответ по документам (нейросеть):')
            sources, full, paths = self._gather(question, extra, cancel, update)
            if not full:
                raise ai.AIError('по вопросу не нашла документов. Попробуйте другие слова или «найди …».')
            text, _ = ai.answer(question, sources, on_text=update, cancel=cancel)
            return text, full, paths

        def done(result):
            text, sources, paths = result
            self.check_facts(text, sources)
            self.remember('ask', question, text, sources, paths)
            # Список результатов поиска слева не трогаем — документы ответа просто перечислены здесь.
            self.say('Документы ответа: ' + ', '.join(Path(p).name for p in paths), 'proof')
        self.ai_background(job, done, label='ответ по документам')

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
            self.remember('formula', task, f)
        self.say('Готовой формулы в справочнике нет — спрашиваю нейросеть…', 'proof')
        self.ai_background(job, done)

    def editor_ai(self, parent, text_widget, status):
        """Кнопка «Нейросеть ▾» в редакторе телеграмм."""
        mb = ttk.Menubutton(parent, text='Нейросеть ▾')
        menu = tk.Menu(mb, tearoff=False)
        mb['menu'] = menu

        def run(how, change=None):
            if editor_busy(text_widget, status):
                return
            original = text_widget.get('1.0', 'end-1c')
            if not original.strip():
                return
            body, sep, tail = original.partition('--- ИСТОЧНИКИ')
            label = change or how
            status.set(f'Нейросеть: «{label}»… (Esc — остановить)')
            stream = EditorStream(self, text_widget.winfo_toplevel(), text_widget, status)

            def done(result):
                if stream.finish(result + ('\n\n' + sep + tail if sep else '')):
                    status.set(f'Готово: «{label}». Отменить — Ctrl+Z.')
            if change:
                # Своими словами — как уточнение: меняется только то, что просят (подпись, адресат, даты — как были).
                job = lambda cancel: ai.revise('телеграмма', body.strip(), change, me=self.my_details(),
                                               on_text=stream.update, cancel=cancel)
            else:
                job = lambda cancel: ai.edit(body, how, on_text=stream.update, cancel=cancel)
            self.ai_background(job, done, on_error=stream.fail, label=f'«{label}»')
        for how in ai.EDITS:
            menu.add_command(label=how, command=lambda h=how: run(h))

        def own():
            from tkinter import simpledialog
            how = simpledialog.askstring('Поправить', 'Что изменить? Например: «поменяй срок на 30.10.2026», '
                                         '«добавь пункт о технике», «адресат — начальник штаба»', parent=text_widget.winfo_toplevel())
            if how and how.strip():
                run(None, change=how.strip())
        menu.add_separator()
        menu.add_command(label='Поправить своими словами…', command=own)
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
