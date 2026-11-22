"""Окно графика метрики: зум колесом, панорамирование и подсказка под курсором.
Сам график рисует graph_render — так же, как изображение для Telegram."""
from __future__ import annotations

from typing import Callable

from gi.repository import Gdk, Gtk

from .graph_math import ZOOM_STEP, ZoomState, decimate_samples, visible_samples
from .graph_render import RGB, GraphSpec, Sample, build_graph_specs, render_graph
from .localization import tr

__all__ = ["GraphWindow", "build_graph_specs"]


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
        width = widget.get_allocated_width()
        samples = decimate_samples(visible_samples(self._get_samples(), self.zoom), max(200, width * 2))
        hover = (self.zoom.hover_x, self.zoom.hover_y) if self.zoom.hovering else None
        render_graph(cr, self.spec, samples, width, widget.get_allocated_height(), self._get_color, hover=hover)
