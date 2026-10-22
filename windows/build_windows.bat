@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 (echo Ошибка установки зависимостей & goto :end)
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name Iskra --collect-all docx --collect-all openpyxl --collect-all pptx --collect-all pypdf --collect-all spylls --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all pymorphy3 --collect-all pymorphy3_dicts_ru --collect-all dawg_python --add-data "dict;dict" iskra.py
if errorlevel 1 (echo Ошибка сборки & goto :end)
copy /y README.txt dist\Iskra\ >nul
echo Готово: dist\Iskra\Iskra.exe
:end
if not "%1"=="nopause" pause
