"""«Сообщить об ошибке»: один файл, по которому разработчик видит причину без расспросов.
В отчёт попадают: версия, Windows, что установлено (движок, части модели, дополнения), список последних
действий БЕЗ их текста, журнал сбоев программы и журнал нейросети. Документы, телеграммы, реквизиты и
справочник людей в отчёт не попадают; путь к папке пользователя заменяется на %USERPROFILE%.
Перехват сбоев: необработанная ошибка в окне или в фоне записывается в data/errors_log.txt."""
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path

LOG_LIMIT = 300_000          # журнал сбоев не растёт бесконечно: остаются последние ~300 КБ
TAIL = 15_000


def _root():
    from iskra_index import ROOT
    return ROOT


def errors_log():
    return _root() / 'errors_log.txt'


def log_crash(where, exc_type, exc, tb):
    text = ''.join(traceback.format_exception(exc_type, exc, tb))
    try:
        path = errors_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''
        new = old + time.strftime('%d.%m.%Y %H:%M:%S ') + where + '\n' + text + '\n'
        path.write_text(new[-LOG_LIMIT:], encoding='utf-8')
    except OSError:
        pass
    return text


def install(root=None, on_error=None):
    """Все необработанные ошибки — в журнал сбоев. on_error(текст) — показать человеку (один раз за минуту)."""
    shown = {'at': 0.0}

    def tell(text):
        if on_error and time.time() - shown['at'] > 60:
            shown['at'] = time.time()
            try:
                on_error(text)
            except Exception:                          # noqa: BLE001 — сообщение об ошибке не должно падать само
                pass

    def tk_hook(exc_type, exc, tb):
        tell(log_crash('Ошибка в окне', exc_type, exc, tb))
    if root is not None:
        root.report_callback_exception = tk_hook
    previous = sys.excepthook

    def sys_hook(exc_type, exc, tb):
        log_crash('Ошибка программы', exc_type, exc, tb)
        previous(exc_type, exc, tb)
    sys.excepthook = sys_hook

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        log_crash(f'Ошибка в фоне ({getattr(args.thread, "name", "")})', args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = thread_hook


def _anon(text):
    home = str(Path.home())
    out = text.replace(home, '%USERPROFILE%') if home and len(home) > 3 else text
    user = os.environ.get('USERNAME') or os.environ.get('USER') or ''
    if len(user) > 2:
        out = out.replace(user, '%USERNAME%')
    return out


def _tail(path, limit=TAIL):
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return '(нет)'
    text = text.strip()
    return ('…\n' + text[-limit:]) if len(text) > limit else (text or '(пусто)')


def _size(path):
    try:
        return f'{Path(path).stat().st_size / 1_048_576:.1f} МБ'
    except OSError:
        return 'нет'


def components():
    import iskra_ai
    import iskra_addons
    lines = []
    try:
        binary, model = iskra_ai.local_files()
        lines.append(f'Движок: {"есть" if binary.is_file() else "НЕТ"} ({binary.name})')
        if model is None:
            lines.append('Модель: НЕ НАЙДЕНА')
        else:
            missing = iskra_ai.missing_parts(model)
            lines.append(f'Модель: {model.name}, {_size(model)}' + (f'; НЕ ХВАТАЕТ ЧАСТЕЙ: {", ".join(missing)}' if missing else ''))
        engine = binary.parent
        dlls = [d for d in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') if not (engine / d).is_file()]
        if dlls:
            lines.append('В engine нет: ' + ', '.join(dlls))
    except Exception as exc:                           # noqa: BLE001 — отчёт собирается при любой поломке
        lines.append('Нейросеть: не удалось проверить — ' + repr(exc))
    for name, title in (('ocr', 'Сканы'), ('voice', 'Голос')):
        try:
            lines.append(f'{title}: {"установлено" if iskra_addons.installed(name) else "нет"}')
        except Exception:                              # noqa: BLE001
            pass
    return lines


def build(description='', version=''):
    """Текст отчёта. Документы и личные данные в него не попадают."""
    from iskra_workflows import read_history
    import iskra_ai
    root = _root()
    lines = ['ОТЧЁТ ОБ ОШИБКЕ «ИСКРЫ»', time.strftime('Составлен: %d.%m.%Y %H:%M'), '',
             'ЧТО ДЕЛАЛИ И ЧТО ПОШЛО НЕ ТАК (со слов пользователя):', description.strip() or '(не описано)', '',
             f'Версия: {version or "?"}', f'Windows: {platform.platform()}', f'Python: {platform.python_version()}',
             f'Сборка: {"программа" if getattr(sys, "frozen", False) else "исходники"}',
             f'Папка программы: {_anon(str(iskra_ai.base_dir()))}', f'Папка данных: {_anon(str(root))}']
    try:
        import shutil
        free = shutil.disk_usage(str(root if root.exists() else root.parent)).free / 1_073_741_824
        lines.append(f'Свободно на диске: {free:.1f} ГБ')
    except OSError:
        pass
    lines += [''] + components()
    lines += ['', 'ПОСЛЕДНИЕ ДЕЙСТВИЯ (только названия, без текста):']
    try:
        for h in read_history(root, 40):
            lines.append(f'{h.get("timestamp", "")}  {h.get("action", "")}')
    except Exception:                                  # noqa: BLE001
        lines.append('(история недоступна)')
    lines += ['', 'ЖУРНАЛ СБОЕВ ПРОГРАММЫ (errors_log.txt):', _tail(errors_log()),
              '', 'ЖУРНАЛ НЕЙРОСЕТИ (ai_log.txt):', _tail(iskra_ai.base_dir() / 'data' / 'ai_log.txt')]
    return _anon('\n'.join(lines)) + '\n'


def save(text, folder=None):
    """Сохраняет отчёт (по умолчанию — на Рабочий стол) и возвращает путь."""
    folder = Path(folder) if folder else Path.home() / 'Desktop'
    if not folder.is_dir():
        folder = _root()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / time.strftime('Искра_отчёт_об_ошибке_%Y-%m-%d_%H%M.txt')
    path.write_text(text, encoding='utf-8-sig')       # BOM: Блокнот откроет без «кракозябр»
    return path


def window(app, version=''):
    """Окно «Сообщить об ошибке»: описание своими словами → отчёт виден целиком → сохранить/скопировать."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    win = tk.Toplevel(app.root)
    win.title('Искра · сообщить об ошибке')
    win.geometry('820x640')
    win.transient(app.root)
    ttk.Label(win, text='Что вы делали и что пошло не так? (например: «нажал Свод, выбрал 5 файлов — окно зависло»)',
              wraplength=790).pack(anchor='w', padx=12, pady=(10, 4))
    desc = tk.Text(win, height=4, wrap='word', font=('Segoe UI', 10)); desc.pack(fill='x', padx=12)
    ttk.Label(win, text='Отчёт (документы, телеграммы и реквизиты в него НЕ попадают — можно прочитать перед отправкой):',
              style='Muted.TLabel', wraplength=790).pack(anchor='w', padx=12, pady=(8, 2))
    view = tk.Text(win, wrap='word', font=('Consolas', 9), background='#FAFAFA', relief='flat')
    view.pack(fill='both', expand=True, padx=12)
    status = tk.StringVar(value='')
    ttk.Label(win, textvariable=status, style='Muted.TLabel', wraplength=790).pack(anchor='w', padx=12, pady=4)
    bar = ttk.Frame(win, padding=(12, 0, 12, 10)); bar.pack(fill='x')
    state = {'text': ''}

    def refresh(_=None):
        state['text'] = build(desc.get('1.0', 'end'), version)
        view.configure(state='normal'); view.delete('1.0', 'end'); view.insert('1.0', state['text'])
        view.configure(state='disabled')

    def save_it():
        refresh()
        try:
            path = save(state['text'])
        except OSError as exc:
            messagebox.showerror('Отчёт', f'Не удалось сохранить: {exc}', parent=win); return
        status.set(f'Сохранено: {path}. Пришлите этот файл разработчику.')
        try:
            import subprocess
            subprocess.Popen(['explorer', '/select,', str(path)])
        except OSError:
            pass

    def copy_it():
        refresh()
        win.clipboard_clear(); win.clipboard_append(state['text'])
        status.set('Отчёт скопирован — вставьте его в письмо или сообщение (Ctrl+V).')
    ttk.Button(bar, text='Сохранить на Рабочий стол', style='Accent.TButton', command=save_it).pack(side='left')
    ttk.Button(bar, text='Копировать', command=copy_it).pack(side='left', padx=6)
    ttk.Button(bar, text='Обновить', command=refresh).pack(side='left')
    ttk.Button(bar, text='Закрыть', command=win.destroy).pack(side='right')
    win.bind('<Escape>', lambda _: win.destroy())
    refresh()
    desc.focus_set()
    return win
