import time
import types
from pathlib import Path

import pytest

from app_core import system_usage as su
from app_core.history import MetricsHistory, samples_from_snapshot


def _tree(root, spec):
    for rel, content in spec.items():
        path = Path(root, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


@pytest.mark.parametrize("spec, expected", [
    ({"hwmon/hwmon0/name": "nvme", "hwmon/hwmon0/temp1_input": "1",
      "hwmon/hwmon1/name": "coretemp", "hwmon/hwmon1/temp1_input": "1", "hwmon/hwmon1/temp1_label": "Core 0",
      "hwmon/hwmon1/temp2_input": "1", "hwmon/hwmon1/temp2_label": "Package id 0"}, "hwmon/hwmon1/temp2_input"),
    ({"hwmon/hwmon0/name": "k10temp", "hwmon/hwmon0/temp1_input": "1", "hwmon/hwmon0/temp1_label": "Tctl",
      "hwmon/hwmon0/temp2_input": "1", "hwmon/hwmon0/temp2_label": "Tdie"}, "hwmon/hwmon0/temp2_input"),
    ({"hwmon/hwmon0/name": "nvme", "hwmon/hwmon0/temp1_input": "1",
      "hwmon/hwmon1/name": "iwlwifi_1", "hwmon/hwmon1/temp1_input": "1"}, None),
    ({"thermal/thermal_zone0/type": "INT3400 Thermal", "thermal/thermal_zone0/temp": "1",
      "thermal/thermal_zone1/type": "x86_pkg_temp", "thermal/thermal_zone1/temp": "1"}, "thermal/thermal_zone1/temp"),
    ({"hwmon/hwmon0/name": "cpu_thermal", "hwmon/hwmon0/temp1_input": "1"}, "hwmon/hwmon0/temp1_input"),
    ({"hwmon/hwmon0/name": "it8728", "hwmon/hwmon0/temp1_input": "1", "hwmon/hwmon0/temp1_label": "SYSTIN",
      "hwmon/hwmon0/temp2_input": "1", "hwmon/hwmon0/temp2_label": "CPUTIN"}, "hwmon/hwmon0/temp2_input"),
])
def test_cpu_temperature_sensor_choice(tmp_path, spec, expected):
    _tree(tmp_path, spec)
    found = su.find_cpu_temp_input(tmp_path / "hwmon", tmp_path / "thermal")
    assert (None if found is None else str(found.relative_to(tmp_path))) == expected


def test_cpu_temperature_read_failure_backs_off(tmp_path, monkeypatch):
    sensor = tmp_path / "temp"
    sensor.write_text("61500\n")
    temp = su.CpuTemperature()
    temp._input = sensor
    assert temp.read() == 61.5
    sensor.unlink()
    calls = []
    monkeypatch.setattr(su, "find_cpu_temp_input", lambda *a: calls.append(1))
    assert temp.read() is None and temp.read() is None
    assert calls == []


def test_network_counts_only_physical_interfaces(tmp_path, monkeypatch):
    for name in ("eth0", "wlan0"):
        (tmp_path / name / "device").mkdir(parents=True)
    for name in ("lo", "docker0", "veth1", "tun0"):
        (tmp_path / name).mkdir()
    (tmp_path / "ppp0").mkdir()
    (tmp_path / "ppp0" / "type").write_text("512\n")
    c = types.SimpleNamespace
    counters = {"lo": c(bytes_recv=10 ** 9, bytes_sent=10 ** 9), "docker0": c(bytes_recv=5, bytes_sent=5),
                "veth1": c(bytes_recv=5, bytes_sent=5), "tun0": c(bytes_recv=5, bytes_sent=5),
                "eth0": c(bytes_recv=1000, bytes_sent=100), "wlan0": c(bytes_recv=0, bytes_sent=0),
                "ppp0": c(bytes_recv=0, bytes_sent=0)}
    monkeypatch.setattr(su.psutil, "net_io_counters", lambda pernic=False: counters)
    original = su.network_counters
    assert set(original(tmp_path)) == {"eth0", "wlan0", "ppp0"}
    monkeypatch.setattr(su, "network_counters", lambda: original(tmp_path))

    state = su.initial_network_state()
    state["time"] -= 1.0
    counters["eth0"] = c(bytes_recv=1000 + 2 * 1024 * 1024, bytes_sent=100 + 1024 * 1024)
    counters["lo"] = c(bytes_recv=10 ** 10, bytes_sent=10 ** 10)
    recv, sent = su.SystemUsage.get_network_speed(state)
    assert 1.9 < recv < 2.01 and 0.9 < sent < 1.01

    counters["eth0"] = c(bytes_recv=10, bytes_sent=10)     # переподключение
    state["time"] -= 1.0
    assert su.SystemUsage.get_network_speed(state) == (0, 0)


def test_formatting():
    assert su.format_temp(None) == "N/A"
    assert su.format_temp(61.56, 1) == "61.6°C"
    assert su.format_count(None) == "N/A" and su.format_count(3) == "3"


def _snapshot(**overrides):
    values = dict(timestamp=time.time(), cpu_temp=None, cpu_usage=10.0, ram_used=1.0, ram_total=2.0,
                  swap_used=0.0, swap_total=0.0, disk_used=5.0, disk_total=10.0, net_recv=0.0, net_sent=0.0,
                  uptime="0:00:01", keyboard_clicks=None, mouse_clicks=5)
    values.update(overrides)
    return su.MetricsSnapshot(**values)


def test_history_without_sensor_or_counters():
    samples = samples_from_snapshot(_snapshot())
    assert samples["cpu"][2] is None
    assert "keyboard" not in samples and samples["mouse"][1] == 5


def test_history_counts_activity_per_minute():
    history = MetricsHistory(10)
    history.append_snapshot(_snapshot(timestamp=100.0, mouse_clicks=10))
    history.append_snapshot(_snapshot(timestamp=110.0, mouse_clicks=30))
    first, second = history.samples("mouse")
    assert first[2] == 0.0
    assert second == (110.0, 30, 120.0)


def test_history_keeps_battery_and_gpu_when_present():
    assert "battery" not in samples_from_snapshot(_snapshot())
    samples = samples_from_snapshot(_snapshot(battery_percent=87.0, battery_plugged=True, gpu_usage=140.0))
    assert samples["battery"][1] == 87.0 and samples["gpu"][1] == 100.0
