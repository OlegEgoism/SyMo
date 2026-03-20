from __future__ import annotations

import json
import os
from typing import Optional

import requests

from app_core.constants import DISCORD_CONFIG_FILE


class DiscordNotifier:
    def __init__(self):
        self.webhook_url: Optional[str] = None
        self.enabled: bool = False
        self.notification_interval: int = 3600
        self.load_config()

    def load_config(self) -> None:
        try:
            if DISCORD_CONFIG_FILE.exists():
                config = json.loads(DISCORD_CONFIG_FILE.read_text(encoding="utf-8"))
                self.webhook_url = (config.get('DISCORD_WEBHOOK_URL') or '').strip() or None
                self.enabled = bool(config.get('enabled', False))
                self.notification_interval = self._normalize_interval(config.get('notification_interval', 3600))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

    def save_config(self, webhook_url: str, enabled: bool, interval: int) -> bool:
        try:
            self.webhook_url = (webhook_url or '').strip() or None
            self.enabled = bool(enabled)
            self.notification_interval = self._normalize_interval(interval)
            DISCORD_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            config_payload = json.dumps({
                'DISCORD_WEBHOOK_URL': self.webhook_url,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval
            }, indent=2)
            temp_path = DISCORD_CONFIG_FILE.with_suffix(DISCORD_CONFIG_FILE.suffix + ".tmp")
            temp_path.write_text(config_payload, encoding="utf-8")
            temp_path.replace(DISCORD_CONFIG_FILE)
            os.chmod(DISCORD_CONFIG_FILE, 0o600)
            return True
        except OSError as e:
            print(f"Ошибка сохранения конфигурации Discord: {e}")
            return False

    @staticmethod
    def _normalize_interval(interval: object) -> int:
        try:
            value = int(interval)
        except (TypeError, ValueError):
            value = 3600
        return max(10, min(86400, value))

    def send_message(self, message: str, force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.webhook_url:
            return False
        try:
            payload = {"content": message, "username": "System Monitor"}
            r = requests.post(self.webhook_url, json=payload, timeout=(3, 7))
            return r.status_code in (200, 204)
        except Exception as e:
            print(f"Ошибка отправки сообщения в Discord: {e}")
            return False
