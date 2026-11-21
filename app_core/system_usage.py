from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import psutil

logger = logging.getLogger(__name__)

SYSFS_NET = Path("/sys/class/net")
SYSFS_HWMON = Path("/sys/class/hwmon")
SYSFS_THERMAL = Path("/sys/class/thermal")


@dataclass(frozen=True)
class MetricsSnapshot:
    """Один согласованный срез метрик, общий для меню, графиков, лога и уведомлений."""

    timestamp: float
    # None — у процессора не найден датчик температуры.
    cpu_temp: Optional[float]
    cpu_usage: float
    ram_used: float
    ram_total: float
    swap_used: float
    swap_total: float
    disk_used: float
    disk_total: float
    net_recv: float
    net_sent: float
    uptime: str
    # None — счётчики недоступны (Wayland) или скрыты.
    keyboard_clicks: Optional[int]
    mouse_clicks: Optional[int]


# Датчики hwmon процессора по убыванию предпочтения: (имя драйвера, метки).
# Пустой кортеж меток — любой вход драйвера.
_CPU_HWMON_SENSORS = (
    ('coretemp', ('package id',)),
    ('k10temp', ('tdie', 'tctl')),
    ('zenpower', ('tdie', 'tctl')),
    ('coretemp', ()),
    ('k10temp', ()),
    ('zenpower', ()),
    ('k8temp', ()),
    ('via_cputemp', ()),
    ('cpu_thermal', ()),
    ('cpu-thermal', ()),
    ('soc_thermal', ()),
    ('acpitz', ()),
)
# Типы thermal_zone на случай, когда драйвер не зарегистрировал hwmon.
_CPU_THERMAL_ZONE_TYPES = ('x86_pkg_temp', 'cpu_thermal', 'cpu-thermal', 'soc_thermal', 'acpitz')
# Последний шанс: вход любого драйвера с такой меткой или thermal_zone с таким типом.
_CPU_LABEL_PREFIXES = ('package', 'tdie', 'tctl', 'cpu')
_SENSOR_REDISCOVERY_SEC = 60.0


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def find_cpu_temp_input(hwmon_root: Path = SYSFS_HWMON, thermal_root: Path = SYSFS_THERMAL) -> Optional[Path]:
    """Файл с температурой процессора в миллиградусах или None, если датчика нет."""
    inputs: Dict[str, list[tuple[str, Path]]] = {}
    for hwmon in sorted(hwmon_root.glob("hwmon*")):
        name = _read_text(hwmon / "name").lower()
        for temp_input in sorted(hwmon.glob("temp*_input")):
            label = _read_text(temp_input.with_name(temp_input.name.replace("_input", "_label"))).lower()
            inputs.setdefault(name, []).append((label, temp_input))

    # Порядок меток в кортеже — тоже приоритет: Tdie точнее Tctl со смещением.
    for name, labels in _CPU_HWMON_SENSORS:
        for prefix in labels or ('',):
            for label, temp_input in inputs.get(name, ()):
                if label.startswith(prefix):
                    return temp_input

    zones: Dict[str, Path] = {}
    for zone in sorted(thermal_root.glob("thermal_zone*")):
        zones.setdefault(_read_text(zone / "type").lower(), zone / "temp")
    for zone_type in _CPU_THERMAL_ZONE_TYPES:
        if zone_type in zones:
            return zones[zone_type]

    for prefix in _CPU_LABEL_PREFIXES:
        for entries in inputs.values():
            for label, temp_input in entries:
                if label.startswith(prefix):
                    return temp_input
        for zone_type, temp in zones.items():
            if zone_type.startswith(prefix):
                return temp
    return None


class CpuTemperature:
    """Температура процессора из одного заранее найденного файла sysfs.

    psutil.sensors_temperatures() каждый раз обходит все датчики системы и
    стоит около 10 мс, а нужен только один.
    """

    def __init__(self) -> None:
        self._input: Optional[Path] = None
        self._logged_input: Optional[Path] = None
        self._next_discovery = float("-inf")

    def read(self) -> Optional[float]:
        if self._input is None:
            if time.monotonic() < self._next_discovery:
                return None
            self._input = find_cpu_temp_input()
            if self._input is None:
                self._next_discovery = time.monotonic() + _SENSOR_REDISCOVERY_SEC
                return None
            if self._input != self._logged_input:
                logger.info("Датчик температуры процессора: %s", self._input)
                self._logged_input = self._input
        try:
            return int(self._input.read_text()) / 1000.0
        except (OSError, ValueError):
            # Номера hwmon могут смениться, например после перезагрузки драйвера;
            # датчик, который стабильно не читается, не перебираем на каждом опросе.
            self._input = None
            self._next_discovery = time.monotonic() + _SENSOR_REDISCOVERY_SEC
            return None


_ARPHRD_PPP = "512"


