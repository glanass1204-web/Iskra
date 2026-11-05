"""Старые форматы .doc и .xls — в .docx и .xlsx через установленные Word и Excel (без окон, копия файла).
Исходный файл не меняется; копия кладётся в папку данных Искры (converted)."""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from iskra_index import ROOT

OLD = {'.doc': ('word', '.docx', 16), '.xls': ('excel', '.xlsx', 51)}

PS = r'''
param([string]$App, [string]$In, [string]$Out, [int]$Fmt)
$ErrorActionPreference = 'Stop'
$o = $null; $d = $null
try {
    if ($App -eq 'word') {
        $o = New-Object -ComObject Word.Application; $o.Visible = $false; $o.DisplayAlerts = 0
        $d = $o.Documents.Open($In, $false, $true, $false)
        $d.SaveAs2($Out, $Fmt); $d.Close($false)
    } else {
        $o = New-Object -ComObject Excel.Application; $o.Visible = $false; $o.DisplayAlerts = $false
        $d = $o.Workbooks.Open($In, 0, $true)
        $d.SaveAs($Out, $Fmt); $d.Close($false)
    }
} finally {
    if ($o) { try { $o.Quit() } catch {}; [Runtime.InteropServices.Marshal]::ReleaseComObject($o) | Out-Null }
}
'''


class ConvertError(Exception):
    pass


def needs(path):
    return Path(path).suffix.lower() in OLD


def convert(path, timeout=120):
    """.doc/.xls → путь к копии .docx/.xlsx. Остальное — как есть. ConvertError с понятной причиной, если нельзя."""
    src = Path(path)
    ext = src.suffix.lower()
    if ext not in OLD:
        return str(src)
    app, new_ext, fmt = OLD[ext]
    name = 'Word' if app == 'word' else 'Excel'
    if sys.platform != 'win32':
        raise ConvertError(f'{src.name}: старый формат {ext} — откройте в {name} и сохраните как {new_ext}.')
    key = hashlib.sha1(f'{src.resolve()}|{src.stat().st_mtime}'.encode('utf-8')).hexdigest()[:10]
    folder = ROOT / 'converted'
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f'{src.stem}_{key}{new_ext}'
    if out.is_file():
        return str(out)
    work = folder / f'{key}_src{ext}'
    shutil.copy2(src, work)                                # открываем копию: исходный файл не трогаем
    script = folder / 'convert.ps1'
    script.write_text(PS, encoding='utf-8-sig')
    try:
        proc = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                               '-App', app, '-In', str(work), '-Out', str(out), '-Fmt', str(fmt)],
                              capture_output=True, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    finally:
        try:
            work.unlink()
        except OSError:
            pass
    if not out.is_file():
        tail = proc.stderr.decode('cp866', 'replace').strip()[-200:] if proc is not None and proc.stderr else ''
        raise ConvertError(f'{src.name}: не удалось пересохранить из {ext} в {new_ext} через {name}'
                           + (f' ({tail})' if tail else '') + f'. Откройте файл в {name} и сохраните как {new_ext}.')
    return str(out)
