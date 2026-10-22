"""Дополнительные архивы (Iskra-dop-….zip) кладут папку рядом с программой: ocr — распознавание сканов,
voice — голосовые команды. Если архив распаковали «Извлечь всё» в отдельную папку, Искра находит её
по соседству (и в Загрузках, на Рабочем столе) и переносит к себе."""
import shutil
import sys
from pathlib import Path

ADDONS = {'ocr': ('tesseract.exe', 'tesseract'), 'voice': ('whisper-cli.exe', 'whisper-cli')}


def base_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def installed(name, base=None):
    folder = Path(base or base_dir()) / name
    return any((folder / marker).is_file() for marker in ADDONS[name])


def gather(base=None, extra_roots=None):
    """Переносит найденные дополнения к программе. Возвращает их названия."""
    base = Path(base).resolve() if base else base_dir()
    if extra_roots is None:
        extra_roots = [Path.home() / 'Downloads', Path.home() / 'Desktop', Path.home() / 'Загрузки']
    roots = [base.parent, base.parent.parent] + [Path(r) for r in extra_roots]
    moved = []
    for name in ADDONS:
        if installed(name, base):
            continue
        for root in roots:
            found = None
            for pattern in (f'*/Iskra/{name}', f'*/*/Iskra/{name}', f'Iskra/{name}'):
                try:
                    found = next((d for d in root.glob(pattern) if d.resolve() != (base / name).resolve()
                                  and installed(name, d.parent)), None)
                except OSError:
                    found = None
                if found:
                    break
            if found:
                try:
                    if (base / name).exists():
                        shutil.rmtree(base / name)
                    shutil.move(str(found), str(base / name))
                    moved.append(name)
                except OSError:
                    pass
                break
    return moved
