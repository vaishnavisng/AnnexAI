@echo off
rem CognifyAI - one-command installer for Windows.
rem
rem Usage:
rem   install.bat                 install everything (skips work that's done)
rem   install.bat --force         force a clean reinstall
rem   install.bat --auto-tools    also try to install winget prereqs
rem
rem Tip: you can also double-click this file from Explorer.

setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 install.py %*
    set "EXITCODE=%errorlevel%"
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python install.py %*
    set "EXITCODE=%errorlevel%"
    goto :end
)

echo.
echo Python 3.10+ is required but was not found on PATH.
echo.
echo Install it with one of:
echo   winget install -e --id Python.Python.3.12
echo   https://www.python.org/downloads
echo.
echo After installing, close this window, open a new one, and re-run install.bat.
set "EXITCODE=1"

:end
rem Pause when launched by double-click so users can read messages.
echo %CMDCMDLINE% | findstr /I /C:"/c " >nul && pause
exit /b %EXITCODE%
