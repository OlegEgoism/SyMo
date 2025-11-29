import json
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "notifications" / "discord.py"


def load_discord_module():
    spec = importlib.util.spec_from_file_location("notifications.discord", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


discord = load_discord_module()


def test_save_config_clamps_interval(tmp_path):
    discord.DISCORD_CONFIG_FILE = tmp_path / "config.json"

    notifier = discord.DiscordNotifier()
    assert notifier.webhook_url is None
    assert notifier.enabled is False

    assert notifier.save_config("  https://example.com/webhook  ", True, 5) is True

    saved = json.loads(discord.DISCORD_CONFIG_FILE.read_text(encoding="utf-8"))
    assert saved["DISCORD_WEBHOOK_URL"] == "https://example.com/webhook"
    assert saved["enabled"] is True
    assert saved["notification_interval"] == 10

    reloaded = discord.DiscordNotifier()
    reloaded.load_config()
    assert reloaded.webhook_url == "https://example.com/webhook"
    assert reloaded.enabled is True
    assert reloaded.notification_interval == 10


def test_send_message_requires_configuration(tmp_path):
    discord.DISCORD_CONFIG_FILE = tmp_path / "config.json"

    notifier = discord.DiscordNotifier()
    assert notifier.send_message("message") is False

    notifier.save_config("", False, 20)
    assert notifier.send_message("message") is False
