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

### Making alerts impossible to miss

Windows mixes toast audio under the quiet **Notifications** volume channel, so
the standard ding is easy to miss. By default this app therefore:

1. asks for the **looping alarm** toast sound (`ms-winsoundevent:Notification.Looping.Alarm`)
   with `scenario=alarm`, so the toast **stays on screen until you dismiss it**
   instead of vanishing after ~5 seconds;
2. plays its **own rising two-tone chirp** ×3 plus the system *Exclamation*
   sound via `winsound`, which uses the normal system volume and so is audible
   even when notification audio is turned down;
3. on Linux, sends the toast with `--urgency=critical --expire-time=0`.

The alarm is played on a background thread, so it never delays monitoring.

| Flag | Effect |
| --- | --- |
| `--sound alarm` | **Default.** Loud looping alarm, toast persists |
| `--sound default` | Normal notification ding |
| `--sound off` | Silent toast |
| `--no-beep` | Keep the toast sound, skip the extra chirp |
| `--beep-repeats N` | Repeat the chirp N times (default 3) |

```bash
python battery_notifier.py --test-notification          # hear the alarm
python battery_notifier.py --sound default --no-beep    # quieter
```

In the tray app, right-click the icon and click **Sound: …** to cycle
alarm → default → off while it runs.

> **Still can't hear it?** Check *Settings > System > Notifications* is on for
> Python, turn **Focus assist / Do not disturb** off (it silences toast audio),
> and raise the *Notifications* channel in **Volume Mixer** while an alert
> plays. The `winsound` chirp ignores that channel, which is exactly why it is
> enabled by default.

## Taskbar / system tray icon

For a visible indicator instead of an invisible background process, run the
tray version — a battery icon sits in the notification area next to the clock:

```bash
pip install pystray Pillow
python tray.py
```

On Windows just double-click **`windows\run_tray.bat`**.

- **Hover** the icon for the exact charge, e.g.
  `Battery Notifier - 78% (charging), 0h 25m left`.
- **Right-click** for battery details, your thresholds, *Show status
  notification*, *Send test notification*, and *Exit*.
- The icon fills up with the charge level and is colour-coded:

| Colour | Meaning |
| --- | --- |
| 🔵 Blue | On battery, normal range |
| 🟢 Green (⚡) | Charging, normal range |
| 🔴 Red | Discharging and at/below `--low` |
| 🟡 Amber (⚡) | Charging and at/above `--high` |
| ⚪ Grey | No battery detected |

### Choosing thresholds from the tray menu

Right-click the icon to set the alert levels without touching the command line:

- **Low battery alert at** → 10 / 15 / 20 / 25 / 30 / 40 / 50 %
- **Charged alert at** → 60 / 70 / 75 / 80 / 85 / 90 / 95 / 100 %
- **Custom thresholds…** → type any exact percentages in a small dialog

The active value is ticked in the menu. Changes apply **immediately** (the
monitor re-arms, so a newly-crossed threshold alerts on the very next check) and
are **saved** to `settings.json` in the state folder, so they are reused next
time you start the app — including after a reboot via the scheduled task.
Invalid combinations (low ≥ high) are refused with an explanatory notification
rather than being applied.

It accepts the same options as the CLI (`--low`, `--high`, `--interval`,
`--repeat-after`, `--log-file`, …) and keeps writing the log and status file, so
`--status` still works alongside it.

> **Can't see the icon?** Windows hides new tray icons by default. Click the
> **^** chevron on the taskbar to see hidden icons, then go to *Settings >
> Personalization > Taskbar > Other system tray icons* and switch **pythonw.exe**
> on to pin it permanently.

To start the tray version at logon instead of the headless one:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install_task.ps1 -Tray
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
- `windows\run_tray.bat` — same, but with a **system tray icon** (see above).
- `windows\status.bat` — reports whether the monitor is currently running.
- `windows\install_task.bat` — double-clickable wrapper that runs the installer
  below with an execution-policy bypass (and `Unblock-File`s it first).
- `windows\install_task.ps1` — registers a **Task Scheduler** job that runs the
  `.bat` at logon (1-minute delay), hidden, allowed to start and keep running on
  battery, with automatic restart on failure. Add `-Tray` to install the
  tray-icon version instead.

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
python battery_notifier.py                        # monitor, alert every 5s
python battery_notifier.py --once                 # one check (cron / Task Scheduler)
python battery_notifier.py --low 25 --high 85 --interval 10
python battery_notifier.py -v                     # debug logging
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--low` | 30 | Alert at or below this % while discharging |
| `--high` | 80 | Alert at or above this % while charging |
| `--interval` | 5 | Seconds between checks — i.e. how often the alert repeats |
| `--repeat-after` | 0 | Minimum seconds between repeats of the same alert (0 = notify on every check) |
| `--once` | off | Check once and exit |
| `--test-notification` | off | Send a sample notification and exit |
| `--status` | off | Report whether the monitor is running, and exit |
| `--log-file [PATH]` | off | Append to a rotating log file (1 MB × 3) |
| `--status-file [PATH]` | on in loop | Heartbeat JSON written after every check |
| `--no-status-file` | off | Disable the heartbeat file |
| `--sound` | `alarm` | `alarm` / `default` / `off` (see below) |
| `--no-beep` | off | Skip the extra audible alarm tone |
| `--beep-repeats` | 3 | How many times to repeat the alarm tone |

### Repeat behaviour

By default the app **keeps notifying on every check** for as long as the
condition holds. With the default `--interval 5` that means **a fresh
notification every 5 seconds** until you take action — plug in when low, or
unplug when charged. Follow-up alerts are tagged `(reminder #2)`,
`(reminder #3)`, …

The nagging stops by itself the moment the battery leaves the alert range.

To throttle instead, pass `--repeat-after`:

```bash
python battery_notifier.py --interval 5 --repeat-after 60   # check every 5s, remind at most every minute
```

A change of condition (low → high, or vice versa) always alerts immediately, and
the reminder counter resets once the battery returns to the normal range.

## Tests

```bash
pip install pytest && pytest
```
