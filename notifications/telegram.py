from __future__ import annotations

import json
import threading
import time
from typing import Optional, TYPE_CHECKING

import requests
from requests import Response
from gi.repository import GLib

from app_core.constants import TELEGRAM_CONFIG_FILE
from app_core.localization import tr
from app_core.system_usage import SystemUsage
from app_core.click_tracker import get_counts

if TYPE_CHECKING:
    from app_core.power_control import PowerControl


class TelegramNotifier:
    MAX_MESSAGE_LENGTH = 4096
    _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    _MAX_SEND_RETRIES = 3

    def __init__(self):
        self.token: Optional[str] = None
        self.chat_id: Optional[str] = None
        self.enabled: bool = False
        self.notification_interval: int = 3600
        self.last_update_id: int = 0
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_running: bool = False
        self.power_control_ref: Optional["PowerControl"] = None
        self.load_config()

    def load_config(self) -> None:
        try:
            if TELEGRAM_CONFIG_FILE.exists():
                config = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                self.token = (config.get('TELEGRAM_BOT_TOKEN') or '').strip() or None
                self.chat_id = (str(config.get('TELEGRAM_CHAT_ID') or '').strip() or None)
                self.enabled = bool(config.get('enabled', False))
                self.notification_interval = self._normalize_interval(config.get('notification_interval', 3600))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

    def save_config(self, token: str, chat_id: str, enabled: bool, interval: int) -> bool:
        try:
            self.token = token.strip() if token else None
            self.chat_id = chat_id.strip() if chat_id else None
            self.enabled = bool(enabled)
            self.notification_interval = self._normalize_interval(interval)
            TELEGRAM_CONFIG_FILE.write_text(json.dumps({
                'TELEGRAM_BOT_TOKEN': self.token,
                'TELEGRAM_CHAT_ID': self.chat_id,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval
            }, indent=2), encoding="utf-8")
            try:
                import os
                os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации Telegram: {e}")
            return False

    @staticmethod
    def _normalize_interval(interval: object) -> int:
        try:
            value = int(interval)
        except (TypeError, ValueError):
            value = 3600
        return max(10, min(86400, value))

    def send_message(self, message: str, force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.token or not self.chat_id:
            return False

        text = self._truncate_message(message, self.MAX_MESSAGE_LENGTH)
        payload = {'chat_id': self.chat_id, 'text': text, 'parse_mode': 'HTML'}
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        try:
            response = self._post_with_retries(url, payload)
            if response is None:
                return False
            if response.status_code != 200:
                print(f"Ошибка отправки в Telegram: HTTP {response.status_code}")
                return False
            data = response.json()
            if not data.get('ok', False):
                print(f"Ошибка Telegram API: {data.get('description', 'unknown error')}")
                return False
            return True
        except ValueError:
            print("Ошибка отправки в Telegram: некорректный JSON в ответе API")
            return False
        except Exception as e:
            print(f"Ошибка отправки сообщения в Telegram: {e}")
            return False

    @staticmethod
    def _truncate_message(message: str, max_length: int) -> str:
        text = str(message or "")
        if len(text) <= max_length:
            return text
        return text[: max_length - 1] + "…"

    def _post_with_retries(self, url: str, payload: dict[str, str]) -> Optional[Response]:
        backoff_seconds = 1.0
        last_response: Optional[Response] = None
        for _attempt in range(self._MAX_SEND_RETRIES):
            try:
                response = requests.post(url, data=payload, timeout=(3, 7))
                last_response = response
                if response.status_code in self._RETRYABLE_STATUS_CODES:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue
                return response
            except requests.exceptions.RequestException as e:
                print(f"Ошибка связи с Telegram API: {e}")
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 8.0)
        return last_response

    def set_power_control(self, power_control: "PowerControl") -> None:
        self.power_control_ref = power_control

    def start_bot(self) -> None:
        if not self.enabled or not self.token or self.bot_running:
            return

        self.bot_running = True
        self.bot_thread = threading.Thread(target=self._bot_worker, daemon=True)
        self.bot_thread.start()
        print("Telegram бот запущен")

    def stop_bot(self) -> None:
        self.bot_running = False
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=2.0)
        print("Telegram бот остановлен")

    def _bot_worker(self) -> None:
        backoff_seconds = 1.0
        while self.bot_running and self.enabled and self.token:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {'timeout': 30, 'offset': self.last_update_id + 1}
                response = requests.get(url, params=params, timeout=35)

                if response.status_code == 200:
                    data = response.json()
                    if data.get('ok'):
                        for update in data.get('result', []):
                            self.last_update_id = update['update_id']

                            message = update.get('message', {})
                            chat_id = str(message.get('chat', {}).get('id', ''))

                            if chat_id != self.chat_id:
                                continue

                            text = message.get('text', '').strip()

                            if text == '/poweroff' and self.power_control_ref:
                                self.send_message(tr('bot_shutdown_message'))
                                GLib.idle_add(self.power_control_ref._shutdown)

                            elif text == '/reboot' and self.power_control_ref:
                                self.send_message(tr('bot_reboot_message'))
                                GLib.idle_add(self.power_control_ref._reboot)

                            elif text == '/status':
                                self._send_system_status()

                            elif text == '/help':
                                help_text = tr('bot_help_message')
                                self.send_message(help_text)
                    backoff_seconds = 1.0

                elif response.status_code == 409:
                    print("Предупреждение: Другой экземпляр бота уже получает обновления")
                    time.sleep(min(backoff_seconds, 30.0))
                    backoff_seconds = min(backoff_seconds * 2, 30.0)
                else:
                    print(f"Ошибка Telegram getUpdates: HTTP {response.status_code}")
                    time.sleep(min(backoff_seconds, 30.0))
                    backoff_seconds = min(backoff_seconds * 2, 30.0)

            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException as e:
                print(f"Ошибка связи с Telegram API: {e}")
                time.sleep(min(backoff_seconds, 30.0))
                backoff_seconds = min(backoff_seconds * 2, 30.0)
            except Exception as e:
                print(f"Неожиданная ошибка в боте: {e}")
                time.sleep(min(backoff_seconds, 30.0))
                backoff_seconds = min(backoff_seconds * 2, 30.0)

    def _send_system_status(self) -> None:
        try:
            cpu_temp = SystemUsage.get_cpu_temp()
            cpu_usage = SystemUsage.get_cpu_usage()
            ram_used, ram_total = SystemUsage.get_ram_usage()
            disk_used, disk_total = SystemUsage.get_disk_usage()
            swap_used, swap_total = SystemUsage.get_swap_usage()
            uptime = SystemUsage.get_uptime()

            kbd, ms = get_counts()

            status_msg = (
                f"🖥 <b>{tr('system_status')}</b>\n"
                f"🔹 <b>{tr('cpu')}:</b> {cpu_usage:.0f}% ({cpu_temp}{tr('temperature')})\n"
                f"🔹 <b>{tr('ram')}:</b> {ram_used:.1f}/{ram_total:.1f} {tr('gb')}\n"
                f"🔹 <b>{tr('swap')}:</b> {swap_used:.1f}/{swap_total:.1f} {tr('gb')}\n"
                f"🔹 <b>{tr('disk')}:</b> {disk_used:.1f}/{disk_total:.1f} {tr('gb')}\n"
                f"🔹 <b>{tr('uptime')}:</b> {uptime}\n"
                f"🔹 <b>{tr('keyboard')}:</b> {kbd} {tr('presses')}\n"
                f"🔹 <b>{tr('mouse')}:</b> {ms} {tr('clicks')}"
            )

            self.send_message(status_msg)
        except Exception as e:
            self.send_message(f"❌ {tr('error')}: {e}")
