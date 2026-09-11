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


def test_repeat_suppression(monkeypatch):
    sent = []
    monkeypatch.setattr(bn, "read_battery", lambda: state(15, False))
    monkeypatch.setattr(bn, "notify", lambda t, m: sent.append(t))
    n = bn.Notifier()
    assert n.check() == "low"
    assert n.check() is None
    assert len(sent) == 1


def test_time_left_format():
    assert bn.BatteryState(50, False, 3660).time_left == "1h 01m"
    assert bn.BatteryState(50, False, None).time_left == "unknown"
