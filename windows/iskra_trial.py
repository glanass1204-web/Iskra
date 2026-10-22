"""Пробный запуск макроса на КОПИИ файла в настоящем Excel/Word — до того, как человек запустит его у себя.
Excel/Word запускаются невидимо через PowerShell (COM); исходный файл не открывается и не меняется.
Окна сообщений макроса (MsgBox) подменяются записью в журнал, чтобы невидимый Excel не ждал нажатия «ОК».
Макросы, которые сами просят выбрать папку или файл, пробно не запускаются — их проверяет только разбор кода.
Для доступа к коду книги Excel/Word на время проверки включается «Доверять доступ к объектной модели VBA»
(только у этого пользователя) и сразу возвращается как было."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

TIMEOUT = 120
MODULE = 'IskraTrial'
HARNESS = 'IskraTrialHarness'
# То, что открывает окно и ждёт человека: невидимый Excel повис бы.
INTERACTIVE = re.compile(r'\b(FileDialog|GetOpenFilename|GetSaveAsFilename|InputBox|BrowseForFolder|Dialogs\s*\(|'
                         r'\.Show\b|SendKeys|UserForm)', re.IGNORECASE)


@dataclass
class Result:
    ok: bool
    error: str = ''                                  # текст ошибки Excel/Word
    messages: list = field(default_factory=list)     # что макрос показал бы в окнах сообщений
    unavailable: str = ''                            # почему пробный запуск невозможен (не ошибка макроса)

    def summary(self):
        if self.unavailable:
            return 'Пробный запуск недоступен: ' + self.unavailable
        if self.ok:
            shown = ('\nМакрос сообщил: ' + ' | '.join(m.strip() for m in self.messages if m.strip())[:400]) if self.messages else ''
            return 'Пробный запуск на копии прошёл без ошибок.' + shown
        shown = ('\nМакрос сообщил: ' + ' | '.join(m.strip() for m in self.messages if m.strip())[:400]) if self.messages else ''
        return 'При пробном запуске ошибка: ' + self.error + shown


def supported():
    return sys.platform == 'win32'


def _strip(line):
    return re.sub(r"'.*$", '', re.sub(r'"(?:[^"]|"")*"', '""', line))


def entry_point(code):
    """Главная процедура: первая Sub без параметров, не Private."""
    for m in re.finditer(r'^\s*(Public\s+|Private\s+)?Sub\s+(\w+)\s*\(\s*\)', code, re.IGNORECASE | re.MULTILINE):
        if not (m.group(1) or '').lower().startswith('private'):
            return m.group(2)
    return ''


def _replace_msgbox(line):
    """MsgBox вне строк и комментариев → IskraTrialMsg (тот же порядок аргументов)."""
    out, i = [], 0
    for m in re.finditer(r'"(?:[^"]|"")*"|\'.*$', line):
        out.append(re.sub(r'\bMsgBox\b', 'IskraTrialMsg', line[i:m.start()], flags=re.IGNORECASE))
        out.append(m.group(0))
        i = m.end()
    out.append(re.sub(r'\bMsgBox\b', 'IskraTrialMsg', line[i:], flags=re.IGNORECASE))
    return ''.join(out)


def harness(entry):
    return '\n'.join([
        'Option Explicit',
        'Public IskraTrialLog As String',
        '',
        'Public Function IskraTrialMsg(Optional ByVal Prompt As Variant = "", Optional ByVal Buttons As Variant = 0, '
        'Optional ByVal Title As Variant = "", Optional ByVal HelpFile As Variant, Optional ByVal Context As Variant) As Long',
        '    If Err.Number <> 0 Then',                       # окно показано из обработчика ошибки — это ошибка макроса
        '        IskraTrialLog = IskraTrialLog & "!ERR " & Err.Number & " " & Err.Description & vbLf',
        '    End If',
        '    IskraTrialLog = IskraTrialLog & "MSG " & Replace(CStr(Prompt), vbLf, " ") & vbLf',
        '    IskraTrialMsg = 6',                              # «Да»/«ОК»
        'End Function',
        '',
        'Public Function IskraTrialRun() As String',
        '    IskraTrialLog = ""',
        '    On Error GoTo Failed',
        f'    Call {entry}',
        '    IskraTrialRun = "OK" & vbLf & IskraTrialLog',
        '    Exit Function',
        'Failed:',
        '    IskraTrialRun = "ERR" & vbLf & "!ERR " & Err.Number & " " & Err.Description & vbLf & IskraTrialLog',
        'End Function', ''])


def prepare(code):
    """(код для пробного запуска, имя главной процедуры, причина отказа). Чистая функция — проверяется тестами."""
    entry = entry_point(code)
    if not entry:
        return '', '', 'в коде нет процедуры Sub без параметров — нечего запускать.'
    body = '\n'.join(_strip(line) for line in code.splitlines())
    m = INTERACTIVE.search(body)
    if m:
        return '', entry, (f'макрос открывает окно выбора или ввода ({m.group(1).strip()}) — без человека его не запустить. '
                           'Код проверен разбором; запустите его на копии файла сами.')
    test = '\n'.join(_replace_msgbox(line) for line in code.replace('\r\n', '\n').split('\n'))
    return test, entry, ''


def parse(raw):
    """Ответ IskraTrialRun → Result."""
    lines = (raw or '').replace('\r', '').split('\n')
    head, rest = lines[0].strip(), [x for x in lines[1:] if x.strip()]
    errors = [x[5:].strip() for x in rest if x.startswith('!ERR ')]
    messages = [x[4:] for x in rest if x.startswith('MSG ')]
    if head == 'OK' and not errors:
        return Result(True, messages=messages)
    if head in ('OK', 'ERR'):
        return Result(False, error=errors[0] if errors else 'макрос сообщил об ошибке', messages=messages)
    return Result(False, unavailable='Excel/Word не вернул результат.')


PS_SCRIPT = r'''
param([string]$App, [string]$File, [string]$Code, [string]$Harness, [string]$Out)
$ErrorActionPreference = 'Stop'
$result = @{ status = 'fail'; text = '' }
$progId = if ($App -eq 'word') { 'Word.Application' } else { 'Excel.Application' }
$folder = if ($App -eq 'word') { 'Word' } else { 'Excel' }
$saved = @()
$o = $null; $doc = $null
function Save-Result { [IO.File]::WriteAllText($Out, ($result | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false)) }
try {
    try { $o = New-Object -ComObject $progId } catch { $result.status = 'noapp'; $result.text = $_.Exception.Message; Save-Result; exit 0 }
    $ver = $o.Version
    try { $o.Quit() } catch {}
    [Runtime.InteropServices.Marshal]::ReleaseComObject($o) | Out-Null
    $o = $null; [GC]::Collect(); Start-Sleep -Milliseconds 800
    $key = "HKCU:\Software\Microsoft\Office\$ver\$folder\Security"
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    $old = (Get-ItemProperty -Path $key -Name AccessVBOM -ErrorAction SilentlyContinue).AccessVBOM
    $saved = @($key, $old)
    Set-ItemProperty -Path $key -Name AccessVBOM -Value 1 -Type DWord
    $o = New-Object -ComObject $progId
    try { [IO.File]::WriteAllText($Out + '.hwnd', [string]$o.Hwnd) } catch {}
    $o.Visible = $false
    try { $o.DisplayAlerts = $(if ($App -eq 'word') { 0 } else { $false }) } catch {}
    try { $o.AutomationSecurity = 1 } catch {}
    if ($App -eq 'word') {
        if ($File) { $doc = $o.Documents.Open($File, $false, $false, $false) }
        else { $doc = $o.Documents.Add(); $p = Join-Path (Split-Path $Out) 'empty.docx'; try { $doc.SaveAs2($p) } catch { try { $doc.SaveAs([ref]$p) } catch {} } }
    } else {
        if ($File) { $doc = $o.Workbooks.Open($File, 0, $false) }
        else { $doc = $o.Workbooks.Add(); try { $doc.SaveAs((Join-Path (Split-Path $Out) 'empty.xlsx'), 51) } catch {} }
    }
    try { $proj = $doc.VBProject; $null = $proj.VBComponents.Count }
    catch { $result.status = 'novbom'; $result.text = $_.Exception.Message; Save-Result; exit 0 }
    $m1 = $proj.VBComponents.Add(1); $m1.Name = 'IskraTrial'
    $m1.CodeModule.AddFromString([IO.File]::ReadAllText($Code, [Text.Encoding]::UTF8))
    $m2 = $proj.VBComponents.Add(1); $m2.Name = 'IskraTrialHarness'
    $m2.CodeModule.AddFromString([IO.File]::ReadAllText($Harness, [Text.Encoding]::UTF8))
    try {
        $result.text = [string]$o.Run('IskraTrialHarness.IskraTrialRun')
        $result.status = 'ran'
    } catch {
        $result.status = 'error'; $result.text = $_.Exception.Message
    }
} catch {
    $result.status = 'fail'; $result.text = $_.Exception.Message
} finally {
    try { if ($doc) { $doc.Close($false) } } catch {}
    try { if ($o) { $o.Quit() } } catch {}
    if ($saved.Count -eq 2) {
        if ($null -eq $saved[1]) { Remove-ItemProperty -Path $saved[0] -Name AccessVBOM -ErrorAction SilentlyContinue }
        else { Set-ItemProperty -Path $saved[0] -Name AccessVBOM -Value $saved[1] -Type DWord }
    }
    Save-Result
}
'''


def _office_pids(app):
    image = 'WINWORD.EXE' if app == 'word' else 'EXCEL.EXE'
    try:
        out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {image}', '/FO', 'CSV', '/NH'], capture_output=True,
                             text=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(m.group(1)) for m in re.finditer(r'^"[^"]+","(\d+)"', out, re.MULTILINE)}


def _pid_of_window(hwnd):
    try:
        import ctypes
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(int(hwnd)), ctypes.byref(pid))
        return pid.value
    except (OSError, ValueError, AttributeError):
        return 0


def _close_own(app, before, out):
    """Закрыть ТОЛЬКО тот Excel/Word, который запустила проверка (по его окну), — не открытые человеком."""
    pid = 0
    try:
        pid = _pid_of_window(Path(str(out) + '.hwnd').read_text().strip())
    except OSError:
        pass
    if not pid:
        new = _office_pids(app) - before
        pid = new.pop() if len(new) == 1 else 0               # неясно, какой наш — лучше не трогать ничего
    if pid:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _decode(status, text, app='excel'):
    text = (text or '').strip()
    if status == 'noapp':
        return Result(False, unavailable='на компьютере не найден Microsoft ' + ('Word' if app == 'word' else 'Excel') + '.')
    if status == 'novbom':
        return Result(False, unavailable='настройки безопасности Office (политика организации) запрещают программам доступ к '
                                         'коду макросов. Проверка выполнена только разбором кода.')
    if status == 'ran':
        return parse(text)
    if status == 'error':
        if re.search(r'compile|компил|syntax|синтакс', text, re.IGNORECASE):
            return Result(False, error='ошибка компиляции (код не собирается): ' + text)
        if re.search(r'disabled|отключ|cannot run|невозможно выполнить', text, re.IGNORECASE):
            return Result(False, unavailable='запуск макросов запрещён настройками Office: ' + text)
        return Result(False, error=text)
    return Result(False, unavailable='не удалось запустить проверку: ' + (text or 'неизвестная причина'))


def run(code, app='excel', file=None, timeout=TIMEOUT, cancel=None):
    """Пробный запуск. file — путь к файлу пользователя: открывается его КОПИЯ во временной папке."""
    if not supported():
        return Result(False, unavailable='пробный запуск работает только в Windows с установленным Office.')
    test, entry, refuse = prepare(code)
    if refuse:
        return Result(False, unavailable=refuse)
    work = Path(tempfile.mkdtemp(prefix='iskra_trial_'))
    try:
        copy = ''
        if file:
            src = Path(file)
            copy = str(work / ('copy' + src.suffix.lower()))
            shutil.copy2(src, copy)
        (work / 'code.bas').write_text(test, encoding='utf-8')
        (work / 'harness.bas').write_text(harness(entry), encoding='utf-8')
        script = work / 'trial.ps1'
        script.write_text(PS_SCRIPT, encoding='utf-8-sig')       # BOM: PowerShell 5 иначе читает как ANSI
        out = work / 'result.json'
        before = _office_pids(app)
        proc = subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                                 '-App', app, '-File', copy, '-Code', str(work / 'code.bas'),
                                 '-Harness', str(work / 'harness.bas'), '-Out', str(out)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started, stopped = time.time(), ''
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                stopped = 'остановлено.'
            elif time.time() - started > timeout:
                stopped = (f'макрос не закончил работу за {timeout} с — возможно, он ждёт ответа в окне или зациклился.')
            if stopped:
                proc.kill()
                _close_own(app, before, out)
                if 'не закончил' in stopped:
                    return Result(False, error=stopped)
                return Result(False, unavailable=stopped)
            time.sleep(0.3)
        _, err = proc.communicate()
        try:
            data = json.loads(out.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            tail = err.decode('cp866', 'replace').strip()[-300:] if err else ''
            return Result(False, unavailable='PowerShell не выполнил проверку (возможно, запрещён политикой). ' + tail)
        return _decode(data.get('status'), data.get('text'), app)
    finally:
        shutil.rmtree(work, ignore_errors=True)
