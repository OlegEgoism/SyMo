"""Значок в трее со шкалами загрузки CPU и RAM.

Подпись рядом со значком AppIndicator показывает в основном GNOME; в KDE и XFCE её
обычно не видно, а значок виден везде.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional

import cairo

RGB = tuple[float, float, float]
SIZE = 64
# Шаг шкалы: значок меняется не на каждый процент, а ступенями.
STEP = 5
TRACK_RGBA = (0.5, 0.5, 0.5, 0.35)


def quantize(percent: float) -> int:
    return int(min(100, max(0, round(float(percent) / STEP) * STEP)))


def icon_directory() -> Path:
    """Каталог в XDG_RUNTIME_DIR (tmpfs, очищается при выходе из сеанса)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(tempfile.gettempdir()) / f"symo-{os.getuid()}"
    directory = base / "symo-icons"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def render_meter(path: Path, cpu: int, ram: int, cpu_rgb: RGB, ram_rgb: RGB) -> None:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    cr = cairo.Context(surface)
    bar_w, gap, top, bottom = 26, 4, 2, SIZE - 2
    height = bottom - top
    for i, (value, rgb) in enumerate(((cpu, cpu_rgb), (ram, ram_rgb))):
        x = 4 + i * (bar_w + gap)
        cr.set_source_rgba(*TRACK_RGBA)
        cr.rectangle(x, top, bar_w, height)
        cr.fill()
        filled = height * value / 100.0
        cr.set_source_rgb(*rgb)
        cr.rectangle(x, bottom - filled, bar_w, filled)
        cr.fill()
    surface.write_to_png(str(path))


class MeterIcon:
    """Готовит файл значка; путь меняется вместе с картинкой, чтобы панель не брала
    старую картинку из своего кэша."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self._directory = directory
        self._current: Optional[tuple] = None

    def reset(self) -> None:
        self._current = None

    def update(self, cpu: float, ram: float, cpu_rgb: RGB, ram_rgb: RGB) -> Optional[Path]:
        """Путь к новому значку или None, если картинка не изменилась."""
        key = (quantize(cpu), quantize(ram), cpu_rgb, ram_rgb)
        if key == self._current:
            return None
        self._current = key
        if self._directory is None:
            self._directory = icon_directory()
        colors = hashlib.sha1(repr((cpu_rgb, ram_rgb)).encode()).hexdigest()[:8]
        path = self._directory / f"symo-meter-{key[0]}-{key[1]}-{colors}.png"
        if not path.exists():
            render_meter(path, key[0], key[1], cpu_rgb, ram_rgb)
        return path
