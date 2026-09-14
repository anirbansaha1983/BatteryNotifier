"""Tests for the system tray UI (headless-safe: no pystray event loop)."""

import battery_notifier as bn
import tray


def st(pct, plugged, secs=3600):
    return bn.BatteryState(percent=pct, plugged=plugged, secs_left=secs)


# --------------------------------------------------------------------------- #
# Icon state mapping
# --------------------------------------------------------------------------- #

def test_icon_state_mapping():
    assert tray.icon_state(st(20, False), 30, 80) == "low"
    assert tray.icon_state(st(30, False), 30, 80) == "low"
    assert tray.icon_state(st(55, False), 30, 80) == "normal"
    assert tray.icon_state(st(50, True), 30, 80) == "charging"
    assert tray.icon_state(st(80, True), 30, 80) == "high"
    assert tray.icon_state(st(20, True), 30, 80) == "charging"   # low but plugged
    assert tray.icon_state(st(95, False), 30, 80) == "normal"
    assert tray.icon_state(None, 30, 80) == "unknown"


def test_icon_state_matches_notifier_logic():
    """Tray colour must agree with when a notification actually fires."""
    for pct in range(0, 101, 5):
        for plugged in (True, False):
            s = st(pct, plugged)
            alert = bn.evaluate(s, 30, 80)
            colour = tray.icon_state(s, 30, 80)
            if alert is None:
                assert colour in ("normal", "charging")
            else:
                assert colour == alert[0]


# --------------------------------------------------------------------------- #
# Icon rendering
# --------------------------------------------------------------------------- #

def test_make_image_sizes_and_mode():
    for pct in (0, 1, 50, 99, 100, None):
        img = tray.make_image(pct, "normal", size=64)
        assert img.size == (64, 64) and img.mode == "RGBA"


def test_make_image_out_of_range_is_clamped():
    tray.make_image(-20, "low")
    tray.make_image(250, "high")


def test_fill_reflects_percentage():
    """A fuller battery must colour more pixels."""
    def filled(pct):
        img = tray.make_image(pct, "normal", size=64)
        target = tray.COLOURS["normal"]
        px = img.load()
        return sum(1 for y in range(img.height) for x in range(img.width)
                   if px[x, y] == target)
    assert filled(10) < filled(50) < filled(95)


def test_colours_differ_per_state():
    states = ("low", "normal", "charging", "high")
    for s in states:
        tray.make_image(50, s)          # each renders without error
    assert len({tray.COLOURS[s] for s in states}) == 4


# --------------------------------------------------------------------------- #
# Tooltip
# --------------------------------------------------------------------------- #

def test_tooltip_contents():
    t = tray.tooltip(st(42, False), 30, 80)
    assert "42%" in t and "on battery" in t and "1h 00m" in t
    assert "charging" in tray.tooltip(st(42, True), 30, 80)
    assert "no battery" in tray.tooltip(None, 30, 80)


def test_tooltip_without_time_estimate():
    t = tray.tooltip(bn.BatteryState(42, False, None), 30, 80)
    assert "42%" in t and "left" not in t


# --------------------------------------------------------------------------- #
# TrayApp behaviour (no real icon)
# --------------------------------------------------------------------------- #

def test_worker_runs_checks_and_stops(monkeypatch):
    monkeypatch.setattr(bn, "read_battery", lambda: st(22, False))
    monkeypatch.setattr(bn, "notify", lambda t, m: None)
    app = tray.TrayApp(bn.Notifier(), interval=0.01)
    import threading
    th = threading.Thread(target=app._worker, daemon=True)
    th.start()
    import time
    time.sleep(0.1)
    app._stop.set()
    th.join(timeout=2)
    assert not th.is_alive()
    assert app.notifier._checks >= 2
    assert app.last_state.percent == 22


def test_worker_survives_check_errors(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("sensor exploded")

    monkeypatch.setattr(bn, "read_battery", boom)
    app = tray.TrayApp(bn.Notifier(), interval=0.01)
    import threading, time
    th = threading.Thread(target=app._worker, daemon=True)
    th.start()
    time.sleep(0.08)
    app._stop.set()
    th.join(timeout=2)
    assert len(calls) >= 2          # kept going despite exceptions
    assert not th.is_alive()


def test_details_text():
    app = tray.TrayApp(bn.Notifier(), interval=60)
    assert "No battery" in app._details()
    app.last_state = st(77, True)
    assert "77%" in app._details() and "charging" in app._details()


def test_exit_sets_stop_flag():
    app = tray.TrayApp(bn.Notifier(), interval=60)

    class FakeIcon:
        stopped = False
        def stop(self):
            self.stopped = True

    app.icon = FakeIcon()
    app._on_exit()
    assert app._stop.is_set() and app.icon.stopped


def test_refresh_icon_updates_image_and_title():
    app = tray.TrayApp(bn.Notifier(), interval=60)

    class FakeIcon:
        icon = None
        title = None

    app.icon = FakeIcon()
    app.last_state = st(15, False)
    app.refresh_icon()
    assert app.icon.icon is not None
    assert "15%" in app.icon.title


def test_refresh_icon_noop_without_icon():
    tray.TrayApp(bn.Notifier(), interval=60).refresh_icon()   # must not raise
