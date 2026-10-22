# Скачивает свежий llama.cpp для Windows x64 (CPU) в папку engine. Нужен интернет — только при сборке.
param([string]$Target = (Join-Path $PSScriptRoot 'engine'), [string]$Tools = '')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ 'User-Agent' = 'Iskra' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
# Самый свежий выпуск со сборкой для Windows x64 на процессоре (бывают выпуски без неё).
$releases = Invoke-RestMethod -Headers $headers 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30'
$release = $null; $asset = $null
foreach ($r in $releases) {
  if ($r.draft) { continue }
  $a = $r.assets | Where-Object { $_.name -match 'win.*cpu.*x64.*\.zip$' -and $_.name -notmatch 'cudart' } | Select-Object -First 1
  if ($a) { $release = $r; $asset = $a; break }
}
if (-not $asset) { throw 'Не найдена сборка llama.cpp для Windows x64 (CPU)' }
$zip = Join-Path $env:TEMP $asset.name
Write-Host "Скачиваю llama.cpp $($release.tag_name): $($asset.name)"
Invoke-WebRequest -Headers $headers $asset.browser_download_url -OutFile $zip
$unpacked = Join-Path $env:TEMP 'iskra_llama'
if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
Expand-Archive $zip $unpacked
New-Item -ItemType Directory -Force $Target | Out-Null
# Нужны только программа для одиночных ответов и её библиотеки (без сервера и сетевых утилит).
Get-ChildItem $unpacked -Recurse -Include 'llama-completion.exe','llama-cli.exe','*.dll' | Copy-Item -Destination $Target -Force
if ($Tools) {
  # Для сборки: программа, которая режет модель на части меньше 2 ГБ (ограничение GitHub на файл).
  New-Item -ItemType Directory -Force $Tools | Out-Null
  Get-ChildItem $unpacked -Recurse -Include 'llama-gguf-split.exe','*.dll' | Copy-Item -Destination $Tools -Force
}
# Движку нужны библиотеки Microsoft Visual C++ (MSVCP140, VCRUNTIME140). На многих рабочих компьютерах их нет —
# кладём рядом с движком (разрешённое Microsoft «локальное» распространение), Windows берёт их из папки программы.
foreach ($dll in 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll') {
  $src = Join-Path $env:SystemRoot "System32\$dll"
  if (Test-Path $src) { Copy-Item $src -Destination $Target -Force }
}
Set-Content (Join-Path $Target 'VERSION.txt') "llama.cpp $($release.tag_name) — https://github.com/ggml-org/llama.cpp (MIT)"
Write-Host "Готово: $Target"
