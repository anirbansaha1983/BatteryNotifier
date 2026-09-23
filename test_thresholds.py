"""Tests for runtime threshold changes, persistence, and repeat cadence."""

import json

import pytest

import battery_notifier as bn
import tray


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    """Keep every test away from the real settings file."""
    monkeypatch.setattr(bn, "default_state_dir", lambda: tmp_path)
    yield


def st(pct, plugged):
    return bn.BatteryState(pct, plugged, 3600)


# --------------------------------------------------------------------------- #
# Repeat cadence
# --------------------------------------------------------------------------- #

def test_default_interval_is_five_seconds():
    assert bn.DEFAULT_INTERVAL == 5
    assert bn.DEFAULT_REPEAT_AFTER == 0


def test_cli_defaults_keep_nagging(monkeypatch):
    args = bn.parse_args([])
    assert args.interval == 5
    assert args.repeat_after == 0


def test_notifies_on_every_check_until_plugged_in(monkeypatch):
    sent = []
    current = {"s": st(22, False)}
    monkeypatch.setattr(bn, "read_battery", lambda: current["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    n = bn.Notifier()
    for _ in range(5):
        n.check()
    assert len(sent) == 5                       # nagged every check
    current["s"] = st(45, True)                 # user plugged in
    n.check()
    assert len(sent) == 5                       # stopped


# --------------------------------------------------------------------------- #
# set_thresholds
# --------------------------------------------------------------------------- #

def test_set_thresholds_updates_and_persists(tmp_path):
    n = bn.Notifier()
    n.set_thresholds(15, 95)
    assert (n.low, n.high) == (15, 95)
    assert json.loads((tmp_path / "settings.json").read_text()) == {"low": 15,
                                                                   "high": 95}


def test_set_thresholds_partial_update():
    n = bn.Notifier(30, 80)
    n.set_thresholds(low=20)
    assert (n.low, n.high) == (20, 80)
    n.set_thresholds(high=90)
    assert (n.low, n.high) == (20, 90)


@pytest.mark.parametrize("low,high", [(90, 80), (50, 50), (-1, 80), (30, 101)])
def test_set_thresholds_rejects_invalid(low, high):
    n = bn.Notifier(30, 80)
    with pytest.raises(ValueError):
        n.set_thresholds(low, high)
    assert (n.low, n.high) == (30, 80)          # unchanged


def test_changing_threshold_rearms_alert(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "read_battery", lambda: st(45, False))
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    n = bn.Notifier(30, 80, repeat_after=600)
    assert n.check() is None                    # 45% is fine at low=30
    n.set_thresholds(low=50)                    # now 45% counts as low
    assert n.check() == "low"
    assert "reminder" not in sent[0]            # counter restarted


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def test_saved_settings_become_cli_defaults():
    bn.save_settings(12, 88)
    args = bn.parse_args([])
    assert args.low == 12 and args.high == 88


def test_explicit_cli_args_beat_saved_settings():
    bn.save_settings(12, 88)
    args = bn.parse_args(["--low", "25", "--high", "75"])
    assert args.low == 25 and args.high == 75


def test_load_settings_tolerates_corruption(tmp_path):
    (tmp_path / "settings.json").write_text("{not json")
    assert bn.load_settings() == {}


def test_load_settings_ignores_non_dict(tmp_path):
    (tmp_path / "settings.json").write_text("[1, 2]")
    assert bn.load_settings() == {}


def test_persist_false_does_not_write(tmp_path):
    bn.Notifier().set_thresholds(10, 90, persist=False)
    assert not (tmp_path / "settings.json").exists()


# --------------------------------------------------------------------------- #
# Tray UI
# --------------------------------------------------------------------------- #

def test_tray_presets_are_valid():
    assert all(1 <= v <= 99 for v in tray.LOW_CHOICES)
    assert all(2 <= v <= 100 for v in tray.HIGH_CHOICES)
    assert max(tray.LOW_CHOICES) < max(tray.HIGH_CHOICES)


def test_tray_set_low_and_high(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    app = tray.TrayApp(bn.Notifier(30, 80), interval=5)
    app.set_low(20)
    app.set_high(95)
    assert (app.notifier.low, app.notifier.high) == (20, 95)
    assert len(sent) == 2 and "20%" in sent[0] and "95%" in sent[1]


def test_tray_rejects_invalid_choice(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    app = tray.TrayApp(bn.Notifier(30, 80), interval=5)
    app.set_low(90)                              # 90 >= high(80)
    assert (app.notifier.low, app.notifier.high) == (30, 80)
    assert "Invalid" in sent[0]


def test_tray_threshold_change_refreshes_icon(monkeypatch):
    monkeypatch.setattr(bn, "notify", lambda t, m: None)

    class FakeIcon:
        icon = None
        title = None

    app = tray.TrayApp(bn.Notifier(30, 80), interval=5)
    app.icon = FakeIcon()
    app.last_state = st(45, False)
    app.set_low(50)                              # 45% now counts as low
    assert app.icon.icon is not None
    assert tray.icon_state(app.last_state, app.notifier.low,
                           app.notifier.high) == "low"


def test_custom_dialog_without_tkinter(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "tkinter":
            raise ImportError("no tkinter")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    tray.TrayApp(bn.Notifier(), interval=5)._custom_dialog()
    assert "Tkinter is not available" in sent[0]
