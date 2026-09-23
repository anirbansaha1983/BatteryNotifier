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
REM Leave LOW/HIGH blank to use the thresholds you picked in the tray menu
REM (saved in %LOCALAPPDATA%\BatteryNotifier\settings.json).
set "LOW="
set "HIGH="
REM How often to check AND re-notify, in seconds.
set "INTERVAL=5"
REM Minimum seconds between repeats of the same alert (0 = every check).
REM 0 = keep notifying every INTERVAL until you plug in / unplug.
set "REPEAT_AFTER=0"
REM Sound: alarm (loud, looping) | default (normal ding) | off
set "SOUND=alarm"
REM How many times to repeat the alarm tone.
set "BEEP_REPEATS=3"
REM ---------------------------------------------------------------------------

REM Common arguments. --log-file and --status-file (no value) use the default
REM location: %LOCALAPPDATA%\BatteryNotifier\
set "ARGS=--interval %INTERVAL% --repeat-after %REPEAT_AFTER% --log-file --status-file --sound %SOUND% --beep-repeats %BEEP_REPEATS%"
if defined LOW  set "ARGS=%ARGS% --low %LOW%"
if defined HIGH set "ARGS=%ARGS% --high %HIGH%"

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
