"""Текст окна «Информация о системе»."""
from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path

import psutil

from .constants import APP_NAME, APP_VERSION
from .localization import tr


def detect_cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" in line and line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or tr('unknown_value')


def build_system_info_text(disk_path: str = "/") -> str:
    uname = platform.uname()
    cpu_count = psutil.cpu_count(logical=False) or 0
    cpu_threads = psutil.cpu_count(logical=True) or 0
    cpu_freq = psutil.cpu_freq()
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(disk_path)
    boot_dt = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    gb = 1024 ** 3

    freq_text = tr('unknown_value')
    if cpu_freq and cpu_freq.max:
        freq_text = f"{cpu_freq.max / 1000:.2f} {tr('ghz')}"
    elif cpu_freq and cpu_freq.current:
        freq_text = f"{cpu_freq.current / 1000:.2f} {tr('ghz')}"

    return "\n".join([
        f"{APP_NAME} {tr('version_label')}: {APP_VERSION}",
        "",
        f"{tr('system_label')}: {uname.system} {uname.release}",
        f"{tr('hostname_label')}: {uname.node}",
        f"{tr('architecture_label')}: {uname.machine}",
        "",
        f"{tr('cpu_label')}: {detect_cpu_model()}",
        f"{tr('cores_label')}: {cpu_count}",
        f"{tr('threads_label')}: {cpu_threads}",
        f"{tr('cpu_frequency_label')}: {freq_text}",
        "",
        f"{tr('ram_total_label')}: {ram.total / gb:.2f} {tr('gb')}",
        f"{tr('ram_available_label')}: {ram.available / gb:.2f} {tr('gb')}",
        f"{tr('swap_total_label')}: {swap.total / gb:.2f} {tr('gb')}",
        f"{tr('disk_total_label')} ({disk_path}): {disk.total / gb:.2f} {tr('gb')}",
        f"{tr('disk_free_label')} ({disk_path}): {disk.free / gb:.2f} {tr('gb')}",
        f"{tr('boot_time_label')}: {boot_dt}",
        f"{tr('python_version_label')}: {platform.python_version()}",
    ])
