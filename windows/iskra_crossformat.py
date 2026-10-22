"""Strict offline Word/Excel extraction: no guesses, provenance for every cell."""
from pathlib import Path
import re
from openpyxl import load_workbook, Workbook
from docx import Document

MISSING='НЕ НАЙДЕНО'

def norm(v):
    return re.sub(r'\s+', ' ', str(v or '').strip()).casefold().replace('ё','е')

NUMBER = re.compile(r'^-?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?$')


def as_number(v):
    """«12», «1 234», «12,5» из Word — числом, чтобы СУММ в Excel их считала. Коды с ведущим нулём («007») — текстом."""
    if isinstance(v, str):
        t = v.strip()
        if NUMBER.match(t) and not (len(t) > 1 and t[0] == '0' and t[1].isdigit()):
            t = t.replace(' ', '').replace('\u00a0', '').replace(',', '.')
            f = float(t)
            return int(f) if f.is_integer() and '.' not in t else f
    return v


def append_as_values(ws, row, numbers=False):
    """Text starting with '=' stays text instead of becoming a formula. numbers=True — для данных из Word:
    «12» становится числом (в Excel из Excel значения уже со своим типом и не трогаются)."""
    ws.append([as_number(v) for v in row] if numbers else row)
    for cell in ws[ws.max_row]:
        if cell.data_type == 'f':
            cell.data_type = 's'

def word_fields(path, headings):
    doc=Document(path)
    found={}; warnings=[]
    labels={norm(h):h for h in headings}
    # Explicit key/value lines only; never infer semantic equivalence.
    for idx,p in enumerate(doc.paragraphs,1):
        line=p.text.strip()
        if ':' not in line: continue
        k,v=line.split(':',1); h=labels.get(norm(k))
        if h and v.strip():
            found.setdefault(h,[]).append((as_number(v.strip()),f'абзац {idx}'))
    for ti,table in enumerate(doc.tables,1):
        for ri,row in enumerate(table.rows,1):
            cells=[c.text.strip() for c in row.cells]
            cells=[c for i,c in enumerate(cells) if i==0 or c!=cells[i-1]]   # объединённые ячейки Word повторяются
            if len(cells)==2:
                key=norm(cells[0]).rstrip(':').strip()                      # «Дата:» — то же поле, что «Дата»
                if key in labels and cells[1]:
                    h=labels[key];found.setdefault(h,[]).append((as_number(cells[1]),f'таблица {ti}, строка {ri}'))
    values={}; locations={}
    for h in headings:
        matches=found.get(h,[])
        unique={norm(v) for v,_ in matches}
        if len(unique)>1:
            values[h]=MISSING
            warnings.append((h,'ПРОТИВОРЕЧИЕ', '; '.join(f'{v} ({loc})' for v,loc in matches)[:1500]))
        elif matches:
            values[h]=matches[0][0];locations[h]=matches[0][1]
        else:
            values[h]=MISSING;warnings.append((h,'НЕ НАЙДЕНО','Нет явно подписанного поля'))
    return [(values,locations,warnings,'Word')]

def excel_fields(path,headings):
    book=load_workbook(path,read_only=True,data_only=True)
    result=[]
    try:
        for sheet in book:
            rows=sheet.iter_rows(values_only=True)
            header=next(rows,None)
            if not header:continue
            mapping={norm(v):i for i,v in enumerate(header) if norm(v)}
            if not any(norm(h) in mapping for h in headings):continue
            for rn,vals in enumerate(rows,2):
                if not any(v is not None and str(v).strip() for v in vals):continue
                values={};locations={};warnings=[]
                for h in headings:
                    ix=mapping.get(norm(h));v=vals[ix] if ix is not None and ix<len(vals) else None
                    if v is None or str(v).strip()=='':
                        values[h]=MISSING;warnings.append((h,'НЕ НАЙДЕНО','Нет столбца или значения'))
                    else:
                        values[h]=v;locations[h]=f'лист {sheet.title}, строка {rn}, столбец {ix+1}'
                result.append((values,locations,warnings,'Excel'))
    finally:book.close()
    return result

