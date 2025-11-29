from constants import SUPPORTED_LANGS
from language import LANGUAGES


def test_supported_languages_match_translations():
    assert set(SUPPORTED_LANGS) == set(LANGUAGES.keys())
