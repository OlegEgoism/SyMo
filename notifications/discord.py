from __future__ import annotations

import logging
from typing import Optional

import requests
from requests import Response

from app_core.constants import DISCORD_CONFIG_FILE
from app_core.settings import atomic_write_json, read_json
from notifications.base import normalize_interval, post_with_retries, truncate_message

logger = logging.getLogger(__name__)


class DiscordNotifier:
    MAX_MESSAGE_LENGTH = 2000
    _MAX_SEND_RETRIES = 3
    _MAX_RETRY_AFTER_SEC = 30.0

    def __init__(self, autoload: bool = True):
        self.webhook_url: Optional[str] = None
        self.enabled: bool = False
        self.notification_interval: int = 3600
        if autoload:
            self.load_config()

    def configure(self, webhook_url: str, enabled: bool, interval: int) -> None:
        """Задать параметры в памяти, не трогая файл конфигурации."""
        self.webhook_url = (webhook_url or '').strip() or None
        self.enabled = bool(enabled)
        self.notification_interval = normalize_interval(interval)

    def load_config(self) -> None:
        config = read_json(DISCORD_CONFIG_FILE)
        if config:
            self.configure(
                config.get('DISCORD_WEBHOOK_URL') or '',
                config.get('enabled', False),
                config.get('notification_interval', 3600),
            )

    def save_config(self, webhook_url: str, enabled: bool, interval: int) -> bool:
        self.configure(webhook_url, enabled, interval)
        try:
            atomic_write_json(DISCORD_CONFIG_FILE, {
                'DISCORD_WEBHOOK_URL': self.webhook_url,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval,
            }, mode=0o600)
            return True
        except Exception as e:
            logger.exception("Ошибка сохранения конфигурации Discord: %s", e)
            return False

    def send_message(self, message: str, force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.webhook_url:
            return False
        payload = {
            "content": truncate_message(message, self.MAX_MESSAGE_LENGTH),
            "username": "System Monitor",
        }
        try:
            response = post_with_retries(
                lambda: requests.post(self.webhook_url, json=payload, timeout=(3, 7)),
                channel="Discord",
                max_attempts=self._MAX_SEND_RETRIES,
                retry_after=self._extract_retry_after,
            )
        except Exception as e:
            logger.exception("Ошибка отправки сообщения в Discord: %s", e)
            return False
        if response is None:
            return False
        if response.status_code not in (200, 204):
            logger.error("Ошибка отправки в Discord: HTTP %s", response.status_code)
            return False
        return True

    @classmethod
    def _extract_retry_after(cls, response: Response) -> float:
        try:
            retry_after = float(response.json().get("retry_after", 1.0))
        except (TypeError, ValueError, AttributeError):
            return 1.0
        return max(0.1, min(cls._MAX_RETRY_AFTER_SEC, retry_after))
