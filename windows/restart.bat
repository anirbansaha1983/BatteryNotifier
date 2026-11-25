@echo off
REM ---------------------------------------------------------------------------
REM Battery Notifier - stop any running copy and start the current code.
REM
REM Use this after updating the app: a process started earlier keeps running the
REM OLD code until it is restarted.
REM
REM   restart.bat          -> restart the tray version (default)
REM   restart.bat headless -> restart the no-icon background version
REM ---------------------------------------------------------------------------

setlocal
set "SCRIPT_DIR=%~dp0"

echo Stopping any running Battery Notifier...

REM Kill the PID recorded in status.json, plus any stragglers running our
REM scripts. Other Python programs are left alone.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$f = Join-Path $env:LOCALAPPDATA 'BatteryNotifier\status.json';" ^
  "$stopped = 0;" ^
  "if (Test-Path $f) {" ^
  "  try { $p = (Get-Content $f -Raw | ConvertFrom-Json).pid;" ^
  "        if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; $stopped++ } } catch {}" ^
  "}" ^
  "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" ^|" ^
  "  Where-Object { $_.CommandLine -match 'battery_notifier|tray\.py' } ^|" ^
  "  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped++ };" ^
  "Write-Host ('Stopped {0} process(es).' -f $stopped)"

REM Clear any toasts the old build left behind in the Action Center.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;" ^
  "try { [Windows.UI.Notifications.ToastNotificationManager]::History.Clear('Battery Notifier') } catch {}" >nul 2>&1

timeout /t 2 >nul

if /i "%~1"=="headless" (
    echo Starting the headless version...
    call "%SCRIPT_DIR%run_battery_notifier.bat"
) else (
    echo Starting the tray version...
    call "%SCRIPT_DIR%run_tray.bat"
)
