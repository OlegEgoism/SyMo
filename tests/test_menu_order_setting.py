from pathlib import Path


def test_menu_order_setting_is_wired_in_app_and_dialog():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')
    dialogs_code = Path('app_core/dialogs.py').read_text(encoding='utf-8')
    constants_code = Path('app_core/constants.py').read_text(encoding='utf-8')

    assert 'MENU_ORDER_DEFAULT = [' in constants_code
    assert "'menu_order': MENU_ORDER_DEFAULT.copy()" in app_code
    assert "default['menu_order'] = self._normalize_menu_order(default.get('menu_order'))" in app_code
    assert "vs['menu_order'] = dialog.get_menu_order()" in app_code

    assert "self.menu_order_view.set_reorderable(True)" in dialogs_code
    assert "def get_menu_order(self) -> list[str]:" in dialogs_code
    assert "def get_menu_visibility(self) -> Dict[str, bool]:" in dialogs_code
    assert "Gtk.ListStore(bool, str, str)" in dialogs_code
