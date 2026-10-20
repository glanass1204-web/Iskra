# Скачивает свежий llama.cpp для Windows x64 (CPU) в папку engine рядом с этим скриптом
# или в папку, переданную первым аргументом. Нужен интернет; запускать на разрешённом компьютере.
param([string]$Target = (Join-Path $PSScriptRoot 'engine'))
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ 'User-Agent' = 'Iskra' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }
$release = Invoke-RestMethod -Headers $headers 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'
$asset = $release.assets | Where-Object { $_.name -match 'bin-win-cpu-x64\.zip$' } | Select-Object -First 1
if (-not $asset) { throw "В выпуске $($release.tag_name) нет сборки win-cpu-x64" }
$zip = Join-Path $env:TEMP $asset.name
Write-Host "Скачиваю llama.cpp $($release.tag_name): $($asset.name)"
Invoke-WebRequest -Headers $headers $asset.browser_download_url -OutFile $zip
$unpacked = Join-Path $env:TEMP 'iskra_llama'
if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
Expand-Archive $zip $unpacked
New-Item -ItemType Directory -Force $Target | Out-Null
# Нужны только программа для одиночных ответов и библиотеки.
Get-ChildItem $unpacked -Recurse -Include 'llama-completion.exe','llama-cli.exe','*.dll' | Copy-Item -Destination $Target -Force
Set-Content (Join-Path $Target 'VERSION.txt') "llama.cpp $($release.tag_name)"
Write-Host "Готово: $Target"
