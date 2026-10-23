@echo off
setlocal
cd /d "%~dp0"
title StockAlerts Core Dashboard

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo First-time setup: opening web\.env in Notepad.
  echo Fill in DASHBOARD_PASSWORD, GITHUB_TOKEN, GITHUB_REPOSITORY and GITHUB_BRANCH, save, then run this file again.
  notepad ".env"
  pause
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 (
    echo Could not create the environment. Make sure Python is installed.
    pause
    exit /b 1
  )
)

echo Checking dashboard dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Read the error above.
  pause
  exit /b 1
)

start "" http://127.0.0.1:8000
echo StockAlerts Core is running. Keep this window open while using the dashboard.
echo To stop it, close this window or press Ctrl+C.
".venv\Scripts\python.exe" app.py
pause
