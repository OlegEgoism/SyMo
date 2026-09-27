"""Чистая (без GTK) логика графиков: зум, панорамирование, выборка точек."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")

ZOOM_MIN = 1.0
ZOOM_MAX = 40.0
ZOOM_STEP = 1.2


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


@dataclass
class ZoomState:
    """Видимое окно графика: scale — кратность зума, center — центр окна в долях [0..1]."""

    scale: float = 1.0
    center: float = 1.0
    dragging: bool = False
    last_x: float = 0.0
    hovering: bool = False
    hover_x: float = 0.0
    hover_y: float = 0.0

    def reset(self) -> None:
        self.scale = 1.0
        self.center = 1.0
        self.dragging = False

    def zoom(self, factor: float, anchor_ratio: float = 0.5) -> bool:
        """Изменить масштаб, удерживая точку под anchor_ratio на месте. True, если что-то изменилось."""
        old_scale = clamp(self.scale, ZOOM_MIN, ZOOM_MAX)
        new_scale = clamp(old_scale * factor, ZOOM_MIN, ZOOM_MAX)
        if abs(new_scale - old_scale) < 1e-9:
            return False

        old_span = 1.0 / old_scale
        new_span = 1.0 / new_scale
        old_center = clamp(self.center, 0.0, 1.0)
        old_left = clamp(old_center - old_span / 2, 0.0, max(0.0, 1.0 - old_span))
        anchor = clamp(float(anchor_ratio), 0.0, 1.0)
        anchor_global = old_left + anchor * old_span

        new_left = clamp(anchor_global - anchor * new_span, 0.0, max(0.0, 1.0 - new_span))
        self.scale = new_scale
        self.center = clamp(new_left + new_span / 2, 0.0, 1.0)
        return True

    def pan_to(self, x: float, width: float) -> bool:
        """Сдвинуть окно при перетаскивании мышью до координаты x. True, если нужно перерисовать."""
        width = max(1.0, float(width))
        span = 1.0 / clamp(self.scale, ZOOM_MIN, ZOOM_MAX)
        current_x = clamp(float(x), 0.0, width)
        if span >= 1.0:
            self.last_x = current_x
            return False
        prev_x = clamp(self.last_x, 0.0, width)
        self.last_x = current_x
        new_center = clamp(self.center, 0.0, 1.0) - ((current_x - prev_x) / width) * span
        self.center = clamp(new_center, span / 2, 1.0 - span / 2)
        return True


def visible_samples(samples: Sequence[T], state: ZoomState) -> list[T]:
    samples = list(samples)
    if len(samples) <= 2:
        return samples
    scale = clamp(state.scale, ZOOM_MIN, ZOOM_MAX)
    if scale <= 1.0:
        return samples

    total = len(samples)
    window_len = max(2, int(round(total / scale)))
    # Левая граница окна в долях; окно у правого края включает последнюю точку.
    left = clamp(state.center, 0.0, 1.0) - 0.5 / scale
    start = int(round(left * total))
    start = min(max(0, start), max(0, total - window_len))
    return samples[start:start + window_len]


def decimate_samples(samples: Sequence[T], max_points: int) -> list[T]:
    """Равномерно проредить точки, чтобы ограничить стоимость отрисовки."""
    samples = list(samples)
    if max_points <= 0 or len(samples) <= max_points:
        return samples
    if max_points == 1:
        return [samples[-1]]
    step = (len(samples) - 1) / float(max_points - 1)
    last = len(samples) - 1
    return [samples[min(last, int(round(idx * step)))] for idx in range(max_points)]


def hover_index(hover_x: float, left: float, plot_w: float, count: int) -> int:
    if count <= 1:
        return 0
    ratio = clamp((hover_x - left) / max(1.0, plot_w), 0.0, 1.0)
    return max(0, min(count - 1, int(round(ratio * (count - 1)))))