def _is_physical_interface(name: str, net_root: Path = SYSFS_NET) -> bool:
    """У физических сетевых карт (Ethernet, Wi-Fi, USB-модем) в sysfs есть device;
    у lo, мостов, veth, docker и VPN-туннелей его нет. PPP (DSL, 3G-модемы) — тоже
    выход в сеть, хотя device у него нет."""
    return (net_root / name / "device").exists() or _read_text(net_root / name / "type") == _ARPHRD_PPP


def network_counters(net_root: Path = SYSFS_NET) -> Dict[str, Tuple[int, int]]:
    """Принято и отправлено байт по физическим интерфейсам.

    Трафик контейнеров и VPN всё равно проходит через физическую карту, поэтому
    виртуальные интерфейсы не учитываются, иначе он посчитался бы дважды.
    """
    per_nic = psutil.net_io_counters(pernic=True)
    physical = {name: (c.bytes_recv, c.bytes_sent) for name, c in per_nic.items()
                if _is_physical_interface(name, net_root)}
    if physical:
        return physical
    # Например, в контейнере или ВМ без физических карт: всё, кроме loopback.
    return {name: (c.bytes_recv, c.bytes_sent) for name, c in per_nic.items() if name != 'lo'}


def format_temp(value: Optional[float], digits: int = 0) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}°C"


def format_count(value: Optional[int]) -> str:
    return "N/A" if value is None else str(value)


def initial_network_state() -> Dict[str, Any]:
    return {'time': time.monotonic(), 'nics': network_counters()}


class SystemUsage:
    _cpu_temperature = CpuTemperature()

    @classmethod
    def get_cpu_temp(cls) -> Optional[float]:
        return cls._cpu_temperature.read()

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
    def get_network_speed(prev_data: Dict[str, Any]) -> Tuple[float, float]:
        nics = network_counters()
        now = time.monotonic()
        elapsed = max(0.0001, now - prev_data['time'])

        recv_delta = sent_delta = 0
        prev_nics = prev_data['nics']
        # Интерфейс, которого не было в прошлый раз, учитывается со следующего замера;
        # счётчик, ставший меньше (переподключение), даёт 0, а не отрицательную скорость.
        for name, (recv, sent) in nics.items():
            if name in prev_nics:
                prev_recv, prev_sent = prev_nics[name]
                recv_delta += max(0, recv - prev_recv)
                sent_delta += max(0, sent - prev_sent)

        prev_data['nics'] = nics
        prev_data['time'] = now
        return recv_delta / elapsed / 1024 / 1024, sent_delta / elapsed / 1024 / 1024

    @staticmethod
    def get_uptime() -> str:
        seconds = max(0.0, time.time() - psutil.boot_time())
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
            "cpu_temp": None,
            "cpu_usage": 0.0,
            "ram": (0.0, 0.0),
            "swap": (0.0, 0.0),
            "disk": (0.0, 0.0),
            "net": (0.0, 0.0),
            "uptime": "00:00:00",
        }
        # Интервалы считаются по монотонным часам: перевод системного времени
        # не должен замораживать метрики.
        self._last_update_ts: Dict[str, float] = {key: float("-inf") for key in self._METRIC_KEYS}

    def collect(self, prev_net_data: Dict[str, Any], intervals: Dict[str, int]) -> Dict[str, Any]:
        now = time.monotonic()
        for key in self._METRIC_KEYS:
            min_interval = max(1, int(intervals.get(key, 1)))
            if now - self._last_update_ts[key] < min_interval:
                continue
            self._cache[key] = self._collect_metric(key, prev_net_data)
            self._last_update_ts[key] = now
        return dict(self._cache)

    def snapshot(
            self,
            prev_net_data: Dict[str, Any],
            intervals: Dict[str, int],
            keyboard_clicks: Optional[int],
            mouse_clicks: Optional[int],
    ) -> MetricsSnapshot:
        data = self.collect(prev_net_data, intervals)
        ram_used, ram_total = data['ram']
        swap_used, swap_total = data['swap']
        disk_used, disk_total = data['disk']
        net_recv, net_sent = data['net']
        return MetricsSnapshot(
            timestamp=time.time(),
            cpu_temp=data['cpu_temp'],
            cpu_usage=float(data['cpu_usage']),
            ram_used=float(ram_used),
            ram_total=float(ram_total),
            swap_used=float(swap_used),
            swap_total=float(swap_total),
            disk_used=float(disk_used),
            disk_total=float(disk_total),
            net_recv=float(net_recv),
            net_sent=float(net_sent),
            uptime=str(data['uptime']),
            keyboard_clicks=keyboard_clicks,
            mouse_clicks=mouse_clicks,
        )

    @staticmethod
    def _collect_metric(key: str, prev_net_data: Dict[str, Any]) -> Any:
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