def merge_crossformat(paths,headings,output,output_format='xlsx',filler=None):
    """Export exact named fields to a new XLSX or DOCX, with per-cell source audit.
    filler(path, [missing headings]) -> {heading: value}: fills fields the rules did not find (local neural network);
    each such value is listed on the audit sheet as «ЗАПОЛНЕНО НЕЙРОСЕТЬЮ»."""
    paths=[Path(p).resolve() for p in paths];output=Path(output).resolve()
    headings=[h.strip() for h in headings if h.strip()]
    if not paths or not headings:raise ValueError('Нужны исходные файлы и названия столбцов')
    if len({norm(h) for h in headings})!=len(headings):raise ValueError('Повторяющиеся названия столбцов')
    if output in paths:raise ValueError('Нельзя перезаписывать исходный документ')
    if output_format not in ('xlsx','docx') or output.suffix.lower()!='.'+output_format:
        raise ValueError('Формат результата должен соответствовать расширению файла')
    records=[];issues=[];provenance=[];failed=[]
    for path in paths:
        try:
            if path.suffix.lower()=='.docx': extracted=word_fields(path,headings)
            elif path.suffix.lower() in ('.xlsx','.xlsm'):extracted=excel_fields(path,headings)
            else:raise ValueError('Неподдерживаемый формат (только .docx/.xlsx/.xlsm)')
            if not extracted:
                issues.append((path.name,'','НЕТ ТАБЛИЦЫ','Не найдены заголовки из задания'))
            for values,locations,warnings,kind in extracted:
                # Только «не найдено»; противоречия между значениями решает человек, а не нейросеть.
                missing=[h for h,typ,_ in warnings if typ=='НЕ НАЙДЕНО' and values.get(h)==MISSING]
                if filler and missing:
                    try:found=filler(path,missing) or {}
                    except Exception as exc:found={};issues.append((path.name,'','НЕЙРОСЕТЬ',str(exc)[:300]))
                    for h,v in found.items():
                        if h in missing and str(v).strip():
                            values[h]=v;locations[h]='найдено нейросетью, значение есть в тексте документа'
                            warnings=[w for w in warnings if w[0]!=h]
                            issues.append((path.name,h,'ЗАПОЛНЕНО НЕЙРОСЕТЬЮ','Проверьте: '+str(v)[:200]))
                records.append((path.name,values))
                for h in headings:
                    provenance.append((len(records),h,path.name,locations.get(h,''),str(values[h])))
                for h,typ,detail in warnings:issues.append((path.name,h,typ,detail))
        except Exception as exc:
            failed.append(path.name);issues.append((path.name,'','ОШИБКА ЧТЕНИЯ',str(exc)[:500]))
    output.parent.mkdir(parents=True,exist_ok=True)
    if output_format=='xlsx':
        wb=Workbook();ws=wb.active;ws.title='Сводная';ws.append(['Источник']+headings)
        for name,values in records:append_as_values(ws,[name]+[values[h] for h in headings])
        audit=wb.create_sheet('Проверка');audit.append(['Файл','Поле','Статус','Пояснение'])
        for issue in issues:append_as_values(audit,list(issue))
        source=wb.create_sheet('Источники');source.append(['Строка сводной','Поле','Файл','Место в документе','Значение'])
        for r,h,name,loc,value in provenance:append_as_values(source,[r+1,h,name,loc,value])
        ws.freeze_panes='B2';ws.auto_filter.ref=ws.dimensions
        wb.save(output)
        check=load_workbook(output,read_only=True)
        try:
            if check['Сводная'].max_row!=len(records)+1:raise RuntimeError('Контроль числа строк не пройден')
        finally:check.close()
    else:
        doc=Document();doc.add_heading('Сводный документ',0)
        t=doc.add_table(rows=1,cols=len(headings)+1);t.style='Table Grid'
        for cell,value in zip(t.rows[0].cells,['Источник']+headings):cell.text=value
        for name,values in records:
            cells=t.add_row().cells
            for cell,value in zip(cells,[name]+[str(values[h]) for h in headings]):cell.text=value
        doc.add_heading('Проверка и замечания',level=1)
        if not issues:doc.add_paragraph('Замечаний не обнаружено в рамках формальной проверки.')
        for name,h,typ,detail in issues:doc.add_paragraph(f'{name} / {h}: {typ}. {detail}')
        doc.add_heading('Источники значений',level=1)
        for r,h,name,loc,value in provenance:doc.add_paragraph(f'Запись {r} / {h}: {name}, {loc or "место не установлено"}; значение: {value}')
        doc.save(output)
        check=Document(output)
        if len(check.tables)!=1 or len(check.tables[0].rows)!=len(records)+1:raise RuntimeError('Контроль числа строк не пройден')
    return {'rows':len(records),'issues':len(issues),'failed':failed,'output':str(output)}
