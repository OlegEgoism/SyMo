from __future__ import annotations

import os
import json
import time
import signal
import locale
import threading
import subprocess
from enum import Enum
from datetime import timedelta
from pathlib import Path
from typing import Dict, Tuple, Optional

import psutil
import requests
from pynput import keyboard, mouse

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# --- AppIndicator / Ayatana fallback ---
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppInd  # type: ignore

# --- i18n (внешний модуль) ---
from language import LANGUAGES  # noqa: E402

# -----------------------
# Константы и пути
# -----------------------
SUPPORTED_LANGS = ['ru', 'en', 'cn', 'de', 'it', 'es', 'tr', 'fr']
APP_ID = "SystemMonitor"
APP_NAME = "SyMo"
ICON_FALLBACK = "system-run-symbolic"
TIME_UPDATE_SEC = 1  # частота обновления UI/логики

HOME = Path.home()
LOG_FILE = HOME / ".symo_log.txt"
SETTINGS_FILE = HOME / ".symo_settings.json"
TELEGRAM_CONFIG_FILE = HOME / ".symo_telegram.json"
DISCORD_CONFIG_FILE = HOME / ".symo_discord.json"

# -----------------------
# Глобальные счётчики
# -----------------------
_clicks_lock = threading.Lock()
keyboard_clicks = 0
mouse_clicks = 0

# -----------------------
# Язык
# -----------------------
current_lang = 'ru'


def tr(key: str) -> str:
    """Локализация: берём карту текущего языка, иначе EN; при отсутствии ключа возвращаем сам ключ."""
    lang_map = LANGUAGES.get(current_lang) or LANGUAGES.get('en', {})
    return lang_map.get(key, key)


def detect_system_language() -> str:
    try:
        env = os.environ.get('LANG', '')
        if env:
            code = env.split('.')[0].split('_')[0].lower()
            return code if code in SUPPORTED_LANGS else 'ru'
        code = (locale.getlocale()[0] or '').split('_')[0].lower()
        return code if code in SUPPORTED_LANGS else 'ru'
    except Exception:
        return 'ru'


