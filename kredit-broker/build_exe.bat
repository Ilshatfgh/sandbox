@echo off
chcp 65001 >nul
rem Сборка KreditBroker.exe в папку dist
cd /d "%~dp0"
if not exist .venv py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --name KreditBroker --add-data "broker\templates;broker\templates" --add-data "broker\static;broker\static" run.py
echo Готово: dist\KreditBroker.exe
pause
