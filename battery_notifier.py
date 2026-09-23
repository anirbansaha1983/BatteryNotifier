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
import threading
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
# Check (and therefore re-alert) every 5 seconds so the reminder keeps nagging
# until you plug in / unplug.
DEFAULT_INTERVAL = 5
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


APP_NAME = "Battery Notifier"

# Sound behaviour. "alarm" = loud looping alarm, "default" = normal toast ding,
# "off" = silent toast.
SOUND_MODES = ("alarm", "default", "off")
DEFAULT_SOUND = "alarm"

# Module-level sound settings, configured from the CLI in main().
_SOUND_MODE = DEFAULT_SOUND
_BEEP_ENABLED = True
_BEEP_REPEATS = 3

# Serialises notify() so a silent UI toast cannot leak its temporary sound
# setting into a concurrent battery alert.
_NOTIFY_LOCK = threading.RLock()


def configure_sound(mode: str = DEFAULT_SOUND, beep: bool = True,
                    repeats: int = 3) -> None:
    """Set how loud/insistent notifications are."""
    global _SOUND_MODE, _BEEP_ENABLED, _BEEP_REPEATS
    if mode not in SOUND_MODES:
        raise ValueError(f"sound mode must be one of {SOUND_MODES}")
    _SOUND_MODE = mode
    _BEEP_ENABLED = beep
    _BEEP_REPEATS = max(0, int(repeats))


