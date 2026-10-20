@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 (echo Ошибка установки зависимостей & goto :end)
py -3 -m PyInstaller --noconfirm --clean --onedir --windowed --name Iskra --collect-all docx --collect-all openpyxl --collect-all pptx --collect-all pypdf iskra.py
if errorlevel 1 (echo Ошибка сборки & goto :end)
mkdir dist\Iskra\engine 2>nul
mkdir dist\Iskra\models 2>nul
copy /y engine\README.txt dist\Iskra\engine\ >nul
copy /y models\README.txt dist\Iskra\models\ >nul
copy /y README.txt dist\Iskra\ >nul
copy /y get_engine.ps1 dist\Iskra\ >nul
copy /y get_model.ps1 dist\Iskra\ >nul
echo Готово: dist\Iskra\Iskra.exe
echo Движок: powershell -ExecutionPolicy Bypass -File dist\Iskra\get_engine.ps1
echo Модель: powershell -ExecutionPolicy Bypass -File dist\Iskra\get_model.ps1
:end
if not "%1"=="nopause" pause
