"""Tests for the loud/urgent notification sound behaviour."""

import sys
import types

import pytest

import battery_notifier as bn


@pytest.fixture(autouse=True)
def _reset_sound():
    yield
    bn.configure_sound(bn.DEFAULT_SOUND, True, 3)


@pytest.fixture
def fake_winsound(monkeypatch):
    played = []
    ws = types.ModuleType("winsound")
    ws.Beep = lambda f, d: played.append(("beep", f, d))
    ws.MessageBeep = lambda t: played.append(("msgbeep", t))
    ws.MB_ICONEXCLAMATION = 0x30
    monkeypatch.setitem(sys.modules, "winsound", ws)
    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bn.time, "sleep", lambda s: None)
    return played


# --------------------------------------------------------------------------- #
# configure_sound
# --------------------------------------------------------------------------- #

def test_default_is_alarm():
    assert bn.DEFAULT_SOUND == "alarm"


def test_configure_sound_rejects_bad_mode():
    with pytest.raises(ValueError):
        bn.configure_sound("loud")


def test_configure_sound_clamps_negative_repeats():
    bn.configure_sound("alarm", True, -5)
    assert bn._BEEP_REPEATS == 0


# --------------------------------------------------------------------------- #
# _play_alarm
# --------------------------------------------------------------------------- #

def test_alarm_beeps_repeatedly(fake_winsound):
    bn.configure_sound("alarm", True, 3)
    bn._play_alarm()
    beeps = [p for p in fake_winsound if p[0] == "beep"]
    assert len(beeps) == 6                      # two tones x 3 repeats
    assert ("msgbeep", 0x30) in fake_winsound   # plus the system sound


def test_sound_off_is_silent(fake_winsound):
    bn.configure_sound("off", True, 3)
    bn._play_alarm()
    assert fake_winsound == []


def test_no_beep_disables_tone(fake_winsound):
    bn.configure_sound("alarm", False, 3)
    bn._play_alarm()
    assert fake_winsound == []


def test_alarm_survives_winsound_failure(monkeypatch, capsys):
    ws = types.ModuleType("winsound")
    def boom(*a, **k):
        raise RuntimeError("no audio device")
    ws.Beep = boom
    ws.MessageBeep = boom
    monkeypatch.setitem(sys.modules, "winsound", ws)
    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bn.time, "sleep", lambda s: None)
    bn.configure_sound("alarm", True, 2)
    bn._play_alarm()                             # must not raise
    assert "\a" in capsys.readouterr().out       # fell back to terminal bell


# --------------------------------------------------------------------------- #
# Toast payloads
# --------------------------------------------------------------------------- #

def _fake_win11toast(monkeypatch):
    sent = {}
    mod = types.ModuleType("win11toast")
    def toast(title, message, **kwargs):
        sent.update(kwargs)
        sent["title"] = title
    mod.toast = toast
    monkeypatch.setitem(sys.modules, "win11toast", mod)
    return sent


def test_win11toast_requests_looping_alarm(monkeypatch):
    sent = _fake_win11toast(monkeypatch)
    bn.configure_sound("alarm", True, 1)
    assert bn._notify_win11toast("T", "M") is True
    assert sent["audio"]["loop"] == "true"
    assert "Looping.Alarm" in sent["audio"]["src"]
    assert sent["duration"] == "long"
    assert sent["scenario"] == "alarm"


def test_win11toast_silent_mode(monkeypatch):
    sent = _fake_win11toast(monkeypatch)
    bn.configure_sound("off", True, 1)
    bn._notify_win11toast("T", "M")
    assert sent["audio"] == {"silent": "true"}


def test_win11toast_default_mode_has_no_custom_audio(monkeypatch):
    sent = _fake_win11toast(monkeypatch)
    bn.configure_sound("default", True, 1)
    bn._notify_win11toast("T", "M")
    assert "audio" not in sent


def test_win11toast_retries_without_options(monkeypatch):
    calls = []
    mod = types.ModuleType("win11toast")
    def toast(title, message, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TypeError("unexpected keyword 'scenario'")
    mod.toast = toast
    monkeypatch.setitem(sys.modules, "win11toast", mod)
    bn.configure_sound("alarm", True, 1)
    assert bn._notify_win11toast("T", "M") is True
    assert len(calls) == 2 and "scenario" not in calls[1]


def test_powershell_toast_embeds_alarm_audio(monkeypatch):
    captured = {}
    def fake_call(cmd, **kwargs):
        captured["script"] = cmd[-1]
        return 0
    monkeypatch.setattr(bn.shutil, "which", lambda n: "powershell")
    monkeypatch.setattr(bn.subprocess, "call", fake_call)
    bn.configure_sound("alarm", True, 1)
    assert bn._notify_powershell("T", "M") is True
    assert "Looping.Alarm" in captured["script"]
    assert "scenario='alarm'" in captured["script"]


def test_linux_alarm_uses_critical_urgency(monkeypatch):
    captured = {}
    monkeypatch.setattr(bn.shutil, "which", lambda n: "/usr/bin/notify-send")
    monkeypatch.setattr(bn.subprocess, "call",
                        lambda cmd, **k: captured.setdefault("cmd", cmd) and 0 or 0)
    bn.configure_sound("alarm", True, 1)
    bn._notify_linux("T", "M")
    assert "--urgency=critical" in captured["cmd"]
    assert "--expire-time=0" in captured["cmd"]


def test_linux_default_mode_is_plain(monkeypatch):
    captured = {}
    monkeypatch.setattr(bn.shutil, "which", lambda n: "/usr/bin/notify-send")
    monkeypatch.setattr(bn.subprocess, "call",
                        lambda cmd, **k: captured.setdefault("cmd", cmd) and 0 or 0)
    bn.configure_sound("default", True, 1)
    bn._notify_linux("T", "M")
    assert "--urgency=critical" not in captured["cmd"]


# --------------------------------------------------------------------------- #
# notify() integration
# --------------------------------------------------------------------------- #

def test_notify_plays_alarm_in_background(monkeypatch):
    played = []
    monkeypatch.setattr(bn, "_play_alarm", lambda: played.append(1))
    monkeypatch.setattr(bn.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bn, "_notify_linux", lambda t, m: True)
    bn.configure_sound("alarm", True, 1)
    bn.notify("T", "M")
    for _ in range(50):
        if played:
            break
        bn.time.sleep(0.01)
    assert played == [1]


def test_notify_skips_alarm_when_off(monkeypatch):
    played = []
    monkeypatch.setattr(bn, "_play_alarm", lambda: played.append(1))
    monkeypatch.setattr(bn.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bn, "_notify_linux", lambda t, m: True)
    bn.configure_sound("off", True, 1)
    bn.notify("T", "M")
    bn.time.sleep(0.05)
    assert played == []


def test_cli_sets_sound_mode(monkeypatch):
    monkeypatch.setattr(bn, "notify", lambda t, m: None)
    bn.main(["--test-notification", "--sound", "off", "--beep-repeats", "7"])
    assert bn._SOUND_MODE == "off"
    assert bn._BEEP_REPEATS == 7


def test_cli_no_beep(monkeypatch):
    monkeypatch.setattr(bn, "notify", lambda t, m: None)
    bn.main(["--test-notification", "--no-beep"])
    assert bn._BEEP_ENABLED is False