def rotate_log_if_needed(max_size_bytes: int) -> None:
    """Простейшая ротация: если лог > max_size_bytes — переименовать в .1 (перезаписать .1 при наличии)."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > max_size_bytes:
            bak = LOG_FILE.with_suffix(LOG_FILE.suffix + ".1")
            try:
                if bak.exists():
                    bak.unlink()
            except Exception:
                pass
            LOG_FILE.rename(bak)
    except Exception as e:
        print("Ошибка ротации лога:", e)


# -----------------------
# Система
# -----------------------
class SystemUsage:
    @staticmethod
    def get_cpu_temp() -> int:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return 0

            # Популярные ключи
            preferred_keys = ('coretemp', 'k10temp', 'cpu-thermal', 'soc_thermal', 'acpitz')
            for key in preferred_keys:
                arr = temps.get(key)
                if arr:
                    # Ищем Package id / Tctl
                    for t in arr:
                        label = (getattr(t, 'label', '') or '').lower()
                        if label.startswith('package') or label.startswith('tctl'):
                            return int(t.current)
                    return int(arr[0].current)

            # Фоллбек на первый сенсор
            first_list = next(iter(temps.values()))
            return int(first_list[0].current) if first_list else 0
        except Exception:
            return 0

    @staticmethod
    def get_cpu_usage() -> float:
        return psutil.cpu_percent()

    @staticmethod
    def get_ram_usage() -> Tuple[float, float]:
        m = psutil.virtual_memory()
        return m.used / (1024 ** 3), m.total / (1024 ** 3)

    @staticmethod
    def get_swap_usage() -> Tuple[float, float]:
        s = psutil.swap_memory()
        return s.used / (1024 ** 3), s.total / (1024 ** 3)

    @staticmethod
    def get_disk_usage() -> Tuple[float, float]:
        d = psutil.disk_usage('/')
        return d.used / (1024 ** 3), d.total / (1024 ** 3)

    @staticmethod
    def get_network_speed(prev_data: Dict[str, float]) -> Tuple[float, float]:
        net = psutil.net_io_counters()
        now = time.time()
        elapsed = max(0.0001, now - prev_data['time'])

        # обработка возможного «сброса» счётчиков
        recv_delta = max(0, net.bytes_recv - prev_data['recv'])
        sent_delta = max(0, net.bytes_sent - prev_data['sent'])

        recv_speed = recv_delta / elapsed / 1024 / 1024
        sent_speed = sent_delta / elapsed / 1024 / 1024

        prev_data['recv'] = net.bytes_recv
        prev_data['sent'] = net.bytes_sent
        prev_data['time'] = now
        return recv_speed, sent_speed

    @staticmethod
    def get_uptime() -> str:
        seconds = time.time() - psutil.boot_time()
        return str(timedelta(seconds=int(seconds)))


# -----------------------
# Нотификаторы
# -----------------------
class TelegramNotifier:
    def __init__(self):
        self.token: Optional[str] = None
        self.chat_id: Optional[str] = None
        self.enabled: bool = False
        self.notification_interval: int = 3600
        self.last_update_id: int = 0
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_running: bool = False
        self.power_control_ref: Optional[PowerControl] = None
        self.load_config()

    def load_config(self) -> None:
        try:
            if TELEGRAM_CONFIG_FILE.exists():
                config = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                self.token = (config.get('TELEGRAM_BOT_TOKEN') or '').strip() or None
                self.chat_id = (str(config.get('TELEGRAM_CHAT_ID') or '').strip() or None)
                self.enabled = bool(config.get('enabled', False))
                self.notification_interval = int(config.get('notification_interval', 3600))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

    def save_config(self, token: str, chat_id: str, enabled: bool, interval: int) -> bool:
        try:
            self.token = token.strip() if token else None
            self.chat_id = chat_id.strip() if chat_id else None
            self.enabled = bool(enabled)
            self.notification_interval = int(max(10, min(86400, interval)))
            TELEGRAM_CONFIG_FILE.write_text(json.dumps({
                'TELEGRAM_BOT_TOKEN': self.token,
                'TELEGRAM_CHAT_ID': self.chat_id,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval
            }, indent=2), encoding="utf-8")
            try:
                os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации Telegram: {e}")
            return False

    def send_message(self, message: str) -> bool:
        if not self.enabled or not self.token or not self.chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {'chat_id': self.chat_id, 'text': message, 'parse_mode': 'HTML'}
            r = requests.post(url, data=payload, timeout=(3, 7))
            return r.status_code == 200
        except Exception as e:
            print(f"Ошибка отправки сообщения в Telegram: {e}")
            return False

    def set_power_control(self, power_control: PowerControl) -> None:
        """Установить ссылку на PowerControl для выполнения команд"""
        self.power_control_ref = power_control

    def start_bot(self) -> None:
        """Запустить фоновый поток для обработки команд бота"""
        if not self.enabled or not self.token or self.bot_running:
            return

        self.bot_running = True
        self.bot_thread = threading.Thread(target=self._bot_worker, daemon=True)
        self.bot_thread.start()
        print("Telegram бот запущен")

    def stop_bot(self) -> None:
        """Остановить бота"""
        self.bot_running = False
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=2.0)
        print("Telegram бот остановлен")

    def _bot_worker(self) -> None:
        """Фоновый обработчик команд Telegram бота"""
        while self.bot_running and self.enabled and self.token:
            try:
                # Получаем обновления
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {'timeout': 30, 'offset': self.last_update_id + 1}
                response = requests.get(url, params=params, timeout=35)

                if response.status_code == 200:
                    data = response.json()
                    if data.get('ok'):
                        for update in data.get('result', []):
                            self.last_update_id = update['update_id']

                            # Проверяем, что сообщение от авторизованного чата
                            message = update.get('message', {})
                            chat_id = str(message.get('chat', {}).get('id', ''))

                            if chat_id != self.chat_id:
                                continue

                            text = message.get('text', '').strip()

                            if text == '/poweroff' and self.power_control_ref:
                                self.send_message(tr('bot_shutdown_message'))
                                # Выполняем в главном потоке GTK
                                GLib.idle_add(self.power_control_ref._shutdown)

                            elif text == '/reboot' and self.power_control_ref:
                                self.send_message(tr('bot_reboot_message'))
                                # Выполняем в главном потоке GTK
                                GLib.idle_add(self.power_control_ref._reboot)

                            elif text == '/status':
                                # Отправляем текущий статус системы
                                self._send_system_status()

                            elif text == '/help':
                                help_text = tr('bot_help_message')
                                self.send_message(help_text)

                elif response.status_code == 409:
                    # Конфликт - другой экземпляр бота уже запущен
                    print("Предупреждение: Другой экземпляр бота уже получает обновления")
                    # time.sleep(10)

            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException as e:
                print(f"Ошибка связи с Telegram API: {e}")
                # time.sleep(10)
            except Exception as e:
                print(f"Неожиданная ошибка в боте: {e}")
                # time.sleep(5)

    def _send_system_status(self) -> None:
        """Отправить текущий статус системы"""
        try:
            cpu_temp = SystemUsage.get_cpu_temp()
            cpu_usage = SystemUsage.get_cpu_usage()
            ram_used, ram_total = SystemUsage.get_ram_usage()
            disk_used, disk_total = SystemUsage.get_disk_usage()
            swap_used, swap_total = SystemUsage.get_swap_usage()
            uptime = SystemUsage.get_uptime()

            with _clicks_lock:
                kbd, ms = keyboard_clicks, mouse_clicks

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
                self.notification_interval = int(config.get('notification_interval', 3600))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

    def save_config(self, webhook_url: str, enabled: bool, interval: int) -> bool:
        try:
            self.webhook_url = (webhook_url or '').strip() or None
            self.enabled = bool(enabled)
            self.notification_interval = int(max(10, min(86400, interval)))
            DISCORD_CONFIG_FILE.write_text(json.dumps({
                'DISCORD_WEBHOOK_URL': self.webhook_url,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval
            }, indent=2), encoding="utf-8")
            try:
                os.chmod(DISCORD_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации Discord: {e}")
            return False

    def send_message(self, message: str) -> bool:
        if not self.enabled or not self.webhook_url:
            return False
        try:
            payload = {"content": message, "username": "System Monitor"}
            r = requests.post(self.webhook_url, json=payload, timeout=(3, 7))
            return r.status_code in (200, 204)
        except Exception as e:
            print(f"Ошибка отправки сообщения в Discord: {e}")
            return False


# -----------------------
# Power control
# -----------------------
class Action(Enum):
    POWER_OFF = "power_off"
    REBOOT = "reboot"
    LOCK = "lock"


def action_label(act: Action) -> str:
    return {
        Action.POWER_OFF: tr('power_off'),
        Action.REBOOT: tr('reboot'),
        Action.LOCK: tr('lock'),
    }.get(act, act.value)


class PowerControl:
    def __init__(self, app: "SystemTrayApp"):
        self.app = app
        self.scheduled_action: Optional[Action] = None
        self.remaining_seconds = 0
        self._update_timer_id = None
        self._notify_timer_id = None
        self._action_timer_id = None
        self.current_dialog: Optional[Gtk.MessageDialog] = None
        self.parent_window: Optional[Gtk.Widget] = None

    def set_parent_window(self, parent: Optional[Gtk.Widget]) -> None:
        self.parent_window = parent if (parent and parent.get_mapped()) else None

    def _open_dialog(self, message: str, title: str = "", info: bool = True) -> Gtk.MessageDialog:
        if self.current_dialog:
            try:
                self.current_dialog.destroy()
            except Exception:
                pass
            self.current_dialog = None
        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.INFO if info else Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK if info else Gtk.ButtonsType.OK_CANCEL,
            text=message
        )
        if title:
            dialog.set_title(title)
        self.current_dialog = dialog
        return dialog

    def _confirm_action(self, _w, action_callback, message: str):
        dialog = self._open_dialog(message, tr('confirm_title'), info=False)

        def on_response(d, response_id):
            if response_id == Gtk.ResponseType.OK and action_callback:
                action_callback()
            d.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()

    def _shutdown(self) -> None:
        """Выключение системы"""
        try:
            if os.system("loginctl poweroff") != 0:
                os.system("systemctl poweroff")
        except Exception as e:
            print(f"Ошибка выключения: {e}")

    def _reboot(self) -> None:
        """Перезагрузка системы"""
        try:
            if os.system("loginctl reboot") != 0:
                os.system("systemctl reboot")
        except Exception as e:
            print(f"Ошибка перезагрузки: {e}")

    @staticmethod
    def _lock_screen() -> None:
        for c in ("loginctl lock-session",
                  "gnome-screensaver-command -l",
                  "xdg-screensaver lock",
                  "dm-tool lock"):
            if os.system(c) == 0:
                return

    def _open_settings(self, *_):
        # Диалог настроек таймера
        dialog = Gtk.Dialog(
            title=tr('settings'),
            transient_for=self.parent_window,
            flags=0
        )
        self.current_dialog = dialog
        box = dialog.get_content_area()
        box.set_border_width(10)

        # Время (минуты)
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_label = Gtk.Label(label=tr('minutes'));
        time_label.set_xalign(0)
        adjustment = Gtk.Adjustment(value=1, lower=1, upper=1440, step_increment=1)
        time_spin = Gtk.SpinButton();
        time_spin.set_adjustment(adjustment);
        time_spin.set_numeric(True)
        time_spin.set_value(1);
        time_spin.set_size_request(150, -1)
        time_box.pack_start(time_label, True, True, 0)
        time_box.pack_start(time_spin, False, False, 0)

        # Действие
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_label_w = Gtk.Label(label=tr('action'));
        action_label_w.set_xalign(0)
        action_combo = Gtk.ComboBoxText()
        action_combo.append(Action.POWER_OFF.value, action_label(Action.POWER_OFF))
        action_combo.append(Action.REBOOT.value, action_label(Action.REBOOT))
        action_combo.append(Action.LOCK.value, action_label(Action.LOCK))
        action_combo.set_active(0)
        action_combo.set_size_request(150, -1)
        action_box.pack_start(action_label_w, True, True, 0)
        action_box.pack_start(action_combo, False, False, 0)

        # Кнопки
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)
        apply_b = Gtk.Button(label=tr('apply'))
        cancel_b = Gtk.Button(label=tr('cancel'))
        reset_b = Gtk.Button(label=tr('reset'))
        apply_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.OK))
        cancel_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.CANCEL))
        reset_b.connect("clicked", self._reset_action_button)
        btn_box.pack_start(reset_b, False, False, 0)
        btn_box.pack_start(cancel_b, False, False, 0)
        btn_box.pack_start(apply_b, False, False, 0)

        # Верстка
        box.add(time_box)
        box.add(action_box)
        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.add(btn_box)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            minutes = time_spin.get_value_as_int()
            action_id = action_combo.get_active_id()
            if minutes <= 0:
                self._show_message(tr('error'), tr('error_minutes_positive'))
                dialog.destroy()
                self.current_dialog = None
                return
            act = Action(action_id)
            self.scheduled_action = act
            self.remaining_seconds = minutes * 60

            if minutes > 1:
                self._notify_timer_id = GLib.timeout_add_seconds(
                    (minutes - 1) * 60, self._notify_before_action, act
                )
            self._action_timer_id = GLib.timeout_add_seconds(
                self.remaining_seconds, self._delayed_action, act
            )
            if self._update_timer_id:
                GLib.source_remove(self._update_timer_id)
            self._update_timer_id = GLib.timeout_add_seconds(1, self._update_indicator_label)

            self._show_message(tr('scheduled'), tr('action_in_time').format(action_label(act), minutes))

        dialog.destroy()
        self.current_dialog = None

    def _reset_action_button(self, *_):
        for tid in ("_update_timer_id", "_notify_timer_id", "_action_timer_id"):
            _id = getattr(self, tid, None)
            if _id:
                GLib.source_remove(_id)
                setattr(self, tid, None)
        self.scheduled_action = None
        self.remaining_seconds = 0
        self.app.indicator.set_label("", "")
        self._show_message(tr('cancelled'), tr('cancelled_text'))

    def _notify_before_action(self, act: Action) -> bool:
        self._notify_timer_id = None
        self._show_message(tr('notification'), tr('action_in_1_min').format(action_label(act)))
        return False

    def _update_indicator_label(self) -> bool:
        if self.remaining_seconds <= 0:
            self.app.indicator.set_label("", "")
            return False
        h = self.remaining_seconds // 3600
        m = (self.remaining_seconds % 3600) // 60
        s = self.remaining_seconds % 60
        self.app.indicator.set_label(f"  {action_label(self.scheduled_action)} — {h:02d}:{m:02d}:{s:02d}", "")
        self.remaining_seconds -= 1
        return True

    def _delayed_action(self, act: Action) -> bool:
        self._action_timer_id = None
        self.app.indicator.set_label("", "")
        self.scheduled_action = None
        self.remaining_seconds = 0
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id)
            self._update_timer_id = None
        if act == Action.POWER_OFF:
            self._shutdown()
        elif act == Action.REBOOT:
            self._reboot()
        elif act == Action.LOCK:
            self._lock_screen()
        return False

    def _show_message(self, title: str, message: str):
        d = self._open_dialog(message, title, info=True)
        d.run()
        d.destroy()
        self.current_dialog = None


# -----------------------
# Диалог настроек
# -----------------------
class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Optional[Gtk.Widget], visibility: Dict):
        super().__init__(title=tr('settings_label'),
                         transient_for=parent if (parent and parent.get_mapped()) else None,
                         flags=0)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL,
                         tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility

        box = self.get_content_area()
        box.set_border_width(10)

        # Шапка
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_halign(Gtk.Align.END)
        link = Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ")
        header.pack_start(link, False, False, 0)
        box.add(header)

        # Чекбоксы видимости
        def add_check(label_key: str, key: str):
            chk = Gtk.CheckButton(label=tr(label_key))
            chk.set_active(self.visibility_settings.get(key, True))
            box.add(chk)
            return chk

        self.tray_cpu_check = add_check('cpu_tray', 'tray_cpu')
        self.tray_ram_check = add_check('ram_tray', 'tray_ram')
        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self.cpu_check = add_check('cpu_info', 'cpu')
        self.ram_check = add_check('ram_loading', 'ram')
        self.swap_check = add_check('swap_loading', 'swap')
        self.disk_check = add_check('disk_loading', 'disk')
        self.net_check = add_check('lan_speed', 'net')
        self.uptime_check = add_check('uptime_label', 'uptime')
        self.keyboard_check = add_check('keyboard_clicks', 'keyboard_clicks')
        self.mouse_check = add_check('mouse_clicks', 'mouse_clicks')

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.power_off_check = add_check('power_off', 'show_power_off')
        self.reboot_check = add_check('reboot', 'show_reboot')
        self.lock_check = add_check('lock', 'show_lock')
        self.timer_check = add_check('settings', 'show_timer')

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.ping_check = add_check('ping_network', 'ping_network')

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        # Логирование
        logging_box = Gtk.Box(spacing=6)
        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        self.logging_check.set_margin_bottom(3)
        logging_box.pack_start(self.logging_check, False, False, 0)

        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        self.download_button.set_margin_bottom(3)
        logging_box.pack_end(self.download_button, False, False, 0)
        box.add(logging_box)

        logsize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        logsize_label = Gtk.Label(label=tr('max_log_size_mb'));
        logsize_label.set_xalign(0)
        self.logsize_spin = Gtk.SpinButton.new_with_range(1, 1024, 1)
        self.logsize_spin.set_value(int(self.visibility_settings.get('max_log_mb', 5)))
        logsize_box.pack_start(logsize_label, False, False, 0)
        logsize_box.pack_start(self.logsize_spin, False, False, 0)
        box.add(logsize_box)

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Telegram
        telegram_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.telegram_enable_check = Gtk.CheckButton(label=tr('telegram_notification'))
        telegram_box.pack_start(self.telegram_enable_check, False, False, 0)
        test_button = Gtk.Button(label=tr('check_telegram'))
        test_button.set_halign(Gtk.Align.END)
        test_button.connect("clicked", self.test_telegram)
        telegram_box.pack_end(test_button, False, False, 0)
        box.add(telegram_box)

        token_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        token_label = Gtk.Label(label=tr('token_bot'));
        token_label.set_xalign(0)
        self.token_entry = Gtk.Entry();
        self.token_entry.set_placeholder_text("123...:ABC...")
        self.token_entry.set_visibility(False)
        token_box.pack_start(token_label, False, False, 0)
        token_box.pack_start(self.token_entry, True, True, 0)
        token_toggle = Gtk.ToggleButton(label="👁");
        token_toggle.set_relief(Gtk.ReliefStyle.NONE)
        token_toggle.connect("toggled", lambda btn: self.token_entry.set_visibility(btn.get_active()))
        token_box.pack_end(token_toggle, False, False, 0)
        box.add(token_box)

        chat_id_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chat_id_label = Gtk.Label(label=tr('id_chat'));
        chat_id_label.set_xalign(0)
        self.chat_id_entry = Gtk.Entry();
        self.chat_id_entry.set_placeholder_text("123456789")
        self.chat_id_entry.set_visibility(False)
        chat_id_box.pack_start(chat_id_label, False, False, 0)
        chat_id_box.pack_start(self.chat_id_entry, True, True, 0)
        chat_id_toggle = Gtk.ToggleButton(label="👁");
        chat_id_toggle.set_relief(Gtk.ReliefStyle.NONE)
        chat_id_toggle.connect("toggled", lambda btn: self.chat_id_entry.set_visibility(btn.get_active()))
        chat_id_box.pack_end(chat_id_toggle, False, False, 0)
        box.add(chat_id_box)

        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        interval_label = Gtk.Label(label=tr('time_send'));
        interval_label.set_xalign(0)
        self.interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1);
        self.interval_spin.set_value(3600)
        interval_box.pack_start(interval_label, False, False, 0)
        interval_box.pack_start(self.interval_spin, True, True, 0)
        interval_box.set_margin_top(3);
        interval_box.set_margin_bottom(3);
        interval_box.set_margin_end(50)
        box.add(interval_box)

        # Discord
        discord_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.discord_enable_check = Gtk.CheckButton(label=tr('discord_notification'))
        discord_box.pack_start(self.discord_enable_check, False, False, 0)
        discord_test_button = Gtk.Button(label=tr('check_discord'))
        discord_test_button.set_halign(Gtk.Align.END)
        discord_test_button.connect("clicked", self.test_discord)
        discord_box.pack_end(discord_test_button, False, False, 0)
        box.add(discord_box)

        webhook_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        webhook_label = Gtk.Label(label=tr('webhook_url'));
        webhook_label.set_xalign(0)
        self.webhook_entry = Gtk.Entry();
        self.webhook_entry.set_placeholder_text("https://discord.com/api/webhooks/...")
        self.webhook_entry.set_visibility(False)
        webhook_box.pack_start(webhook_label, False, False, 0)
        webhook_box.pack_start(self.webhook_entry, True, True, 0)
        webhook_toggle = Gtk.ToggleButton(label="👁");
        webhook_toggle.set_relief(Gtk.ReliefStyle.NONE)
        webhook_toggle.connect("toggled", lambda btn: self.webhook_entry.set_visibility(btn.get_active()))
        webhook_box.pack_end(webhook_toggle, False, False, 0)
        box.add(webhook_box)

        discord_interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        discord_interval_label = Gtk.Label(label=tr('time_send'));
        discord_interval_label.set_xalign(0)
        self.discord_interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1);
        self.discord_interval_spin.set_value(3600)
        discord_interval_box.pack_start(discord_interval_label, False, False, 0)
        discord_interval_box.pack_start(self.discord_interval_spin, True, True, 0)
        discord_interval_box.set_margin_top(3);
        discord_interval_box.set_margin_bottom(30);
        discord_interval_box.set_margin_end(50)
        box.add(discord_interval_box)

        # Предзагрузка конфигов
        try:
            if TELEGRAM_CONFIG_FILE.exists():
                config = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                self.token_entry.set_text(config.get('TELEGRAM_BOT_TOKEN', '') or '')
                self.chat_id_entry.set_text(str(config.get('TELEGRAM_CHAT_ID', '') or ''))
                self.telegram_enable_check.set_active(bool(config.get('enabled', False)))
                self.interval_spin.set_value(int(config.get('notification_interval', 3600)))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

        try:
            if DISCORD_CONFIG_FILE.exists():
                config = json.loads(DISCORD_CONFIG_FILE.read_text(encoding="utf-8"))
                self.webhook_entry.set_text(config.get('DISCORD_WEBHOOK_URL', '') or '')
                self.discord_enable_check.set_active(bool(config.get('enabled', False)))
                self.discord_interval_spin.set_value(int(config.get('notification_interval', 3600)))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

        self.show_all()

    def _message(self, title: str, message: str):
        d = Gtk.MessageDialog(transient_for=self, flags=0,
                              message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK,
                              text=message)
        d.set_title(title)
        d.run()
        d.destroy()

    def test_telegram(self, _w):
        token = self.token_entry.get_text().strip()
        chat_id = self.chat_id_entry.get_text().strip()
        enabled = self.telegram_enable_check.get_active()
        interval = int(self.interval_spin.get_value())
        if not token or not chat_id:
            self._message(tr('error'), tr('bot_message'))
            return
        notifier = TelegramNotifier()
        if notifier.save_config(token, chat_id, enabled, interval):
            ok = notifier.send_message(tr('test_message'))
            self._message(tr('ok') if ok else tr('error'),
                          tr('test_message_ok') if ok else tr('test_message_error'))
        else:
            self._message(tr('error'), tr('setting_telegram_error'))

    def test_discord(self, _w):
        webhook_url = self.webhook_entry.get_text().strip()
        enabled = self.discord_enable_check.get_active()
        interval = int(self.discord_interval_spin.get_value())
        if not webhook_url:
            self._message(tr('error'), tr('webhook_required'))
            return
        notifier = DiscordNotifier()
        if notifier.save_config(webhook_url, enabled, interval):
            ok = notifier.send_message(tr('test_message'))
            self._message(tr('ok') if ok else tr('error'),
                          tr('test_message_ok') if ok else tr('test_message_error'))
        else:
            self._message(tr('error'), tr('setting_discord_error'))

    def download_log_file(self, _w):
        dialog = Gtk.FileChooserDialog(
            title=tr('download_log'),
            parent=self if (self.get_mapped()) else None,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL,
                           tr('apply_label'), Gtk.ResponseType.OK)
        dialog.set_current_name("info_log.txt")
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dest = Path(dialog.get_filename())
            try:
                if not LOG_FILE.exists():
                    raise FileNotFoundError(LOG_FILE)
                dest.write_text(LOG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                print("Ошибка сохранения лога:", e)
        dialog.destroy()


# -----------------------
# Основное приложение
# -----------------------
class SystemTrayApp:
    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self.load_settings()

        # Язык
        if not self.visibility_settings.get('language'):
            self.visibility_settings['language'] = detect_system_language()
            self.save_settings()
        global current_lang
        current_lang = self.visibility_settings['language']

        # Индикатор
        self.indicator = AppInd.Indicator.new(APP_ID, ICON_FALLBACK, AppInd.IndicatorCategory.SYSTEM_SERVICES)
        icon_path = Path(__file__).resolve().parent / "logo.png"
        try:
            if icon_path.exists():
                if hasattr(self.indicator, "set_icon_full"):
                    self.indicator.set_icon_full(str(icon_path), APP_NAME)
                else:
                    self.indicator.set_icon(str(icon_path))
            else:
                self.indicator.set_icon(ICON_FALLBACK)
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")
            self.indicator.set_icon(ICON_FALLBACK)
        self.indicator.set_status(AppInd.IndicatorStatus.ACTIVE)

        # Сигналы завершения
        signal.signal(signal.SIGTERM, self.quit)
        signal.signal(signal.SIGINT, self.quit)

        # PowerControl
        self.power_control = PowerControl(self)
        self.power_control.set_parent_window(None)

        # Меню
        self.create_menu()

        # Сеть: предыдущее состояние
        net = psutil.net_io_counters()
        self.prev_net_data = {'recv': net.bytes_recv, 'sent': net.bytes_sent, 'time': time.time()}

        # Глобальные слушатели
        self.keyboard_listener = None
        self.mouse_listener = None
        self._notify_no_global_hooks = False
        self.init_listeners()

        # Нотификаторы
        self.telegram_notifier = TelegramNotifier()
        self.discord_notifier = DiscordNotifier()
        self.last_telegram_notification_time = 0.0
        self.last_discord_notification_time = 0.0

        # Настройка связи между нотификатором и power control
        self.telegram_notifier.set_power_control(self.power_control)

        # Запуск Telegram бота если он включен
        if self.telegram_notifier.enabled:
            self.telegram_notifier.start_bot()

        self.settings_dialog: Optional[SettingsDialog] = None

        # Прогресс-диалог пинга (неблокирующий)
        self._progress_dialog: Optional[Gtk.MessageDialog] = None

        # Лог
        if self.visibility_settings.get('logging_enabled', True) and not LOG_FILE.exists():
            try:
                LOG_FILE.write_text("", encoding="utf-8")
            except Exception as e:
                print("Не удалось создать файл лога:", e)

    # --- Утилиты ---
    @staticmethod
    def _thread(target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()

    def init_listeners(self):
        try:
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press, daemon=True)
            self.keyboard_listener.start()
        except Exception as e:
            print("Не удалось запустить keyboard listener:", e)
            self.keyboard_listener = None
            self._notify_no_global_hooks = True
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click, daemon=True)
            self.mouse_listener.start()
        except Exception as e:
            print("Не удалось запустить mouse listener:", e)
            self.mouse_listener = None
            self._notify_no_global_hooks = True

    # --- Безопасное закрытие прогресс-диалога ---
    def _close_progress_dialog(self):
        if self._progress_dialog:
            try:
                self._progress_dialog.destroy()
            except Exception:
                pass
            self._progress_dialog = None

    # --- Обработчики ввода ---
    def on_key_press(self, _key):
        global keyboard_clicks
        with _clicks_lock:
            keyboard_clicks += 1

    def on_mouse_click(self, _x, _y, _button, pressed):
        if not pressed:
            return
        global mouse_clicks
        with _clicks_lock:
            mouse_clicks += 1

    # --- Пинг (c авто-закрытием waiting-диалога) ---
    def on_ping_click(self, *_):
        host = "8.8.8.8";
        count = 4;
        timeout = 5

        # Показать неблокирующий диалог "в процессе"
        def show_progress():
            # если уже есть и он отображается — не создаём второй
            if self._progress_dialog and self._progress_dialog.get_mapped():
                return False
            parent = self.settings_dialog if (self.settings_dialog and self.settings_dialog.get_mapped()) else None
            d = Gtk.MessageDialog(
                transient_for=parent,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text=tr('ping_running')
            )
            d.set_title(tr('ping_network'))
            d.set_modal(True)
            d.show()  # неблокирующе
            self._progress_dialog = d
            return False

        GLib.idle_add(show_progress)

        def worker():
            cmd = ["ping", "-c", str(count), "-w", str(timeout), host]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                ok = (proc.returncode == 0)
                out = proc.stdout.strip() or proc.stderr.strip() or tr('ping_error')
                title = tr('ok') if ok else tr('error')
                msg = f"{tr('ping_done')} {host}\n\n{out}"
            except Exception as e:
                title = tr('error')
                msg = f"{tr('ping_error')}: {e}"

            # На главном потоке: закрыть прогресс и показать итог
            def finish():
                self._close_progress_dialog()
                self._show_message(title, msg)
                return False

            GLib.idle_add(finish)

        self._thread(worker)

    # --- Меню ---
    def create_menu(self):
        self.menu = Gtk.Menu()

        # Верхняя «индикаторная» часть
        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.keyboard_item = Gtk.MenuItem(label=f"{tr('keyboard_clicks')}: 0")
        self.mouse_item = Gtk.MenuItem(label=f"{tr('mouse_clicks')}: 0")

        # Пинг
        self.ping_item = Gtk.MenuItem(label=tr('ping_network'))
        self.ping_item.connect("activate", self.on_ping_click)
        self.ping_top_sep = Gtk.SeparatorMenuItem()
        self.ping_bottom_sep = Gtk.SeparatorMenuItem()

        # Power
        self.power_separator = Gtk.SeparatorMenuItem()
        self.power_off_item = Gtk.MenuItem(label=tr('power_off'))
        self.power_off_item.connect("activate", self.power_control._confirm_action,
                                    self.power_control._shutdown, tr('confirm_text_power_off'))
        self.reboot_item = Gtk.MenuItem(label=tr('reboot'))
        self.reboot_item.connect("activate", self.power_control._confirm_action,
                                 self.power_control._reboot, tr('confirm_text_reboot'))
        self.lock_item = Gtk.MenuItem(label=tr('lock'))
        self.lock_item.connect("activate", self.power_control._confirm_action,
                               self.power_control._lock_screen, tr('confirm_text_lock'))
        self.timer_item = Gtk.MenuItem(label=tr('settings'))
        self.timer_item.connect("activate", self.power_control._open_settings)

        self.main_separator = Gtk.SeparatorMenuItem()
        self.exit_separator = Gtk.SeparatorMenuItem()

        self.settings_item = Gtk.MenuItem(label=tr('settings_label'))
        self.settings_item.connect("activate", self.show_settings)

        # Language submenu
        self.language_menu = Gtk.Menu()
        group_root = None
        for code in SUPPORTED_LANGS:
            label = (LANGUAGES.get(code) or LANGUAGES.get('en', {})).get('language_name', code)
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group_root, label)
            if group_root is None:
                group_root = item
            item.set_active(code == current_lang)
            item.connect("activate", self._on_language_selected, code)
            self.language_menu.append(item)
        self.language_menu_item = Gtk.MenuItem(label=tr('language'))
        self.language_menu_item.set_submenu(self.language_menu)

        self.quit_item = Gtk.MenuItem(label=tr('exit_app'))
        self.quit_item.connect("activate", self.quit)

        # Сборка меню
        self.update_menu_visibility()

        if any([
            self.visibility_settings.get('show_power_off', True),
            self.visibility_settings.get('show_reboot', True),
            self.visibility_settings.get('show_lock', True),
            self.visibility_settings.get('show_timer', True)
        ]):
            self.menu.append(self.power_separator)
            if self.visibility_settings.get('show_power_off', True):
                self.menu.append(self.power_off_item)
            if self.visibility_settings.get('show_reboot', True):
                self.menu.append(self.reboot_item)
            if self.visibility_settings.get('show_lock', True):
                self.menu.append(self.lock_item)
            if self.visibility_settings.get('show_timer', True):
                self.menu.append(self.timer_item)

        self.menu.append(self.main_separator)

        if self.visibility_settings.get('ping_network', True):
            self.menu.append(self.ping_top_sep)
            self.menu.append(self.ping_item)
            self.menu.append(self.ping_bottom_sep)

        self.menu.append(self.language_menu_item)
        self.menu.append(self.settings_item)
        self.menu.append(self.exit_separator)
        self.menu.append(self.quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def _on_language_selected(self, widget, lang_code: str):
        global current_lang
        if widget.get_active() and current_lang != lang_code:
            current_lang = lang_code
            self.visibility_settings['language'] = current_lang
            self.save_settings()
            self.create_menu()

    def load_settings(self) -> Dict:
        default = {
            'cpu': True, 'ram': True, 'swap': True, 'disk': True, 'net': True, 'uptime': True,
            'tray_cpu': True, 'tray_ram': True, 'keyboard_clicks': True, 'mouse_clicks': True,
            'language': None, 'logging_enabled': True,
            'show_power_off': True, 'show_reboot': True, 'show_lock': True, 'show_timer': True,
            'max_log_mb': 5, 'ping_network': True,
        }
        try:
            if self.settings_file.exists():
                saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
                default.update(saved)
        except Exception:
            pass
        return default

    def save_settings(self) -> None:
        try:
            self.settings_file.write_text(json.dumps(self.visibility_settings, indent=2), encoding="utf-8")
        except Exception as e:
            print("Ошибка сохранения настроек:", e)

    def update_menu_visibility(self) -> None:
        # Сначала очищаем всё, кроме «скелета»
        children = list(self.menu.get_children()) if hasattr(self, 'menu') else []
        keep = [
            getattr(self, 'main_separator', None),
            getattr(self, 'power_separator', None),
            getattr(self, 'exit_separator', None),
            getattr(self, 'language_menu_item', None),
            getattr(self, 'settings_item', None),
            getattr(self, 'quit_item', None),
        ]
        if getattr(self, 'ping_item', None) and self.visibility_settings.get('ping_network', True):
            keep.extend([self.ping_item, getattr(self, 'ping_top_sep', None), getattr(self, 'ping_bottom_sep', None)])
        keep = [x for x in keep if x is not None]

        for ch in children:
            if ch not in keep:
                try:
                    self.menu.remove(ch)
                except Exception:
                    pass

        # Препенды в правильном порядке
        def prepend_if(flag_key: str, item: Gtk.MenuItem):
            if self.visibility_settings.get(flag_key, True):
                self.menu.prepend(item)

        prepend_if('mouse_clicks', self.mouse_item)
        prepend_if('keyboard_clicks', self.keyboard_item)
        prepend_if('uptime', self.uptime_item)
        prepend_if('net', self.net_item)
        prepend_if('disk', self.disk_item)
        prepend_if('swap', self.swap_item)
        prepend_if('ram', self.ram_item)
        prepend_if('cpu', self.cpu_temp_item)

        self.menu.show_all()

    # --- Settings dialog ---
    def show_settings(self, _w):
        if self.settings_dialog and self.settings_dialog.get_mapped():
            self.settings_dialog.present()
            return

        dialog = SettingsDialog(None, self.visibility_settings)
        self.power_control.set_parent_window(dialog)
        self.settings_dialog = dialog

        try:
            response = dialog.run()

            if response == Gtk.ResponseType.OK:
                vs = self.visibility_settings
                vs['cpu'] = dialog.cpu_check.get_active()
                vs['ram'] = dialog.ram_check.get_active()
                vs['swap'] = dialog.swap_check.get_active()
                vs['disk'] = dialog.disk_check.get_active()
                vs['net'] = dialog.net_check.get_active()
                vs['uptime'] = dialog.uptime_check.get_active()
                vs['tray_cpu'] = dialog.tray_cpu_check.get_active()
                vs['tray_ram'] = dialog.tray_ram_check.get_active()
                vs['keyboard_clicks'] = dialog.keyboard_check.get_active()
                vs['mouse_clicks'] = dialog.mouse_check.get_active()
                vs['show_power_off'] = dialog.power_off_check.get_active()
                vs['show_reboot'] = dialog.reboot_check.get_active()
                vs['show_lock'] = dialog.lock_check.get_active()
                vs['show_timer'] = dialog.timer_check.get_active()
                vs['logging_enabled'] = dialog.logging_check.get_active()
                vs['ping_network'] = dialog.ping_check.get_active()
                vs['max_log_mb'] = int(dialog.logsize_spin.get_value())

                # Telegram - перезапускаем бота при изменении настроек
                tel_enabled_before = getattr(self, 'telegram_notifier', TelegramNotifier()).enabled
                if self.telegram_notifier.save_config(
                        dialog.token_entry.get_text().strip(),
                        dialog.chat_id_entry.get_text().strip(),
                        dialog.telegram_enable_check.get_active(),
                        int(dialog.interval_spin.get_value())
                ):
                    self.telegram_notifier.load_config()
                    if self.telegram_notifier.enabled and not tel_enabled_before:
                        self.last_telegram_notification_time = 0.0
                        self.telegram_notifier.start_bot()
                    elif not self.telegram_notifier.enabled and tel_enabled_before:
                        self.telegram_notifier.stop_bot()
                    elif self.telegram_notifier.enabled and tel_enabled_before:
                        # Перезапускаем бота для применения новых настроек
                        self.telegram_notifier.stop_bot()
                        self.telegram_notifier.start_bot()

                # Discord
                disc_enabled_before = getattr(self, 'discord_notifier', DiscordNotifier()).enabled
                if self.discord_notifier.save_config(
                        dialog.webhook_entry.get_text().strip(),
                        dialog.discord_enable_check.get_active(),
                        int(dialog.discord_interval_spin.get_value())
                ):
                    self.discord_notifier.load_config()
                    if self.discord_notifier.enabled and not disc_enabled_before:
                        self.last_discord_notification_time = 0.0

                self.save_settings()
                self.create_menu()

        finally:
            self.power_control.set_parent_window(None)
            if self.settings_dialog:
                try:
                    self.settings_dialog.destroy()
                except Exception:
                    pass
            self.settings_dialog = None

    # --- Обновление UI / логика ---
    def update_info(self) -> bool:
        try:
            with _clicks_lock:
                kbd, ms = keyboard_clicks, mouse_clicks

            cpu_temp = SystemUsage.get_cpu_temp()
            cpu_usage = SystemUsage.get_cpu_usage()
            ram_used, ram_total = SystemUsage.get_ram_usage()
            disk_used, disk_total = SystemUsage.get_disk_usage()
            swap_used, swap_total = SystemUsage.get_swap_usage()
            net_recv_speed, net_sent_speed = SystemUsage.get_network_speed(self.prev_net_data)
            uptime = SystemUsage.get_uptime()

            self._update_ui(cpu_temp, cpu_usage,
                            ram_used, ram_total,
                            disk_used, disk_total,
                            swap_used, swap_total,
                            net_recv_speed, net_sent_speed,
                            uptime, kbd, ms)

            now = time.time()
            # Telegram
            if (self.telegram_notifier.enabled and
                    now - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval):
                self._thread(self.send_telegram_notification,
                             cpu_temp, cpu_usage, ram_used, ram_total,
                             disk_used, disk_total, swap_used, swap_total,
                             net_recv_speed, net_sent_speed, uptime, kbd, ms)
                self.last_telegram_notification_time = now

            # Discord
            if (self.discord_notifier.enabled and
                    now - self.last_discord_notification_time >= self.discord_notifier.notification_interval):
                self._thread(self.send_discord_notification,
                             cpu_temp, cpu_usage, ram_used, ram_total,
                             disk_used, disk_total, swap_used, swap_total,
                             net_recv_speed, net_sent_speed, uptime, kbd, ms)
                self.last_discord_notification_time = now

            # Лог
            if self.visibility_settings.get('logging_enabled', True):
                max_mb = int(self.visibility_settings.get('max_log_mb', 5))
                max_mb = max(1, min(max_mb, 1024))
                rotate_log_if_needed(max_mb * 1024 * 1024)

                try:
                    line = (f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"CPU: {cpu_usage:.0f}% {cpu_temp}°C | "
                            f"RAM: {ram_used:.1f}/{ram_total:.1f} GB | "
                            f"SWAP: {swap_used:.1f}/{swap_total:.1f} GB | "
                            f"Disk: {disk_used:.1f}/{disk_total:.1f} GB | "
                            f"Net: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s | "
                            f"Uptime: {uptime} | "
                            f"Keys: {kbd} | "
                            f"Clicks: {ms}\n")

                    with LOG_FILE.open("a", encoding="utf-8", buffering=1024 * 64) as f:
                        f.write(line)

                except Exception as e:
                    print("Ошибка записи в лог:", e)

            return True
        except Exception as e:
            print(f"Ошибка в update_info: {e}")
            return True  # не останавливаем таймер

    def send_telegram_notification(self, cpu_temp, cpu_usage, ram_used, ram_total,
                                   disk_used, disk_total, swap_used, swap_total,
                                   net_recv_speed, net_sent_speed, uptime,
                                   keyboard_clicks_val, mouse_clicks_val):
        msg = (
            f"<b>{tr('system_status')}</b>\n"
            f"<b>{tr('cpu')}:</b> {cpu_usage:.0f}% ({cpu_temp}{tr('temperature')})\n"
            f"<b>{tr('ram')}:</b> {ram_used:.1f}/{ram_total:.1f} {tr('gb')}\n"
            f"<b>{tr('swap')}:</b> {swap_used:.1f}/{swap_total:.1f} {tr('gb')}\n"
            f"<b>{tr('disk')}:</b> {disk_used:.1f}/{disk_total:.1f} {tr('gb')}\n"
            f"<b>{tr('network')}:</b> ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s\n"
            f"<b>{tr('uptime')}:</b> {uptime}\n"
            f"<b>{tr('keyboard')}:</b> {keyboard_clicks_val} {tr('presses')}\n"
            f"<b>{tr('mouse')}:</b> {mouse_clicks_val} {tr('clicks')}"
        )
        self.telegram_notifier.send_message(msg)

    def send_discord_notification(self, cpu_temp, cpu_usage, ram_used, ram_total,
                                  disk_used, disk_total, swap_used, swap_total,
                                  net_recv_speed, net_sent_speed, uptime,
                                  keyboard_clicks_val, mouse_clicks_val):
        msg = (
            f"**{tr('system_status')}**\n"
            f"**{tr('cpu')}**: {cpu_usage:.0f}% ({cpu_temp}{tr('temperature')})\n"
            f"**{tr('ram')}**: {ram_used:.1f}/{ram_total:.1f} {tr('gb')}\n"
            f"**{tr('swap')}**: {swap_used:.1f}/{swap_total:.1f} {tr('gb')}\n"
            f"**{tr('disk')}**: {disk_used:.1f}/{disk_total:.1f} {tr('gb')}\n"
            f"**{tr('network')}**: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s\n"
            f"**{tr('uptime')}**: {uptime}\n"
            f"**{tr('keyboard')}**: {keyboard_clicks_val} {tr('presses')}\n"
            f"**{tr('mouse')}**: {mouse_clicks_val} {tr('clicks')}"
        )
        self.discord_notifier.send_message(msg)

    def _show_message(self, title: str, message: str):
        parent = self.settings_dialog if (self.settings_dialog and self.settings_dialog.get_mapped()) else None
        d = Gtk.MessageDialog(transient_for=parent, flags=0,
                              message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK, text=message)
        d.set_title(title);
        d.run();
        d.destroy()

    def _update_ui(self, cpu_temp, cpu_usage, ram_used, ram_total,
                   disk_used, disk_total, swap_used, swap_total,
                   net_recv_speed, net_sent_speed, uptime,
                   keyboard_clicks_val, mouse_clicks_val):
        try:
            if self.visibility_settings.get('cpu', True):
                self.cpu_temp_item.set_label(f"{tr('cpu_info')}: {cpu_usage:.0f}%  🌡{cpu_temp}°C")
            if self.visibility_settings.get('ram', True):
                self.ram_item.set_label(f"{tr('ram_loading')}: {ram_used:.1f}/{ram_total:.1f} GB")
            if self.visibility_settings.get('swap', True):
                self.swap_item.set_label(f"{tr('swap_loading')}: {swap_used:.1f}/{swap_total:.1f} GB")
            if self.visibility_settings.get('disk', True):
                self.disk_item.set_label(f"{tr('disk_loading')}: {disk_used:.1f}/{disk_total:.1f} GB")
            if self.visibility_settings.get('net', True):
                self.net_item.set_label(f"{tr('lan_speed')}: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s")
            if self.visibility_settings.get('uptime', True):
                self.uptime_item.set_label(f"{tr('uptime_label')}: {uptime}")
            if self.visibility_settings.get('keyboard_clicks', True):
                self.keyboard_item.set_label(f"{tr('keyboard_clicks')}: {keyboard_clicks_val}")
            if self.visibility_settings.get('mouse_clicks', True):
                self.mouse_item.set_label(f"{tr('mouse_clicks')}: {mouse_clicks_val}")

            tray_parts = []
            if self.visibility_settings.get('tray_cpu', True):
                tray_parts.append(f"{tr('cpu_info')}: {cpu_usage:.0f}%")
            if self.visibility_settings.get('tray_ram', True):
                tray_parts.append(f"{tr('ram_loading')}: {ram_used:.1f}GB")
            tray_text = "  ".join(tray_parts)
            if self.telegram_notifier.enabled or self.discord_notifier.enabled:
                tray_text = "⤴  " + tray_text
            self.indicator.set_label(tray_text, "")
        except Exception as e:
            print(f"Ошибка в _update_ui: {e}")

    # --- Завершение ---
    def quit(self, *args):
        # Остановить Telegram бота
        if self.telegram_notifier:
            self.telegram_notifier.stop_bot()

        # Снять таймеры PowerControl
        for tid in ("_update_timer_id", "_notify_timer_id", "_action_timer_id"):
            _id = getattr(self.power_control, tid, None)
            if _id:
                GLib.source_remove(_id)
                setattr(self.power_control, tid, None)

        # Закрыть диалоги
        if self.power_control.current_dialog:
            try:
                self.power_control.current_dialog.destroy()
            except Exception:
                pass
            self.power_control.current_dialog = None

        self._close_progress_dialog()

        if self.settings_dialog:
            try:
                self.settings_dialog.destroy()
            except Exception:
                pass
            self.settings_dialog = None

        # Остановить слушатели
        try:
            if self.keyboard_listener:
                self.keyboard_listener.stop()
        except Exception:
            pass
        try:
            if self.mouse_listener:
                self.mouse_listener.stop()
        except Exception:
            pass

        Gtk.main_quit()

    # --- Запуск ---
    def run(self):
        GLib.timeout_add_seconds(TIME_UPDATE_SEC, self.update_info)
        Gtk.main()


# -----------------------
# Entry point
# -----------------------
if __name__ == "__main__":
    Gtk.init([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()