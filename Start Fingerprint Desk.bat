@echo off
rem One-click launcher for Fingerprint Desk (local demo app).
rem Double-click this file: it checks dependencies (installs them on first
rem run), starts the local server, and opens http://localhost:8765.
title Fingerprint Desk
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3.10+ and try again.
  pause
  exit /b 1
)

python -c "import numpy, cv2, PIL, fastapi, uvicorn, multipart, fitz, pikepdf" >nul 2>nul
if errorlevel 1 (
  echo First run: installing dependencies, this can take a few minutes...
  python -m pip install -q -r requirements.txt -r app\requirements.txt
  if errorlevel 1 (
    echo Dependency install failed. Run manually:
    echo   pip install -r requirements.txt -r app\requirements.txt
    pause
    exit /b 1
  )
)

echo Starting Fingerprint Desk at http://localhost:8765
echo Close this window to stop the app.
if not defined FD_NO_BROWSER (
  start "" cmd /c "timeout /t 2 >nul & start "" http://localhost:8765"
)
python app\serve.py
pause
