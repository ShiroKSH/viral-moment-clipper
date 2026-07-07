@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.11 -m venv .venv
  )
  if not exist .venv python -m venv .venv
)

call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\pip.exe install -r requirements.txt

if not exist config.yaml copy config.example.yaml config.yaml

pushd frontend
call npm install
popd

echo Install complete.
