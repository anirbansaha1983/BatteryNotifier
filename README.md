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

## Is it running?

Because the app runs under `pythonw.exe` there is **no window** — that is normal.
Verify it in any of these ways.

**1. Ask the app (most reliable).** It writes a heartbeat file after every check:

```bash
python battery_notifier.py --status
```

```
RUNNING - pid 12345, last check 12s ago
  status file : C:\Users\you\AppData\Local\BatteryNotifier\status.json
  running since: 2026-09-11T16:26:56
  checks       : 42   notifications: 2
  battery      : 78% (charging), 0h 25m left
  thresholds   : low<=30%  high>=80%
```

Exit code is `0` when running, `1` when not — handy for scripting. On Windows
just double-click **`windows\status.bat`**, which additionally lists the matching
`pythonw.exe` processes and the scheduled-task state.

**2. Read the log.** `%LOCALAPPDATA%\BatteryNotifier\battery_notifier.log`
(rotating, 1 MB × 3) gets a line per check:

```powershell
Get-Content "$env:LOCALAPPDATA\BatteryNotifier\battery_notifier.log" -Tail 20 -Wait
```

**3. Look for the process.**

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object CommandLine -like '*battery_notifier*' |
  Select-Object ProcessId, CommandLine
```

Task Manager shows it under the **Details** tab (not Processes) as `pythonw.exe`.

**4. Force a notification** to confirm the toast path end-to-end:

```bash
python battery_notifier.py --test-notification
```

Related flags: `--log-file [PATH]`, `--status-file [PATH]` (both default to
`%LOCALAPPDATA%\BatteryNotifier\` on Windows, `~/.local/state/battery-notifier/`
elsewhere) and `--no-status-file` to disable the heartbeat.

To **stop** it: `Stop-Process -Id <pid>`, or `taskkill /IM pythonw.exe` (note this
kills *all* windowless Python processes).

## Windows: auto-start at login

```powershell
pip install -r requirements.txt
```

Then either **double-click `windows\install_task.bat`**, or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install_task.ps1
```

> **"running scripts is disabled on this system"?**
> That is the PowerShell execution policy (default `Restricted`), not a problem
> with the script. Running `.\install_task.ps1` directly triggers it. Use
> `install_task.bat` or the `-ExecutionPolicy Bypass -File` command above — both
> scope the bypass to a single process and change nothing system-wide.
> If you would rather allow local scripts permanently, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (no admin rights needed).

- `windows\run_battery_notifier.bat` — launches the monitor with `pythonw.exe`
  so there is **no console window**. Edit the `LOW` / `HIGH` / `INTERVAL` /
  `REPEAT_AFTER` variables at the top to tune it. Double-click to run manually.
- `windows\install_task.bat` — double-clickable wrapper that runs the installer
  below with an execution-policy bypass (and `Unblock-File`s it first).
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
| `--status` | off | Report whether the monitor is running, and exit |
| `--log-file [PATH]` | off | Append to a rotating log file (1 MB × 3) |
| `--status-file [PATH]` | on in loop | Heartbeat JSON written after every check |
| `--no-status-file` | off | Disable the heartbeat file |

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
