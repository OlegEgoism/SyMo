from app_core.language import LANGUAGES


def test_menu_order_keys_exist_for_all_languages():
    required = {'menu_order_title', 'menu_order_hint'}
    for lang_code, lang_map in LANGUAGES.items():
        missing = required - set(lang_map.keys())
        assert not missing, f"{lang_code} missing keys: {sorted(missing)}"
