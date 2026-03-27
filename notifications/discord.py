from __future__ import annotations

import json
import time
from typing import Optional

import requests
from requests import Response

from app_core.constants import DISCORD_CONFIG_FILE


class DiscordNotifier:
    MAX_MESSAGE_LENGTH = 2000
    _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    _MAX_SEND_RETRIES = 3

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
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

    def save_config(self, webhook_url: str, enabled: bool, interval: int) -> bool:
        try:
            self.webhook_url = (webhook_url or '').strip() or None
            self.enabled = bool(enabled)
            self.notification_interval = self._normalize_interval(interval)
            DISCORD_CONFIG_FILE.write_text(json.dumps({
                'DISCORD_WEBHOOK_URL': self.webhook_url,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval
            }, indent=2), encoding="utf-8")
            try:
                import os
                os.chmod(DISCORD_CONFIG_FILE, 0o600)
            except Exception as e:
                print(f"Ошибка: {e}")
            return True
        except Exception as e:
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
            payload = {
                "content": self._truncate_message(message, self.MAX_MESSAGE_LENGTH),
                "username": "System Monitor",
            }
            response = self._post_with_retries(payload)
            if response is None:
                return False
            if response.status_code not in (200, 204):
                print(f"Ошибка отправки в Discord: HTTP {response.status_code}")
                return False
            return True
        except Exception as e:
            print(f"Ошибка отправки сообщения в Discord: {e}")
            return False

    @staticmethod
    def _truncate_message(message: str, max_length: int) -> str:
        text = str(message or "")
        if len(text) <= max_length:
            return text
        return text[: max_length - 1] + "…"

    def _post_with_retries(self, payload: dict[str, str]) -> Optional[Response]:
        backoff_seconds = 1.0
        last_response: Optional[Response] = None
        for _attempt in range(self._MAX_SEND_RETRIES):
            try:
                response = requests.post(self.webhook_url, json=payload, timeout=(3, 7))
                last_response = response
                if response.status_code == 429:
                    retry_after = self._extract_retry_after(response)
                    time.sleep(max(0.1, retry_after))
                    continue
                if response.status_code in self._RETRYABLE_STATUS_CODES:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue
                return response
            except requests.exceptions.RequestException as e:
                print(f"Ошибка связи с Discord API: {e}")
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 8.0)
        return last_response

    @staticmethod
    def _extract_retry_after(response: Response) -> float:
        try:
            data = response.json()
            retry_after = float(data.get("retry_after", 1.0))
            return max(0.1, retry_after)
        except (TypeError, ValueError, AttributeError):
            return 1.0
