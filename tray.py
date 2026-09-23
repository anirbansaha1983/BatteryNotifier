#!/usr/bin/env python3
"""System tray (taskbar) icon for Battery Notifier.

Shows a live battery icon in the notification area so you can see at a glance
that the monitor is running:

    python tray.py                 # run the monitor with a tray icon
    python tray.py --low 25 --high 85

The icon colour reflects the current state:
    green  - charging
    blue   - normal, on battery
    amber  - high alert (charging and >= --high)
    red    - low alert (discharging and <= --low)

Right-click the icon for battery details, a test notification, and Exit.

Requires: pip install pystray Pillow
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from typing import Optional

import battery_notifier as bn

LOG = logging.getLogger("battery_notifier.tray")

# Icon colours (RGBA).
# Preset percentages offered in the tray menu.
LOW_CHOICES = (10, 15, 20, 25, 30, 40, 50)
HIGH_CHOICES = (60, 70, 75, 80, 85, 90, 95, 100)

COLOURS = {
    "charging": (46, 160, 67, 255),    # green
    "normal": (56, 139, 253, 255),     # blue
    "high": (219, 154, 4, 255),        # amber
    "low": (218, 54, 51, 255),         # red
    "unknown": (139, 148, 158, 255),   # grey
}


def icon_state(state: Optional[bn.BatteryState], low: int, high: int) -> str:
    """Map a battery reading to one of the COLOURS keys."""
    if state is None:
        return "unknown"
    if not state.plugged and state.percent <= low:
        return "low"
    if state.plugged and state.percent >= high:
        return "high"
    return "charging" if state.plugged else "normal"


def make_image(percent: Optional[float], status: str, size: int = 64):
    """Draw a battery icon filled to `percent`, tinted for `status`."""
    from PIL import Image, ImageDraw  # imported lazily: optional dependency

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    colour = COLOURS.get(status, COLOURS["unknown"])
    outline = (230, 237, 243, 255)

    # Battery body + terminal (horizontal battery).
    left, top, right, bottom = size * 0.08, size * 0.28, size * 0.82, size * 0.72
    d.rounded_rectangle([left, top, right, bottom], radius=size * 0.08,
                        outline=outline, width=max(2, size // 22))
    d.rounded_rectangle([right + size * 0.02, size * 0.41,
                         right + size * 0.12, size * 0.59],
                        radius=size * 0.03, fill=outline)

    # Fill level.
    pad = max(3, size // 16)
    if percent is not None:
        inner_l, inner_r = left + pad, right - pad
        width = (inner_r - inner_l) * max(0.0, min(100.0, percent)) / 100.0
        if width > 0:
            d.rectangle([inner_l, top + pad, inner_l + width, bottom - pad],
                        fill=colour)
    else:
        d.line([left + pad, bottom - pad, right - pad, top + pad],
               fill=COLOURS["unknown"], width=max(2, size // 20))

    # Charging bolt.
    if status in ("charging", "high"):
        cx, cy, s = size * 0.45, size * 0.5, size * 0.20
        d.polygon([(cx + s * 0.25, cy - s), (cx - s * 0.45, cy + s * 0.15),
                   (cx, cy + s * 0.15), (cx - s * 0.25, cy + s),
                   (cx + s * 0.5, cy - s * 0.15), (cx, cy - s * 0.15)],
                  fill=(255, 255, 255, 255))
    return img


def tooltip(state: Optional[bn.BatteryState], low: int, high: int) -> str:
    if state is None:
        return "Battery Notifier - no battery detected"
    mode = "charging" if state.plugged else "on battery"
    text = f"Battery Notifier - {state.percent:.0f}% ({mode})"
    if state.secs_left is not None:
        text += f", {state.time_left} left"
    return text


class TrayApp:
    """Runs the Notifier loop in a thread and mirrors it in the tray icon."""

    def __init__(self, notifier: bn.Notifier, interval: float) -> None:
        self.notifier = notifier
        self.interval = interval
        self._stop = threading.Event()
        self.icon = None
        self.last_state: Optional[bn.BatteryState] = None

    # -- menu actions ------------------------------------------------------ #
    def _details(self) -> str:
        s = self.last_state
        if s is None:
            return "No battery detected"
        return (f"{s.percent:.0f}% - "
                f"{'charging' if s.plugged else 'discharging'}"
                f"{'' if s.secs_left is None else f' ({s.time_left} left)'}")

    def _on_test(self) -> None:
        bn.notify(f"{bn.APP_NAME} - Test",
                  "If you can see this toast, notifications are working.")

    def _on_show_status(self) -> None:
        bn.notify(f"{bn.APP_NAME} - Status",
                  f"{self._details()}. Checks: {self.notifier._checks}, "
                  f"alerts sent: {self.notifier._notifications}.", urgent=False)

    def _on_cycle_sound(self) -> None:
        """Cycle alarm -> default -> off and preview the new setting."""
        nxt = {"alarm": "default", "default": "off", "off": "alarm"}[bn._SOUND_MODE]
        bn.configure_sound(nxt, bn._BEEP_ENABLED, bn._BEEP_REPEATS)
        LOG.info("Sound mode set to %s", nxt)
        bn.notify(f"{bn.APP_NAME} - Sound", f"Sound mode is now '{nxt}'.")

    def _on_exit(self) -> None:
        LOG.info("Exit requested from tray menu.")
        self._stop.set()
        if self.icon is not None:
            self.icon.stop()

    # -- threshold selection ----------------------------------------------- #
    def set_low(self, value: int) -> None:
        self._apply_thresholds(low=value)

    def set_high(self, value: int) -> None:
        self._apply_thresholds(high=value)

    def _apply_thresholds(self, low: Optional[int] = None,
                          high: Optional[int] = None) -> None:
        try:
            self.notifier.set_thresholds(low, high)
        except ValueError as exc:
            LOG.warning("Rejected threshold change: %s", exc)
            bn.notify(f"{bn.APP_NAME} - Invalid setting", str(exc), urgent=False)
            return
        bn.notify(f"{bn.APP_NAME} - Thresholds updated",
                  f"Now alerting at {self.notifier.low}% or below (on battery) "
                  f"and {self.notifier.high}% or above (charging).",
                  urgent=False)
        self.refresh_icon()

    def _on_custom_thresholds(self) -> None:
        """Ask for exact percentages with a small dialog."""
        threading.Thread(target=self._custom_dialog, daemon=True,
                         name="threshold-dialog").start()

    def _custom_dialog(self) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog, messagebox
        except Exception:
            bn.notify(f"{bn.APP_NAME} - Custom thresholds",
                      "Tkinter is not available; pick a value from the menu "
                      "or use --low/--high on the command line.", urgent=False)
            return
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            low = simpledialog.askinteger(
                f"{bn.APP_NAME} - Low threshold",
                "Notify when the battery drops to this % or below\n"
                "while discharging (1-99):",
                initialvalue=self.notifier.low, minvalue=1, maxvalue=99,
                parent=root)
            if low is None:
                root.destroy()
                return
            high = simpledialog.askinteger(
                f"{bn.APP_NAME} - High threshold",
                "Notify when the battery reaches this % or above\n"
                "while charging (2-100):",
                initialvalue=self.notifier.high, minvalue=low + 1, maxvalue=100,
                parent=root)
            if high is None:
                root.destroy()
                return
            try:
                self.notifier.set_thresholds(low, high)
            except ValueError as exc:
                messagebox.showerror(f"{bn.APP_NAME} - Invalid", str(exc),
                                     parent=root)
                root.destroy()
                return
            root.destroy()
            bn.notify(f"{bn.APP_NAME} - Thresholds updated",
                      f"Now alerting at {low}% or below (on battery) "
                      f"and {high}% or above (charging).", urgent=False)
            self.refresh_icon()
        except Exception:
            LOG.exception("Custom threshold dialog failed")

    def build_menu(self):
        import pystray

        def low_item(value):
            return pystray.MenuItem(
                f"{value}%",
                lambda: self.set_low(value),
                checked=lambda _, v=value: self.notifier.low == v,
                radio=True)

        def high_item(value):
            return pystray.MenuItem(
                f"{value}%",
                lambda: self.set_high(value),
                checked=lambda _, v=value: self.notifier.high == v,
                radio=True)

        low_menu = pystray.Menu(*[low_item(v) for v in LOW_CHOICES])
        high_menu = pystray.Menu(*[high_item(v) for v in HIGH_CHOICES])

        return pystray.Menu(
            pystray.MenuItem(lambda _: self._details(), None, enabled=False),
            pystray.MenuItem(
                lambda _: f"Thresholds: <={self.notifier.low}%  >={self.notifier.high}%",
                None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Low battery alert at", low_menu),
            pystray.MenuItem("Charged alert at", high_menu),
            pystray.MenuItem("Custom thresholds...",
                             lambda: self._on_custom_thresholds()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show status notification", lambda: self._on_show_status()),
            pystray.MenuItem("Send test notification", lambda: self._on_test()),
            pystray.MenuItem(
                lambda _: f"Sound: {bn._SOUND_MODE}"
                          f"{'' if bn._BEEP_ENABLED else ' (no beep)'}",
                lambda: self._on_cycle_sound()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: self._on_exit()),
        )

    # -- worker ------------------------------------------------------------ #
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                self.notifier.check()
                self.last_state = bn.read_battery()
                self.refresh_icon()
            except Exception:
                LOG.exception("Error during battery check")
            self._stop.wait(self.interval)

    def refresh_icon(self) -> None:
        if self.icon is None:
            return
        s = self.last_state
        status = icon_state(s, self.notifier.low, self.notifier.high)
        try:
            self.icon.icon = make_image(None if s is None else s.percent, status)
            self.icon.title = tooltip(s, self.notifier.low, self.notifier.high)
        except Exception:
            LOG.exception("Could not update tray icon")

    def run(self) -> int:
        try:
            import importlib
            import pystray
            importlib.import_module("PIL.Image")   # used later by make_image()
        except Exception:
            print("The tray icon needs pystray and Pillow:\n"
                  "    pip install pystray Pillow", file=sys.stderr)
            return 3

        self.last_state = bn.read_battery()
        status = icon_state(self.last_state, self.notifier.low, self.notifier.high)
        self.icon = pystray.Icon(
            "battery_notifier",
            icon=make_image(None if self.last_state is None
                            else self.last_state.percent, status),
            title=tooltip(self.last_state, self.notifier.low, self.notifier.high),
            menu=self.build_menu(),
        )

        threading.Thread(target=self._worker, daemon=True, name="battery-check").start()
        LOG.info("Tray icon started. Right-click it for options.")
        try:
            self.icon.run()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
        return 0


def main(argv=None) -> int:
    args = bn.parse_args(argv)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = bn.resolve_path(args.log_file, "battery_notifier.log")
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

    bn.configure_sound(args.sound, not args.no_beep, args.beep_repeats)

    status_file = (None if args.no_status_file
                   else bn.resolve_path(args.status_file, "status.json")
                   or bn.default_dir_file("status.json"))
    try:
        notifier = bn.Notifier(args.low, args.high, args.repeat_after, status_file)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return TrayApp(notifier, args.interval).run()


if __name__ == "__main__":
    raise SystemExit(main())
