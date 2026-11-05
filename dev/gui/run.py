import sys, time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); 
from drive import *
from docx import Document
from docx.shared import Pt
import make as M
sys.path.insert(0, '/home/user/iskra/windows')
import test_highlight_xlsx as TX

W = Path(tempfile.mkdtemp()); TX.TMP = W
results = []
def ok(name, cond, info=''):
    results.append((name, bool(cond), info)); print(('OK  ' if cond else 'FAIL'), name, '' if cond else info)

# ---------- A. все пункты меню ----------
menubar = root.nametowidget(root['menu'])
crawled = 0
def crawl(menu, path=''):
    global crawled
    last = menu.index('end')
    if last is None: return
    for i in range(last + 1):
        kind = menu.type(i)
        if kind == 'cascade':
            sub = root.nametowidget(menu.entrycget(i, 'menu')); crawl(sub, path + menu.entrycget(i, 'label') + ' → ')
        elif kind == 'command':
            label = menu.entrycget(i, 'label')
            if any(x in label for x in ('Выход', 'Закрыть программу')): continue
            before = toplevels(); n = len(ERRORS)
            try:
                menu.invoke(i); pump(0.4)
            except Exception as exc:
                ERRORS.append(f'{path}{label}: {exc!r}')
            if len(ERRORS) > n: print('  ошибка в меню:', path + label, ERRORS[-1][-300:])
            close_new(before); crawled += 1
for i in range(menubar.index('end') + 1):
    if menubar.type(i) == 'cascade':
        crawl(root.nametowidget(menubar.entrycget(i, 'menu')), menubar.entrycget(i, 'label') + ' → ')
ok(f'меню: открыто пунктов {crawled}, без ошибок', not ERRORS, '\n'.join(e[-400:] for e in ERRORS))
ERRORS.clear()

# ---------- B/C. перенос изменений: Word и Excel ----------
def transfer(tpl, base, srcs, out):
    before = toplevels()
    app.highlight_window(); pump()
    win = [w for w in toplevels() if w not in before][0]
    picks = [w for w in walk(win) if isinstance(w, ttk.Button) and w.cget('text') == 'Выбрать…']
    ANS['open'] = str(tpl); picks[0].invoke()
    ANS['open'] = str(base) if base else ''; picks[1].invoke()
    ANS['opens'] = [str(s) for s in srcs]; button(win, 'Добавить файлы…').invoke()
    ANS['save'] = str(out); ANS['yesno'] = False
    button(win, 'Собрать в один документ').invoke()
    t0 = time.time()
    while time.time() - t0 < 60 and len(toplevels()) < len(before) + 2:
        pump(0.2)
    pump(0.5)
    close_new(before)

was = [['', '', '77 км', '', '', '', '', '', ''], ['', '', '105 км', '', '', '', '', '', ''],
       ['КП 5447 обр СпН', '', '56 км', 'НШ гв п/п-к Залупа В.А.', '12188 4444', '27/2', 'с-в окраина ЗАЛУПИНСК', 'помещение', '4 сут. с 19.10.2026'],
       ['КП 7001', '', '40 км', 'НШ м-р Иванов И.И.', '11111 2222', '30/5', 'ЛИМАН', 'палатки', '2 сут. с 21.10.2026']]