def _play_alarm() -> None:
    """Play an attention-grabbing sound, independent of the toast.

    Windows toast audio is mixed under the "Notifications" volume channel, which
    is quiet (and muted entirely by Focus Assist / Do Not Disturb). A direct
    beep or system sound is far harder to miss.
    """
    if not _BEEP_ENABLED or _SOUND_MODE == "off":
        return

    system = platform.system()
    repeats = max(1, _BEEP_REPEATS)

    if system == "Windows":
        try:
            import winsound  # type: ignore

            for i in range(repeats):
                # Rising two-tone chirp - cuts through background noise.
                winsound.Beep(880, 250)
                winsound.Beep(1245, 250)
                if i < repeats - 1:
                    time.sleep(0.12)
            # Also fire the system "exclamation" sound at system volume.
            winsound.MessageBeep(getattr(winsound, "MB_ICONEXCLAMATION", 0x30))
            return
        except Exception as exc:
            LOG.debug("winsound beep failed: %s", exc)

    if system == "Darwin":
        try:
            if shutil.which("afplay"):
                for _ in range(repeats):
                    subprocess.call(
                        ["afplay", "-v", "2",
                         "/System/Library/Sounds/Sosumi.aiff"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        except Exception as exc:
            LOG.debug("afplay failed: %s", exc)

    if system == "Linux":
        for player, args in (
            ("paplay", ["/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"]),
            ("aplay", ["/usr/share/sounds/alsa/Front_Center.wav"]),
        ):
            if shutil.which(player):
                try:
                    for _ in range(repeats):
                        subprocess.call([player, *args],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
                    return
                except Exception as exc:
                    LOG.debug("%s failed: %s", player, exc)

    # Universal fallback: terminal bell.
    try:
        for _ in range(repeats):
            sys.stdout.write("\a")
            sys.stdout.flush()
            time.sleep(0.25)
    except Exception:
        pass


def _notify_win11toast(title: str, message: str) -> bool:
    """Modern Windows 10/11 toast via win11toast (WinRT-backed)."""
    try:
        from win11toast import toast  # type: ignore
    except Exception:
        return False

    kwargs = {"app_id": APP_NAME}
    if _SOUND_MODE == "alarm":
        # Looping alarm audio + long duration so the toast stays on screen
        # until dismissed, instead of vanishing after a few seconds.
        kwargs["audio"] = {"src": "ms-winsoundevent:Notification.Looping.Alarm",
                           "loop": "true"}
        kwargs["duration"] = "long"
        kwargs["scenario"] = "alarm"
    elif _SOUND_MODE == "off":
        kwargs["audio"] = {"silent": "true"}
        kwargs["duration"] = "short"
    else:
        kwargs["duration"] = "short"

    try:
        toast(title, message, **kwargs)
        return True
    except Exception as exc:
        LOG.debug("win11toast (rich) failed: %s", exc)

    try:  # retry without the fancy options
        toast(title, message, app_id=APP_NAME)
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
        t = Notification(app_id=APP_NAME, title=title, msg=message,
                         duration="long" if _SOUND_MODE == "alarm" else "short")
        try:
            if _SOUND_MODE == "alarm":
                t.set_audio(audio.LoopingAlarm, loop=True)
            elif _SOUND_MODE == "default":
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
    if _SOUND_MODE == "alarm":
        audio_xml = ("<audio src='ms-winsoundevent:Notification.Looping.Alarm' "
                     "loop='true'/>")
        scenario = " scenario='alarm'"
    elif _SOUND_MODE == "off":
        audio_xml = "<audio silent='true'/>"
        scenario = ""
    else:
        audio_xml = ""
        scenario = ""

    xml = (f"<toast{scenario}><visual><binding template='ToastText02'>"
           f"<text id='1'>{safe_title}</text>"
           f"<text id='2'>{safe_message}</text>"
           f"</binding></visual>{audio_xml}</toast>")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType=WindowsRuntime] > $null;"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml(@'\n{xml}\n'@);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        f"'{APP_NAME}').Show([Windows.UI.Notifications.ToastNotification]::new($x));"
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


def _notify_linux(title: str, message: str) -> bool:
    if not shutil.which("notify-send"):
        return False
    cmd = ["notify-send", title, message]
    if _SOUND_MODE == "alarm":
        # Critical urgency never auto-dismisses and bypasses Do Not Disturb.
        cmd[1:1] = ["--urgency=critical", "--expire-time=0"]
    return subprocess.call(cmd) == 0


def notify(title: str, message: str, urgent: bool = True) -> None:
    """Best-effort desktop notification; always falls back to the console.

    `urgent=True` (battery alerts) uses the loud, looping, persistent toast plus
    the extra alarm tone. `urgent=False` (UI confirmations such as "thresholds
    updated") shows a brief, silent toast instead - the user just clicked a
    menu item, so there is nothing to grab their attention about.
    """
    global _SOUND_MODE
    system = platform.system()
    backends = {
        "Darwin": [_notify_macos, _notify_plyer],
        "Linux": [_notify_linux, _notify_plyer],
        # Prefer real toasts, then plyer, then built-in PowerShell.
        "Windows": [_notify_win11toast, _notify_winotify,
                    _notify_plyer, _notify_powershell],
    }.get(system, [_notify_plyer])

    # Play the alarm on a background thread so a multi-second sound never
    # delays the toast or the monitoring loop.
    if urgent and _BEEP_ENABLED and _SOUND_MODE != "off":
        threading.Thread(target=_play_alarm, daemon=True,
                         name="battery-alarm").start()

    # Non-urgent toasts are rendered silently and briefly. The lock keeps a
    # concurrent battery alert from picking up the temporary "off" mode.
    with _NOTIFY_LOCK:
        previous_mode = _SOUND_MODE
        if not urgent:
            _SOUND_MODE = "off"
        try:
            for backend in backends:
                try:
                    if backend(title, message):
                        LOG.debug("Notification sent via %s", backend.__name__)
                        break
                except Exception as exc:  # pragma: no cover
                    LOG.debug("%s failed: %s", backend.__name__, exc)
            else:
                LOG.warning("No desktop notifier available; printing instead.")
        finally:
            _SOUND_MODE = previous_mode

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


def settings_file() -> Path:
    """Where user-chosen thresholds are remembered between runs."""
    return default_state_dir() / "settings.json"


def load_settings() -> dict:
    """Read saved thresholds, or {} if none/unreadable."""
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(low: int, high: int) -> bool:
    """Persist the chosen thresholds. Returns True on success."""
    path = settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"low": int(low), "high": int(high)}, indent=2),
                       encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception as exc:
        LOG.debug("Could not save settings to %s: %s", path, exc)
        return False


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

    def set_thresholds(self, low: Optional[int] = None,
                       high: Optional[int] = None, persist: bool = True) -> None:
        """Change thresholds while running (used by the tray UI)."""
        new_low = self.low if low is None else int(low)
        new_high = self.high if high is None else int(high)
        if not 0 <= new_low < new_high <= 100:
            raise ValueError(
                f"Invalid thresholds: need 0 <= low ({new_low}) "
                f"< high ({new_high}) <= 100")
        self.low, self.high = new_low, new_high
        # Re-arm so the new setting can alert immediately.
        self._last_kind = None
        self._alert_count = 0
        LOG.info("Thresholds updated: low<=%d%%, high>=%d%%", new_low, new_high)
        if persist:
            save_settings(new_low, new_high)

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
    saved = load_settings()
    p.add_argument("--low", type=int, default=saved.get("low", DEFAULT_LOW),
                   help="Notify at or below this %% while discharging (default 30, "
                        "or your last saved choice).")
    p.add_argument("--high", type=int, default=saved.get("high", DEFAULT_HIGH),
                   help="Notify at or above this %% while charging (default 80, "
                        "or your last saved choice).")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                   help="Seconds between checks, i.e. how often the reminder "
                        "repeats (default 5).")
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
    p.add_argument("--sound", choices=SOUND_MODES, default=DEFAULT_SOUND,
                   help="Toast sound: 'alarm' (loud, looping, stays on screen; "
                        "default), 'default' (normal ding) or 'off' (silent).")
    p.add_argument("--no-beep", action="store_true",
                   help="Do not play the extra audible beep/alarm tone "
                        "(the toast sound is still used).")
    p.add_argument("--beep-repeats", type=int, default=3, metavar="N",
                   help="How many times to repeat the alarm tone (default 3).")
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

    configure_sound(args.sound, not args.no_beep, args.beep_repeats)

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
