@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  call install.bat
)

call .venv\Scripts\python.exe -m pip install -r requirements-speakers.txt

echo SpeechBrain speaker backend installed.
echo Set speakers.embedding_backend: speechbrain in config.yaml or in Settings.
