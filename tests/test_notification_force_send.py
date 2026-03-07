import importlib.util
import sys
import types
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_discord_send_message_force_ignores_enabled(tmp_path, monkeypatch):
    discord = _load_module(
        "notifications.discord",
        Path(__file__).resolve().parents[1] / "notifications" / "discord.py",
    )
    discord.DISCORD_CONFIG_FILE = tmp_path / "discord.json"

    notifier = discord.DiscordNotifier()
    notifier.save_config("https://example.com/webhook", False, 60)

    called = {}

    def fake_post(url, json, timeout):
        called["url"] = url
        called["json"] = json
        called["timeout"] = timeout
        return types.SimpleNamespace(status_code=204)

    monkeypatch.setattr(discord.requests, "post", fake_post)

    assert notifier.send_message("test", force=True) is True
    assert called["url"] == "https://example.com/webhook"


def test_telegram_send_message_force_ignores_enabled(tmp_path, monkeypatch):
    if "gi" not in sys.modules:
        fake_glib = types.SimpleNamespace(idle_add=lambda *args, **kwargs: None)
        fake_repository = types.SimpleNamespace(GLib=fake_glib)
        sys.modules["gi"] = types.SimpleNamespace(repository=fake_repository)
        sys.modules["gi.repository"] = fake_repository

    telegram = _load_module(
        "notifications.telegram",
        Path(__file__).resolve().parents[1] / "notifications" / "telegram.py",
    )
    telegram.TELEGRAM_CONFIG_FILE = tmp_path / "telegram.json"

    notifier = telegram.TelegramNotifier()
    notifier.save_config("token", "100", False, 60)

    called = {}

    def fake_post(url, data, timeout):
        called["url"] = url
        called["data"] = data
        called["timeout"] = timeout
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    assert notifier.send_message("test", force=True) is True
    assert called["url"] == "https://api.telegram.org/bottoken/sendMessage"
