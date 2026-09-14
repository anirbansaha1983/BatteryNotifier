@echo off
REM ---------------------------------------------------------------------------
REM Battery Notifier - start with a system tray (taskbar) icon.
REM
REM A battery icon appears in the notification area (bottom-right, next to the
REM clock). Hover it for the current charge; right-click for the menu / Exit.
REM
REM Tip: Windows hides new tray icons by default. Click the "^" chevron, or go to
REM Settings > Personalization > Taskbar > Other system tray icons and turn
REM "pythonw.exe" ON to pin it permanently.
REM ---------------------------------------------------------------------------

setlocal

set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%..\tray.py"

REM Tunables ------------------------------------------------------------------
set "LOW=30"
set "HIGH=80"
set "INTERVAL=60"
set "REPEAT_AFTER=300"
REM ---------------------------------------------------------------------------

set "ARGS=--low %LOW% --high %HIGH% --interval %INTERVAL% --repeat-after %REPEAT_AFTER% --log-file --status-file"

set "PYW="
for %%P in (pythonw.exe) do if not defined PYW set "PYW=%%~$PATH:P"

if defined PYW (
    start "" "%PYW%" "%APP%" %ARGS%
    goto :started
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" py -3 -w "%APP%" %ARGS%
    goto :started
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" /min python "%APP%" %ARGS%
    goto :started
)

echo Python was not found on PATH. Install Python 3.9+ and re-run this script.
pause
exit /b 1

:started
echo Battery Notifier started with a tray icon.
echo Look for the battery icon near the clock (click "^" if it is hidden).
timeout /t 6 >nul
