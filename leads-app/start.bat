@echo off
rem Запуск «Базы лидов» на Windows. Первый запуск ставит зависимости (1-2 минуты).
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Первый запуск: создаю окружение...
  py -3 -m venv .venv || (echo Не найден Python. Установите Python 3.11+ с python.org & pause & exit /b)
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
.venv\Scripts\python run.py
