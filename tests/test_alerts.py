import time

from app_core.alerts import REPEAT_SEC, AlertMonitor
from app_core.system_usage import MetricsSnapshot

SETTINGS = {'alert_cpu_temp_c': 90, 'alert_ram_percent': 95, 'alert_disk_percent': 0}


def _snapshot(temp=50.0, ram=1.0):
    return MetricsSnapshot(timestamp=time.time(), cpu_temp=temp, cpu_usage=1.0, ram_used=ram, ram_total=100.0,
                           swap_used=0.0, swap_total=0.0, disk_used=99.0, disk_total=100.0, net_recv=0.0,
                           net_sent=0.0, uptime="", keyboard_clicks=None, mouse_clicks=None)


def test_alert_fires_once_and_rearms_after_hysteresis():
    monitor = AlertMonitor()
    assert monitor.check(_snapshot(temp=80), SETTINGS, 0) == []
    assert len(monitor.check(_snapshot(temp=91), SETTINGS, 1)) == 1
    assert monitor.check(_snapshot(temp=92), SETTINGS, 2) == []          # всё ещё выше: не повторять
    assert monitor.check(_snapshot(temp=88), SETTINGS, 3) == []          # в зоне гистерезиса
    assert monitor.check(_snapshot(temp=91), SETTINGS, 4) == []
    assert monitor.check(_snapshot(temp=80), SETTINGS, 5) == []          # спало ниже порога − 5
    assert len(monitor.check(_snapshot(temp=91), SETTINGS, 6)) == 1


def test_alert_repeats_after_an_hour_and_respects_zero():
    monitor = AlertMonitor()
    assert len(monitor.check(_snapshot(ram=96), SETTINGS, 0)) == 1       # диск выключен порогом 0
    assert monitor.check(_snapshot(ram=96), SETTINGS, REPEAT_SEC - 1) == []
    assert len(monitor.check(_snapshot(ram=96), SETTINGS, REPEAT_SEC)) == 1


def test_no_sensor_means_no_alert():
    assert AlertMonitor().check(_snapshot(temp=None), SETTINGS, 0) == []
