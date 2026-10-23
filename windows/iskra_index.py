"""Local document index: text extraction, SQLite FTS5 search. No network, no GUI."""
import codecs
import os
import re
import sqlite3
import sys
from pathlib import Path

# Portable mode: keep index and settings beside the executable, not in AppData.
BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
ROOT = Path(os.environ.get('ISKRA_DATA_DIR', str(BASE / 'data'))).resolve()
DB = ROOT / 'index.sqlite3'
import iskra_ocr

EXT = {'.docx', '.xlsx', '.xlsm', '.pptx', '.pdf', '.txt', '.md', '.csv'}


def supported(path):
    """Читаемый файл; картинки — только когда установлено распознавание сканов (архив Iskra-dop-skany.zip)."""
    ext = Path(path).suffix.lower()
    return ext in EXT or (ext in iskra_ocr.IMAGES and iskra_ocr.available())
MAX_CHARS = 2_000_000
# Bump when the stored search text changes, so old indexes are rebuilt automatically.
SCHEMA_VERSION = 2


def read_text_file(p):
    raw = Path(p).read_bytes()
    # BOM first: UTF-16 without this check is silently "decoded" as cp1251 garbage.
    for bom, enc in ((codecs.BOM_UTF8, 'utf-8-sig'), (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16')):
        if raw.startswith(bom):
            return raw.decode(enc, errors='replace')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp1251', errors='replace')


def extract(p):
    p = Path(p)
    ext = p.suffix.lower()
    if ext in ('.txt', '.md', '.csv'):
        return read_text_file(p)
    if ext == '.docx':
        from docx import Document
        d = Document(p)
        lines = [x.text for x in d.paragraphs]
        for t in d.tables:
            for r in t.rows:
                lines.append(' | '.join(c.text for c in r.cells))
        return '\n'.join(lines)
    if ext in ('.xlsx', '.xlsm'):
        from openpyxl import load_workbook
        # Cached values: people search for numbers and names, not for formula text.
        w = load_workbook(p, read_only=True, data_only=True)
        try:
            # Номер строки — по счёту, а не из ячейки: пустая первая ячейка в режиме чтения не знает своей строки.
            return '\n'.join(
                f'{s.title}!{n}: ' + ' | '.join(str(v) for v in row if v is not None)
                for s in w for n, row in enumerate(s.iter_rows(values_only=True), 1) if any(v is not None for v in row))
        finally:
            w.close()
    if ext == '.pptx':
        from pptx import Presentation
        return '\n'.join(sh.text for sl in Presentation(p).slides for sh in sl.shapes if sh.has_text_frame)
    if ext == '.pdf':
        from pypdf import PdfReader
        pages = PdfReader(str(p)).pages
        text = '\n'.join(page.extract_text() or '' for page in pages)
        if iskra_ocr.looks_scanned(text, len(pages)) and iskra_ocr.available():
            return iskra_ocr.recognize(p, 'pdf') or text
        return text
    if ext in iskra_ocr.IMAGES:
        return iskra_ocr.recognize(p, 'image')
    return ''


def fold(text):
    """ё → е and lower case: FTS5 unicode61 removes diacritics only for Latin letters."""
    return text.replace('ё', 'е').replace('Ё', 'Е')


def searchable(path, content):
    # The file name is searchable too: people often remember only the title.
    name = Path(path).stem.replace('_', ' ').replace('-', ' ')
    return fold(name + '\n' + content[:MAX_CHARS])


def connect():
    ROOT.mkdir(parents=True, exist_ok=True)
    # The background indexer writes while the window searches: WAL + timeout instead of "database is locked".
    c = sqlite3.connect(DB, timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
    row = c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if row is None or int(row[0]) < SCHEMA_VERSION:
        c.execute('DROP TABLE IF EXISTS docs')
        c.execute('DROP TABLE IF EXISTS search')
        c.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    c.execute('CREATE TABLE IF NOT EXISTS docs (path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER)')
    c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(path UNINDEXED, content, tokenize="unicode61")')
    if iskra_ocr.available() and c.execute("SELECT value FROM meta WHERE key='ocr'").fetchone() is None:
        # Распознавание только что установлено: PDF-сканы, прочитанные раньше как пустые, перечитываются.
        c.execute("DELETE FROM docs WHERE lower(path) LIKE '%.pdf' AND path IN "
                  "(SELECT path FROM search WHERE length(content) < 300)")
        c.execute("INSERT OR REPLACE INTO meta VALUES ('ocr', '1')")
    c.commit()
    return c


def index_folder(folder, notify):
    c = connect()
    found = set(); done = 0; errors = 0; failed = set()
    scan_errors = []

    def walk_error(err):
        scan_errors.append(str(err))
        notify(f'Нет доступа к папке: {err}')

    try:
        for base, dirs, files in os.walk(folder, onerror=walk_error):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('$RECYCLE.BIN', 'System Volume Information')]
            for name in files:
                p = Path(base) / name
                if not supported(p) or name.startswith('~$'):
                    continue
                path = str(p); found.add(path)
                try:
                    st = p.stat(); mtime = st.st_mtime_ns
                    old = c.execute('SELECT mtime,size FROM docs WHERE path=?', (path,)).fetchone()
                    if old != (mtime, st.st_size):
                        content = extract(p)
                        c.execute('DELETE FROM search WHERE path=?', (path,))
                        c.execute('INSERT INTO search(path,content) VALUES (?,?)', (path, searchable(path, content)))
                        c.execute('INSERT OR REPLACE INTO docs VALUES (?,?,?)', (path, mtime, st.st_size))
                    done += 1
                    if done % 20 == 0:
                        c.commit()
                        notify(f'Обработано: {done}, ошибок: {errors}')
                except Exception as e:
                    errors += 1; failed.add(path); notify(f'Не удалось прочитать {name}: {e}')
        # Never delete stale records when traversal was incomplete due to access errors.
        if scan_errors:
            c.commit()
            notify(f'Проверка частичная: {len(scan_errors)} ошибок доступа. Удаление записей пропущено.')
            return
        # Only remove entries from this folder; other indexed folders remain untouched.
        prefix = str(Path(folder).resolve()) + os.sep
        for (path,) in c.execute('SELECT path FROM docs').fetchall():
            if path.startswith(prefix) and path not in found and path not in failed:
                c.execute('DELETE FROM docs WHERE path=?', (path,))
                c.execute('DELETE FROM search WHERE path=?', (path,))
        c.commit()
        notify(f'Готово: {done} файлов, ошибок: {errors}')
    finally:
        c.close()


def forget_folder(folder):
    """Remove a folder's documents from the index (the files themselves are not touched)."""
    prefix = str(Path(folder).resolve()) + os.sep
    c = connect()
    try:
        paths = [p for (p,) in c.execute('SELECT path FROM docs').fetchall() if p.startswith(prefix)]
        for p in paths:
            c.execute('DELETE FROM docs WHERE path=?', (p,))
            c.execute('DELETE FROM search WHERE path=?', (p,))
        c.commit()
        return len(paths)
    finally:
        c.close()


def stem(word):
    """Crude Russian stemming for prefix search: «договоров» and «договоры» both become «договор*»."""
    if not re.search('[а-я]', word):
        return word
    if len(word) >= 7:
        return word[:-2]
    if len(word) >= 5:
        return word[:-1]
    return word


def search_docs(q, limit=100, any_word=False):
    """any_word=True — достаточно любого из слов (для нейросети: вопрос обычной фразой)."""
    tokens = re.findall(r'[^\W_]+', fold(q.lower()), re.UNICODE)
    if not tokens:
        return []
    # Короткое слово (сокращение «ПУ», «КП», «БР») — точно, а не как начало слова: иначе «пу*» найдёт «пункт», «путь».
    expression = (' OR ' if any_word else ' AND ').join(
        '"' + x.replace('"', '') + '"' if len(x) <= 2 else '"' + stem(x).replace('"', '') + '"*' for x in tokens[:12])
    c = connect()
    try:
        return c.execute(
            'SELECT path, snippet(search,1,"[","]","…",18) FROM search WHERE search MATCH ? ORDER BY rank LIMIT ?',
            (expression, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def stats():
    c = connect()
    try:
        return c.execute('SELECT COUNT(*) FROM docs').fetchone()[0]
    finally:
        c.close()


def iter_documents(max_chars=None):
    """(path, indexed text) for every document — for checks across all files, e.g. deadlines.
    max_chars: only the beginning of each text (folder overview over thousands of files)."""
    c = connect()
    try:
        query = 'SELECT path, substr(content, 1, ?) FROM search' if max_chars else 'SELECT path, content FROM search'
        for path, content in c.execute(query, (max_chars,) if max_chars else ()):
            yield path, content
    finally:
        c.close()
