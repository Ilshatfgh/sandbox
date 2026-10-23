@echo off
chcp 65001 >nul
rem Запуск из исходников: при первом запуске создаёт окружение и ставит зависимости
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || (echo Установите Python 3.11+ с python.org & pause & exit /b 1)
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python run.py
pause
