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

REM Prefer pythonw.exe (windowless). Fall back to the py launcher, then python.
set "PYW="
for %%P in (pythonw.exe) do if not defined PYW set "PYW=%%~$PATH:P"

if defined PYW (
    start "" "%PYW%" "%APP%" --low %LOW% --high %HIGH% --interval %INTERVAL% --repeat-after %REPEAT_AFTER%
    goto :eof
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" py -3 -w "%APP%" --low %LOW% --high %HIGH% --interval %INTERVAL% --repeat-after %REPEAT_AFTER%
    goto :eof
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" /min python "%APP%" --low %LOW% --high %HIGH% --interval %INTERVAL% --repeat-after %REPEAT_AFTER%
    goto :eof
)

echo Python was not found on PATH. Install Python 3.9+ and re-run this script.
pause
