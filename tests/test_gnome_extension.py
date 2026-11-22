from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "gnome_extension"


def _common_block(variant):
    text = (ROOT / variant / "extension.js").read_text(encoding="utf-8")
    start = text.index("// >>> common")
    end = text.index("// <<< common")
    return text[text.index("\n", start) + 1:end]


def test_both_extension_variants_share_the_same_indicator_code():
    assert _common_block("gnome-42-44") == _common_block("gnome-45")
