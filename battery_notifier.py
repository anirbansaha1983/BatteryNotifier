#!/usr/bin/env python3
"""Battery Notifier.

Monitors the system battery and sends a desktop notification when:
  a) the battery is NOT charging and the charge is <= 30%
  b) the battery IS charging and the charge is >= 80%

Usage:
    python battery_notifier.py                 # run forever, check every 60s
    python battery_notifier.py --once          # single check (good for cron)
    python battery_notifier.py --low 25 --high 85 --interval 30
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import psutil
except ImportError:  # pragma: no cover
    print("psutil is required. Install it with: pip install -r requirements.txt")
    raise SystemExit(1)


LOG = logging.getLogger("battery_notifier")

DEFAULT_LOW = 30
DEFAULT_HIGH = 80
DEFAULT_INTERVAL = 60
# 0 => re-notify on every check while the condition holds (keep nagging).
DEFAULT_REPEAT_AFTER = 0.0


@dataclass(frozen=True)
class BatteryState:
    percent: float
    plugged: bool
    secs_left: Optional[int] = None

    @property
    def time_left(self) -> str:
        if self.secs_left is None or self.secs_left < 0:
            return "unknown"
        hours, rem = divmod(int(self.secs_left), 3600)
        minutes = rem // 60
        return f"{hours}h {minutes:02d}m"


def read_battery() -> Optional[BatteryState]:
    """Return the current battery state, or None if there is no battery."""
    getter = getattr(psutil, "sensors_battery", None)
    if getter is None:
        return None
    battery = getter()
    if battery is None:
        return None
    secs = battery.secsleft
    if secs in (getattr(psutil, "POWER_TIME_UNLIMITED", -1),
                getattr(psutil, "POWER_TIME_UNKNOWN", -2)):
        secs = None
    return BatteryState(percent=battery.percent,
                        plugged=bool(battery.power_plugged),
                        secs_left=secs)


# --------------------------------------------------------------------------- #
# Notification backends
# --------------------------------------------------------------------------- #

def _notify_macos(title: str, message: str) -> bool:
    if not shutil.which("osascript"):
        return False
    script = f'display notification {message!r} with title {title!r}'
    return subprocess.call(["osascript", "-e", script]) == 0


def _notify_linux(title: str, message: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    return subprocess.call(["notify-send", title, message]) == 0


APP_NAME = "Battery Notifier"


def _notify_win11toast(title: str, message: str) -> bool:
    """Modern Windows 10/11 toast via win11toast (WinRT-backed)."""
    try:
        from win11toast import toast  # type: ignore
    except Exception:
        return False
    try:
        toast(title, message, app_id=APP_NAME, duration="short")
        return True
    except Exception as exc:
        LOG.debug("win11toast failed: %s", exc)
        return False


def _notify_winotify(title: str, message: str) -> bool:
    """Windows 10/11 toast via winotify (pure-Python, no WinRT needed)."""
    try:
        from winotify import Notification, audio  # type: ignore
    except Exception:
        return False
    try:
        t = Notification(app_id=APP_NAME, title=title, msg=message)
        try:
            t.set_audio(audio.Default, loop=False)
        except Exception:
            pass
        t.show()
        return True
    except Exception as exc:
        LOG.debug("winotify failed: %s", exc)
        return False


def _notify_powershell(title: str, message: str) -> bool:
    """Last-resort Windows toast using built-in PowerShell + WinRT APIs."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n=$t.GetElementsByTagName('text');"
        f"$n.Item(0).AppendChild($t.CreateTextNode('{safe_title}')) > $null;"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{safe_message}')) > $null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        f"'{APP_NAME}').Show([Windows.UI.Notifications.ToastNotification]::new($t));"
    )
    try:
        return subprocess.call(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) == 0
    except Exception as exc:
        LOG.debug("powershell toast failed: %s", exc)
        return False


def _notify_plyer(title: str, message: str) -> bool:
    try:
        from plyer import notification  # type: ignore
        notification.notify(title=title, message=message,
                            app_name=APP_NAME, timeout=10)
        return True
    except Exception as exc:
        LOG.debug("plyer failed: %s", exc)
        return False