now = [r[:] for r in was]
now[2] = ['КП 5447 обр СпН', '', '43 км', 'НШ м-р Петров П.П.', '12188 4444', '27/4', 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК', 'помещение', '1 сут. с 05.11.2026']
M.build(W / 'шаблон.docx', was, font='Times New Roman', size=10)
M.build(W / 'документ.docx', was, font='Arial', size=9)
M.build(W / 'рота.docx', now, green={(2, k, -1) for k in range(9)} - {(2, 6, -1)} | {(2, 6, 1)}, font='Courier New', size=11)
out = W / 'итог.docx'
transfer(W / 'шаблон.docx', W / 'документ.docx', [W / 'рота.docx'], out)
if out.exists():
    t = Document(str(out)).tables[0]
    names = [r.cells[0].text for r in t.rows]
    ok('Word: файл создан, без задвоения', names.count('КП 5447 обр СпН') == 1, names)
    ok('Word: км и положение с новым пунктом снизу', t.cell(4, 2).text == '43 км' and t.cell(4, 6).text == 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК',
       (t.cell(4, 2).text, t.cell(4, 6).text))
    ok('Word: сутки при переезде', t.cell(4, 8).text.startswith('1 сут. с'), t.cell(4, 8).text)
    fonts = {(r.font.name, r.font.size) for c in t._cells for p in c.paragraphs for r in p.runs if r.text.strip()}
    ok('Word: шрифт шаблона', fonts == {('Times New Roman', Pt(10))}, fonts)
else:
    ok('Word: файл создан', False, LOG[-3:])
ok('Word: без ошибок', not ERRORS, '\n'.join(e[-600:] for e in ERRORS)); ERRORS.clear()

tplx = TX.book('шаблон.xlsx', TX.WAS, font=('Times New Roman', 12)); docx_ = TX.book('документ.xlsx', TX.WAS, font=('Arial', 9))
moved = [r[:] for r in TX.WAS]; moved[0] = ['КП 5447 обр СпН', '43 км', 'НШ м-р Петров П.П.', '27/4', 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК', '4 сут. с 19.10.2026']
srcx = TX.book('рота.xlsx', moved, green={(0, 0): 'all', (0, 1): 'all', (0, 2): 'all', (0, 3): 'all', (0, 4): 'second_line'})
outx = W / 'итог.xlsx'
transfer(tplx, docx_, [srcx], outx)
if outx.exists():
    from openpyxl import load_workbook
    import iskra_highlight_xlsx as X
    ws = load_workbook(outx, rich_text=True).active
    ok('Excel: перенос', X._text(ws.cell(4, 2).value) == '43 км' and X._text(ws.cell(4, 5).value) == 'с-в окраина ЗАЛУПИНСК\nПЕЧОРИНСК',
       [X._text(c.value) for c in ws[4]])
else:
    ok('Excel: файл создан', False, LOG[-3:])
ok('Excel: без ошибок', not ERRORS, '\n'.join(e[-600:] for e in ERRORS)); ERRORS.clear()

# ---------- D. шаблон телеграммы + редактор ----------
d = Document()
for l in ('ТЕЛЕГРАММА', 'Командирам подразделений', 'Во исполнение указаний штаба округа ПРИКАЗЫВАЮ провести проверку подразделений в установленный срок и доложить.',
          'Начальник штаба', 'полковник П.П. Сидоров'):
    d.add_paragraph(l)
d.save(W / 'тлг.docx')
app.save_doc_templates({'Телеграмма': str(W / 'тлг.docx')})
before = toplevels()
res = app.telegrams(initial='В целях повышения живучести ПУ ПРИКАЗЫВАЮ:\n1. Провести маскировку.\n2. Доложить.')
pump()
win = res[0] if isinstance(res, tuple) else [w for w in toplevels() if w not in before][0]
ANS['save'] = str(W / 'тлг_итог.docx'); button(win, 'Сохранить в Word').invoke(); pump()
if (W / 'тлг_итог.docx').exists():
    texts = [p.text for p in Document(str(W / 'тлг_итог.docx')).paragraphs]
    ok('телеграмма по шаблону: шапка + текст + подпись', texts == ['ТЕЛЕГРАММА', 'Командирам подразделений', 'В целях повышения живучести ПУ ПРИКАЗЫВАЮ:',
                                                                    '1. Провести маскировку.', '2. Доложить.', 'Начальник штаба', 'полковник П.П. Сидоров'], texts)
else:
    ok('телеграмма сохранена', False, LOG[-3:])
close_new(before)
ok('редактор: без ошибок', not ERRORS, '\n'.join(e[-600:] for e in ERRORS)); ERRORS.clear()

# ---------- E. отпускной билет по своему бланку ----------
d = Document()
for l in ('{Штамп}', 'ОТПУСКНОЙ БИЛЕТ', '{ФИО} убыл {Вид отпуска}', 'сроком на {Сроком на} с {С} по {По}', 'Командир {Командир}'):
    d.add_paragraph(l)
d.save(W / 'бланк.docx')
app.save_doc_templates({'Телеграмма': str(W / 'тлг.docx'), 'Отпускной билет': str(W / 'бланк.docx')})
before = toplevels()
win = app.leave_ticket_window(); pump()
entries = [w for w in walk(win) if isinstance(w, ttk.Entry)]
vals = ['в/ч 12345', 'капитан Иванов Иван Иванович', None, '15', '01.11.2026']
for e, v in zip(entries, vals):
    if v is None: continue
    e.delete(0, 'end'); e.insert(0, v)
pump()
ANS['save'] = str(W / 'билет.docx'); ANS['yesno'] = True
button(win, 'Сохранить в Word').invoke(); pump()
if (W / 'билет.docx').exists():
    texts = [p.text for p in Document(str(W / 'билет.docx')).paragraphs]
    ok('отпускной по бланку', texts[0] == 'в/ч 12345' and 'пятнадцать суток' in texts[3] and '"15" ноября' in texts[3], texts)
else:
    ok('отпускной сохранён', False, LOG[-3:])
close_new(before)
ok('отпускной: без ошибок', not ERRORS, '\n'.join(e[-600:] for e in ERRORS)); ERRORS.clear()

print('ИТОГ:', sum(1 for r in results if r[1]), 'из', len(results))
for n, good, info in results:
    if not good: print('НЕ ПРОШЛО:', n, str(info)[:1500])
root.destroy()
os._exit(0)
