@echo off
setlocal
cd /d "%~dp0"
title Xingyue Studio - Setup

rem ===================================================================
rem  One-time environment setup (GUI + CLI share the same .venv).
rem  Interpreter detection and dependency install both live in
rem  launcher.py, so this file stays a thin wrapper.
rem ===================================================================
set "BOOT="
where py >nul 2>nul && set "BOOT=py -3"
if not defined BOOT (
  where python >nul 2>nul && set "BOOT=python"
)
if not defined BOOT (
  echo.
  echo [ERROR] Python not found on PATH.
  echo   Install from https://www.python.org/downloads/
  echo   and tick "tcl/tk and IDLE" plus "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

echo ============================================
echo   Step 1/2  Prepare environment (.venv)
echo ============================================
%BOOT% "%~dp0launcher.py" --setup
if errorlevel 1 (
  echo [ERROR] Environment setup failed.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   Step 2/2  Detect browsers
echo ============================================
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py" browsers

echo.
echo ============================================
echo  Done.
echo    GUI  : double-click  qi-dong.bat  (Chinese file name)
echo    CLI  : .venv\Scripts\python.exe main.py studio
echo    Help : .venv\Scripts\python.exe main.py
echo ============================================
pause
exit /b 0
