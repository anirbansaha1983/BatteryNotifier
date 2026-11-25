@echo off
REM ---------------------------------------------------------------------------
REM Battery Notifier - install the "start at logon" scheduled task.
REM
REM Double-click this file. It calls install_task.ps1 with an execution policy
REM bypass scoped to this single PowerShell process, so you never have to change
REM your machine's PowerShell settings.
REM
REM   install_task.bat              -> install the scheduled task
REM   install_task.bat -Uninstall   -> remove the scheduled task
REM ---------------------------------------------------------------------------

setlocal

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%install_task.ps1"

if not exist "%PS1%" (
    echo ERROR: Could not find "%PS1%".
    pause
    exit /b 1
)

REM Clear the "downloaded from the internet" mark, which can also block the file.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%PS1%' -ErrorAction SilentlyContinue" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo The installer exited with code %RC%.
)

echo.
pause
exit /b %RC%
