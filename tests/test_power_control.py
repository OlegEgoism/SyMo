import pytest
from gi.repository import GLib

from app_core import power_control as pc
from app_core.localization import tr


@pytest.fixture
def power(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(pc, "_now", lambda: clock[0])
    monkeypatch.setattr(pc.GLib, "timeout_add_seconds", lambda *a: 1)
    monkeypatch.setattr(pc.GLib, "source_remove", lambda *a: True)
    control = pc.PowerControl()
    control.warnings, control.ran = [], []
    control._show_warning = control.warnings.append
    control.run_action = lambda act, notify_remote=None: control.ran.append(act)
    control.clock = clock
    return control


def test_one_minute_timer_warns_at_once_and_runs(power):
    power.schedule(pc.Action.POWER_OFF, 1)
    assert power.warnings == [pc.Action.POWER_OFF]
    power.clock[0] += 59
    assert power._tick() is True and power.ran == []
    power.clock[0] += 1
    assert power._tick() is False and power.ran == [pc.Action.POWER_OFF] and power.scheduled_action is None


def test_deadline_passed_during_sleep_is_postponed(power):
    power.schedule(pc.Action.REBOOT, 10)
    assert power.warnings == []
    power.clock[0] += 4000
    assert power._tick() is True and power.ran == [] and power.remaining_seconds() == 60
    power.clock[0] += 60
    power._tick()
    assert power.ran == [pc.Action.REBOOT]


def test_remote_requester_is_told_about_local_changes(power):
    remote = []
    power.schedule(pc.Action.POWER_OFF, 5, notify_remote=remote.append)
    assert power.remote_scheduled_action() == pc.Action.POWER_OFF
    power.cancel_by_user()
    assert remote == [tr("bot_action_cancelled_locally").format(tr("power_off"))]
    remote.clear()
    power.schedule(pc.Action.POWER_OFF, 5, notify_remote=remote.append)
    power.schedule(pc.Action.LOCK, 7)
    assert remote == [tr("bot_action_rescheduled_locally").format(tr("lock"), 7)]
    assert power.cancel_schedule() == pc.Action.LOCK and power.cancel_schedule() is None


class FakeBus:
    def __init__(self, owners, fail=()):
        self.owners, self.fail, self.calls = owners, fail, []

    def call_sync(self, name, path, iface, method, params, rtype, flags, timeout, cancel):
        if method == "NameHasOwner":
            return GLib.Variant("(b)", (params.unpack()[0] in self.owners,))
        self.calls.append((name, method, params.unpack() if params else None))
        if name in self.fail:
            raise GLib.Error("fail")


def test_session_manager_fallbacks(monkeypatch):
    bus = FakeBus({"org.kde.ksmserver"})
    monkeypatch.setattr(pc.Gio, "bus_get_sync", lambda *a: bus)
    assert pc.request_via_session_manager(pc.Action.POWER_OFF)
    assert bus.calls == [("org.kde.ksmserver", "logout", (0, 2, 2))]

    bus = FakeBus({"org.gnome.SessionManager", "org.xfce.SessionManager"}, fail={"org.gnome.SessionManager"})
    monkeypatch.setattr(pc.Gio, "bus_get_sync", lambda *a: bus)
    assert pc.request_via_session_manager(pc.Action.REBOOT)
    assert [c[1] for c in bus.calls] == ["RequestReboot", "Restart"]

    monkeypatch.setattr(pc.Gio, "bus_get_sync", lambda *a: FakeBus(set()))
    assert not pc.request_via_session_manager(pc.Action.POWER_OFF)
    assert not pc.request_via_session_manager(pc.Action.LOCK)
