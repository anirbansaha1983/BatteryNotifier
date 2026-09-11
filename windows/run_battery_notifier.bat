@echo off
REM ---------------------------------------------------------------------------
REM Battery Notifier - Windows launcher
REM Runs the monitor silently in the background using pythonw.exe (no console).
REM Double-click to start, or point Task Scheduler at this file.
REM ---------------------------------------------------------------------------

setlocal

REM Folder containing this .bat (repo root is one level up).
set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%..\battery_notifier.py"

REM Tunables ------------------------------------------------------------------
set "LOW=30"
set "HIGH=80"
set "INTERVAL=60"
REM Minimum seconds between repeats of the same alert (0 = every check).
set "REPEAT_AFTER=300"
REM ---------------------------------------------------------------------------

REM Common arguments. --log-file and --status-file (no value) use the default
REM location: %LOCALAPPDATA%\BatteryNotifier\
set "ARGS=--low %LOW% --high %HIGH% --interval %INTERVAL% --repeat-after %REPEAT_AFTER% --log-file --status-file"

REM Prefer pythonw.exe (windowless). Fall back to the py launcher, then python.
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
echo Battery Notifier started in the background (no window is expected).
echo.
echo   Logs   : %LOCALAPPDATA%\BatteryNotifier\battery_notifier.log
echo   Status : %LOCALAPPDATA%\BatteryNotifier\status.json
echo.
echo Verify any time by running:  status.bat
timeout /t 6 >nul
