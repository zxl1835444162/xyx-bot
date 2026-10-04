@echo off
cd /d "%~dp0"
title Zhaoshi Xingyue Studio

set "VENV312=%~dp0.venv312\Scripts\python.exe"
set "SYSPY=C:\Python312\python.exe"

echo ============================================
echo   Zhaoshi Group . Xingyue Studio
echo ============================================
echo.

if exist "%VENV312%" goto :run

if not exist "%SYSPY%" goto :nopython

echo [SETUP] Creating GUI environment, please wait...
"%SYSPY%" -m venv "%~dp0.venv312"
"%VENV312%" -m pip install -r "%~dp0requirements-gui.txt" -q
goto :run

:nopython
echo [ERROR] Python 3.12 not found at %SYSPY%
echo Please install Python from https://www.python.org/downloads/
pause
exit /b 1

:run
echo [RUN] Starting GUI...
"%VENV312%" "%~dp0run_gui.py"
if errorlevel 1 pause
exit /b 0
