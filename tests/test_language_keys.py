from app_core.constants import SUPPORTED_LANGS
from app_core.language import LANGUAGES


def test_supported_languages_match_translations():
    assert set(SUPPORTED_LANGS) == set(LANGUAGES.keys())
