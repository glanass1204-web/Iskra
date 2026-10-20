@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 (echo Ошибка установки зависимостей & pause & exit /b 1)
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name Iskra --collect-all docx --collect-all openpyxl --collect-all pptx --collect-all pypdf iskra.py
if errorlevel 1 (echo Ошибка сборки & pause & exit /b 1)
echo Готово: dist\Iskra\Iskra.exe
pause
