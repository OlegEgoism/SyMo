"""Потокобезопасная история метрик для графиков в окнах и в Telegram."""
from __future__ import annotations

import threading
from collections import deque
from typing import Deque, Dict, Tuple

from .system_usage import MetricsSnapshot

# Формат сэмплов по ключам:
#   cpu:              (ts, usage_percent, temp_celsius или None)
#   ram / swap / disk: (ts, used_gb, total_gb, percent)
#   net:              (ts, recv_mbps, sent_mbps)
#   keyboard / mouse: (ts, count, per_minute); нет сэмплов, пока счётчики недоступны
HISTORY_KEYS = ('cpu', 'ram', 'swap', 'disk', 'net', 'keyboard', 'mouse')
RATE_KEYS = ('keyboard', 'mouse')

Sample = Tuple[float, ...]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _usage_sample(ts: float, used: object, total: object) -> Sample:
    used_f = _to_float(used)
    total_f = _to_float(total)
    percent = (used_f / total_f * 100.0) if total_f > 0 else 0.0
    return ts, used_f, total_f, _clamp(percent, 0.0, 100.0)


def samples_from_snapshot(snapshot: MetricsSnapshot) -> Dict[str, Sample]:
    ts = snapshot.timestamp
    temp = None if snapshot.cpu_temp is None else _clamp(_to_float(snapshot.cpu_temp), 0.0, 150.0)
    samples = {
        'cpu': (ts, _clamp(_to_float(snapshot.cpu_usage), 0.0, 100.0), temp),
        'ram': _usage_sample(ts, snapshot.ram_used, snapshot.ram_total),
        'swap': _usage_sample(ts, snapshot.swap_used, snapshot.swap_total),
        'disk': _usage_sample(ts, snapshot.disk_used, snapshot.disk_total),
        'net': (ts, max(0.0, _to_float(snapshot.net_recv)), max(0.0, _to_float(snapshot.net_sent))),
    }
    # Скорость в минуту досчитывает MetricsHistory: для неё нужен предыдущий сэмпл.
    if snapshot.keyboard_clicks is not None:
        samples['keyboard'] = (ts, max(0, int(snapshot.keyboard_clicks)), 0.0)
    if snapshot.mouse_clicks is not None:
        samples['mouse'] = (ts, max(0, int(snapshot.mouse_clicks)), 0.0)
    return samples


def _with_rate(sample: Sample, previous: Sample | None) -> Sample:
    """Нажатий в минуту между предыдущим и текущим сэмплом счётчика."""
    if previous is None:
        return sample
    ts, count = sample[0], sample[1]
    elapsed = ts - previous[0]
    if elapsed <= 0:
        return ts, count, previous[2]
    return ts, count, max(0, count - previous[1]) / elapsed * 60.0


class MetricsHistory:
    """Кольцевые буферы по каждой метрике.

    Пишет главный поток, читает ещё и поток Telegram-бота, поэтому доступ
    защищён блокировкой, а наружу отдаются копии.
    """

    def __init__(self, maxlen: int) -> None:
        self._lock = threading.Lock()
        self._maxlen = max(1, int(maxlen))
        self._data: Dict[str, Deque[Sample]] = {key: deque(maxlen=self._maxlen) for key in HISTORY_KEYS}

    @property
    def maxlen(self) -> int:
        return self._maxlen

    def append_snapshot(self, snapshot: MetricsSnapshot) -> None:
        samples = samples_from_snapshot(snapshot)
        with self._lock:
            for key, sample in samples.items():
                buf = self._data[key]
                if key in RATE_KEYS:
                    sample = _with_rate(sample, buf[-1] if buf else None)
                buf.append(sample)

    def samples(self, key: str) -> list[Sample]:
        with self._lock:
            buf = self._data.get(key)
            return list(buf) if buf is not None else []

    def resize(self, maxlen: int) -> None:
        maxlen = max(1, int(maxlen))
        with self._lock:
            if maxlen == self._maxlen:
                return
            self._maxlen = maxlen
            self._data = {key: deque(buf, maxlen=maxlen) for key, buf in self._data.items()}
