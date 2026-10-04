@echo off
cd /d "%~dp0"
title Zhaoshi Xingyue Studio

set "VENV312=%~dp0.venv312\Scripts\python.exe"
set "VENVMAIN=%~dp0.venv\Scripts\python.exe"
set "SYSPY=C:\Python312\python.exe"

echo ============================================
echo   Zhaoshi Group . Xingyue Studio
echo ============================================
echo.

if exist "%VENV312%" goto :run312
if exist "%SYSPY%" goto :mkgui

echo [ERROR] No usable Python found.
echo Please install Python 3.12 from python.org
pause
exit /b 1

:mkgui
echo [SETUP] Creating GUI environment with system Python...
"%SYSPY%" -m venv "%~dp0.venv312"
"%VENV312%" -m pip install -r "%~dp0requirements-gui.txt" -q
goto :run312

:run312
echo [RUN] %VENV312%
"%VENV312%" "%~dp0run_gui.py"
if errorlevel 1 pause
exit /b 0
