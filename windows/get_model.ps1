# Скачивает модель Qwen3.5-4B (Apache 2.0, ~2,8 ГБ) в папку models. Нужен интернет — только при сборке.
param([string]$Target = (Join-Path $PSScriptRoot 'models'),
      [string]$Url = 'https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/resolve/main/Qwen_Qwen3.5-4B-Q4_K_M.gguf')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force $Target | Out-Null
$file = Join-Path $Target ([IO.Path]::GetFileName($Url))
if (-not (Test-Path $file)) {
  Write-Host "Скачиваю модель: $Url"
  Invoke-WebRequest $Url -OutFile $file
}
$size = (Get-Item $file).Length
if ($size -lt 500MB) { throw "Файл модели слишком маленький ($size байт) — загрузка не удалась" }
Set-Content (Join-Path $Target 'README.txt') @"
Модель: Qwen3.5-4B (Alibaba Qwen), квантование GGUF $([IO.Path]::GetFileName($Url)).
Лицензия: Apache 2.0 — https://huggingface.co/Qwen/Qwen3.5-4B
Источник файла: $Url
Модель работает только на этом компьютере через llama.cpp (папка engine). Интернет не нужен.
Можно заменить на другую модель GGUF: положите файл .gguf сюда и удалите старый.
"@
Write-Host "Готово: $file ($([math]::Round($size / 1GB, 2)) ГБ)"
