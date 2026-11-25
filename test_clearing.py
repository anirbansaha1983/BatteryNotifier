"""Alerts must not linger after the user plugs in / unplugs."""

import sys
import types

import pytest

import battery_notifier as bn
import tray


def st(pct, plugged, secs=3600):
    return bn.BatteryState(pct, plugged, secs)


@pytest.fixture
def fake_win11toast(monkeypatch):
    calls = {"toast": [], "clear": []}
    mod = types.ModuleType("win11toast")
    mod.toast = lambda t, m, **kw: calls["toast"].append(kw)
    mod.clear_toast = lambda **kw: calls["clear"].append(kw)
    monkeypatch.setitem(sys.modules, "win11toast", mod)
    return calls


# --------------------------------------------------------------------------- #
# The core complaint: no new alerts once the charger is unplugged
# --------------------------------------------------------------------------- #

def test_no_alerts_after_unplugging_when_full(monkeypatch):
    sent = []
    cur = {"s": st(100, True, None)}
    monkeypatch.setattr(bn, "read_battery", lambda: cur["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m, urgent=True: sent.append(t))
    monkeypatch.setattr(bn, "clear_notifications", lambda: None)
    n = bn.Notifier(30, 80, status_file=None)
    for _ in range(3):
        n.check()
    assert len(sent) == 3
    cur["s"] = st(100, False, 7200)        # charger removed
    for _ in range(5):
        n.check()
    assert len(sent) == 3                   # nothing new


def test_no_alerts_after_plugging_in_when_low(monkeypatch):
    sent = []
    cur = {"s": st(15, False)}
    monkeypatch.setattr(bn, "read_battery", lambda: cur["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m, urgent=True: sent.append(t))
    monkeypatch.setattr(bn, "clear_notifications", lambda: None)
    n = bn.Notifier(30, 80, status_file=None)
    n.check()
    cur["s"] = st(15, True)                 # plugged in, below high threshold
    for _ in range(5):
        n.check()
    assert len(sent) == 1


# --------------------------------------------------------------------------- #
# Stale toasts are actively cleared
# --------------------------------------------------------------------------- #

def test_toasts_cleared_when_condition_resolves(monkeypatch):
    cleared = []
    cur = {"s": st(100, True, None)}
    monkeypatch.setattr(bn, "read_battery", lambda: cur["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m, urgent=True: None)
    monkeypatch.setattr(bn, "clear_notifications", lambda: cleared.append(1))
    n = bn.Notifier(30, 80, status_file=None)
    n.check()
    assert cleared == []                    # still alerting
    cur["s"] = st(100, False, 7200)         # user unplugged
    n.check()
    assert cleared == [1]                   # toasts removed
    n.check()
    assert cleared == [1]                   # only once


def test_toasts_cleared_when_alert_kind_changes(monkeypatch):
    cleared = []
    cur = {"s": st(15, False)}
    monkeypatch.setattr(bn, "read_battery", lambda: cur["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m, urgent=True: None)
    monkeypatch.setattr(bn, "clear_notifications", lambda: cleared.append(1))
    n = bn.Notifier(30, 80, status_file=None)
    n.check()
    cur["s"] = st(95, True)                 # straight to "high"
    n.check()
    assert cleared == [1]


def test_run_clears_on_exit(monkeypatch):
    cleared = []
    monkeypatch.setattr(bn, "read_battery", lambda: st(50, False))
    monkeypatch.setattr(bn, "clear_notifications", lambda: cleared.append(1))

    def stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(bn.time, "sleep", stop)
    bn.Notifier(status_file=None).run(interval=0.01)
    assert cleared == [1]


def test_tray_exit_clears(monkeypatch):
    cleared = []
    monkeypatch.setattr(bn, "clear_notifications", lambda: cleared.append(1))
    app = tray.TrayApp(bn.Notifier(status_file=None), interval=5)

    class FakeIcon:
        def stop(self):
            pass

    app.icon = FakeIcon()
    app._on_exit()
    assert cleared == [1]


# --------------------------------------------------------------------------- #
# Toasts replace rather than stack
# --------------------------------------------------------------------------- #

def test_alert_toasts_are_tagged_so_they_replace(fake_win11toast, monkeypatch):
    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    bn.configure_sound("alarm", False, 1)
    bn._notify_win11toast("T", "M")
    kw = fake_win11toast["toast"][0]
    assert kw["tag"] == bn.TOAST_TAG
    assert kw["group"] == bn.TOAST_GROUP
    bn.configure_sound(bn.DEFAULT_SOUND, True, 3)


def test_clear_notifications_uses_tag_and_group(fake_win11toast):
    bn.clear_notifications()
    assert fake_win11toast["clear"] == [
        {"app_id": bn.APP_NAME, "tag": bn.TOAST_TAG, "group": bn.TOAST_GROUP}]


def test_clear_notifications_survives_missing_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "win11toast", None)
    bn.clear_notifications()        # must not raise


def test_clear_notifications_survives_errors(monkeypatch):
    mod = types.ModuleType("win11toast")
    def boom(**kw):
        raise RuntimeError("history unavailable")
    mod.clear_toast = boom
    monkeypatch.setitem(sys.modules, "win11toast", mod)
    bn.clear_notifications()        # must not raise


# --------------------------------------------------------------------------- #
# Clearing works for every backend, not just win11toast
# --------------------------------------------------------------------------- #

def test_powershell_clear_used_when_win11toast_missing(monkeypatch):
    """winotify / PowerShell toasts must still get cleared."""
    monkeypatch.setitem(sys.modules, "win11toast", None)
    captured = {}

    def fake_call(cmd, **kwargs):
        captured["script"] = cmd[-1]
        return 0

    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bn.shutil, "which", lambda n: "powershell")
    monkeypatch.setattr(bn.subprocess, "call", fake_call)
    bn.clear_notifications()
    assert "RemoveGroup" in captured["script"]
    assert bn.TOAST_GROUP in captured["script"]
    assert "Clear" in captured["script"]


def test_win11toast_preferred_over_powershell(fake_win11toast, monkeypatch):
    calls = []
    monkeypatch.setattr(bn.subprocess, "call",
                        lambda *a, **k: calls.append(1) or 0)
    bn.clear_notifications()
    assert fake_win11toast["clear"] and calls == []


def test_win11toast_falls_back_to_group_clear(monkeypatch):
    attempts = []
    mod = types.ModuleType("win11toast")

    def clear_toast(**kw):
        attempts.append(kw)
        if "tag" in kw:
            raise AttributeError("group value is required to clear a toast")

    mod.clear_toast = clear_toast
    monkeypatch.setitem(sys.modules, "win11toast", mod)
    bn.clear_notifications()
    assert len(attempts) == 2 and "tag" not in attempts[1]


def test_powershell_clear_skipped_off_windows(monkeypatch):
    monkeypatch.setattr(bn.platform, "system", lambda: "Linux")
    assert bn._clear_via_powershell() is False


def test_clear_is_noop_when_nothing_available(monkeypatch):
    monkeypatch.setitem(sys.modules, "win11toast", None)
    monkeypatch.setattr(bn.platform, "system", lambda: "Linux")
    bn.clear_notifications()        # must not raise


# --------------------------------------------------------------------------- #
# Default toasts self-dismiss, so nothing can linger
# --------------------------------------------------------------------------- #

def test_default_toasts_are_not_persistent():
    bn.configure_sound("alarm", True, 3)
    assert bn._PERSISTENT_TOAST is False


def test_cli_persistent_toast_flag(monkeypatch):
    monkeypatch.setattr(bn, "notify", lambda t, m, urgent=True: None)
    bn.main(["--test-notification", "--persistent-toast"])
    assert bn._PERSISTENT_TOAST is True
    bn.main(["--test-notification"])
    assert bn._PERSISTENT_TOAST is False


# --------------------------------------------------------------------------- #
# Version reporting (detecting a stale running process)
# --------------------------------------------------------------------------- #

def test_status_file_records_version(tmp_path, monkeypatch):
    import json as _json
    sf = tmp_path / "status.json"
    monkeypatch.setattr(bn, "read_battery", lambda: st(55, False))
    bn.Notifier(status_file=sf).check()
    assert _json.loads(sf.read_text())["version"] == bn.__version__


def test_status_warns_when_running_old_version(tmp_path, capsys):
    import os as _os
    sf = tmp_path / "status.json"
    bn.write_status(sf, {"pid": _os.getpid(), "version": "0.0.1",
                         "checks": 5, "notifications_sent": 1,
                         "thresholds": {"low": 30, "high": 80},
                         "battery": None})
    bn.print_status(sf)
    out = capsys.readouterr().out
    assert "OUT OF DATE" in out and "0.0.1" in out


def test_status_quiet_when_version_matches(tmp_path, capsys):
    import os as _os
    sf = tmp_path / "status.json"
    bn.write_status(sf, {"pid": _os.getpid(), "version": bn.__version__,
                         "checks": 5, "notifications_sent": 1,
                         "thresholds": {"low": 30, "high": 80},
                         "battery": None})
    bn.print_status(sf)
    assert "OUT OF DATE" not in capsys.readouterr().out


def test_status_handles_missing_version(tmp_path, capsys):
    import os as _os
    sf = tmp_path / "status.json"
    bn.write_status(sf, {"pid": _os.getpid(), "checks": 1,
                         "notifications_sent": 0,
                         "thresholds": {"low": 30, "high": 80},
                         "battery": None})
    bn.print_status(sf)
    out = capsys.readouterr().out
    assert "pre-1.3.0 build" in out and "OUT OF DATE" in out
