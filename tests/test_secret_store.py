import json

import pytest

from app_core import secret_store
from notifications import discord, telegram


@pytest.fixture
def keyring(monkeypatch):
    vault = {}
    monkeypatch.setattr(secret_store, "available", lambda: True)
    monkeypatch.setattr(secret_store, "store", lambda key, value: vault.__setitem__(key, value) or True)
    monkeypatch.setattr(secret_store, "lookup", lambda key: vault.get(key))
    monkeypatch.setattr(secret_store, "clear", lambda key: vault.pop(key, None))
    return vault


def test_plaintext_token_moves_to_the_keyring(tmp_path, monkeypatch, keyring):
    path = tmp_path / "tg.json"
    monkeypatch.setattr(telegram, "TELEGRAM_CONFIG_FILE", path)
    path.write_text(json.dumps({"TELEGRAM_BOT_TOKEN": "123:secret", "TELEGRAM_CHAT_ID": "1", "enabled": True}))
    notifier = telegram.TelegramNotifier()
    assert notifier.token == "123:secret"
    data = json.loads(path.read_text())
    assert data["TELEGRAM_BOT_TOKEN"] is None and data["TELEGRAM_BOT_TOKEN_in_keyring"] is True
    assert "123:secret" not in path.read_text() and keyring == {"telegram_bot_token": "123:secret"}
    assert telegram.TelegramNotifier().token == "123:secret"


def test_webhook_in_keyring_and_cleared(tmp_path, monkeypatch, keyring):
    path = tmp_path / "dc.json"
    monkeypatch.setattr(discord, "DISCORD_CONFIG_FILE", path)
    notifier = discord.DiscordNotifier(autoload=False)
    assert notifier.save_config("https://discord.com/api/webhooks/1/x", True, 60)
    assert "webhooks" not in path.read_text() and discord.DiscordNotifier().webhook_url.endswith("/x")
    assert notifier.save_config("", False, 60)
    assert keyring == {} and json.loads(path.read_text())["DISCORD_WEBHOOK_URL"] is None


def test_without_keyring_the_file_keeps_the_value(tmp_path, monkeypatch):
    path = tmp_path / "tg.json"
    monkeypatch.setattr(telegram, "TELEGRAM_CONFIG_FILE", path)
    assert telegram.TelegramNotifier(autoload=False).save_config("123:secret", "1", True, 60)
    assert json.loads(path.read_text())["TELEGRAM_BOT_TOKEN"] == "123:secret"
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_keyring_entry_means_no_token(tmp_path, monkeypatch, keyring):
    path = tmp_path / "tg.json"
    monkeypatch.setattr(telegram, "TELEGRAM_CONFIG_FILE", path)
    path.write_text(json.dumps({"TELEGRAM_BOT_TOKEN": None, "TELEGRAM_BOT_TOKEN_in_keyring": True}))
    assert telegram.TelegramNotifier().token is None
