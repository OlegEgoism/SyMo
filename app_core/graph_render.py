"""Описание графиков и их отрисовка через cairo без GTK: одна и та же картинка
и в окне графика, и в изображении для Telegram."""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Optional, Sequence

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

from .localization import tr
from .system_usage import format_temp

Sample = tuple
RGB = tuple[float, float, float]

BG_RGB: RGB = (0.09, 0.09, 0.09)
GRID_RGB: RGB = (0.2, 0.2, 0.2)
FOOTER_RGB: RGB = (0.75, 0.75, 0.75)
VALUES_RGB: RGB = (0.95, 0.95, 0.95)
TITLE_RGB: RGB = (0.92, 0.92, 0.92)
GRID_LINES = 4
MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 16, 16, 36
TITLE_HEIGHT = 28
# Пауза между точками длиннее этой — сон или остановка опроса: линия прерывается.
GAP_BREAK_SEC = 5.0


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


@dataclass(frozen=True)
class Series:
    color_key: str
    legend: Callable[[], str]
    legend_text_rgb: RGB
    # None — значения нет (например, у процессора нет датчика температуры): разрыв линии.
    value: Callable[[Sample], Optional[float]]
    # Собственный максимум линии (например, температура на шкале процентов CPU).
    max_value: Optional[Callable[[Sequence[Sample]], float]] = None


@dataclass(frozen=True)
class GraphSpec:
    key: str
    title: Callable[[], str]
    series: tuple[Series, ...]
    axis_max: Callable[[Sequence[Sample]], float]
    axis_label: Callable[[float], str]
    axis_label_rgb: RGB
    current_values: Callable[[Sample], str]
    hover_lines: Callable[[Sample], list[str]]
    margin_left: int = 48


def _percent_axis(_samples) -> float:
    return 100.0


def _percent_label(mark: float) -> str:
    return f"{int(round(mark))}%"


def _usage_spec(key: str, title_key: str, color_key: str, axis_rgb: RGB, legend_rgb: RGB) -> GraphSpec:
    return GraphSpec(
        key=key,
        title=lambda: tr(title_key),
        series=(Series(color_key, lambda: f"{tr(title_key)} (%)", legend_rgb, lambda s: s[3]),),
        axis_max=_percent_axis,
        axis_label=_percent_label,
        axis_label_rgb=axis_rgb,
        current_values=lambda s: f"{tr(title_key)}: {s[1]:.1f}/{s[2]:.1f} {tr('gb')} ({s[3]:.0f}%)",
        hover_lines=lambda s: [_fmt_time(s[0]), f"{tr(title_key)}: {s[3]:.1f}%", f"{s[1]:.1f}/{s[2]:.1f} {tr('gb')}"],
    )


def _counter_spec(key: str, title_key: str, color_key: str, legend_rgb: RGB) -> GraphSpec:
    """Клавиатура и мышь: активность в минуту (s[2]), а не счётчик с запуска (s[1])."""
    def per_minute(s: Sample) -> str:
        return f"{s[2]:.0f} {tr('per_minute')}"

    return GraphSpec(
        key=key,
        title=lambda: tr(title_key),
        series=(Series(color_key, lambda: f"{tr(title_key)}, {tr('per_minute')}", legend_rgb, lambda s: s[2]),),
        axis_max=lambda samples: max(1.0, max(s[2] for s in samples)) * 1.05,
        axis_label=lambda mark: f"{int(mark)}",
        axis_label_rgb=(0.85, 0.85, 0.85),
        current_values=lambda s: f"{tr(title_key)}: {per_minute(s)} · {tr('total_label')} {s[1]}",
        hover_lines=lambda s: [_fmt_time(s[0]), f"{tr(title_key)}: {per_minute(s)}", f"{tr('total_label')}: {s[1]}"],
        margin_left=58,
    )


