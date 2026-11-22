import string

from app_core.constants import SUPPORTED_LANGS
from app_core.language import LANGUAGES


def _fields(text):
    return [f for _, f, _, _ in string.Formatter().parse(text) if f is not None]


def test_all_languages_have_the_same_keys():
    reference = set(LANGUAGES["ru"])
    for lang, strings in LANGUAGES.items():
        assert set(strings) == reference, lang


def test_placeholders_match_russian():
    for lang, strings in LANGUAGES.items():
        for key, text in strings.items():
            assert len(_fields(text)) == len(_fields(LANGUAGES["ru"][key])), (lang, key)


def test_supported_languages_come_from_the_dictionary():
    assert SUPPORTED_LANGS == list(LANGUAGES)
    assert all(LANGUAGES[code]["language_flag"] for code in SUPPORTED_LANGS)
