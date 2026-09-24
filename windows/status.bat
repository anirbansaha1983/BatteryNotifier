@echo off
REM ---------------------------------------------------------------------------
REM Battery Notifier - is it running?
REM
REM Shows three things:
REM   1. the app's own heartbeat/status file (most reliable)
REM   2. the actual process, looked up by the PID recorded in that file
REM   3. the scheduled task state, if installed
REM ---------------------------------------------------------------------------

setlocal
set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%..\battery_notifier.py"

echo ============================================================
echo  1. Heartbeat status file
echo ============================================================
python "%APP%" --status
set "APP_RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  2. Running process
echo ============================================================
REM Look the process up by the PID in status.json. Matching on the command line
REM alone is unreliable: the tray build runs "tray.py", not "battery_notifier.py",
REM and Windows hides CommandLine for processes owned by other users.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$f = Join-Path $env:LOCALAPPDATA 'BatteryNotifier\status.json';" ^
  "$pidFromFile = $null;" ^
  "if (Test-Path $f) { try { $pidFromFile = (Get-Content $f -Raw | ConvertFrom-Json).pid } catch {} }" ^
  "$found = $false;" ^
  "if ($pidFromFile) {" ^
  "  $proc = Get-Process -Id $pidFromFile -ErrorAction SilentlyContinue;" ^
  "  if ($proc) { $found = $true; Write-Host ('PID {0} : {1} (started {2})' -f $proc.Id, $proc.ProcessName, $proc.StartTime) }" ^
  "  else { Write-Host ('PID {0} from status.json is no longer running.' -f $pidFromFile) }" ^
  "}" ^
  "$others = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" ^| Where-Object { $_.CommandLine -match 'battery_notifier|tray\.py' };" ^
  "foreach ($o in $others) { if ($o.ProcessId -ne $pidFromFile) { $found = $true; Write-Host ('PID {0} : {1}' -f $o.ProcessId, $o.CommandLine) } }" ^
  "if (-not $found) { Write-Host 'No Battery Notifier process found.' }"

echo.
echo ============================================================
echo  3. Scheduled task
echo ============================================================
schtasks /query /tn "BatteryNotifier" /fo LIST 2>nul | findstr /i "TaskName Status Next Last"
if errorlevel 1 echo Scheduled task "BatteryNotifier" is not installed (start it manually with run_tray.bat).

echo.
if "%APP_RC%"=="0" (
    echo RESULT: Battery Notifier appears to be RUNNING.
) else (
    echo RESULT: Battery Notifier does NOT appear to be running.
    echo         Start it with run_tray.bat or run_battery_notifier.bat
)

echo.
pause