def build_graph_specs() -> Dict[str, GraphSpec]:
    specs = [
        GraphSpec(
            key='cpu',
            title=lambda: tr('cpu_info').strip(),
            series=(
                Series('graph_line_color_cpu', lambda: f"{tr('cpu')} (%)", (0.88, 0.92, 1.0), lambda s: s[1]),
                Series('graph_line_color_temp', lambda: f"{tr('temperature_label')} (°C)", (1.0, 0.88, 0.82),
                       lambda s: s[2],
                       max_value=lambda samples: max(100.0, max((s[2] for s in samples if s[2] is not None),
                                                                default=0.0) + 5.0)),
            ),
            axis_max=_percent_axis,
            axis_label=_percent_label,
            axis_label_rgb=(0.72, 0.82, 0.9),
            current_values=lambda s: f"{tr('cpu')}: {s[1]:.0f}%   {tr('temperature_label')}: {format_temp(s[2], 1)}",
            hover_lines=lambda s: [_fmt_time(s[0]), f"{tr('cpu')}: {s[1]:.1f}%",
                                   f"{tr('temperature_label')}: {format_temp(s[2], 1)}"],
        ),
        _usage_spec('ram', 'ram_loading', 'graph_line_color_ram', (0.72, 0.9, 0.72), (0.9, 1.0, 0.9)),
        _usage_spec('swap', 'swap_loading', 'graph_line_color_swap', (0.9, 0.72, 0.95), (0.98, 0.88, 1.0)),
        _usage_spec('disk', 'disk_loading', 'graph_line_color_disk', (0.7, 0.85, 1.0), (0.88, 0.95, 1.0)),
        GraphSpec(
            key='net',
            title=lambda: tr('lan_speed'),
            series=(
                Series('graph_line_color_net_recv', lambda: f"↓ {tr('mbps')}", (0.85, 1.0, 0.87), lambda s: s[1]),
                Series('graph_line_color_net_sent', lambda: f"↑ {tr('mbps')}", (1.0, 0.94, 0.8), lambda s: s[2]),
            ),
            axis_max=lambda samples: max(1.0, max(max(s[1], s[2]) for s in samples) * 1.15),
            axis_label=lambda mark: f"{mark:.1f}",
            axis_label_rgb=(0.8, 0.8, 0.8),
            current_values=lambda s: f"{tr('lan_speed')}: ↓{s[1]:.1f} / ↑{s[2]:.1f} {tr('mbps')}",
            hover_lines=lambda s: [_fmt_time(s[0]), f"↓ {s[1]:.2f} {tr('mbps')}", f"↑ {s[2]:.2f} {tr('mbps')}"],
            margin_left=58,
        ),
        _counter_spec('keyboard', 'keyboard_clicks', 'graph_line_color_keyboard', (1.0, 0.96, 0.78)),
        _counter_spec('mouse', 'mouse_clicks', 'graph_line_color_mouse', (0.85, 0.98, 1.0)),
    ]
    return {spec.key: spec for spec in specs}


