@echo off
cd /d "%~dp0"
title Zhaoshi Xingyue Studio - Setup

set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "VENV=%~dp0.venv"

echo ============================================
echo   Setup CLI environment
echo ============================================
echo.

if not exist "%VENV%" goto :mkvenv
goto :installdeps

:mkvenv
echo [1/3] Creating virtual environment...
"%PY%" -m venv "%VENV%"
goto :installdeps

:installdeps
echo [2/3] Installing dependencies...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip -q
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"

echo [3/3] Detecting browsers...
"%VENV%\Scripts\python.exe" "%~dp0main.py" browsers

echo.
echo ============================================
echo  Done. Next steps:
echo    login : .venv\Scripts\python.exe main.py login
echo    studio: .venv\Scripts\python.exe main.py studio
echo    help  : .venv\Scripts\python.exe main.py
echo.
echo  For the GUI, run start.bat instead.
echo ============================================
pause
