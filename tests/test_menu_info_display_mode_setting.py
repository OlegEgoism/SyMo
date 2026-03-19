from pathlib import Path


def test_menu_info_display_mode_setting_is_wired_in_app_and_dialog():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')
    language_code = Path('app_core/language.py').read_text(encoding='utf-8')

    assert "'info_display_mode': 'detailed'" in app_code
    assert "default['info_display_mode'] = self._sanitize_info_display_mode(default.get('info_display_mode'))" in app_code
    assert "vs['info_display_mode'] = dialog.get_info_display_mode()" in app_code
    assert "if normalized in {'detailed', 'compact'} else 'detailed'" in app_code

    assert "self.info_mode_combo = Gtk.ComboBoxText()" in dialogs_code
    assert "self.info_mode_combo.append('detailed', tr('menu_info_mode_detailed'))" in dialogs_code
    assert "self.info_mode_combo.append('compact', tr('menu_info_mode_compact'))" in dialogs_code
    assert "def get_info_display_mode(self) -> str:" in dialogs_code

    assert "'menu_info_display_mode'" in language_code
    assert "'menu_info_mode_detailed'" in language_code
    assert "'menu_info_mode_compact'" in language_code
