from app_core.language import LANGUAGES


def test_action_label_is_not_empty_for_all_languages():
    for code, lang_map in LANGUAGES.items():
        assert str(lang_map.get("action", "")).strip(), f"{code}: action label must not be empty"


def test_spanish_clicks_translation_is_spanish():
    assert LANGUAGES["es"]["clicks"] == "clics"


def test_chinese_apply_label_has_no_padding_spaces():
    assert LANGUAGES["cn"]["apply_label"] == LANGUAGES["cn"]["apply_label"].strip()
