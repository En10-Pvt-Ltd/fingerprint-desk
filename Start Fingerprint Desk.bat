@echo off
rem One-click launcher for Fingerprint Desk (local, single-operator mode).
rem Double-click this file: it checks for Python 3.11+, installs dependencies
rem on first run, starts the loopback-only local server, and opens the app in
rem your browser at http://localhost:8765.
title Fingerprint Desk
cd /d "%~dp0"

rem Local mode: no accounts and loopback-only. The server verifies its real
rem bound socket at startup and refuses to serve on anything but this machine.
set FF_MODE=local

where python >nul 2>nul
if errorlevel 1 goto :nopython

rem Minimum supported interpreter is Python 3.11.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :oldpython

python -c "import numpy, cv2, PIL, fastapi, uvicorn, multipart, fitz, pikepdf" >nul 2>nul
if errorlevel 1 (
  echo First run: installing dependencies, this can take a few minutes...
  python -m pip install -q -r requirements.txt -r app\requirements.txt
  if errorlevel 1 (
    echo.
    echo Dependency install failed. Run this manually, then try again:
    echo   pip install -r requirements.txt -r app\requirements.txt
    pause
    exit /b 1
  )
)

echo Starting Fingerprint Desk (local mode) at http://localhost:8765
echo Close this window to stop the app.
if not defined FD_NO_BROWSER (
  start "" cmd /c "timeout /t 2 >nul & start "" http://localhost:8765"
)
python app\serve.py
pause
exit /b 0

:nopython
echo.
echo Python was not found on PATH, and Fingerprint Desk needs Python 3.11 or newer.
echo Download it from:
echo   https://www.python.org/downloads/
echo During install, tick "Add python.exe to PATH", then run this file again.
echo.
pause
exit /b 1

:oldpython
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo.
echo Your Python is %PYVER%, but Fingerprint Desk needs Python 3.11 or newer.
echo Download a newer version from:
echo   https://www.python.org/downloads/
echo During install, tick "Add python.exe to PATH", then run this file again.
echo.
pause
exit /b 1