def notify(title: str, message: str) -> None:
    """Best-effort desktop notification; always falls back to the console."""
    system = platform.system()
    backends = {
        "Darwin": [_notify_macos, _notify_plyer],
        "Linux": [_notify_linux, _notify_plyer],
        # Prefer real toasts, then plyer, then built-in PowerShell.
        "Windows": [_notify_win11toast, _notify_winotify,
                    _notify_plyer, _notify_powershell],
    }.get(system, [_notify_plyer])

    for backend in backends:
        try:
            if backend(title, message):
                LOG.debug("Notification sent via %s", backend.__name__)
                break
        except Exception as exc:  # pragma: no cover
            LOG.debug("%s failed: %s", backend.__name__, exc)
    else:
        LOG.warning("No desktop notifier available; printing instead.")

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}: {message}")


# --------------------------------------------------------------------------- #
# Core logic
# --------------------------------------------------------------------------- #

def evaluate(state: BatteryState, low: int, high: int) -> Optional[tuple[str, str, str]]:
    """Return (kind, title, message) if a notification is warranted."""
    if not state.plugged and state.percent <= low:
        return (
            "low",
            "Battery Low - Plug In Charger",
            f"Battery at {state.percent:.0f}% and discharging "
            f"(about {state.time_left} left).",
        )
    if state.plugged and state.percent >= high:
        return (
            "high",
            "Battery Charged - Unplug Charger",
            f"Battery at {state.percent:.0f}% while charging.",
        )
    return None


def default_state_dir() -> Path:
    """Per-user directory for the log and status files."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        return Path(base) / "BatteryNotifier"
    return Path(os.environ.get("XDG_STATE_HOME",
                               Path.home() / ".local" / "state")) / "battery-notifier"


def write_status(path: Path, payload: dict) -> None:
    """Atomically write the heartbeat/status JSON file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # never let telemetry break monitoring
        LOG.debug("Could not write status file %s: %s", path, exc)


class Notifier:
    """Checks the battery and notifies, avoiding repeat spam."""

    def __init__(self, low: int = DEFAULT_LOW, high: int = DEFAULT_HIGH,
                 repeat_after: float = DEFAULT_REPEAT_AFTER,
                 status_file: Optional[Path] = None) -> None:
        if not 0 <= low < high <= 100:
            raise ValueError("Require 0 <= low < high <= 100")
        if repeat_after < 0:
            raise ValueError("repeat_after must be >= 0")
        self.low = low
        self.high = high
        self.repeat_after = repeat_after
        self._last_kind: Optional[str] = None
        self._last_time: float = 0.0
        self._alert_count = 0
        self.status_file = status_file
        self._checks = 0
        self._notifications = 0
        self._started = time.time()

    def _heartbeat(self, state: Optional["BatteryState"],
                   alert: Optional[str]) -> None:
        if self.status_file is None:
            return
        write_status(self.status_file, {
            "pid": os.getpid(),
            "app": APP_NAME,
            "running_since": datetime.fromtimestamp(self._started).isoformat(timespec="seconds"),
            "last_check": datetime.now().isoformat(timespec="seconds"),
            "checks": self._checks,
            "notifications_sent": self._notifications,
            "thresholds": {"low": self.low, "high": self.high},
            "battery": None if state is None else {
                "percent": round(state.percent, 1),
                "charging": state.plugged,
                "time_left": state.time_left,
            },
            "last_alert": alert or self._last_kind,
        })

    def check(self) -> Optional[str]:
        self._checks += 1
        state = read_battery()
        if state is None:
            LOG.info("No battery detected on this system.")
            self._heartbeat(None, None)
            return None

        LOG.info("Battery %.0f%% (%s)", state.percent,
                 "charging" if state.plugged else "discharging")

        result = evaluate(state, self.low, self.high)
        if result is None:
            if self._last_kind is not None:
                LOG.info("Battery back in normal range; alerts reset.")
            self._last_kind = None
            self._alert_count = 0
            self._heartbeat(state, None)
            return None

        kind, title, message = result
        now = time.monotonic()

        if kind != self._last_kind:
            # New condition: alert immediately and restart the counter.
            self._alert_count = 0
        elif self.repeat_after > 0 and (now - self._last_time) < self.repeat_after:
            LOG.debug("Suppressing repeat '%s' notification (%.0fs of %.0fs elapsed)",
                      kind, now - self._last_time, self.repeat_after)
            self._heartbeat(state, kind)
            return None

        self._alert_count += 1
        if self._alert_count > 1:
            message = f"{message} (reminder #{self._alert_count})"

        notify(title, message)
        self._notifications += 1
        self._last_kind, self._last_time = kind, now
        self._heartbeat(state, kind)
        return kind

    def run(self, interval: float = DEFAULT_INTERVAL) -> None:
        repeat = ("every check" if self.repeat_after <= 0
                  else f"at most every {self.repeat_after:.0f}s")
        LOG.info("Monitoring battery (low<=%d%%, high>=%d%%, checking every %.0fs, "
                 "re-notifying %s). Ctrl+C to stop.",
                 self.low, self.high, interval, repeat)
        try:
            while True:
                self.check()
                time.sleep(interval)
        except KeyboardInterrupt:
            LOG.info("Stopped.")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Notify on low/high battery charge.")
    p.add_argument("--low", type=int, default=DEFAULT_LOW,
                   help="Notify at or below this %% while discharging (default 30).")
    p.add_argument("--high", type=int, default=DEFAULT_HIGH,
                   help="Notify at or above this %% while charging (default 80).")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                   help="Seconds between checks (default 60).")
    p.add_argument("--repeat-after", type=float, default=DEFAULT_REPEAT_AFTER,
                   help="Minimum seconds between repeats of the same alert. "
                        "0 (default) re-notifies on every check while the "
                        "condition holds.")
    p.add_argument("--once", action="store_true", help="Check once and exit.")
    p.add_argument("--test-notification", action="store_true",
                   help="Send a sample notification to verify the backend, then exit.")
    p.add_argument("--status", action="store_true",
                   help="Print whether the monitor is running (reads the status "
                        "file) and exit.")
    p.add_argument("--log-file", metavar="PATH", nargs="?", const="",
                   help="Append logs to PATH (rotating, 1 MB x 3). With no value, "
                        "uses the default location.")
    p.add_argument("--status-file", metavar="PATH", nargs="?", const="",
                   help="Write a heartbeat JSON file after every check. "
                        "Defaults to the standard location when running the loop.")
    p.add_argument("--no-status-file", action="store_true",
                   help="Disable the heartbeat status file entirely.")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return p.parse_args(argv)


