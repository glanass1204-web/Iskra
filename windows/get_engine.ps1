# Скачивает свежий llama.cpp для Windows x64 (CPU) в папку engine. Нужен интернет — только при сборке.
param([string]$Target = (Join-Path $PSScriptRoot 'engine'), [string]$Tools = '')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ 'User-Agent' = 'Iskra' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
# Самый свежий выпуск со сборкой для Windows x64 на процессоре (бывают выпуски без неё).
$tag = $null; $url = $null; $name = $null
try {
  $releases = Invoke-RestMethod -Headers $headers 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30'
  foreach ($r in $releases) {
    if ($r.draft) { continue }
    $a = $r.assets | Where-Object { $_.name -match 'win.*cpu.*x64.*\.zip$' -and $_.name -notmatch 'cudart' } | Select-Object -First 1
    if ($a) { $tag = $r.tag_name; $url = $a.browser_download_url; $name = $a.name; break }
  }
} catch { Write-Host "Список выпусков недоступен: $($_.Exception.Message)" }
if (-not $url) {
  # Запасной путь без API: последний выпуск по ссылке releases/latest, имя файла — по образцу llama-<тег>-bin-win-cpu-x64.zip
  # releases/latest переадресует на страницу последнего выпуска — номер выпуска берём из итогового адреса.
  $resp = Invoke-WebRequest 'https://github.com/ggml-org/llama.cpp/releases/latest' -Headers @{ 'User-Agent' = 'Iskra' }
  $final = [string]$resp.BaseResponse.RequestMessage.RequestUri
  Write-Host "Последний выпуск: $final"
  if ($final -match '/tag/([^/?#]+)') { $tag = $Matches[1] }
  if (-not $tag) { throw 'Не найдена сборка llama.cpp для Windows x64 (CPU)' }
  $name = "llama-$tag-bin-win-cpu-x64.zip"
  $url = "https://github.com/ggml-org/llama.cpp/releases/download/$tag/$name"
}
$zip = Join-Path $env:TEMP $name
Write-Host "Скачиваю llama.cpp ${tag}: $name"
Invoke-WebRequest -Headers @{ 'User-Agent' = 'Iskra' } $url -OutFile $zip
$unpacked = Join-Path $env:TEMP 'iskra_llama'
if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
Expand-Archive $zip $unpacked
New-Item -ItemType Directory -Force $Target | Out-Null
# Программа для одиночных ответов и быстрый режим (llama-server: слушает только 127.0.0.1, с ключом) с библиотеками.
Get-ChildItem $unpacked -Recurse -Include 'llama-completion.exe','llama-cli.exe','llama-server.exe','*.dll' | Copy-Item -Destination $Target -Force
if ($Tools) {
  # Для сборки: программа, которая режет модель на части меньше 2 ГБ (ограничение GitHub на файл).
  New-Item -ItemType Directory -Force $Tools | Out-Null
  Get-ChildItem $unpacked -Recurse -Include 'llama-gguf-split.exe','*.dll' | Copy-Item -Destination $Tools -Force
}
# Движку нужны библиотеки Microsoft Visual C++ (MSVCP140, VCRUNTIME140). На многих рабочих компьютерах их нет —
# кладём рядом с движком (разрешённое Microsoft «локальное» распространение), Windows берёт их из папки программы.
foreach ($dll in 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll', 'vcomp140.dll') {
  $src = Join-Path $env:SystemRoot "System32\$dll"
  if (Test-Path $src) { Copy-Item $src -Destination $Target -Force }
}
Set-Content (Join-Path $Target 'VERSION.txt') "llama.cpp $tag — https://github.com/ggml-org/llama.cpp (MIT)"
Write-Host "Готово: $Target"
