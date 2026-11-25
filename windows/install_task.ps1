<#
.SYNOPSIS
    Registers Battery Notifier to start automatically at logon via Task Scheduler.

.DESCRIPTION
    Creates a scheduled task that launches windows\run_battery_notifier.bat at
    user logon (plus a 1-minute delay so the desktop is ready). The task runs
    hidden, in the interactive user session, on battery as well as on AC.

    Run from a normal (non-admin) PowerShell prompt:
        powershell -ExecutionPolicy Bypass -File .\windows\install_task.ps1

    Or simply double-click windows\install_task.bat, which applies the
    execution-policy bypass for you.

    NOTE: running ".\install_task.ps1" directly may fail with
    "running scripts is disabled on this system" - that is Windows'
    PowerShell execution policy, not an error in this script. Use either of
    the two forms above.

    Remove it later with:
        powershell -ExecutionPolicy Bypass -File .\windows\install_task.ps1 -Uninstall
        (or: install_task.bat -Uninstall)
#>

param(
    [string]$TaskName = "BatteryNotifier",
    [switch]$Uninstall,
    [switch]$Tray      # install the tray-icon version instead of the headless one
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    } else {
        Write-Host "No scheduled task named '$TaskName' found." -ForegroundColor Yellow
    }
    return
}

$batchName = if ($Tray) { "run_tray.bat" } else { "run_battery_notifier.bat" }
$batch = Join-Path $PSScriptRoot $batchName
if (-not (Test-Path $batch)) {
    throw "Could not find $batch"
}
Write-Host "Using launcher: $batchName" -ForegroundColor Cyan

$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"$batch`"" -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"   # let the desktop settle before starting

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Notifies when the battery is low while discharging or full while charging." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (runs at logon)." -ForegroundColor Green
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
