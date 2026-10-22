"""Распознавание сканов без интернета: Tesseract (папка ocr рядом с программой, дополнительный архив
Iskra-dop-skany.zip) читает картинки и PDF-сканы. Страницы PDF рисуются в картинку библиотекой pdfium.
Результат запоминается (data/ocr_cache), чтобы один и тот же скан не распознавался дважды."""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGES = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp'}
MAX_PAGES = 40
DPI = 300
BINARY = None            # для тестов: другой tesseract
TESSDATA = None


def base_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def _exe():
    if BINARY:
        return Path(BINARY)
    return base_dir() / 'ocr' / ('tesseract.exe' if sys.platform == 'win32' else 'tesseract')


def _tessdata():
    return Path(TESSDATA) if TESSDATA else base_dir() / 'ocr' / 'tessdata'


_checked = (0.0, False)


def available():
    global _checked
    import time
    now = time.monotonic()
    if BINARY is None and now - _checked[0] < 60:
        return _checked[1]
    ok = _exe().is_file() and (_tessdata() / 'rus.traineddata').is_file()
    _checked = (now, ok)
    return ok


def _cache_file(path):
    st = Path(path).stat()
    key = hashlib.sha1(f'{Path(path).resolve()}|{st.st_mtime_ns}|{st.st_size}'.encode('utf-8')).hexdigest()
    return Path(os.environ.get('ISKRA_DATA_DIR', str(base_dir() / 'data'))) / 'ocr_cache' / (key + '.txt')


def _work_dir():
    """Временные картинки — внутри папки программы (data/ocr_tmp), чтобы путь к ним из папки ocr был относительным
    и латиницей: Tesseract не понимает русские буквы ни в командной строке, ни в TESSDATA_PREFIX."""
    d = Path(os.environ.get('ISKRA_DATA_DIR', str(base_dir() / 'data'))) / 'ocr_tmp'
    try:
        d.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix='ocr_', dir=d))
    except OSError:
        return Path(tempfile.mkdtemp(prefix='iskra_ocr_'))


def _rel(path, start):
    try:
        return os.path.relpath(path, start)
    except ValueError:
        return str(path)


def _tesseract(image):
    tessdata = _tessdata()
    langs = 'rus+eng' if (tessdata / 'eng.traineddata').is_file() else 'rus'
    home = _exe().parent
    env = dict(os.environ, OMP_THREAD_LIMIT='2')
    env.pop('TESSDATA_PREFIX', None)
    out = subprocess.run([str(_exe()), _rel(image, home), 'stdout', '--tessdata-dir', _rel(tessdata, home),
                          '-l', langs, '--psm', '3'], cwd=str(home), capture_output=True, env=env, timeout=300,
                         stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if out.returncode != 0:
        raise RuntimeError('распознавание не удалось: ' + out.stderr.decode('utf-8', 'replace')[-300:])
    return out.stdout.decode('utf-8', 'replace')


def _write_pgm(bitmap, target):
    """Страница в серых тонах → PGM (его читает Tesseract), без сторонних библиотек картинок."""
    w, h, stride = bitmap.width, bitmap.height, bitmap.stride
    data = bytes(bitmap.buffer)
    with open(target, 'wb') as f:
        f.write(f'P5\n{w} {h}\n255\n'.encode('ascii'))
        if stride == w:
            f.write(data[:w * h])
        else:
            for y in range(h):
                f.write(data[y * stride:y * stride + w])


def pdf_pages_text(path, max_pages=MAX_PAGES):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    texts = []
    tmp = _work_dir()
    try:
        for i in range(min(len(pdf), max_pages)):
            page = pdf[i]
            bitmap = page.render(scale=DPI / 72, grayscale=True)
            image = tmp / f'p{i}.pgm'
            _write_pgm(bitmap, image)
            bitmap.close()
            page.close()
            texts.append(_tesseract(image))
            image.unlink()
        if len(pdf) > max_pages:
            texts.append(f'[распознаны первые {max_pages} страниц из {len(pdf)}]')
    finally:
        pdf.close()
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
    return '\n'.join(texts)


def recognize(path, kind=None):
    """Текст скана (картинка или PDF без текстового слоя). Пустая строка, если распознавание не установлено."""
    if not available():
        return ''
    path = Path(path)
    cache = _cache_file(path)
    if cache.is_file():
        return cache.read_text(encoding='utf-8')
    kind = kind or ('pdf' if path.suffix.lower() == '.pdf' else 'image')
    if kind == 'pdf':
        text = pdf_pages_text(path)
    else:
        # Копия во временную папку под латинским именем — Tesseract не всегда открывает файлы с русскими именами.
        tmp = _work_dir()
        try:
            copy = tmp / ('scan' + path.suffix.lower())
            copy.write_bytes(path.read_bytes())
            text = _tesseract(copy)
        finally:
            for f in tmp.iterdir():
                f.unlink()
            tmp.rmdir()
    text = '[РАСПОЗНАНО СО СКАНА — проверьте цифры и фамилии]\n' + text.strip() if text.strip() else ''
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding='utf-8')
    except OSError:
        pass
    return text


def looks_scanned(text, pages):
    """В PDF почти нет текста — значит, это скан."""
    return len((text or '').strip()) < 40 * max(1, pages)
