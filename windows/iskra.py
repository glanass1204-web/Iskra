import os, threading, queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from iskra_services import AutoIndexer, telegram_check, telegram_template, excel_formula
from iskra_macros import MACROS, export_macro
from iskra_workflows import compare_texts, normalize_layout, draft_from_sources, save_history, read_history
from iskra_consolidate import consolidate
from iskra_crossformat import merge_crossformat
from iskra_giga import generate, local_files

from iskra_index import ROOT, extract, index_folder, search_docs, forget_folder

ROOT.mkdir(parents=True, exist_ok=True)

class App:
    def __init__(self,root):
        self.root=root;root.title('Искра — локальный помощник');root.geometry('950x680');root.minsize(700,480)
        self.events=queue.Queue();self.results=[]
        self.indexer=AutoIndexer(ROOT,index_folder,self.events.put)
        self.indexer.start()
        root.protocol('WM_DELETE_WINDOW',self.close)
        frame=ttk.Frame(root,padding=12);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Искра · поиск по документам',font=('Segoe UI',17,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Всё обрабатывается на этом компьютере. Исходные файлы не изменяются.').pack(anchor='w',pady=(0,12))
        top=ttk.Frame(frame);top.pack(fill='x')
        ttk.Button(top,text='Выбрать папку и создать индекс',command=self.choose).pack(side='left')
        ttk.Button(top,text='Проверить новые файлы',command=self.indexer.scan_now).pack(side='left',padx=8)
        ttk.Button(top,text='Папки',command=self.folders_window).pack(side='left')
        ttk.Button(top,text='Открыть папку результатов',command=lambda:os.startfile(str(ROOT))).pack(side='left',padx=8)
        self.status=tk.StringVar(value='Готов к работе');ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=8)
        s=ttk.Frame(frame);s.pack(fill='x')
        self.query=tk.StringVar();entry=ttk.Entry(s,textvariable=self.query,font=('Segoe UI',12));entry.pack(side='left',fill='x',expand=True);entry.bind('<Return>',lambda e:self.find())
        ttk.Button(s,text='Найти',command=self.find).pack(side='left',padx=(8,0))
        pane=ttk.Panedwindow(frame,orient='vertical');pane.pack(fill='both',expand=True,pady=10)
        listframe=ttk.Frame(pane);pane.add(listframe,weight=2)
        self.listbox=tk.Listbox(listframe,font=('Segoe UI',10));self.listbox.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(listframe,command=self.listbox.yview);scroll.pack(side='right',fill='y');self.listbox.config(yscrollcommand=scroll.set)
        self.listbox.bind('<<ListboxSelect>>',self.show)
        preview=ttk.Frame(pane);pane.add(preview,weight=1)
        self.text=tk.Text(preview,wrap='word',font=('Segoe UI',10),height=10);self.text.pack(fill='both',expand=True)
        actions=ttk.Frame(frame);actions.pack(fill='x')
        ttk.Button(actions,text='Открыть документ',command=self.open_selected).pack(side='left')
        ttk.Button(actions,text='Скопировать фрагмент',command=self.copy).pack(side='left',padx=8)
        ttk.Button(actions,text='Сохранить текст в Word',command=self.save_word).pack(side='left')
        ttk.Button(actions,text='Формулы Excel',command=self.formulas).pack(side='right')
        ttk.Button(actions,text='Собрать сводную',command=self.consolidation).pack(side='right',padx=8)
        ttk.Button(actions,text='Word ↔ Excel',command=self.crossformat).pack(side='right',padx=8)
        ttk.Button(actions,text='Библиотека макросов',command=self.macros).pack(side='right',padx=8)
        ttk.Button(actions,text='ИИ GigaChat',command=self.giga_window).pack(side='right',padx=8)
        ttk.Button(actions,text='Телеграммы',command=self.telegrams).pack(side='right',padx=8)
        ttk.Button(actions,text='Сравнить',command=self.compare_files).pack(side='right',padx=8)
        ttk.Button(actions,text='История',command=self.history).pack(side='right',padx=8)
        self.root.after(100,self.poll)
    def choose(self):
        folder=filedialog.askdirectory(title='Выберите папку с документами')
        if folder:
            self.indexer.add_folder(folder)
            self.status.set('Папка добавлена. Индексирование запущено в фоне.')
    def poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                if isinstance(event,tuple) and event[0]=='giga_ok':
                    _,win,field,status,answer,truncated,done=event
                    if win.winfo_exists():
                        field.delete('1.0','end');field.insert('1.0',answer)
                        note='Готов проект. Проверьте факты по исходным документам.'
                        if truncated:note+=' Не поместились целиком: '+', '.join(truncated[:5])+'.'
                        status.set(note);done()
                elif isinstance(event,tuple) and event[0]=='giga_error':
                    _,win,status,error,done=event
                    if win.winfo_exists():status.set('Ошибка: '+error);done()
                else:self.status.set(str(event))
        except queue.Empty:pass
        self.root.after(150,self.poll)
    def find(self):
        self.results=search_docs(self.query.get());self.listbox.delete(0,'end')
        for path,_ in self.results:self.listbox.insert('end',f'{Path(path).name}   —   {path}')
        more=' (показаны первые 100)' if len(self.results)>=100 else ''
        self.status.set(f'Найдено: {len(self.results)}{more}')
        if self.query.get().strip():save_history(ROOT,'Поиск',self.query.get())
    def show(self,event=None):
        i=self.selected()
        if i is None:return
        path,snip=self.results[i];self.text.delete('1.0','end');self.text.insert('end',f'Файл: {path}\n\n{snip}')
    def selected(self):
        ids=self.listbox.curselection();return ids[0] if ids else None
    def open_selected(self):
        i=self.selected()
        if i is not None:
            try:os.startfile(self.results[i][0])
            except OSError as e:messagebox.showerror('Ошибка',str(e))
    def copy(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.text.get('1.0','end-1c'))
    def save_word(self):
        from docx import Document
        path=filedialog.asksaveasfilename(defaultextension='.docx',filetypes=[('Word','*.docx')],initialdir=str(ROOT))
        if path:
            d=Document()
            for line in self.text.get('1.0','end-1c').splitlines():d.add_paragraph(line)
            d.save(path);self.status.set(f'Сохранено: {path}')
    def close(self):
        self.indexer.stop()
        self.root.destroy()

    def folders_window(self):
        win=tk.Toplevel(self.root);win.title('Искра · папки для поиска');win.geometry('700x360')
        ttk.Label(win,text='Эти папки проверяются при запуске и каждые 15 минут.').pack(anchor='w',padx=12,pady=8)
        box=tk.Listbox(win,font=('Segoe UI',10));box.pack(fill='both',expand=True,padx=12)
        def refresh():
            box.delete(0,'end')
            for f in self.indexer.folders():
                box.insert('end',f+('' if Path(f).is_dir() else '   (сейчас недоступна)'))
        def remove():
            ix=box.curselection()
            if not ix:return
            folder=self.indexer.folders()[ix[0]]
            if not messagebox.askyesno('Убрать папку',f'Убрать из поиска?\n{folder}\n\nСами файлы не удаляются.',parent=win):return
            self.indexer.remove_folder(folder)
            removed=forget_folder(folder)
            self.status.set(f'Папка убрана из поиска, записей удалено: {removed}')
            refresh()
        buttons=ttk.Frame(win);buttons.pack(fill='x',padx=12,pady=8)
        ttk.Button(buttons,text='Добавить папку',command=lambda:(self.choose(),refresh())).pack(side='left')
        ttk.Button(buttons,text='Убрать выбранную',command=remove).pack(side='left',padx=8)
        refresh()

    def crossformat(self):
        files=filedialog.askopenfilenames(title='Выберите Word и Excel документы',filetypes=[('Word и Excel','*.docx *.xlsx *.xlsm')])
        if not files:return
        win=tk.Toplevel(self.root);win.title('Word ↔ Excel · сбор данных');win.geometry('640x350')
        ttk.Label(win,text='Названия нужных полей (по одному в строке). Точные подписи в исходниках:',wraplength=600).pack(anchor='w',padx=12,pady=8)
        fields=tk.Text(win,height=7);fields.pack(fill='both',expand=True,padx=12)
        fields.insert('1.0','Организация\nДата\nНомер\nКоличество')
        fmt=tk.StringVar(value='xlsx')
        ttk.Radiobutton(win,text='Результат: Excel',variable=fmt,value='xlsx').pack(anchor='w',padx=12)
        ttk.Radiobutton(win,text='Результат: Word',variable=fmt,value='docx').pack(anchor='w',padx=12)
        ttk.Label(win,text='Если поле отсутствует или противоречиво — НЕ НАЙДЕНО. Никаких догадок.',wraplength=600).pack(anchor='w',padx=12,pady=6)
        def run():
            ext=fmt.get()
            output=filedialog.asksaveasfilename(parent=win,title='Сохранить новый сводный файл',defaultextension='.'+ext,filetypes=[('Результат','*.'+ext)])
            if not output:return
            try:
                result=merge_crossformat(files,fields.get('1.0','end').splitlines(),output,ext)
                save_history(ROOT,'Сводная Word/Excel',f"{len(files)} файлов, {result['rows']} записей, {result['issues']} замечаний")
                messagebox.showinfo('Сбор завершён',f"Записей: {result['rows']}\nЗамечаний: {result['issues']}\nНе прочитано файлов: {len(result['failed'])}\n\n{output}\n\nПроверьте раздел источников и замечаний.",parent=win)
                win.destroy()
            except Exception as exc:messagebox.showerror('Ошибка',str(exc),parent=win)
        ttk.Button(win,text='Собрать и проверить',command=run).pack(pady=8)

    def consolidation(self):
        template=filedialog.askopenfilename(title='Общий Excel-файл: заголовки в первой строке',filetypes=[('Excel','*.xlsx')])
        if not template:return
        sources=filedialog.askopenfilenames(title='Выберите исходные Excel-файлы',filetypes=[('Excel','*.xlsx *.xlsm')])
        if not sources:return
        output=filedialog.asksaveasfilename(title='Сохранить новую сводную таблицу',defaultextension='.xlsx',initialdir=str(ROOT),filetypes=[('Excel','*.xlsx')])
        if not output:return
        win=tk.Toplevel(self.root);win.title('Сбор сводной · настройки');win.geometry('580x230')
        ttk.Label(win,text='Необязательно: название столбца с уникальным номером / кодом').pack(anchor='w',padx=12,pady=(15,5))
        value=tk.StringVar();ttk.Entry(win,textvariable=value).pack(fill='x',padx=12)
        ttk.Label(win,text='Совпадение колонок — по точным заголовкам (без учёта регистра).\nПроверьте лист «Проверка» в итоговом файле.',wraplength=540).pack(anchor='w',padx=12,pady=10)
        def run():
            try:
                result=consolidate(template,sources,output,value.get().strip() or None)
                save_history(ROOT,'Сводная Excel',f"{len(sources)} файлов, {result['rows']} строк")
                messagebox.showinfo('Сводная готова',f"Собрано строк: {result['rows']}\nЗамечаний: {result['issues']}\nПропущено файлов: {result['skipped_files']}\n\n{output}\n\nОткройте лист «Проверка».",parent=win)
                win.destroy()
            except Exception as exc:messagebox.showerror('Ошибка объединения',str(exc),parent=win)
        ttk.Button(win,text='Собрать и проверить',command=run).pack(pady=8)

    def giga_window(self):
        win=tk.Toplevel(self.root);win.title('Искра · GigaChat офлайн');win.geometry('850x650')
        binary,model=local_files()
        status=tk.StringVar(value=('Движок: '+('есть' if binary.is_file() else 'НЕТ')+'; GGUF: '+(model.name if model else 'НЕТ')))
        ttk.Label(win,textvariable=status,wraplength=800).pack(anchor='w',padx=12,pady=8)
        ttk.Label(win,text='Задача (только по выбранным источникам):').pack(anchor='w',padx=12)
        request=tk.Text(win,height=3,wrap='word');request.pack(fill='x',padx=12)
        request.insert('1.0','Подготовь проект ответа на документ. Не добавляй отсутствующих сведений.')
        files=[]
        chosen=tk.StringVar(value='Источники не выбраны')
        ttk.Label(win,textvariable=chosen,wraplength=800).pack(anchor='w',padx=12,pady=4)
        def add_files():
            for p in filedialog.askopenfilenames(parent=win,title='Выберите исходные документы',filetypes=[('Документы','*.docx *.xlsx *.pptx *.pdf *.txt *.md *.csv')]):
                if p not in files:files.append(p)
            chosen.set('Выбрано документов: '+str(len(files))+'; '+', '.join(Path(p).name for p in files[:6]))
        ttk.Button(win,text='Выбрать документы-источники',command=add_files).pack(anchor='w',padx=12)
        result=tk.Text(win,wrap='word');result.pack(fill='both',expand=True,padx=12,pady=8)
        cancel=threading.Event()
        def finished():
            run_button.configure(state='normal');stop_button.configure(state='disabled')
        def run():
            if not files:
                messagebox.showwarning('Нет источников','Выберите исходные документы.',parent=win);return
            # One generation at a time: several llama.cpp processes would choke the CPU.
            run_button.configure(state='disabled');stop_button.configure(state='normal');cancel.clear()
            status.set('Генерация на этом компьютере, обычно 2–10 минут. Можно остановить.')
            task=request.get('1.0','end-1c')
            def work():
                try:
                    sources=[(Path(p).name,extract(Path(p))) for p in files]
                    answer,truncated=generate(task,sources,cancel=cancel)
                    self.events.put(('giga_ok',win,result,status,answer,truncated,finished))
                except Exception as exc:self.events.put(('giga_error',win,status,str(exc),finished))
            threading.Thread(target=work,daemon=True).start()
        win.protocol('WM_DELETE_WINDOW',lambda:(cancel.set(),win.destroy()))
        def save():
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.docx',filetypes=[('Word','*.docx')])
            if path:
                from docx import Document
                d=Document()
                for line in result.get('1.0','end-1c').splitlines():d.add_paragraph(line)
                d.save(path);status.set('Сохранено: '+path)
                save_history(ROOT,'Проект GigaChat',Path(path).name)
        buttons=ttk.Frame(win);buttons.pack(fill='x',padx=12,pady=8)
        run_button=ttk.Button(buttons,text='Создать проект',command=run);run_button.pack(side='left')
        stop_button=ttk.Button(buttons,text='Остановить',command=cancel.set,state='disabled');stop_button.pack(side='left',padx=8)
        ttk.Button(buttons,text='Сохранить в Word',command=save).pack(side='left',padx=8)
        ttk.Label(win,text='Ответ нейросети требует проверки по оригиналам. Факты не подтверждаются автоматически.',wraplength=800).pack(anchor='w',padx=12,pady=5)

    def telegrams(self):
        win=tk.Toplevel(self.root);win.title('Искра · редактор телеграмм');win.geometry('800x650')
        ttk.Label(win,text='Проект телеграммы · исходные документы не изменяются',font=('Segoe UI',12,'bold')).pack(anchor='w',padx=12,pady=8)
        t=tk.Text(win,wrap='word',font=('Segoe UI',11));t.pack(fill='both',expand=True,padx=12)
        t.insert('1.0',telegram_template())
        status=tk.StringVar(value='Используйте утверждённый образец организации. Шаблон здесь — пример.')
        ttk.Label(win,textvariable=status,wraplength=750).pack(anchor='w',padx=12,pady=6)
        buttons=ttk.Frame(win);buttons.pack(fill='x',padx=12,pady=8)
        def check():
            issues=telegram_check(t.get('1.0','end-1c'))
            messagebox.showinfo('Проверка перед отправкой','\n'.join('• '+x for x in issues),parent=win)
        def save():
            from docx import Document
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.docx',filetypes=[('Word','*.docx')],initialdir=str(ROOT))
            if path:
                d=Document()
                for line in t.get('1.0','end-1c').splitlines():d.add_paragraph(line)
                d.save(path);status.set('Проект сохранён: '+path)
        ttk.Button(buttons,text='Проверить текст',command=check).pack(side='left')
        ttk.Button(buttons,text='Сохранить проект Word',command=save).pack(side='left',padx=8)
        def tidy():
            t.replace('1.0','end',normalize_layout(t.get('1.0','end-1c')))
            status.set('Пробелы и пустые строки приведены к единому виду. Проверьте текст.')
        def prepare():
            ix=self.selected()
            if ix is None:
                messagebox.showinfo('Источник','Сначала найдите и выберите документ в главном окне.',parent=win);return
            path=self.results[ix][0]
            try:
                text=draft_from_sources('По выбранному документу',[(path,extract(Path(path)))])
                t.replace('1.0','end',text)
                save_history(ROOT,'Проект телеграммы',Path(path).name)
                status.set('Создан черновик с выдержками из источника. Это НЕ готовый ИИ-ответ.')
            except Exception as exc:messagebox.showerror('Ошибка',str(exc),parent=win)
        ttk.Button(buttons,text='Убрать лишние пробелы',command=tidy).pack(side='left',padx=8)
        ttk.Button(buttons,text='Черновик по выбранному файлу',command=prepare).pack(side='left',padx=8)

    def compare_files(self):
        first=filedialog.askopenfilename(title='Старая редакция',filetypes=[('Документы','*.docx *.xlsx *.pptx *.pdf *.txt *.md *.csv')])
        if not first:return
        second=filedialog.askopenfilename(title='Новая редакция',filetypes=[('Документы','*.docx *.xlsx *.pptx *.pdf *.txt *.md *.csv')])
        if not second:return
        try:
            diff=compare_texts(extract(Path(first)),extract(Path(second)))
        except Exception as exc:
            messagebox.showerror('Ошибка сравнения',str(exc));return
        win=tk.Toplevel(self.root);win.title('Искра · сравнение редакций');win.geometry('900x650')
        area=tk.Text(win,wrap='none',font=('Consolas',10));area.pack(fill='both',expand=True,padx=10,pady=10)
        area.insert('1.0',diff)
        def save():
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.txt',filetypes=[('Текст','*.txt')])
            if path:Path(path).write_text(diff,encoding='utf-8')
        ttk.Button(win,text='Сохранить сравнение',command=save).pack(pady=8)
        save_history(ROOT,'Сравнение',f'{Path(first).name} / {Path(second).name}')

    def history(self):
        win=tk.Toplevel(self.root);win.title('Искра · история действий');win.geometry('800x500')
        area=tk.Text(win,wrap='word',font=('Segoe UI',10));area.pack(fill='both',expand=True,padx=12,pady=12)
        for item in read_history(ROOT):
            area.insert('end',f"{item['timestamp']} · {item['action']} · {item['details']}\n")
        area.configure(state='disabled')

    def macros(self):
        win=tk.Toplevel(self.root);win.title('Искра · библиотека макросов (офлайн)');win.geometry('900x680')
        ttk.Label(win,text='Готовые VBA-макросы для Word и Excel',font=('Segoe UI',13,'bold')).pack(anchor='w',padx=12,pady=(12,3))
        ttk.Label(win,text='Макросы НЕ запускаются автоматически. Сначала проверьте на копии документа.',wraplength=850).pack(anchor='w',padx=12)
        area=ttk.Frame(win);area.pack(fill='both',expand=True,padx=12,pady=10)
        names=tk.Listbox(area,width=43,exportselection=False);names.pack(side='left',fill='y')
        code=tk.Text(area,wrap='none',font=('Consolas',10));code.pack(side='left',fill='both',expand=True,padx=(8,0))
        for m in MACROS:names.insert('end',f'{m.app}: {m.title}')
        status=tk.StringVar(value='Выберите макрос слева. Его код можно проверить перед сохранением.')
        ttk.Label(win,textvariable=status,wraplength=860).pack(anchor='w',padx=12,pady=4)
        def current():
            ix=names.curselection()
            return MACROS[ix[0]] if ix else None
        def show(event=None):
            m=current()
            if not m:return
            code.delete('1.0','end');code.insert('1.0',m.code)
            status.set(m.description)
        def copy():
            m=current()
            if m:
                win.clipboard_clear();win.clipboard_append(code.get('1.0','end-1c'))
                status.set('Код скопирован. Перед запуском проверьте его и используйте копию файла.')
        def save():
            m=current()
            if not m:return
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.bas',initialfile='Iskra_'+m.key+'.bas',filetypes=[('Модуль VBA','*.bas')])
            if path:
                try:
                    export_macro(m,path);status.set('Модуль сохранён: '+path)
                except (OSError,ValueError) as e:messagebox.showerror('Ошибка',str(e),parent=win)
        buttons=ttk.Frame(win);buttons.pack(fill='x',padx=12,pady=10)
        ttk.Button(buttons,text='Копировать код',command=copy).pack(side='left')
        ttk.Button(buttons,text='Сохранить .bas',command=save).pack(side='left',padx=8)
        ttk.Button(buttons,text='Как подключить',command=lambda:messagebox.showinfo('Инструкция','Word / Excel: Alt+F11 → Файл → Импорт файла → выберите .bas.\nСохраните документ как .docm или .xlsm.\nМакросы могут быть запрещены политиками организации.\nВсегда сначала проверяйте на копии.',parent=win)).pack(side='left')
        names.bind('<<ListboxSelect>>',show)
        names.selection_set(0);show()

    def formulas(self):
        win=tk.Toplevel(self.root);win.title('Искра · формулы Excel');win.geometry('740x480')
        ttk.Label(win,text='Опишите задачу обычными словами',font=('Segoe UI',12,'bold')).pack(anchor='w',padx=12,pady=8)
        request=tk.StringVar()
        ttk.Entry(win,textvariable=request,font=('Segoe UI',11)).pack(fill='x',padx=12)
        result=tk.Text(win,wrap='word',font=('Segoe UI',11));result.pack(fill='both',expand=True,padx=12,pady=12)
        result.insert('1.0','Примеры: «сумма», «среднее», «количество по условию», «разница дат», «если», «впр».\n\nФормулы приведены для русской локализации Excel. Проверьте диапазоны перед вставкой.')
        def suggest():
            formula, note=excel_formula(request.get())
            result.delete('1.0','end')
            result.insert('1.0',(formula+'\n\n' if formula else '')+note)
        ttk.Button(win,text='Подобрать формулу',command=suggest).pack(pady=(0,10))

if __name__=='__main__':
    root=tk.Tk();App(root);root.mainloop()
