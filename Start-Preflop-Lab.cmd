@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -Command "try { $reply = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2; if ($reply.app -eq 'preflop-lab') { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
  start "" "http://127.0.0.1:8765"
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  echo Missing local Python environment. See APP-README.md for setup.
  pause
  exit /b 1
)
echo Preflop Lab is starting at http://127.0.0.1:8765
echo Keep this window open while using the app. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m preflop_lab.server --port 8765 --open-browser
if errorlevel 1 pause
endlocal
