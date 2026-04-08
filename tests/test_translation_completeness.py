import re

from app_core.language import LANGUAGES


PLACEHOLDER_RE = re.compile(r"\{\}")


def test_all_languages_have_same_keys_as_english():
    en_keys = set(LANGUAGES['en'].keys())
    for code, lang_map in LANGUAGES.items():
        missing = sorted(en_keys - set(lang_map.keys()))
        extra = sorted(set(lang_map.keys()) - en_keys)
        assert not missing, f"{code}: missing keys: {missing}"
        assert not extra, f"{code}: extra keys: {extra}"


def test_placeholder_counts_match_english():
    en = LANGUAGES['en']
    for code, lang_map in LANGUAGES.items():
        mismatches = []
        for key, en_value in en.items():
            if not isinstance(en_value, str):
                continue
            en_count = len(PLACEHOLDER_RE.findall(en_value))
            other_count = len(PLACEHOLDER_RE.findall(str(lang_map.get(key, ''))))
            if en_count != other_count:
                mismatches.append((key, en_count, other_count))
        assert not mismatches, f"{code}: placeholder mismatches: {mismatches}"