def _layout(cr, text: str, size_px: float, bold: bool = False) -> Pango.Layout:
    # Pango, а не «игрушечный» текст cairo: он подбирает шрифт для любого письма,
    # и иероглифы не превращаются в квадраты.
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string("Sans Bold" if bold else "Sans")
    font.set_absolute_size(size_px * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(text, -1)
    return layout


def text_width(cr, text: str, size_px: float, bold: bool = False) -> float:
    return _layout(cr, text, size_px, bold).get_pixel_size()[0]


def draw_text(cr, text: str, x: float, baseline_y: float, size_px: float, rgb: RGB,
              bold: bool = False, align: str = "left") -> float:
    """Нарисовать строку так, чтобы её базовая линия была на baseline_y; вернуть ширину."""
    layout = _layout(cr, text, size_px, bold)
    width = layout.get_pixel_size()[0]
    if align == "right":
        x -= width
    elif align == "center":
        x -= width / 2
    cr.set_source_rgb(*rgb)
    cr.move_to(x, baseline_y - layout.get_baseline() / Pango.SCALE)
    PangoCairo.show_layout(cr, layout)
    return width


def _x_positions(samples: Sequence[Sample], left: float, plot_w: float) -> list[float]:
    """Координата X по времени точки: сон и пропуски видны как разрывы, а не сжимаются."""
    t0, t1 = samples[0][0], samples[-1][0]
    if t1 - t0 <= 1e-9:
        step = plot_w / max(1, len(samples) - 1)
        return [left + step * i for i in range(len(samples))]
    scale = plot_w / (t1 - t0)
    return [left + (s[0] - t0) * scale for s in samples]


def nearest_index(xs: Sequence[float], x: float) -> int:
    i = bisect.bisect_left(xs, x)
    if i <= 0:
        return 0
    if i >= len(xs):
        return len(xs) - 1
    return i if xs[i] - x < x - xs[i - 1] else i - 1


def render_graph(cr, spec: GraphSpec, samples: Sequence[Sample], width: float, height: float,
                 get_color: Callable[[str], RGB], hover: Optional[tuple[float, float]] = None,
                 title: Optional[str] = None) -> None:
    top = MARGIN_TOP + (TITLE_HEIGHT if title else 0)
    margin_left = spec.margin_left
    plot_w = max(10, width - margin_left - MARGIN_RIGHT)
    plot_h = max(10, height - top - MARGIN_BOTTOM)

    cr.set_source_rgb(*BG_RGB)
    cr.paint()
    if title:
        draw_text(cr, title, margin_left, 22, 16, TITLE_RGB, bold=True)
    cr.set_source_rgb(*GRID_RGB)
    cr.set_line_width(1)
    for i in range(GRID_LINES + 1):
        y = top + plot_h * i / GRID_LINES
        cr.move_to(margin_left, y)
        cr.line_to(margin_left + plot_w, y)
    cr.stroke()

    if not samples:
        draw_text(cr, tr('no_data_yet'), width / 2, max(20, height / 2), 14, (0.78, 0.78, 0.78), align="center")
        return
    if len(samples) == 1:
        samples = [samples[0], samples[0]]

    axis_max = max(1e-9, spec.axis_max(samples))
    for i in range(GRID_LINES + 1):
        y = top + plot_h * i / GRID_LINES
        draw_text(cr, spec.axis_label(axis_max * (1 - i / GRID_LINES)), margin_left - 6, y + 4, 10,
                  spec.axis_label_rgb, align="right")

    xs = _x_positions(samples, margin_left, plot_w)
    drawn = [(series, get_color(series.color_key)) for series in spec.series
             if any(series.value(sample) is not None for sample in samples)]
    for series, color in drawn:
        max_value = max(1e-9, series.max_value(samples) if series.max_value else axis_max)
        cr.set_source_rgb(*color)
        cr.set_line_width(2)
        line_started = False
        prev_ts = None
        for x, sample in zip(xs, samples):
            value = series.value(sample)
            if value is None or (prev_ts is not None and sample[0] - prev_ts > GAP_BREAK_SEC):
                line_started = False
            prev_ts = sample[0]
            if value is None:
                continue
            y = top + plot_h * (1.0 - min(value, max_value) / max_value)
            if line_started:
                cr.line_to(x, y)
            else:
                cr.move_to(x, y)
                line_started = True
        cr.stroke()

    legend_y = top - 4 if title else 12
    legend_x = float(margin_left)
    for series, color in drawn:
        cr.set_source_rgb(*color)
        cr.rectangle(legend_x, legend_y - 8, 12, 8)
        cr.fill()
        legend_x += 18 + draw_text(cr, series.legend(), legend_x + 18, legend_y, 12, series.legend_text_rgb) + 24
    draw_text(cr, spec.current_values(samples[-1]), width - MARGIN_RIGHT, legend_y, 12, VALUES_RGB, align="right")

    if hover is not None:
        _draw_hover(cr, spec, samples, xs, hover, width, height, top, margin_left + plot_w, top + plot_h)

    draw_text(cr, f"◀ {_fmt_time(samples[0][0])}", margin_left, height - 10, 11, FOOTER_RGB)
    draw_text(cr, f"{_fmt_time(samples[-1][0])} ▶", width - MARGIN_RIGHT, height - 10, 11, FOOTER_RGB, align="right")


def _draw_hover(cr, spec: GraphSpec, samples: Sequence[Sample], xs: Sequence[float], hover: tuple[float, float],
                width: float, height: float, top: float, right: float, bottom: float) -> None:
    hover_x = max(0.0, min(float(width), hover[0]))
    hover_y = max(0.0, min(float(height), hover[1]))
    if hover_x < xs[0] - 1 or hover_x > right or hover_y < top or hover_y > bottom:
        return
    idx = nearest_index(xs, hover_x)
    lines = spec.hover_lines(samples[idx])
    if not lines:
        return

    cr.set_source_rgba(1.0, 1.0, 1.0, 0.22)
    cr.set_line_width(1)
    cr.move_to(xs[idx], top)
    cr.line_to(xs[idx], bottom)
    cr.stroke()

    padding, line_height = 6, 14
    box_w = max(text_width(cr, line, 11) for line in lines) + padding * 2
    box_h = line_height * len(lines) + padding * 2
    box_x = max(4.0, min(hover_x + 12, max(4.0, width - box_w - 4)))
    box_y = max(4.0, min(hover_y + 12, max(4.0, height - box_h - 4)))
    cr.set_source_rgba(0.05, 0.05, 0.05, 0.88)
    cr.rectangle(box_x, box_y, box_w, box_h)
    cr.fill()
    for i, line in enumerate(lines):
        draw_text(cr, line, box_x + padding, box_y + padding + line_height * (i + 1) - 3, 11, (0.96, 0.96, 0.96))
