import json
import importlib.util
import sys
import types
from pathlib import Path

from app_core import localization


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_discord_load_config_handles_invalid_interval(tmp_path):
    discord = _load_module(
        "notifications.discord",
        Path(__file__).resolve().parents[1] / "notifications" / "discord.py",
    )
    discord.DISCORD_CONFIG_FILE = tmp_path / "discord.json"
    discord.DISCORD_CONFIG_FILE.write_text(
        json.dumps({
            "DISCORD_WEBHOOK_URL": "https://example.com/hook",
            "enabled": True,
            "notification_interval": "broken",
        }),
        encoding="utf-8",
    )

    notifier = discord.DiscordNotifier()

    assert notifier.webhook_url == "https://example.com/hook"
    assert notifier.enabled is True
    assert notifier.notification_interval == 3600


def test_telegram_load_config_handles_invalid_interval(tmp_path):
    if 'gi' not in sys.modules:
        fake_glib = types.SimpleNamespace(idle_add=lambda *args, **kwargs: None)
        fake_repository = types.SimpleNamespace(GLib=fake_glib)
        sys.modules['gi'] = types.SimpleNamespace(repository=fake_repository)
        sys.modules['gi.repository'] = fake_repository

    telegram = _load_module(
        "notifications.telegram",
        Path(__file__).resolve().parents[1] / "notifications" / "telegram.py",
    )
    telegram.TELEGRAM_CONFIG_FILE = tmp_path / "telegram.json"
    telegram.TELEGRAM_CONFIG_FILE.write_text(
        json.dumps({
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "100",
            "enabled": True,
            "notification_interval": "broken",
        }),
        encoding="utf-8",
    )

    notifier = telegram.TelegramNotifier()

    assert notifier.token == "test-token"
    assert notifier.chat_id == "100"
    assert notifier.enabled is True
    assert notifier.notification_interval == 3600


def test_set_language_falls_back_to_russian_for_invalid_value():
    prev_lang = localization.get_language()
    try:
        localization.set_language("de")
        assert localization.get_language() == "de"

        localization.set_language("unsupported-lang")
        assert localization.get_language() == "ru"
    finally:
        localization.set_language(prev_lang)
