import battery_notifier as bn


def state(pct, plugged):
    return bn.BatteryState(percent=pct, plugged=plugged, secs_left=3600)


def test_low_while_discharging():
    assert bn.evaluate(state(30, False), 30, 80)[0] == "low"
    assert bn.evaluate(state(12, False), 30, 80)[0] == "low"


def test_no_alert_in_normal_range():
    assert bn.evaluate(state(50, False), 30, 80) is None
    assert bn.evaluate(state(50, True), 30, 80) is None
    assert bn.evaluate(state(20, True), 30, 80) is None
    assert bn.evaluate(state(95, False), 30, 80) is None


def test_high_while_charging():
    assert bn.evaluate(state(80, True), 30, 80)[0] == "high"
    assert bn.evaluate(state(100, True), 30, 80)[0] == "high"


def test_notifies_every_check_by_default(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "read_battery", lambda: state(15, False))
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    n = bn.Notifier()
    assert [n.check() for _ in range(3)] == ["low", "low", "low"]
    assert len(sent) == 3
    assert "reminder #2" in sent[1] and "reminder #3" in sent[2]


def test_repeat_after_throttles(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "read_battery", lambda: state(15, False))
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(t))
    n = bn.Notifier(repeat_after=900)
    assert n.check() == "low"
    assert n.check() is None
    assert len(sent) == 1


def test_state_change_alerts_immediately(monkeypatch):
    sent = []
    current = {"s": state(15, False)}
    monkeypatch.setattr(bn, "read_battery", lambda: current["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(t))
    n = bn.Notifier(repeat_after=900)
    assert n.check() == "low"
    current["s"] = state(95, True)          # plugged in, now high
    assert n.check() == "high"
    assert len(sent) == 2


def test_normal_range_resets_counter(monkeypatch):
    sent = []
    current = {"s": state(15, False)}
    monkeypatch.setattr(bn, "read_battery", lambda: current["s"])
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(m))
    n = bn.Notifier()
    n.check(); n.check()
    current["s"] = state(50, False)
    assert n.check() is None
    current["s"] = state(15, False)
    n.check()
    assert "reminder" not in sent[-1]        # counter restarted


def test_time_left_format():
    assert bn.BatteryState(50, False, 3660).time_left == "1h 01m"
    assert bn.BatteryState(50, False, None).time_left == "unknown"


# --------------------------------------------------------------------------- #
# Notification backend selection
# --------------------------------------------------------------------------- #

def _fake_backend(name, ok, calls):
    def backend(title, message):
        calls.append(name)
        return ok
    backend.__name__ = name
    return backend


def test_windows_prefers_win11toast(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bn, "_notify_win11toast", _fake_backend("win11toast", True, calls))
    monkeypatch.setattr(bn, "_notify_winotify", _fake_backend("winotify", True, calls))
    monkeypatch.setattr(bn, "_notify_plyer", _fake_backend("plyer", True, calls))
    bn.notify("T", "M")
    assert calls == ["win11toast"]


def test_windows_falls_back_through_chain(monkeypatch):
    calls = []
    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bn, "_notify_win11toast", _fake_backend("win11toast", False, calls))
    monkeypatch.setattr(bn, "_notify_winotify", _fake_backend("winotify", False, calls))
    monkeypatch.setattr(bn, "_notify_plyer", _fake_backend("plyer", True, calls))
    monkeypatch.setattr(bn, "_notify_powershell", _fake_backend("powershell", True, calls))
    bn.notify("T", "M")
    assert calls == ["win11toast", "winotify", "plyer"]


def test_console_fallback_when_all_backends_fail(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(bn.platform, "system", lambda: "Windows")
    for attr in ("_notify_win11toast", "_notify_winotify", "_notify_plyer",
                 "_notify_powershell"):
        monkeypatch.setattr(bn, attr, _fake_backend(attr, False, calls))
    bn.notify("Title", "Message")
    assert "Title: Message" in capsys.readouterr().out
    assert len(calls) == 4


def test_backends_missing_modules_return_false():
    # No win11toast/winotify/plyer installed in this environment -> graceful False.
    assert bn._notify_win11toast("T", "M") is False
    assert bn._notify_winotify("T", "M") is False


def test_test_notification_flag(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(t))
    assert bn.main(["--test-notification"]) == 0
    assert sent and "Test" in sent[0]
