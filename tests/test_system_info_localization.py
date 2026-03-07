from app_core.language import LANGUAGES


SYSTEM_INFO_KEYS = {
    'system_info',
    'system_info_title',
    'system_info_error',
    'unknown_value',
    'system_label',
    'hostname_label',
    'architecture_label',
    'cpu_label',
    'cores_label',
    'threads_label',
    'cpu_frequency_label',
    'ram_total_label',
}


def test_system_info_keys_exist_for_all_languages():
    for code, lang_map in LANGUAGES.items():
        missing = sorted(SYSTEM_INFO_KEYS - set(lang_map))
        assert not missing, f"{code}: missing keys {missing}"


def test_system_info_strings_are_localized_for_non_english_languages():
    en = LANGUAGES['en']
    for code, lang_map in LANGUAGES.items():
        if code == 'en':
            continue
        assert lang_map['system_info'] != en['system_info'], code
        assert lang_map['system_info_title'] != en['system_info_title'], code
        assert lang_map['system_info_error'] != en['system_info_error'], code
        assert lang_map['unknown_value'] != en['unknown_value'], code


def test_french_uptime_is_french():
    assert LANGUAGES['fr']['uptime'] == 'Temps de fonctionnement'
