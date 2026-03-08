from pathlib import Path


def test_show_system_info_setting_is_wired_in_app_and_dialog():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')

    assert "'show_system_info': True" in app_code
    assert "visibility_settings.get('show_system_info', True)" in app_code
    assert "vs['show_system_info'] = dialog.system_info_check.get_active()" in app_code

    assert "self.system_info_check = add_check('system_info', 'show_system_info')" in dialogs_code


def test_tray_order_and_queue_settings_are_wired_in_app_and_dialog():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')

    assert "'tray_display_order': ['cpu', 'ram']" in app_code
    assert "'tray_cycle_enabled': False" in app_code
    assert "vs['tray_display_order'] = parse_tray_order_text(dialog.tray_order_entry.get_text())" in app_code
    assert "vs['tray_cycle_enabled'] = dialog.tray_cycle_check.get_active()" in app_code

    assert "self.tray_cycle_check = Gtk.CheckButton(label=tr('tray_cycle_enabled'))" in dialogs_code
    assert "self.tray_order_entry = Gtk.Entry()" in dialogs_code
