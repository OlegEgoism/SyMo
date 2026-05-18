from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Dict, Tuple

import psutil


class SystemUsage:
    @staticmethod
    def get_cpu_temp() -> int:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return 0

            preferred_keys = ('coretemp', 'k10temp', 'cpu-thermal', 'soc_thermal', 'acpitz')
            for key in preferred_keys:
                arr = temps.get(key)
                if arr:
                    for t in arr:
                        label = (getattr(t, 'label', '') or '').lower()
                        if label.startswith('package') or label.startswith('tctl'):
                            return int(t.current)
                    return int(arr[0].current)

            first_list = next(iter(temps.values()))
            return int(first_list[0].current) if first_list else 0
        except Exception:
            return 0

    @staticmethod
    def get_cpu_usage() -> float:
        return psutil.cpu_percent()

    @staticmethod
    def get_ram_usage() -> Tuple[float, float]:
        m = psutil.virtual_memory()
        return m.used / (1024 ** 3), m.total / (1024 ** 3)

    @staticmethod
    def get_swap_usage() -> Tuple[float, float]:
        s = psutil.swap_memory()
        return s.used / (1024 ** 3), s.total / (1024 ** 3)

    @staticmethod
    def get_disk_usage() -> Tuple[float, float]:
        d = psutil.disk_usage('/')
        return d.used / (1024 ** 3), d.total / (1024 ** 3)

    @staticmethod
    def get_network_speed(prev_data: Dict[str, float]) -> Tuple[float, float]:
        net = psutil.net_io_counters()
        now = time.time()
        elapsed = max(0.0001, now - prev_data['time'])

        recv_delta = max(0, net.bytes_recv - prev_data['recv'])
        sent_delta = max(0, net.bytes_sent - prev_data['sent'])

        recv_speed = recv_delta / elapsed / 1024 / 1024
        sent_speed = sent_delta / elapsed / 1024 / 1024

        prev_data['recv'] = net.bytes_recv
        prev_data['sent'] = net.bytes_sent
        prev_data['time'] = now
        return recv_speed, sent_speed

    @staticmethod
    def get_uptime() -> str:
        seconds = time.time() - psutil.boot_time()
        return str(timedelta(seconds=int(seconds)))


class MetricsSampler:
    """Collect metrics using per-metric cache intervals to reduce psutil polling."""

    _METRIC_KEYS = (
        "cpu_temp",
        "cpu_usage",
        "ram",
        "swap",
        "disk",
        "net",
        "uptime",
    )

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {
            "cpu_temp": 0,
            "cpu_usage": 0.0,
            "ram": (0.0, 0.0),
            "swap": (0.0, 0.0),
            "disk": (0.0, 0.0),
            "net": (0.0, 0.0),
            "uptime": "00:00:00",
        }
        self._last_update_ts: Dict[str, float] = {key: 0.0 for key in self._METRIC_KEYS}

    def collect(self, prev_net_data: Dict[str, float], intervals: Dict[str, int]) -> Dict[str, Any]:
        now = time.time()
        for key in self._METRIC_KEYS:
            min_interval = max(1, int(intervals.get(key, 1)))
            if now - self._last_update_ts[key] < min_interval:
                continue
            self._cache[key] = self._collect_metric(key, prev_net_data)
            self._last_update_ts[key] = now
        return dict(self._cache)

    @staticmethod
    def _collect_metric(key: str, prev_net_data: Dict[str, float]) -> Any:
        if key == "cpu_temp":
            return SystemUsage.get_cpu_temp()
        if key == "cpu_usage":
            return SystemUsage.get_cpu_usage()
        if key == "ram":
            return SystemUsage.get_ram_usage()
        if key == "swap":
            return SystemUsage.get_swap_usage()
        if key == "disk":
            return SystemUsage.get_disk_usage()
        if key == "net":
            return SystemUsage.get_network_speed(prev_net_data)
        if key == "uptime":
            return SystemUsage.get_uptime()
        return 0
