"""Проверка сборки: всё, что нужно движку нейросети, лежит в папке engine — кроме частей самой Windows.
Библиотеки Visual C++ (msvcp140, vcruntime140 …) на сервере сборки установлены, а на рабочих компьютерах часто нет,
поэтому они обязаны быть в engine. Запуск: python check_engine_deps.py <папка engine>."""
import os
import sys
from pathlib import Path

import pefile

# Ставятся отдельно (Visual C++ Redistributable, OpenMP) — не часть Windows.
NOT_WINDOWS = ('msvcp', 'vcruntime', 'concrt', 'vccorlib', 'vcomp', 'libomp', 'mfc', 'ucrtbased')


def imports(path):
    pe = pefile.PE(str(path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                                           pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
    names = [e.dll.decode() for e in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])]
    names += [e.dll.decode() for e in getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', [])]
    pe.close()
    return names


def main(engine):
    engine = Path(engine)
    local = {p.name.lower() for p in engine.iterdir()}
    system32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    bad = []
    for f in sorted(engine.glob('*.exe')) + sorted(engine.glob('*.dll')):
        for dll in imports(f):
            low = dll.lower()
            if low in local or low.startswith(('api-ms-win-', 'ext-ms-')):
                continue
            if low.startswith(NOT_WINDOWS) or not (system32 / dll).is_file():
                bad.append(f'{f.name} -> {dll}')
    for line in bad:
        print('НЕТ В engine:', line)
    print('Зависимости движка: ' + ('НЕ ХВАТАЕТ' if bad else 'всё на месте'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
