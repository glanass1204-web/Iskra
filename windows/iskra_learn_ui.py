"""Окно «Чему научилась Искра» и фоновое обучение по документам (справочник, словарь)."""
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import iskra_harvest
import iskra_learn
import iskra_memory
from iskra_tools_ui import _window

FIRST_RUN = 120_000          # мс после запуска: сначала пусть проиндексируются папки
EVERY = 6 * 3600 * 1000      # потом — раз в 6 часов


class LearnMixin:
    _harvest_running = False
    harvest_result = None

    def start_learning(self):
        self.root.after(FIRST_RUN, self.harvest_now)

    def harvest_now(self, announce=False, done=None):
        """Пройти по документам в фоне: кандидаты в справочник и слова для словаря."""
        if self._harvest_running:
            return
        self._harvest_running = True
        people = getattr(self, 'people', None)
        spell = self.spellchecker() if hasattr(self, 'spellchecker') else None

        def work():
            try:
                result = iskra_harvest.run(people, spell, pause=lambda: time.sleep(0.02))
            except Exception as exc:                       # noqa: BLE001 — фоновое обучение не должно мешать работе
                import iskra_bugreport
                import sys
                iskra_bugreport.log_crash('Обучение по документам', type(exc), exc, sys.exc_info()[2])
                result = None

            def finish():
                self._harvest_running = False
                old = self.harvest_result or {}
                self.harvest_result = result
                if result and result['people'] and result['people'] > old.get('people', 0):
                    self.say(f'Нашла в документах людей, которых нет в справочнике: {result["people"]}. '
                             'Файл → «Справочник людей…» → «Найдено в документах».', 'proof')
                elif announce and result:
                    self.say(f'Изучила документы: новых людей для справочника — {result["people"]}, '
                             f'слов в словаре из ваших документов — {result["words"]}.', 'proof')
                if done:
                    done(result)
            self.events.put(('call', finish))
        threading.Thread(target=work, daemon=True, name='обучение').start()
        if not announce:
            self.root.after(EVERY, self.harvest_now)

    def people_found_window(self, on_added=None):
        """Люди из документов, которых нет в справочнике: отметить и добавить одной кнопкой."""
        win = _window(self, 'найдено в документах', '960x480')
        ttk.Label(win, text='Эти люди встречаются в ваших документах (подписи, исполнители), но их нет в справочнике. '
                            'Выделите нужных (Ctrl+щелчок, Ctrl+A) и нажмите «Добавить».', wraplength=920).pack(anchor='w', padx=12, pady=8)
        cols = ('fio', 'rank', 'position', 'count', 'file')
        tree = ttk.Treeview(win, columns=cols, show='headings', selectmode='extended')
        for c, h, w in zip(cols, ('Фамилия И.О.', 'Звание', 'Должность', 'Раз', 'Например, в файле'), (160, 170, 300, 50, 220)):
            tree.heading(c, text=h); tree.column(c, width=w)
        tree.pack(fill='both', expand=True, padx=12)
        status = tk.StringVar()
        ttk.Label(win, textvariable=status, style='Muted.TLabel').pack(anchor='w', padx=12, pady=4)
        bar = ttk.Frame(win, padding=(12, 0, 12, 10)); bar.pack(fill='x')
        found = {}

        def refresh():
            tree.delete(*tree.get_children()); found.clear()
            for c in iskra_harvest.candidates():
                iid = tree.insert('', 'end', values=(c['fio'], c['rank'], c['position'], c['count'], c.get('file', '')))
                found[iid] = c
            status.set(f'Найдено: {len(found)}.' if found else
                       'Пока никого нового. Искра изучает документы раз в несколько часов — или нажмите «Изучить сейчас».')

        def add():
            chosen = [found[i] for i in tree.selection()]
            if not chosen:
                status.set('Выделите людей в списке.'); return
            for c in chosen:
                self.people.add(fio=c['fio'], rank=c['rank'], position=c['position'], sex='м')
            iskra_harvest.hide([c['fio'] for c in chosen])
            refresh()
            status.set(f'Добавлено в справочник: {len(chosen)}. Звания и должности при необходимости поправьте в справочнике.')
            if on_added:
                on_added()

        def skip():
            chosen = [found[i] for i in tree.selection()]
            if chosen:
                iskra_harvest.hide([c['fio'] for c in chosen])
                refresh()

        def study():
            status.set('Изучаю документы…')
            self.harvest_now(announce=True, done=lambda r: win.winfo_exists() and refresh())
        tree.bind('<Control-a>', lambda e: tree.selection_set(tree.get_children()))
        ttk.Button(bar, text='Добавить в справочник', style='Accent.TButton', command=add).pack(side='left')
        ttk.Button(bar, text='Не предлагать', command=skip).pack(side='left', padx=6)
        ttk.Button(bar, text='Изучить сейчас', command=study).pack(side='left')
        ttk.Button(bar, text='Закрыть', command=win.destroy).pack(side='right')
        refresh()
        return win

    def learning_window(self):
        """Чему научилась Искра: что запомнено, и как это забыть."""
        win = _window(self, 'чему научилась Искра', '760x470')
        ttk.Label(win, text='Искра учится на этом компьютере, без интернета: запоминает ваши документы, правки и выбор '
                            'и подсказывает их нейросети. Сама нейросеть при этом не меняется — всё можно забыть.',
                  wraplength=730).pack(anchor='w', padx=12, pady=(10, 6))
        body = ttk.Frame(win, padding=(12, 0)); body.pack(fill='both', expand=True)

        def row(r, title, value, forget=None, show=None):
            ttk.Label(body, text=title, font=('Segoe UI', 10, 'bold')).grid(row=r, column=0, sticky='w', pady=5)
            ttk.Label(body, text=value, wraplength=330).grid(row=r, column=1, sticky='w', padx=10)
            if show:
                ttk.Button(body, text='Показать', command=show).grid(row=r, column=2, padx=3)
            if forget:
                ttk.Button(body, text='Забыть', command=forget).grid(row=r, column=3, padx=3)

        def ask_forget(what, do):
            if messagebox.askyesno('Забыть', f'Забыть {what}?', parent=win):
                do(); win.destroy(); self.learning_window()

        def build():
            stats = iskra_memory.stats()
            spell = self.spellchecker() if hasattr(self, 'spellchecker') else None
            words = len(spell.auto_words) if spell is not None else 0
            rules = iskra_learn.rules()
            row(0, 'Ваши правки', f'запомнено документов: {iskra_learn.count()}; устойчивых правок: {len(rules)}',
                lambda: ask_forget('ваши правки', iskra_learn.forget),
                (lambda: messagebox.showinfo('Ваши правки', '\n'.join(rules) or 'Пока нет правок, повторившихся '
                                             'хотя бы в двух документах.', parent=win)))
            row(1, 'Отправленные документы', f'{stats["sent"]} — образцы для новых, «как в прошлый раз»',
                lambda: ask_forget('отправленные документы (сами файлы Word останутся)', lambda: iskra_memory.forget('sent')))
            row(2, 'Поиск', f'запомнено документов, которые вы открывали: {stats["search"]}',
                lambda: ask_forget('что вы открывали в поиске', lambda: iskra_memory.forget('search')))
            row(3, 'Словарь', f'слов из ваших документов: {words}',
                lambda: ask_forget('слова из документов (Искра выучит их заново при следующем изучении)', forget_words))
            row(4, 'Справочник', f'найдено людей в документах: {len(iskra_harvest.candidates())}',
                show=lambda: self.people_found_window())

        def forget_words():
            import iskra_harvest as h
            try:
                (h._root() / 'auto_words.txt').unlink()
            except OSError:
                pass
            spell = self.spellchecker() if hasattr(self, 'spellchecker') else None
            if spell is not None:
                spell.auto_words = set()
        build()
        bar = ttk.Frame(win, padding=(12, 6, 12, 10)); bar.pack(fill='x')
        ttk.Button(bar, text='Изучить документы сейчас', command=lambda: self.harvest_now(
            announce=True, done=lambda r: win.winfo_exists() and (win.destroy(), self.learning_window()))).pack(side='left')
        ttk.Button(bar, text='Закрыть', command=win.destroy).pack(side='right')
        return win
