"""Окно «Отпускной билет»: поля бланка (приложение 30 к ИД-2017), даты считаются сами, сохранение в Word А5."""
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import iskra_forms as forms
from iskra_index import ROOT
from iskra_tools_ui import _window


def short_name(full):
    """«капитан Иванов Иван Иванович» → «Иванов И.И.»."""
    words = re.findall(r'[А-ЯЁ][а-яё-]+', full or '')
    if len(words) >= 3:
        return f'{words[-3]} {words[-2][0]}.{words[-1][0]}.'
    return words[0] if words else ''


class FormsMixin:
    def leave_ticket_window(self):
        win = _window(self, 'отпускной билет', '720x560')
        ttk.Label(win, text='Отпускной билет по форме приложения 30 к Инструкции по делопроизводству в ВС РФ. '
                            'Даты окончания и явки считаются сами — их можно поправить.',
                  style='Muted.TLabel', wraplength=680).pack(anchor='w', padx=12, pady=(10, 4))
        form = ttk.Frame(win, padding=12); form.pack(fill='both', expand=True)
        form.columnconfigure(1, weight=1)
        fields = [('stamp', 'Угловой штамп (часть, адрес):'), ('who', 'Воинское звание, фамилия, имя, отчество:'),
                  ('kind_place', 'Убыл (вид отпуска и населённый пункт):'), ('days', 'Сроком на (суток):'),
                  ('start', 'С (дд.мм.гггг):'), ('end', 'По (дд.мм.гггг):'), ('back_name', 'Фамилия и инициалы:'),
                  ('unit', 'Явиться к месту службы в:'), ('back_date', 'Дата явки (дд.мм.гггг):'),
                  ('vpd', 'ВПД — требования за №:'), ('commander', 'Командир (начальник):')]
        v = {k: tk.StringVar() for k, _ in fields}
        v['kind_place'].set('в основной отпуск за  год в г. ')
        v['unit'].set('войсковую часть ')
        for i, (key, label) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky='w', pady=3, padx=(0, 8))
            ttk.Entry(form, textvariable=v[key]).grid(row=i, column=1, sticky='we', pady=3)
        me = self.my_details() if hasattr(self, 'my_details') else {}
        sig = [x.strip() for x in me.get('signature', '').splitlines() if x.strip()]
        if sig:
            v['commander'].set(' '.join(sig))

        def recount(*_):
            start, days = forms.parse_date(v['start'].get()), v['days'].get().strip()
            if start and days.isdigit() and int(days) > 0:
                end, back = forms.leave_dates(start, int(days))
                v['end'].set(end.strftime('%d.%m.%Y'))
                v['back_date'].set(back.strftime('%d.%m.%Y'))
        v['start'].trace_add('write', recount)
        v['days'].trace_add('write', recount)
        v['who'].trace_add('write', lambda *_: v['back_name'].set(short_name(v['who'].get())))

        def values():
            f = {k: v[k].get() for k, _ in fields}
            for key in ('start', 'end', 'back_date'):
                f[key] = forms.parse_date(v[key].get())
            return f

        def save():
            f = values()
            text = forms.leave_ticket_text(f)
            if '[УТОЧНИТЬ' in text and not messagebox.askyesno(
                    'Отпускной билет', 'Заполнены не все поля (будут пометки [УТОЧНИТЬ]). Всё равно сохранить?', parent=win):
                return
            name = short_name(v['who'].get()) or 'отпускной билет'
            path = filedialog.asksaveasfilename(parent=win, defaultextension='.docx', filetypes=[('Word', '*.docx')],
                                                initialdir=str(ROOT), initialfile=f'Отпускной билет {name}.docx')
            if path:
                forms.save_leave_ticket(f, path)
                self.say(f'Отпускной билет сохранён: {path}', 'proof')
                win.destroy()

        def to_editor():
            self.telegrams(initial=forms.leave_ticket_text(values()),
                           note='Отпускной билет. Для печати по форме (А5, штамп) — кнопка «Сохранить в Word» в окне билета.')

        bar = ttk.Frame(win, padding=(12, 0, 12, 10)); bar.pack(fill='x')
        ttk.Button(bar, text='Сохранить в Word (А5)', style='Accent.TButton', command=save).pack(side='right')
        ttk.Button(bar, text='Открыть в редакторе', command=to_editor).pack(side='right', padx=6)
        return win
