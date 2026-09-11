@echo off
REM ---------------------------------------------------------------------------
REM Battery Notifier - is it running?
REM
REM Shows three things:
REM   1. the app's own heartbeat/status file (most reliable)
REM   2. any matching pythonw.exe processes
REM   3. the scheduled task state, if installed
REM ---------------------------------------------------------------------------

setlocal
set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%..\battery_notifier.py"

echo ============================================================
echo  1. Heartbeat status file
echo ============================================================
where pythonw.exe >nul 2>&1
python "%APP%" --status
set "APP_RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  2. Running pythonw.exe processes
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | Where-Object { $_.CommandLine -like '*battery_notifier*' };" ^
  "if ($p) { $p | Select-Object ProcessId, CreationDate, CommandLine | Format-List } else { Write-Host 'No battery_notifier process found.' }"

echo.
echo ============================================================
echo  3. Scheduled task
echo ============================================================
schtasks /query /tn "BatteryNotifier" /fo LIST 2>nul | findstr /i "TaskName Status Next Last"
if errorlevel 1 echo Scheduled task "BatteryNotifier" is not installed.

echo.
if "%APP_RC%"=="0" (
    echo RESULT: Battery Notifier appears to be RUNNING.
) else (
    echo RESULT: Battery Notifier does NOT appear to be running.
    echo         Start it with run_battery_notifier.bat
)

echo.
pause
