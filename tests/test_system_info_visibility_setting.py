from pathlib import Path


def test_show_system_info_setting_is_wired_in_app_and_dialog():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')

    assert "'show_system_info': True" in app_code
    assert "'show_system_info': self.system_info_item" in app_code
    assert "vs['show_system_info'] = dialog.system_info_check.get_active()" in app_code

    assert "self.system_info_check = add_check('system_info', 'show_system_info')" in dialogs_code
