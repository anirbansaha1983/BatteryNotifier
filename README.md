# BatteryNotifier

Monitors the system battery and sends a desktop notification when:

- **a)** the battery is **not charging** and the charge is **30% or below**
- **b)** the battery is **charging** and the charge is **80% or above**

## Install

```bash
pip install -r requirements.txt
```

Notification backends, tried in order per platform (first success wins; the
alert is always echoed to the console too):

| Platform | Backends |
| --- | --- |
| Windows | `win11toast` → `winotify` → `plyer` → built-in PowerShell toast |
| macOS | `osascript` → `plyer` |
| Linux | `notify-send` (`libnotify-bin`) → `plyer` |

Verify your setup with:

```bash
python battery_notifier.py --test-notification
```

## Windows: auto-start at login

```powershell
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\windows\install_task.ps1
```

- `windows\run_battery_notifier.bat` — launches the monitor with `pythonw.exe`
  so there is **no console window**. Edit the `LOW` / `HIGH` / `INTERVAL` /
  `REPEAT_AFTER` variables at the top to tune it. Double-click to run manually.
- `windows\install_task.ps1` — registers a **Task Scheduler** job that runs the
  `.bat` at logon (1-minute delay), hidden, allowed to start and keep running on
  battery, with automatic restart on failure.

Useful follow-ups:

```powershell
Start-ScheduledTask -TaskName BatteryNotifier          # start now
Get-ScheduledTask   -TaskName BatteryNotifier          # check state
powershell -ExecutionPolicy Bypass -File .\windows\install_task.ps1 -Uninstall
```

Prefer a GUI? Task Scheduler → *Create Task* → Triggers: *At log on* → Actions:
*Start a program* → `cmd.exe` with argument `/c "C:\path\to\windows\run_battery_notifier.bat"`
→ Conditions: untick *Start the task only if the computer is on AC power*.

## Usage

```bash
python battery_notifier.py                        # monitor, check every 60s
python battery_notifier.py --once                 # one check (cron / Task Scheduler)
python battery_notifier.py --low 25 --high 85 --interval 30
python battery_notifier.py -v                     # debug logging
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--low` | 30 | Alert at or below this % while discharging |
| `--high` | 80 | Alert at or above this % while charging |
| `--interval` | 60 | Seconds between checks |
| `--repeat-after` | 0 | Minimum seconds between repeats of the same alert (0 = notify on every check) |
| `--once` | off | Check once and exit |
| `--test-notification` | off | Send a sample notification and exit |

### Repeat behaviour

By default the app **keeps notifying on every check** for as long as the
condition holds, so a low battery nags you once per `--interval` until you plug
in. Follow-up alerts are tagged `(reminder #2)`, `(reminder #3)`, …

To throttle instead, pass `--repeat-after`:

```bash
python battery_notifier.py --interval 30 --repeat-after 600   # remind at most every 10 min
```

A change of condition (low → high, or vice versa) always alerts immediately, and
the reminder counter resets once the battery returns to the normal range.

## Tests

```bash
pip install pytest && pytest
```
