from pathlib import Path


def test_graph_windows_have_plus_minus_zoom_controls():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "def _build_graph_zoom_controls(self, graph_key: str, area: Gtk.DrawingArea) -> Gtk.Box:" in code
    assert 'zoom_out_button = Gtk.Button(label="-")' in code
    assert "zoom_out_button.set_tooltip_text(tr('zoom_out'))" in code
    assert 'zoom_reset_button = Gtk.Button(label="↻")' in code
    assert "zoom_reset_button.set_tooltip_text(tr('reset_zoom'))" in code
    assert 'zoom_in_button = Gtk.Button(label="+")' in code
    assert "zoom_in_button.set_tooltip_text(tr('zoom_in'))" in code
    assert "btn.set_size_request(28, 24)" in code
    assert "def _reset_graph_zoom(self, graph_key: str, area: Optional[Gtk.DrawingArea] = None) -> None:" in code


def test_each_graph_attaches_zoom_controls():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "def _maybe_add_graph_zoom_controls(self, box: Gtk.Box, graph_key: str, area: Gtk.DrawingArea) -> None:" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'cpu', area)" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'ram', area)" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'swap', area)" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'disk', area)" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'net', area)" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'keyboard', area)" in code
    assert "self._maybe_add_graph_zoom_controls(box, 'mouse', area)" in code


def test_zoom_control_order_is_minus_plus_then_reset():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    minus_idx = code.index("controls.pack_start(zoom_out_button, False, False, 0)")
    plus_idx = code.index("controls.pack_start(zoom_in_button, False, False, 0)")
    reset_idx = code.index("controls.pack_start(zoom_reset_button, False, False, 0)")
    assert minus_idx < plus_idx < reset_idx
