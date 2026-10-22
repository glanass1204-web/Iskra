# Собирает голосовые команды (whisper.cpp, MIT; модель Whisper small, MIT) в папку voice. Нужен интернет — только при сборке.
param([string]$Target = (Join-Path $PSScriptRoot 'voice'), [string]$ModelCache = (Join-Path $PSScriptRoot 'voice-cache'))
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ 'User-Agent' = 'Iskra' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
$tag = $null; $url = $null
try {
  $releases = Invoke-RestMethod -Headers $headers 'https://api.github.com/repos/ggml-org/whisper.cpp/releases?per_page=20'
  foreach ($r in $releases) {
    if ($r.draft) { continue }
    $a = $r.assets | Where-Object { $_.name -match '^whisper-bin-x64\.zip$' } | Select-Object -First 1
    if ($a) { $tag = $r.tag_name; $url = $a.browser_download_url; break }
  }
} catch { Write-Host "Список выпусков недоступен: $($_.Exception.Message)" }
if (-not $url) {
  $resp = Invoke-WebRequest 'https://github.com/ggml-org/whisper.cpp/releases/latest' -MaximumRedirection 0 -SkipHttpErrorCheck -Headers @{ 'User-Agent' = 'Iskra' }
  $loc = [string]$resp.Headers.Location
  if ($loc -match '/tag/([^/]+)$') { $tag = $Matches[1] }
  if (-not $tag) { throw 'Не найдена сборка whisper.cpp для Windows x64' }
  $url = "https://github.com/ggml-org/whisper.cpp/releases/download/$tag/whisper-bin-x64.zip"
}
$zip = Join-Path $env:TEMP 'whisper-bin-x64.zip'
Write-Host "Скачиваю whisper.cpp ${tag}"
Invoke-WebRequest -Headers @{ 'User-Agent' = 'Iskra' } $url -OutFile $zip
$unpacked = Join-Path $env:TEMP 'iskra_whisper'
if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
Expand-Archive $zip $unpacked
New-Item -ItemType Directory -Force $Target | Out-Null
Get-ChildItem $unpacked -Recurse -Include 'whisper-cli.exe', '*.dll' | Copy-Item -Destination $Target -Force
if (-not (Test-Path (Join-Path $Target 'whisper-cli.exe'))) { throw 'В сборке whisper.cpp нет whisper-cli.exe' }
foreach ($dll in 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll', 'vcomp140.dll') {
  $src = Join-Path $env:SystemRoot "System32\$dll"
  if (Test-Path $src) { Copy-Item $src -Destination $Target -Force }
}
# Модель распознавания русской речи: small, сжатая (~190 МБ). Кэшируется между сборками.
New-Item -ItemType Directory -Force $ModelCache | Out-Null
$model = Join-Path $ModelCache 'ggml-small-q5_1.bin'
if (-not (Test-Path $model) -or (Get-Item $model).Length -lt 100MB) {
  Invoke-WebRequest 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin' -OutFile $model
}
Copy-Item $model $Target -Force
Set-Content (Join-Path $Target 'VERSION.txt') "whisper.cpp $tag — https://github.com/ggml-org/whisper.cpp (MIT); модель Whisper small (MIT, OpenAI)"
Write-Host "Готово: $Target"
