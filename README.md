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
| `--repeat-after` | 900 | Seconds before repeating the same alert |
| `--once` | off | Check once and exit |

The same alert is not repeated until `--repeat-after` elapses, and the state is
reset once the battery returns to the normal range.

## Tests

```bash
pip install pytest && pytest
```
