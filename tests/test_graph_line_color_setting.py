from pathlib import Path


def test_graph_line_color_setting_is_persisted_and_exposed_in_settings_dialog():
    app_code = Path("app_core/app.py").read_text(encoding="utf-8")
    dialogs_code = Path("app_core/dialogs.py").read_text(encoding="utf-8")

    assert "'graph_line_color': '#36c7ed'" in app_code
    assert "default['graph_line_color'] = self._sanitize_graph_line_color(default.get('graph_line_color'))" in app_code
    assert "vs['graph_line_color'] = self._sanitize_graph_line_color(dialog.get_graph_line_color())" in app_code

    assert "self.graph_line_color_button = Gtk.ColorButton()" in dialogs_code
    assert "def get_graph_line_color(self) -> str:" in dialogs_code


def test_telegram_graph_renderer_uses_configured_graph_line_color():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")

    assert "def _graph_line_color_rgb(self) -> tuple[float, float, float]:" in code
    assert "cr.set_source_rgb(*self._graph_line_color_rgb())" in code
    assert "graph_line_color" in code
