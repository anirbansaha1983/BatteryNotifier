# BatteryNotifier

Monitors the system battery and sends a desktop notification when:

- **a)** the battery is **not charging** and the charge is **30% or below**
- **b)** the battery is **charging** and the charge is **80% or above**

## Install

```bash
pip install -r requirements.txt
```

On Linux, desktop notifications use `notify-send` (`libnotify-bin`); on macOS
`osascript`; on Windows `plyer`. If no backend is available the alert is printed
to the console.

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
