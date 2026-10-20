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
EXT = {'.docx', '.xlsx', '.xlsm', '.pptx', '.pdf', '.txt', '.md', '.csv'}
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
            return '\n'.join(
                f'{s.title}!{row[0].row}: ' + ' | '.join(str(c.value) for c in row if c.value is not None)
                for s in w for row in s.iter_rows() if any(c.value is not None for c in row))
        finally:
            w.close()
    if ext == '.pptx':
        from pptx import Presentation
        return '\n'.join(sh.text for sl in Presentation(p).slides for sh in sl.shapes if sh.has_text_frame)
    if ext == '.pdf':
        from pypdf import PdfReader
        return '\n'.join(page.extract_text() or '' for page in PdfReader(str(p)).pages)
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
                if p.suffix.lower() not in EXT or name.startswith('~$'):
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


def search_docs(q, limit=100):
    tokens = re.findall(r'[^\W_]+', fold(q.lower()), re.UNICODE)
    if not tokens:
        return []
    expression = ' AND '.join('"' + stem(x).replace('"', '') + '"*' for x in tokens[:12])
    c = connect()
    try:
        return c.execute(
            'SELECT path, snippet(search,1,"[","]","…",18) FROM search WHERE search MATCH ? ORDER BY rank LIMIT ?',
            (expression, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()
