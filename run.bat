@echo off
setlocal
cd /d "%~dp0"

if not exist config.yaml copy config.example.yaml config.yaml

start "Viral Moment Clipper API" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 7878 --reload"
pushd frontend
start "Viral Moment Clipper UI" cmd /k "set VITE_API_BASE=http://127.0.0.1:7878/api&& npm run dev -- --host 127.0.0.1 --port 5173"
popd

timeout /t 2 >nul
start http://127.0.0.1:5173