def resolve_path(value: Optional[str], default_name: str) -> Optional[Path]:
    """'' (flag given, no value) -> default path; None -> not requested."""
    if value is None:
        return None
    return Path(value).expanduser() if value else default_dir_file(default_name)


def default_dir_file(name: str) -> Path:
    return default_state_dir() / name


def print_status(status_file: Path) -> int:
    """Report whether the monitor looks alive, based on the status file."""
    if not status_file.exists():
        print(f"NOT RUNNING - no status file at {status_file}")
        print("Start it with windows\\run_battery_notifier.bat "
              "(or python battery_notifier.py).")
        return 1
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Status file at {status_file} is unreadable: {exc}")
        return 1

    age = time.time() - status_file.stat().st_mtime
    pid = data.get("pid")
    alive = _pid_alive(pid)
    state = "RUNNING" if alive else "STALE (process not found)"
    print(f"{state} - pid {pid}, last check {age:.0f}s ago")
    print(f"  status file : {status_file}")
    print(f"  running since: {data.get('running_since')}")
    print(f"  checks       : {data.get('checks')}   "
          f"notifications: {data.get('notifications_sent')}")
    battery = data.get("battery")
    if battery:
        print(f"  battery      : {battery['percent']}% "
              f"({'charging' if battery['charging'] else 'discharging'}), "
              f"{battery['time_left']} left")
    thresholds = data.get("thresholds", {})
    print(f"  thresholds   : low<={thresholds.get('low')}%  "
          f"high>={thresholds.get('high')}%")
    return 0 if alive else 1


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        return psutil.pid_exists(int(pid))
    except Exception:
        return False


def main(argv=None) -> int:
    args = parse_args(argv)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = resolve_path(args.log_file, "battery_notifier.log")
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.handlers.RotatingFileHandler(
                log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
        except Exception as exc:
            print(f"Warning: cannot write log file {log_file}: {exc}", file=sys.stderr)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers)

    if args.status:
        return print_status(resolve_path(args.status_file, "status.json")
                            or default_dir_file("status.json"))

    if args.test_notification:
        notify(f"{APP_NAME} - Test",
               "If you can see this toast, notifications are working.")
        return 0

    if args.no_status_file:
        status_file = None
    else:
        status_file = (resolve_path(args.status_file, "status.json")
                       or default_dir_file("status.json"))

    try:
        notifier = Notifier(args.low, args.high, args.repeat_after, status_file)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if log_file:
        LOG.info("Logging to %s", log_file)
    if status_file:
        LOG.info("Status file: %s (check with --status)", status_file)

    if args.once:
        notifier.check()
    else:
        notifier.run(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
