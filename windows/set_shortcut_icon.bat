@echo off
REM ---------------------------------------------------------------------------
REM Put the Battery Notifier icon on shortcuts to run_tray.bat.
REM
REM Windows cannot give a .bat file its own icon, so this creates a real
REM shortcut (.lnk) that runs run_tray.bat and carries assets\battery-notifier.ico.
REM
REM   set_shortcut_icon.bat                -> Desktop + Start Menu
REM   set_shortcut_icon.bat --where desktop
REM   set_shortcut_icon.bat --remove
REM ---------------------------------------------------------------------------

setlocal
set "SCRIPT_DIR=%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 "%SCRIPT_DIR%shortcut_icon.py" %*
    goto :done
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python "%SCRIPT_DIR%shortcut_icon.py" %*
    goto :done
)

echo Python was not found on PATH. Install Python 3.9+ and re-run this script.

:done
echo.
pause
