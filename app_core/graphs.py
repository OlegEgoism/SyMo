"""Окна графиков метрик. Все графики описываются декларативно через GraphSpec
и рисуются одним классом GraphWindow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Optional, Sequence

from gi.repository import Gdk, Gtk

from .graph_math import ZOOM_STEP, ZoomState, decimate_samples, hover_index, visible_samples
from .localization import tr

Sample = tuple
RGB = tuple[float, float, float]

BG_RGB: RGB = (0.09, 0.09, 0.09)
GRID_RGB: RGB = (0.2, 0.2, 0.2)
FOOTER_RGB: RGB = (0.75, 0.75, 0.75)
VALUES_RGB: RGB = (0.95, 0.95, 0.95)
GRID_LINES = 4
MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 16, 16, 36


def text_width(text_extents) -> float:
    """Ширина текста из cairo text_extents: объект с .width или кортеж, где ширина — [2]."""
    width = getattr(text_extents, "width", None)
    if width is not None:
        return float(width)
    try:
        return float(text_extents[2])
    except Exception:
        return 0.0


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


@dataclass(frozen=True)
class Series:
    color_key: str
    legend: Callable[[], str]
    legend_text_rgb: RGB
    value: Callable[[Sample], float]
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
    return GraphSpec(
        key=key,
        title=lambda: tr(title_key),
        series=(Series(color_key, lambda: tr(title_key), legend_rgb, lambda s: s[1]),),
        axis_max=lambda samples: max(1, max(s[1] for s in samples)) * 1.05,
        axis_label=lambda mark: f"{int(mark)}",
        axis_label_rgb=(0.85, 0.85, 0.85),
        current_values=lambda s: f"{tr(title_key)}: {s[1]}",
        hover_lines=lambda s: [_fmt_time(s[0]), f"{tr(title_key)}: {s[1]}"],
        margin_left=58,
    )


def build_graph_specs() -> Dict[str, GraphSpec]:
    specs = [
        GraphSpec(
            key='cpu',
            title=lambda: tr('cpu_info'),
            series=(
                Series('graph_line_color_cpu', lambda: f"{tr('cpu')} (%)", (0.88, 0.92, 1.0), lambda s: s[1]),
                Series('graph_line_color_temp', lambda: tr('temperature'), (1.0, 0.88, 0.82), lambda s: s[2],
                       max_value=lambda samples: max(100.0, max(s[2] for s in samples) + 5.0)),
            ),
            axis_max=_percent_axis,
            axis_label=_percent_label,
            axis_label_rgb=(0.72, 0.82, 0.9),
            current_values=lambda s: f"{tr('cpu')}: {s[1]:.0f}%   {tr('temperature')}: {s[2]:.1f}°C",
            hover_lines=lambda s: [_fmt_time(s[0]), f"{tr('cpu')}: {s[1]:.1f}%", f"{tr('temperature')}: {s[2]:.1f}°C"],
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


class GraphWindow:
    """Окно одного графика с зумом колесом, панорамированием и подсказкой под курсором."""

    def __init__(
            self,
            spec: GraphSpec,
            get_samples: Callable[[], list[Sample]],
            get_color: Callable[[str], RGB],
            show_zoom_controls: bool,
            on_destroy: Callable[["GraphWindow"], None],
    ) -> None:
        self.spec = spec
        self._get_samples = get_samples
        self._get_color = get_color
        self._on_destroy = on_destroy
        self.zoom = ZoomState()

        self.window = Gtk.Window()
        self.window.set_default_size(720, 380)
        self.window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(680, 320)
        self.area.connect("draw", self._on_draw)
        self._connect_events()
        if show_zoom_controls:
            box.pack_start(self._build_zoom_controls(), False, False, 0)
        box.pack_start(self.area, True, True, 0)

        self.window.add(box)
        self.window.connect("destroy", lambda *_: self._on_destroy(self))
        self.refresh_texts()
        self.window.show_all()

    def present(self) -> None:
        self.window.present()

    def is_visible(self) -> bool:
        return self.window.get_visible()

    def refresh_texts(self) -> None:
        self.window.set_title(f"{self.spec.title()} — {tr('system_status')}")
        self.queue_draw()

    def queue_draw(self) -> None:
        self.area.queue_draw()

    def destroy(self) -> None:
        self.window.destroy()

    def zoom_by(self, factor: float, anchor_ratio: float = 0.5) -> None:
        if self.zoom.zoom(factor, anchor_ratio):
            self.queue_draw()

    def reset_zoom(self) -> None:
        self.zoom.reset()
        self.queue_draw()

    def _build_zoom_controls(self) -> Gtk.Box:
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_halign(Gtk.Align.END)
        buttons = (
            ("-", tr('zoom_out'), lambda *_: self.zoom_by(1 / ZOOM_STEP)),
            ("+", tr('zoom_in'), lambda *_: self.zoom_by(ZOOM_STEP)),
            ("↻", tr('reset_zoom'), lambda *_: self.reset_zoom()),
        )
        for label, tooltip, handler in buttons:
            btn = Gtk.Button(label=label)
            btn.set_tooltip_text(tooltip)
            btn.set_size_request(28, 24)
            btn.connect("clicked", handler)
            controls.pack_start(btn, False, False, 0)
        return controls

    def _connect_events(self) -> None:
        area = self.area
        area.set_events(
            area.get_events()
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        area.connect('scroll-event', self._on_scroll)
        area.connect('button-press-event', self._on_button_press)
        area.connect('motion-notify-event', self._on_motion)
        area.connect('button-release-event', self._on_button_release)
        area.connect('leave-notify-event', self._on_leave)

    def _on_scroll(self, widget, event) -> bool:
        width = max(1, widget.get_allocated_width())
        anchor_ratio = max(0.0, min(float(width), float(getattr(event, 'x', width / 2)))) / width
        factor = 1.0
        if event.direction == Gdk.ScrollDirection.UP:
            factor = ZOOM_STEP
        elif event.direction == Gdk.ScrollDirection.DOWN:
            factor = 1 / ZOOM_STEP
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            delta_y = float(getattr(event, 'delta_y', 0.0))
            factor = ZOOM_STEP if delta_y < 0 else (1 / ZOOM_STEP if delta_y > 0 else 1.0)
        if factor == 1.0:
            return False
        self.zoom_by(factor, anchor_ratio)
        return True

    def _on_button_press(self, _widget, event) -> bool:
        if event.button != Gdk.BUTTON_PRIMARY:
            return False
        self.zoom.dragging = True
        self.zoom.last_x = float(getattr(event, 'x', 0.0))
        return True

    def _on_button_release(self, _widget, event) -> bool:
        if event.button != Gdk.BUTTON_PRIMARY:
            return False
        self.zoom.dragging = False
        return True

    def _on_motion(self, widget, event) -> bool:
        self.zoom.hovering = True
        self.zoom.hover_x = float(getattr(event, 'x', 0.0))
        self.zoom.hover_y = float(getattr(event, 'y', 0.0))
        if not self.zoom.dragging:
            widget.queue_draw()
            return False
        if self.zoom.pan_to(self.zoom.hover_x, widget.get_allocated_width()):
            widget.queue_draw()
            return True
        return False

    def _on_leave(self, widget, _event) -> bool:
        self.zoom.hovering = False
        widget.queue_draw()
        return False

    def _on_draw(self, widget, cr) -> None:
        spec = self.spec
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        margin_left = spec.margin_left
        plot_w = max(10, width - margin_left - MARGIN_RIGHT)
        plot_h = max(10, height - MARGIN_TOP - MARGIN_BOTTOM)

        cr.set_source_rgb(*BG_RGB)
        cr.paint()
        cr.set_source_rgb(*GRID_RGB)
        for i in range(GRID_LINES + 1):
            y = MARGIN_TOP + plot_h * i / GRID_LINES
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        samples = decimate_samples(visible_samples(self._get_samples(), self.zoom), max(200, width * 2))
        if not samples:
            self._draw_no_data(cr, width, height)
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        axis_max = max(1e-9, spec.axis_max(samples))
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(*spec.axis_label_rgb)
        for i in range(GRID_LINES + 1):
            y = MARGIN_TOP + plot_h * i / GRID_LINES
            label = spec.axis_label(axis_max * (1 - i / GRID_LINES))
            cr.move_to(max(2, margin_left - text_width(cr.text_extents(label)) - 6), y + 4)
            cr.show_text(label)

        step_x = plot_w / (len(samples) - 1)
        colors = [self._get_color(series.color_key) for series in spec.series]
        for series, color in zip(spec.series, colors):
            max_value = max(1e-9, series.max_value(samples) if series.max_value else axis_max)
            cr.set_source_rgb(*color)
            cr.set_line_width(2)
            for idx, sample in enumerate(samples):
                x = margin_left + step_x * idx
                y = MARGIN_TOP + plot_h * (1.0 - series.value(sample) / max_value)
                if idx == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()

        cr.set_font_size(12)
        legend_x = float(margin_left)
        for series, color in zip(spec.series, colors):
            legend = series.legend()
            cr.set_source_rgb(*color)
            cr.rectangle(legend_x, 4, 12, 8)
            cr.fill()
            cr.set_source_rgb(*series.legend_text_rgb)
            cr.move_to(legend_x + 18, 12)
            cr.show_text(legend)
            legend_x += 18 + text_width(cr.text_extents(legend)) + 24

        values_text = spec.current_values(samples[-1])
        cr.set_source_rgb(*VALUES_RGB)
        cr.move_to(width - MARGIN_RIGHT - text_width(cr.text_extents(values_text)), 12)
        cr.show_text(values_text)

        self._draw_hover(cr, width, height, samples, margin_left, plot_w, plot_h)

        cr.set_source_rgb(*FOOTER_RGB)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {_fmt_time(samples[0][0])}")
        end_text = f"{_fmt_time(samples[-1][0])} ▶"
        cr.move_to(width - MARGIN_RIGHT - text_width(cr.text_extents(end_text)), height - 10)
        cr.show_text(end_text)

    @staticmethod
    def _draw_no_data(cr, width: int, height: int) -> None:
        message = tr('no_data_yet')
        cr.set_source_rgb(*BG_RGB)
        cr.paint()
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(14)
        cr.set_source_rgb(0.78, 0.78, 0.78)
        cr.move_to(max(8, (width - text_width(cr.text_extents(message))) / 2), max(20, height / 2))
        cr.show_text(message)

    def _draw_hover(self, cr, width: int, height: int, samples: list[Sample],
                    left: float, plot_w: float, plot_h: float) -> None:
        state = self.zoom
        if not state.hovering or not samples:
            return
        hover_x = max(0.0, min(float(width), state.hover_x))
        hover_y = max(0.0, min(float(height), state.hover_y))
        top, right, bottom = MARGIN_TOP, left + plot_w, MARGIN_TOP + plot_h
        if hover_x < left or hover_x > right or hover_y < top or hover_y > bottom:
            return

        idx = hover_index(hover_x, left, plot_w, len(samples))
        point_x = left if len(samples) <= 1 else left + plot_w * idx / (len(samples) - 1)
        lines = self.spec.hover_lines(samples[idx])
        if not lines:
            return

        cr.set_source_rgba(1.0, 1.0, 1.0, 0.22)
        cr.set_line_width(1)
        cr.move_to(point_x, top)
        cr.line_to(point_x, bottom)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(11)
        padding, line_height = 6, 14
        max_w = max(text_width(cr.text_extents(line)) for line in lines)
        box_w = max_w + padding * 2
        box_h = line_height * len(lines) + padding * 2
        box_x = max(4.0, min(hover_x + 12, max(4.0, width - box_w - 4)))
        box_y = max(4.0, min(hover_y + 12, max(4.0, height - box_h - 4)))

        cr.set_source_rgba(0.05, 0.05, 0.05, 0.88)
        cr.rectangle(box_x, box_y, box_w, box_h)
        cr.fill()
        cr.set_source_rgb(0.96, 0.96, 0.96)
        for i, line in enumerate(lines):
            cr.move_to(box_x + padding, box_y + padding + line_height * (i + 1) - 3)
            cr.show_text(line)
