@echo off
setlocal
cd /d "%~dp0"
title Xingyue Studio

rem ===================================================================
rem  Boot interpreter only. Everything else (venv, deps, which Python
rem  actually runs the app) is decided by launcher.py -- one single
rem  source of truth, cross-platform, no hard-coded machine paths.
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

%BOOT% "%~dp0launcher.py" %*
if errorlevel 1 pause
exit /b 0
