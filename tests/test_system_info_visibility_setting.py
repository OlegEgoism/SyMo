from pathlib import Path


def test_show_system_info_setting_is_wired_in_app_and_dialog():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')

    assert "'show_system_info': True" in app_code
    assert "'show_system_info': self.system_info_item" in app_code
    assert "menu_visibility = dialog.get_menu_visibility()" in app_code
    assert "vs.update(menu_visibility)" in app_code

    assert "('system_info', 'show_system_info')" in dialogs_code
    assert "def get_menu_visibility(self) -> Dict[str, bool]:" in dialogs_code
