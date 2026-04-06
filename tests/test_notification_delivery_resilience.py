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


def test_discord_send_message_retries_on_rate_limit(tmp_path, monkeypatch):
    discord = _load_module(
        "notifications.discord",
        Path(__file__).resolve().parents[1] / "notifications" / "discord.py",
    )
    discord.DISCORD_CONFIG_FILE = tmp_path / "discord.json"
    notifier = discord.DiscordNotifier()
    notifier.save_config("https://example.com/webhook", True, 60)

    attempts = {"count": 0}

    def fake_post(url, json, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return types.SimpleNamespace(status_code=429, json=lambda: {"retry_after": 0})
        return types.SimpleNamespace(status_code=204, json=lambda: {})

    monkeypatch.setattr(discord.requests, "post", fake_post)
    monkeypatch.setattr(discord.time, "sleep", lambda *_args, **_kwargs: None)

    assert notifier.send_message("ok") is True
    assert attempts["count"] == 2


def test_telegram_send_message_checks_ok_flag(tmp_path, monkeypatch):
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
    notifier.save_config("token", "100", True, 60)

    def fake_post(_url, _data, _timeout):
        return types.SimpleNamespace(status_code=200, json=lambda: {"ok": False, "description": "Bad Request"})

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    assert notifier.send_message("ok") is False


def test_telegram_send_photo_checks_ok_flag(tmp_path, monkeypatch):
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
    notifier.save_config("token", "100", True, 60)

    photo = tmp_path / "screen.png"
    photo.write_bytes(b"png")

    def fake_post(_url, _data, _files, _timeout):
        return types.SimpleNamespace(status_code=200, json=lambda: {"ok": False, "description": "Bad Request"})

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    assert notifier.send_photo(str(photo), "caption") is False


def test_capture_screenshot_uses_gdk_path_first(tmp_path, monkeypatch):
    if "gi" not in sys.modules:
        fake_glib = types.SimpleNamespace(idle_add=lambda *args, **kwargs: None)
        fake_repository = types.SimpleNamespace(GLib=fake_glib)
        sys.modules["gi"] = types.SimpleNamespace(repository=fake_repository)
        sys.modules["gi.repository"] = fake_repository

    telegram = _load_module(
        "notifications.telegram",
        Path(__file__).resolve().parents[1] / "notifications" / "telegram.py",
    )
    notifier = telegram.TelegramNotifier()

    def fake_gdk_capture(path):
        Path(path).write_bytes(b"ok")
        return True

    monkeypatch.setattr(notifier, "_capture_screenshot_with_gdk", fake_gdk_capture)
    monkeypatch.setattr(telegram.shutil, "which", lambda _name: None)

    path = notifier._capture_screenshot_to_temp()
    assert path is not None
    assert Path(path).exists()
    Path(path).unlink(missing_ok=True)
