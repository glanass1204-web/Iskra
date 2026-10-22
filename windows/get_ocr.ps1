# Собирает распознавание сканов (Tesseract, Apache 2.0) в папку ocr: программа, её библиотеки, русский и английский языки.
# Нужен интернет — только при сборке.
param([string]$Target = (Join-Path $PSScriptRoot 'ocr'))
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = Join-Path $env:ProgramFiles 'Tesseract-OCR'
if (-not (Test-Path (Join-Path $dir 'tesseract.exe'))) {
  choco install tesseract -y --no-progress | Out-Host
}
if (-not (Test-Path (Join-Path $dir 'tesseract.exe'))) { throw 'Tesseract не установился' }
New-Item -ItemType Directory -Force (Join-Path $Target 'tessdata') | Out-Null
Copy-Item (Join-Path $dir 'tesseract.exe') $Target -Force
Get-ChildItem $dir -Filter *.dll | Copy-Item -Destination $Target -Force
foreach ($lang in 'eng', 'osd') {
  $f = Join-Path $dir "tessdata\$lang.traineddata"
  if (Test-Path $f) { Copy-Item $f (Join-Path $Target 'tessdata') -Force }
}
Invoke-WebRequest 'https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata' -OutFile (Join-Path $Target 'tessdata\rus.traineddata')
# Библиотеки Visual C++ — как у движка нейросети, на случай если сборка Tesseract их требует.
foreach ($dll in 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') {
  $src = Join-Path $env:SystemRoot "System32\$dll"
  if (Test-Path $src) { Copy-Item $src -Destination $Target -Force }
}
& (Join-Path $Target 'tesseract.exe') --version | Out-Host
Set-Content (Join-Path $Target 'VERSION.txt') "Tesseract OCR — https://github.com/tesseract-ocr/tesseract (Apache 2.0); языки: tessdata"
Write-Host "Готово: $Target"
