"""Окно журнала исходящих и кнопка «Присвоить номер» в редакторе телеграмм."""
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog

import iskra_journal as jr
from iskra_index import ROOT
from iskra_tools_ui import _window

COLS = [('number', '№', 70), ('date', 'Дата', 90), ('to', 'Кому', 220), ('subject', 'О чём', 330),
        ('reply_by', 'Ответ до', 90), ('answered', 'Ответ получен', 110)]


class JournalMixin:
    def start_journal(self):
        self.journal = jr.Journal(ROOT)

    def journal_replies(self, items):
        """Новые входящие (в фоновом потоке): если ссылаются на наш исходящий номер — отметить ответ."""
        from iskra_index import extract
        for it in items:
            try:
                text = extract(Path(it['path']))
            except Exception:
                continue
            for done in self.journal.match_reply(text, it['path']):
                msg = f'Пришёл ответ на исходящую № {done["number"]} ({done["to"] or "без адресата"}): «{it["name"]}».'
                self.events.put(('call', lambda m=msg: self.say(m, 'proof')))

    def journal_window(self):
        win = _window(self, 'журнал исходящих', '1000x520')
        top = ttk.Frame(win, padding=(12, 8)); top.pack(fill='x')
        info = tk.StringVar()
        ttk.Label(top, textvariable=info).pack(side='left')
        tree = ttk.Treeview(win, columns=[c for c, _, _ in COLS], show='headings', height=15)
        for c, title, w in COLS:
            tree.heading(c, text=title); tree.column(c, width=w)
        tree.tag_configure('late', foreground='#C00000')
        tree.tag_configure('done', foreground='#2E7D32')
        tree.pack(fill='both', expand=True, padx=12)
        buttons = ttk.Frame(win, padding=(12, 8)); buttons.pack(fill='x')

        def refresh():
            tree.delete(*tree.get_children())
            late = {it['number'] for it, overdue in self.journal.waiting() if overdue}
            for i, it in enumerate(reversed(self.journal.items)):
                tag = 'done' if it['answered'] else ('late' if it['number'] in late else '')
                tree.insert('', 'end', iid=str(i), values=[it[c] for c, _, _ in COLS], tags=(tag,))
            info.set(f'Записей: {len(self.journal.items)}. Следующий номер: {self.journal.peek()}. '
                     f'Ждём ответа: {len(self.journal.waiting())}.')

        def chosen():
            sel = tree.selection()
            return list(reversed(self.journal.items))[int(sel[0])] if sel else None

        def add():
            to = simpledialog.askstring('Исходящая', 'Кому:', parent=win)
            if to is None:
                return
            subject = simpledialog.askstring('Исходящая', 'О чём:', parent=win) or ''
            due = simpledialog.askstring('Исходящая', 'Ждём ответ до (ДД.ММ.ГГГГ, можно пусто):', parent=win) or ''
            it = self.journal.register(to, subject, reply_by=due)
            refresh(); messagebox.showinfo('Журнал', f'Присвоен номер {it["number"]}.', parent=win)

        def answered():
            it = chosen()
            if it:
                self.journal.update(it['number'], answered='' if it['answered'] else date.today().strftime('%d.%m.%Y'))
                refresh()

        def due():
            it = chosen()
            if it:
                value = simpledialog.askstring('Срок ответа', 'Ждём ответ до (ДД.ММ.ГГГГ):', initialvalue=it['reply_by'], parent=win)
                if value is not None:
                    self.journal.update(it['number'], reply_by=value.strip()); refresh()

        def remove():
            it = chosen()
            if it and messagebox.askyesno('Журнал', f'Удалить запись № {it["number"]}? Номер не вернётся в нумерацию.', parent=win):
                self.journal.remove(it['number']); refresh()

        def settings():
            fmt = simpledialog.askstring('Нумерация', 'Вид номера ({n} — порядковый номер, {год} — год), например «{n}/шт»:',
                                         initialvalue=self.journal.settings.get('format', '{n}'), parent=win)
            if fmt is None:
                return
            nxt = simpledialog.askinteger('Нумерация', 'Следующий порядковый номер:',
                                          initialvalue=int(self.journal.settings.get('next', 1)), parent=win)
            self.journal.configure(fmt, nxt); refresh()

        def export():
            path = filedialog.asksaveasfilename(parent=win, defaultextension='.xlsx', initialfile='Журнал исходящих.xlsx',
                                                filetypes=[('Excel', '*.xlsx')])
            if path:
                self.journal.to_xlsx(path); info.set('Выгружено: ' + path)

        def open_file():
            it = chosen()
            path = it and (it['answer_file'] or it['file'])
            if path:
                from iskra_tools_ui import _open_path
                _open_path(path)

        tree.bind('<Double-1>', lambda _: open_file())
        ttk.Button(buttons, text='Добавить вручную', command=add).pack(side='left')
        ttk.Button(buttons, text='Ответ получен / снять', command=answered).pack(side='left', padx=6)
        ttk.Button(buttons, text='Срок ответа…', command=due).pack(side='left')
        ttk.Button(buttons, text='Удалить', command=remove).pack(side='left', padx=6)
        ttk.Button(buttons, text='Выгрузить в Excel', command=export).pack(side='right')
        ttk.Button(buttons, text='Нумерация…', command=settings).pack(side='right', padx=6)
        refresh()

    def journal_button(self, parent, t, status):
        """«Присвоить номер»: запись в журнал, номер и дата — в текст телеграммы."""
        def assign():
            text = t.get('1.0', 'end-1c').split('--- ИСТОЧНИКИ')[0]
            to = jr.addressee_from_text(text)
            subject = jr.subject_from_text(text)
            due = simpledialog.askstring('Присвоить номер', f'Номер будет: {self.journal.peek()}\nКому: {to or "?"}\n\n'
                                         'Ждём ответ до (ДД.ММ.ГГГГ, можно оставить пустым):', parent=t.winfo_toplevel())
            if due is None:
                return
            it = self.journal.register(to, subject, reply_by=due)
            new, placed = jr.put_number(t.get('1.0', 'end-1c'), it['number'], it['date'])
            if not placed:
                # В тексте нет места для номера — ставим в начало строки, где стоит курсор.
                t.insert('insert linestart', f'№ {it["number"]} от {it["date"]}\n')
            else:
                t.delete('1.0', 'end'); t.insert('1.0', new)
            status.set(f'Зарегистрировано в журнале исходящих: № {it["number"]} от {it["date"]}.' +
                       ('' if placed else ' Места для номера в тексте не было — вписала строкой у курсора, перенесите куда нужно.'))
        return ttk.Button(parent, text='Присвоить номер', command=assign)
