from app_core.language import LANGUAGES


def test_menu_order_keys_exist_for_all_languages():
    required = {
        'menu_order_title',
        'display_section',
        'logging_section',
        'notification_section',
        'graph_history_minutes',
        'graph_history_hint',
    }
    for lang_code, lang_map in LANGUAGES.items():
        missing = required - set(lang_map.keys())
        assert not missing, f"{lang_code} missing keys: {sorted(missing)}"
