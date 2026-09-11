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
import logging
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
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


def _notify_windows(title: str, message: str) -> bool:
    try:
        from plyer import notification  # type: ignore
    except Exception:
        return False
    try:
        notification.notify(title=title, message=message, timeout=10)
        return True
    except Exception:
        return False


def _notify_plyer(title: str, message: str) -> bool:
    try:
        from plyer import notification  # type: ignore
        notification.notify(title=title, message=message, timeout=10)
        return True
    except Exception:
        return False


def notify(title: str, message: str) -> None:
    """Best-effort desktop notification; always falls back to the console."""
    system = platform.system()
    backends = {
        "Darwin": [_notify_macos, _notify_plyer],
        "Linux": [_notify_linux, _notify_plyer],
        "Windows": [_notify_windows],
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


class Notifier:
    """Checks the battery and notifies, avoiding repeat spam."""

    def __init__(self, low: int = DEFAULT_LOW, high: int = DEFAULT_HIGH,
                 repeat_after: float = 15 * 60) -> None:
        if not 0 <= low < high <= 100:
            raise ValueError("Require 0 <= low < high <= 100")
        self.low = low
        self.high = high
        self.repeat_after = repeat_after
        self._last_kind: Optional[str] = None
        self._last_time: float = 0.0

    def check(self) -> Optional[str]:
        state = read_battery()
        if state is None:
            LOG.info("No battery detected on this system.")
            return None

        LOG.info("Battery %.0f%% (%s)", state.percent,
                 "charging" if state.plugged else "discharging")

        result = evaluate(state, self.low, self.high)
        if result is None:
            self._last_kind = None
            return None

        kind, title, message = result
        now = time.monotonic()
        if kind == self._last_kind and (now - self._last_time) < self.repeat_after:
            LOG.debug("Suppressing repeat '%s' notification", kind)
            return None

        notify(title, message)
        self._last_kind, self._last_time = kind, now
        return kind

    def run(self, interval: float = DEFAULT_INTERVAL) -> None:
        LOG.info("Monitoring battery (low<=%d%%, high>=%d%%, every %.0fs). Ctrl+C to stop.",
                 self.low, self.high, interval)
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
    p.add_argument("--repeat-after", type=float, default=15 * 60,
                   help="Seconds before repeating the same alert (default 900).")
    p.add_argument("--once", action="store_true", help="Check once and exit.")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        notifier = Notifier(args.low, args.high, args.repeat_after)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.once:
        notifier.check()
    else:
        notifier.run(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
