from app_core.language import LANGUAGES


TRAY_ORDER_KEYS = {
    'tray_order',
    'tray_order_cpu_ram',
    'tray_order_ram_cpu',
    'menu_info_order',
}


def test_tray_order_keys_exist_for_all_languages():
    for code, lang_map in LANGUAGES.items():
        missing = sorted(TRAY_ORDER_KEYS - set(lang_map))
        assert not missing, f"{code}: missing keys {missing}"
