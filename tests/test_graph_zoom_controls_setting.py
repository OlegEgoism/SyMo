from pathlib import Path


def test_zoom_controls_setting_defaults_to_true():
    app_code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "'show_graph_zoom_controls': True" in app_code


def test_settings_dialog_exposes_zoom_controls_toggle():
    dialogs_code = Path("app_core/dialogs.py").read_text(encoding="utf-8")
    assert "self.show_zoom_controls_check = Gtk.CheckButton(label=tr('show_graph_zoom_controls'))" in dialogs_code
    assert "self.show_zoom_controls_check.set_active(self.visibility_settings.get('show_graph_zoom_controls', True))" in dialogs_code
    graph_history_idx = dialogs_code.index("logging_card_content.add(graph_history_box)")
    zoom_toggle_idx = dialogs_code.index("logging_card_content.add(self.show_zoom_controls_check)")
    assert graph_history_idx < zoom_toggle_idx


def test_zoom_controls_setting_saved_from_dialog():
    app_code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "vs['show_graph_zoom_controls'] = dialog.show_zoom_controls_check.get_active()" in app_code
    assert "if self.visibility_settings.get('show_graph_zoom_controls', True):" in app_code
