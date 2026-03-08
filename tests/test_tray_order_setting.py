from pathlib import Path


def test_tray_order_setting_is_saved_and_applied():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')

    assert "'tray_info_order': ['cpu', 'ram']" in app_code
    assert "vs['tray_info_order'] = self._normalize_tray_order(dialog.get_tray_info_order())" in app_code
    assert "for metric in order:" in app_code
    assert "if metric == 'cpu' and self.visibility_settings.get('tray_cpu', True):" in app_code
    assert "if metric == 'ram' and self.visibility_settings.get('tray_ram', True):" in app_code


    assert "'info_menu_order': ['cpu', 'ram', 'swap', 'disk', 'net', 'keyboard_clicks', 'mouse_clicks', 'uptime']" in app_code
    assert "vs['info_menu_order'] = self._normalize_info_menu_order(dialog.get_info_menu_order())" in app_code
    assert "order = self._normalize_info_menu_order(self.visibility_settings.get('info_menu_order'))" in app_code
    assert "if self.visibility_settings.get(key, True):" in app_code

    assert "self.info_order_list = Gtk.ListBox()" in dialogs_code
    assert "def get_info_menu_order(self) -> list[str]:" in dialogs_code
    assert "def _move_info_order_up(self, _btn) -> None:" in dialogs_code
    assert "def _move_info_order_down(self, _btn) -> None:" in dialogs_code
    assert "self.tray_order_combo = Gtk.ComboBoxText()" in dialogs_code
    assert "self.tray_order_combo.append('cpu_ram', tr('tray_order_cpu_ram'))" in dialogs_code
    assert "self.tray_order_combo.append('ram_cpu', tr('tray_order_ram_cpu'))" in dialogs_code
    assert "def get_tray_info_order(self) -> list[str]:" in dialogs_code
