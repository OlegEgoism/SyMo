from pathlib import Path


def test_readme_languages_match_supported_set():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "Arabic" not in readme


def test_telegram_polling_contains_backoff_logic():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "backoff_seconds = 1.0" in code
    assert "backoff_seconds = min(backoff_seconds * 2, 30.0)" in code


def test_uninstall_handles_desktop_name_variants():
    code = Path("uninstall-symo.sh").read_text(encoding="utf-8")
    assert "SyMo.desktop" in code
    assert "symo.desktop" in code
