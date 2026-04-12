from pathlib import Path


def test_graph_line_color_setting_is_persisted_and_exposed_in_settings_dialog():
    app_code = Path("app_core/app.py").read_text(encoding="utf-8")
    dialogs_code = Path("app_core/dialogs.py").read_text(encoding="utf-8")

    assert "'graph_line_color_cpu': '#19ccff'" in app_code
    assert "'graph_line_color_temp': '#ff6633'" in app_code
    assert "'graph_line_color_mouse': '#66e6ff'" in app_code
    assert "for color_key, color_value in dialog.get_graph_line_colors().items():" in app_code

    assert "self.graph_line_color_buttons: dict[str, Gtk.ColorButton] = {}" in dialogs_code
    assert "def get_graph_line_colors(self) -> Dict[str, str]:" in dialogs_code
    assert "graph_colors_card, graph_colors_content = card(tr('graph_colors_title'))" in dialogs_code
    assert "graph_colors_info = Gtk.Label(label=tr('graph_colors_info'))" in dialogs_code
    assert "self.set_default_size(760, 600)" in dialogs_code


def test_telegram_graph_renderer_uses_configured_graph_line_color():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")

    assert "def _graph_line_color_rgb(self, metric: str) -> tuple[float, float, float]:" in code
    assert "cr.set_source_rgb(*self._graph_line_color_rgb(metric))" in code
    assert '"temp": "graph_line_color_temp"' in code
    assert '"mouse": "graph_line_color_mouse"' in code
