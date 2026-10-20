# Скачивает GigaChat 3.1 10B (GGUF Q4_K_M, около 6,5 ГБ) в папку models.
param([string]$Target = (Join-Path $PSScriptRoot 'models'))
$ErrorActionPreference = 'Stop'
$name = 'GigaChat3.1-10B-A1.8B-q4_K_M.gguf'
$urls = @(
  "https://huggingface.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF/resolve/main/$name",
  "https://huggingface.co/SergeyLizin/GigaChat3.1-10B-A1.8B-GGUF/resolve/main/$name"
)
New-Item -ItemType Directory -Force $Target | Out-Null
$out = Join-Path $Target $name
foreach ($url in $urls) {
  try {
    Write-Host "Скачиваю $url (около 6,5 ГБ, это долго)..."
    # curl.exe есть в Windows 10/11 и умеет докачку (-C -) при обрыве.
    & curl.exe -L --fail --retry 5 -C - -o $out $url
    if ($LASTEXITCODE -eq 0) { Write-Host "Готово: $out"; exit 0 }
  } catch { Write-Host $_ }
}
throw 'Не удалось скачать модель. Скачайте файл вручную и положите в папку models.'
