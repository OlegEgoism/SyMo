from pathlib import Path


def test_graph_windows_have_plus_minus_zoom_controls():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "def _build_graph_zoom_controls(self, graph_key: str, area: Gtk.DrawingArea) -> Gtk.Box:" in code
    assert 'zoom_out_button = Gtk.Button(label="-")' in code
    assert 'zoom_in_button = Gtk.Button(label="+")' in code


def test_each_graph_attaches_zoom_controls():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "self._build_graph_zoom_controls('cpu', area)" in code
    assert "self._build_graph_zoom_controls('ram', area)" in code
    assert "self._build_graph_zoom_controls('swap', area)" in code
    assert "self._build_graph_zoom_controls('disk', area)" in code
    assert "self._build_graph_zoom_controls('net', area)" in code
    assert "self._build_graph_zoom_controls('keyboard', area)" in code
    assert "self._build_graph_zoom_controls('mouse', area)" in code
