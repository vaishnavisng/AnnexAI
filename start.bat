@echo off
rem AnnexAI - one-command launcher for Windows.
rem
rem Usage:
rem   start.bat                   backend + frontend, opens browser
rem   start.bat --backend-only
rem   start.bat --frontend-only
rem   start.bat --no-browser
rem
rem Tip: you can also double-click this file from Explorer.

setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 start.py %*
    set "EXITCODE=%errorlevel%"
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python start.py %*
    set "EXITCODE=%errorlevel%"
    goto :end
)

echo.
echo Python 3.10+ is required but was not found on PATH.
echo Run install.bat first, or install Python from:
echo   https://www.python.org/downloads
set "EXITCODE=1"

:end
rem Pause when launched by double-click so users can read messages.
echo %CMDCMDLINE% | findstr /I /C:"/c " >nul && pause
exit /b %EXITCODE%
