import gi
import os
import signal
import json
import psutil
import time
import requests
import locale
import threading
import subprocess
from enum import Enum
from datetime import timedelta
from pynput import keyboard, mouse
from language import LANGUAGES

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

# Совместимость: AppIndicator3 или AyatanaAppIndicator3
try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppInd

SUPPORTED_LANGS = ['ru', 'en', 'cn', 'de', 'it', 'es', 'tr', 'fr']

keyboard_clicks = 0
mouse_clicks = 0
_clicks_lock = threading.Lock()

current_lang = 'ru'
time_update = 1  # период обновления, сек.

LOG_FILE = os.path.join(os.path.expanduser("~"), ".symo_log.txt")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".symo_settings.json")
TELEGRAM_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".symo_telegram.json")
DISCORD_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".symo_discord.json")


def _rotate_log_if_needed(max_size_bytes: int):
    """Простейшая ротация: если лог > max_size_bytes — переименовать в .1 (перезаписать .1 при наличии)."""
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > max_size_bytes:
            bak = LOG_FILE + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(LOG_FILE, bak)
    except Exception as e:
        print("Ошибка ротации лога:", e)


def tr(key: str):
    """Локализация: берём карту текущего языка, иначе EN; при отсутствии ключа возвращаем сам ключ."""
    lang_map = LANGUAGES.get(current_lang) or LANGUAGES.get('en', {})
    return lang_map.get(key, key)


def detect_system_language():
    try:
        env = os.environ.get('LANG', '')
        if env:
            code = env.split('.')[0].split('_')[0].lower()
            return code if code in SUPPORTED_LANGS else 'ru'
        code = (locale.getlocale()[0] or '').split('_')[0].lower()
        return code if code in SUPPORTED_LANGS else 'ru'
    except Exception:
        return 'ru'


class SystemUsage:
    @staticmethod
    def get_cpu_temp():
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return 0
            preferred_keys = ('coretemp', 'k10temp', 'cpu-thermal', 'soc_thermal', 'acpitz')
            for key in preferred_keys:
                arr = temps.get(key)
                if arr:
                    for t in arr:
                        if getattr(t, 'label', '').lower().startswith('package'):
                            return int(t.current)
                    return int(arr[0].current)
            first_list = next(iter(temps.values()))
            return int(first_list[0].current) if first_list else 0
        except Exception:
            return 0

    @staticmethod
    def get_cpu_usage():
        return psutil.cpu_percent()

    @staticmethod
    def get_ram_usage():
        memory = psutil.virtual_memory()
        return memory.used / (1024 ** 3), memory.total / (1024 ** 3)

    @staticmethod
    def get_swap_usage():
        swap = psutil.swap_memory()
        return swap.used / (1024 ** 3), swap.total / (1024 ** 3)

    @staticmethod
    def get_disk_usage():
        disk = psutil.disk_usage('/')
        return disk.used / (1024 ** 3), disk.total / (1024 ** 3)

    @staticmethod
    def get_network_speed(prev_data):
        net = psutil.net_io_counters()
        current_time = time.time()
        elapsed = current_time - prev_data['time']
        # интерфейс мог сброситься
        if net.bytes_recv < prev_data['recv'] or net.bytes_sent < prev_data['sent']:
            prev_data['recv'] = net.bytes_recv
            prev_data['sent'] = net.bytes_sent
            prev_data['time'] = current_time
            return 0.0, 0.0
        if elapsed <= 0:
            recv_speed = sent_speed = 0.0
        else:
            recv_speed = (net.bytes_recv - prev_data['recv']) / elapsed / 1024 / 1024
            sent_speed = (net.bytes_sent - prev_data['sent']) / elapsed / 1024 / 1024
        prev_data['recv'] = net.bytes_recv
        prev_data['sent'] = net.bytes_sent
        prev_data['time'] = current_time
        return recv_speed, sent_speed

    @staticmethod
    def get_uptime():
        seconds = time.time() - psutil.boot_time()
        return str(timedelta(seconds=int(seconds)))


class TelegramNotifier:
    def __init__(self):
        self.token = None
        self.chat_id = None
        self.enabled = False
        self.notification_interval = 3600
        self.load_config()

    def load_config(self):
        try:
            if os.path.exists(TELEGRAM_CONFIG_FILE):
                with open(TELEGRAM_CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.token = (config.get('TELEGRAM_BOT_TOKEN') or '').strip() or None
                    self.chat_id = (str(config.get('TELEGRAM_CHAT_ID') or '').strip() or None)
                    self.enabled = bool(config.get('enabled', False))
                    self.notification_interval = int(config.get('notification_interval', 3600))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

    def save_config(self, token, chat_id, enabled, interval):
        try:
            self.token = token.strip() if token else None
            self.chat_id = chat_id.strip() if chat_id else None
            self.enabled = bool(enabled)
            self.notification_interval = int(interval)
            with open(TELEGRAM_CONFIG_FILE, "w") as f:
                json.dump({
                    'TELEGRAM_BOT_TOKEN': self.token,
                    'TELEGRAM_CHAT_ID': self.chat_id,
                    'enabled': self.enabled,
                    'notification_interval': self.notification_interval
                }, f, indent=2)
            try:
                os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации Telegram: {e}")
            return False

    def send_message(self, message):
        if not self.enabled or not self.token or not self.chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=payload, timeout=(3, 7))
            return response.status_code == 200
        except Exception as e:
            print(f"Ошибка отправки сообщения в Telegram: {e}")
            return False


class DiscordNotifier:
    def __init__(self):
        self.webhook_url = None
        the_enabled = False
        self.enabled = False
        self.notification_interval = 3600
        self.load_config()

    def load_config(self):
        try:
            if os.path.exists(DISCORD_CONFIG_FILE):
                with open(DISCORD_CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.webhook_url = (config.get('DISCORD_WEBHOOK_URL') or '').strip()
                    self.enabled = bool(config.get('enabled', False))
                    self.notification_interval = int(config.get('notification_interval', 3600))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

    def save_config(self, webhook_url, enabled, interval):
        try:
            self.webhook_url = (webhook_url or '').strip()
            self.enabled = bool(enabled)
            self.notification_interval = int(interval)
            with open(DISCORD_CONFIG_FILE, "w") as f:
                json.dump({
                    'DISCORD_WEBHOOK_URL': self.webhook_url,
                    'enabled': self.enabled,
                    'notification_interval': self.notification_interval
                }, f, indent=2)
            try:
                os.chmod(DISCORD_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации Discord: {e}")
            return False

    def send_message(self, message):
        if not self.enabled or not self.webhook_url:
            return False
        try:
            payload = {"content": message, "username": "System Monitor"}
            response = requests.post(self.webhook_url, json=payload, timeout=(3, 7))
            return response.status_code in (200, 204)
        except Exception as e:
            print(f"Ошибка отправки сообщения в Discord: {e}")
            return False


class Action(Enum):
    POWER_OFF = "power_off"
    REBOOT = "reboot"
    LOCK = "lock"


def action_label(act: Action) -> str:
    if act == Action.POWER_OFF:
        return tr('power_off')
    if act == Action.REBOOT:
        return tr('reboot')
    if act == Action.LOCK:
        return tr('lock')
    return str(act.value)


class PowerControl:
    def __init__(self, app):
        self.app = app
        self.scheduled_action = None
        self.remaining_seconds = 0
        self._update_timer_id = None
        self._notify_timer_id = None
        self._action_timer_id = None
        self.current_dialog = None
        self.parent_window = None

    def set_parent_window(self, parent):
        if parent is None:
            self.parent_window = None
        elif isinstance(parent, Gtk.Widget) and parent.get_mapped():
            self.parent_window = parent
        else:
            self.parent_window = None

    def _confirm_action(self, widget, action_callback, message):
        if self.current_dialog and isinstance(self.current_dialog, Gtk.Widget):
            self.current_dialog.destroy()
            self.current_dialog = None
        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=message or tr('confirm_title')
        )
        dialog.set_title(tr('confirm_title'))
        self.current_dialog = dialog

        def on_response(d, response_id):
            if response_id == Gtk.ResponseType.OK and action_callback:
                action_callback()
            if isinstance(d, Gtk.Widget):
                d.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()

    def _shutdown(self):
        if os.system("loginctl poweroff") != 0:
            os.system("systemctl poweroff")

    def _reboot(self):
        if os.system("loginctl reboot") != 0:
            os.system("systemctl reboot")

    def _lock_screen(self):
        cmds = [
            "loginctl lock-session",
            "gnome-screensaver-command -l",
            "xdg-screensaver lock",
            "dm-tool lock",
        ]
        for c in cmds:
            if os.system(c) == 0:
                return

    def _open_settings(self, *_):
        if self.current_dialog and isinstance(self.current_dialog, Gtk.Widget):
            self.current_dialog.destroy()
            self.current_dialog = None

        dialog = Gtk.Dialog(
            title=tr('settings'),
            transient_for=self.parent_window,
            flags=0
        )
        self.current_dialog = dialog
        content = dialog.get_content_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        content.add(box)

        # Время таймера
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_label = Gtk.Label(label=tr('minutes')); time_label.set_xalign(0)
        adjustment = Gtk.Adjustment(value=1, lower=1, upper=1440, step_increment=1)
        time_spin = Gtk.SpinButton(); time_spin.set_adjustment(adjustment); time_spin.set_numeric(True)
        time_spin.set_value(1); time_spin.set_size_request(150, -1)
        time_box.pack_start(time_label, True, True, 0)
        time_box.pack_start(time_spin, False, False, 0)

        # Действие
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_label_w = Gtk.Label(label=tr('action')); action_label_w.set_xalign(0)
        action_combo = Gtk.ComboBoxText()
        action_combo.append(Action.POWER_OFF.value, action_label(Action.POWER_OFF))
        action_combo.append(Action.REBOOT.value, action_label(Action.REBOOT))
        action_combo.append(Action.LOCK.value, action_label(Action.LOCK))
        action_combo.set_active(0)
        action_combo.set_size_request(150, -1)
        action_box.pack_start(action_label_w, True, True, 0)
        action_box.pack_start(action_combo, False, False, 0)

        apply_button = Gtk.Button(label=tr('apply'))
        cancel_button = Gtk.Button(label=tr('cancel'))
        reset_button = Gtk.Button(label=tr('reset'))

        apply_button.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.OK))
        cancel_button.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.CANCEL))
        reset_button.connect("clicked", lambda *_: self._reset_action_button())

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        button_box.pack_start(reset_button, False, False, 0)
        button_box.pack_start(cancel_button, False, False, 0)
        button_box.pack_start(apply_button, False, False, 0)

        box.pack_start(time_box, False, False, 0)
        box.pack_start(action_box, False, False, 0)
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(6); sep.set_margin_bottom(6)
        box.pack_start(sep, False, False, 0)
        box.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            minutes = time_spin.get_value_as_int()
            action_id = action_combo.get_active_id()
            if minutes <= 0:
                self._show_message(tr('error'), tr('error_minutes_positive'))
                if isinstance(dialog, Gtk.Widget):
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

        if isinstance(dialog, Gtk.Widget):
            dialog.destroy()
        self.current_dialog = None

    def _reset_action_button(self, *_):
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id); self._update_timer_id = None
        if self._notify_timer_id:
            GLib.source_remove(self._notify_timer_id); self._notify_timer_id = None
        if self._action_timer_id:
            GLib.source_remove(self._action_timer_id); self._action_timer_id = None
        self.scheduled_action = None
        self.remaining_seconds = 0
        self.app.indicator.set_label("", "")
        self._show_message(tr('cancelled'), tr('cancelled_text'))

    def _notify_before_action(self, act: Action):
        self._notify_timer_id = None
        self._show_message(tr('notification'), tr('action_in_1_min').format(action_label(act)))
        return False

    def _update_indicator_label(self):
        if self.remaining_seconds <= 0:
            self.app.indicator.set_label("", "")
            return False
        hours = self.remaining_seconds // 3600
        minutes = (self.remaining_seconds % 3600) // 60
        seconds = self.remaining_seconds % 60
        label = f"  {action_label(self.scheduled_action)} — {hours:02d}:{minutes:02d}:{seconds:02d}"
        self.app.indicator.set_label(label, "")
        self.remaining_seconds -= 1
        return True

    def _delayed_action(self, act: Action):
        self._action_timer_id = None
        self.app.indicator.set_label("", "")
        self.scheduled_action = None
        self.remaining_seconds = 0
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id); self._update_timer_id = None
        if act == Action.POWER_OFF:
            self._shutdown()
        elif act == Action.REBOOT:
            self._reboot()
        elif act == Action.LOCK:
            self._lock_screen()
        return False

    def _show_message(self, title, message):
        if self.current_dialog:
            self.current_dialog.destroy()
            self.current_dialog = None
        parent = self.parent_window if (self.parent_window and self.parent_window.get_mapped()) else None
        dialog = Gtk.MessageDialog(
            transient_for=parent,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.set_title(title)
        self.current_dialog = dialog

        def on_response(d, response_id):
            if isinstance(d, Gtk.Widget):
                d.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, visibility):
        super().__init__(title=tr('settings_label'), transient_for=parent if isinstance(parent, Gtk.Widget) else None, flags=0)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL, tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility
        box = self.get_content_area()
        box.set_border_width(10)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_halign(Gtk.Align.END)
        link = Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ")
        link.set_halign(Gtk.Align.END)
        header.pack_start(link, False, False, 0)
        box.add(header)

        self.tray_cpu_check = Gtk.CheckButton(label=tr('cpu_tray'))
        self.tray_cpu_check.set_active(self.visibility_settings.get('tray_cpu', True))
        box.add(self.tray_cpu_check)

        self.tray_ram_check = Gtk.CheckButton(label=tr('ram_tray'))
        self.tray_ram_check.set_active(self.visibility_settings.get('tray_ram', True))
        box.add(self.tray_ram_check)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(6); sep.set_margin_bottom(6)
        box.add(sep)

        self.cpu_check = Gtk.CheckButton(label=tr('cpu_info'))
        self.cpu_check.set_active(self.visibility_settings['cpu'])
        box.add(self.cpu_check)

        self.ram_check = Gtk.CheckButton(label=tr('ram_loading'))
        self.ram_check.set_active(self.visibility_settings['ram'])
        box.add(self.ram_check)

        self.swap_check = Gtk.CheckButton(label=tr('swap_loading'))
        self.swap_check.set_active(self.visibility_settings['swap'])
        box.add(self.swap_check)

        self.disk_check = Gtk.CheckButton(label=tr('disk_loading'))
        self.disk_check.set_active(self.visibility_settings['disk'])
        box.add(self.disk_check)

        self.net_check = Gtk.CheckButton(label=tr('lan_speed'))
        self.net_check.set_active(self.visibility_settings['net'])
        box.add(self.net_check)

        self.uptime_check = Gtk.CheckButton(label=tr('uptime_label'))
        self.uptime_check.set_active(self.visibility_settings['uptime'])
        box.add(self.uptime_check)

        self.keyboard_check = Gtk.CheckButton(label=tr('keyboard_clicks'))
        self.keyboard_check.set_active(self.visibility_settings.get('keyboard_clicks', True))
        box.add(self.keyboard_check)

        self.mouse_check = Gtk.CheckButton(label=tr('mouse_clicks'))
        self.mouse_check.set_active(self.visibility_settings.get('mouse_clicks', True))
        box.add(self.mouse_check)

        sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep3.set_margin_top(6); sep3.set_margin_bottom(6)
        box.add(sep3)

        self.power_off_check = Gtk.CheckButton(label=tr('power_off'))
        self.power_off_check.set_active(self.visibility_settings.get('show_power_off', True))
        box.add(self.power_off_check)

        self.reboot_check = Gtk.CheckButton(label=tr('reboot'))
        self.reboot_check.set_active(self.visibility_settings.get('show_reboot', True))
        box.add(self.reboot_check)

        self.lock_check = Gtk.CheckButton(label=tr('lock'))
        self.lock_check.set_active(self.visibility_settings.get('show_lock', True))
        box.add(self.lock_check)

        self.timer_check = Gtk.CheckButton(label=tr('settings'))
        self.timer_check.set_active(self.visibility_settings.get('show_timer', True))
        box.add(self.timer_check)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.set_margin_top(6); sep2.set_margin_bottom(6)
        box.add(sep2)

        # Переключатель видимости кнопки Ping в трее
        self.ping_check = Gtk.CheckButton(label=tr('ping_network'))
        self.ping_check.set_active(self.visibility_settings.get('ping_network', True))
        box.add(self.ping_check)

        sep4 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep4.set_margin_top(6); sep4.set_margin_bottom(6)
        box.add(sep4)

        # --- Блок логирования ---
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

        # Максимальный размер лога (MB)
        logsize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        logsize_label = Gtk.Label(label=tr('max_log_size_mb'))
        logsize_label.set_xalign(0)
        self.logsize_spin = Gtk.SpinButton.new_with_range(1, 1024, 1)
        self.logsize_spin.set_value(int(self.visibility_settings.get('max_log_mb', 1000)))
        logsize_box.pack_start(logsize_label, False, False, 0)
        logsize_box.pack_start(self.logsize_spin, False, False, 0)
        box.add(logsize_box)

        sep4 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep4.set_margin_top(6); sep4.set_margin_bottom(6)
        box.add(sep4)

        # --- Telegram ---
        telegram_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.telegram_enable_check = Gtk.CheckButton(label=tr('telegram_notification'))
        self.telegram_enable_check.set_margin_top(3); self.telegram_enable_check.set_margin_bottom(3)
        telegram_box.pack_start(self.telegram_enable_check, False, False, 0)

        test_button = Gtk.Button(label=tr('check_telegram'))
        test_button.set_margin_top(3); test_button.set_margin_bottom(3)
        test_button.set_halign(Gtk.Align.END)
        test_button.connect("clicked", self.test_telegram)
        telegram_box.pack_end(test_button, False, False, 0)
        box.add(telegram_box)

        token_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        token_label = Gtk.Label(label=tr('token_bot')); token_label.set_xalign(0)
        self.token_entry = Gtk.Entry(); self.token_entry.set_placeholder_text("123...:ABC..."); self.token_entry.set_visibility(False)
        token_box.pack_start(token_label, False, False, 0)
        token_box.pack_start(self.token_entry, True, True, 0)
        token_toggle = Gtk.ToggleButton(label="👁"); token_toggle.set_relief(Gtk.ReliefStyle.NONE)
        token_toggle.connect("toggled", lambda btn: self.token_entry.set_visibility(btn.get_active()))
        token_box.pack_end(token_toggle, False, False, 0)
        box.add(token_box)

        chat_id_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chat_id_label = Gtk.Label(label=tr('id_chat')); chat_id_label.set_xalign(0)
        self.chat_id_entry = Gtk.Entry(); self.chat_id_entry.set_placeholder_text("123456789"); self.chat_id_entry.set_visibility(False)
        chat_id_box.pack_start(chat_id_label, False, False, 0)
        chat_id_box.pack_start(self.chat_id_entry, True, True, 0)
        chat_id_toggle = Gtk.ToggleButton(label="👁"); chat_id_toggle.set_relief(Gtk.ReliefStyle.NONE)
        chat_id_toggle.connect("toggled", lambda btn: self.chat_id_entry.set_visibility(btn.get_active()))
        chat_id_box.pack_end(chat_id_toggle, False, False, 0)
        box.add(chat_id_box)

        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        interval_label = Gtk.Label(label=tr('time_send')); interval_label.set_xalign(0)
        self.interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1); self.interval_spin.set_value(3600)
        interval_box.pack_start(interval_label, False, False, 0)
        interval_box.pack_start(self.interval_spin, True, True, 0)
        interval_box.set_margin_top(3); interval_box.set_margin_bottom(3); interval_box.set_margin_end(50)
        box.add(interval_box)

        # --- Discord ---
        discord_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.discord_enable_check = Gtk.CheckButton(label=tr('discord_notification'))
        self.discord_enable_check.set_margin_top(3); self.discord_enable_check.set_margin_bottom(3)
        discord_box.pack_start(self.discord_enable_check, False, False, 0)

        self.discord_test_button = Gtk.Button(label=tr('check_discord'))
        self.discord_test_button.set_margin_top(3); self.discord_test_button.set_margin_bottom(3)
        self.discord_test_button.set_halign(Gtk.Align.END)
        self.discord_test_button.connect("clicked", self.test_discord)
        discord_box.pack_end(self.discord_test_button, False, False, 0)
        box.add(discord_box)

        webhook_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        webhook_label = Gtk.Label(label=tr('webhook_url')); webhook_label.set_xalign(0)
        self.webhook_entry = Gtk.Entry(); self.webhook_entry.set_placeholder_text("https://discord.com/api/webhooks/..."); self.webhook_entry.set_visibility(False)
        webhook_box.pack_start(webhook_label, False, False, 0)
        webhook_box.pack_start(self.webhook_entry, True, True, 0)
        webhook_toggle = Gtk.ToggleButton(label="👁"); webhook_toggle.set_relief(Gtk.ReliefStyle.NONE)
        webhook_toggle.connect("toggled", lambda btn: self.webhook_entry.set_visibility(btn.get_active()))
        webhook_box.pack_end(webhook_toggle, False, False, 0)
        box.add(webhook_box)

        discord_interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        discord_interval_label = Gtk.Label(label=tr('time_send')); discord_interval_label.set_xalign(0)
        self.discord_interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1); self.discord_interval_spin.set_value(3600)
        discord_interval_box.pack_start(discord_interval_label, False, False, 0)
        discord_interval_box.pack_start(self.discord_interval_spin, True, True, 0)
        discord_interval_box.set_margin_top(3); discord_interval_box.set_margin_bottom(30); discord_interval_box.set_margin_end(50)
        box.add(discord_interval_box)

        # Загрузка конфигов
        try:
            if os.path.exists(TELEGRAM_CONFIG_FILE):
                with open(TELEGRAM_CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.token_entry.set_text(config.get('TELEGRAM_BOT_TOKEN', '') or '')
                    self.chat_id_entry.set_text(str(config.get('TELEGRAM_CHAT_ID', '') or ''))
                    self.telegram_enable_check.set_active(bool(config.get('enabled', False)))
                    self.interval_spin.set_value(int(config.get('notification_interval', 3600)))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

        try:
            if os.path.exists(DISCORD_CONFIG_FILE):
                with open(DISCORD_CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.webhook_entry.set_text(config.get('DISCORD_WEBHOOK_URL', '') or '')
                    self.discord_enable_check.set_active(bool(config.get('enabled', False)))
                    self.discord_interval_spin.set_value(int(config.get('notification_interval', 3600)))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

        self.show_all()

    def test_telegram(self, widget):
        token = self.token_entry.get_text().strip()
        chat_id = self.chat_id_entry.get_text().strip()
        enabled = self.telegram_enable_check.get_active()
        interval = int(self.interval_spin.get_value())
        if not token or not chat_id:
            self._show_message(title=tr('error'), message=tr('bot_message'))
            return
        notifier = TelegramNotifier()
        if notifier.save_config(token, chat_id, enabled, interval):
            test_message = tr('test_message')
            ok = notifier.send_message(test_message)
            self._show_message(title=tr('ok') if ok else tr('error'),
                               message=tr('test_message_ok') if ok else tr('test_message_error'))
        else:
            self._show_message(title=tr('error'), message=tr('setting_telegram_error'))

    def test_discord(self, widget):
        webhook_url = self.webhook_entry.get_text().strip()
        enabled = self.discord_enable_check.get_active()
        interval = int(self.discord_interval_spin.get_value())
        if not webhook_url:
            self._show_message(title=tr('error'), message=tr('webhook_required'))
            return
        notifier = DiscordNotifier()
        if notifier.save_config(webhook_url, enabled, interval):
            test_message = tr('test_message')
            ok = notifier.send_message(test_message)
            self._show_message(title=tr('ok') if ok else tr('error'),
                               message=tr('test_message_ok') if ok else tr('test_message_error'))
        else:
            self._show_message(title=tr('error'), message=tr('setting_discord_error'))

    def _show_message(self, title, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.set_title(title)
        dialog.run()
        dialog.destroy()

    def download_log_file(self, widget):
        dialog = Gtk.FileChooserDialog(
            title=tr('download_log'),
            parent=self if isinstance(self, Gtk.Widget) and self.get_mapped() else None,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL, tr('apply_label'), Gtk.ResponseType.OK)
        dialog.set_current_name("info_log.txt")
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dest_path = dialog.get_filename()
            try:
                if not os.path.exists(LOG_FILE):
                    raise FileNotFoundError(LOG_FILE)
                with open(LOG_FILE, "r", encoding="utf-8") as src, open(dest_path, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            except Exception as e:
                print("Ошибка сохранения лога:", e)
        if isinstance(dialog, Gtk.Widget):
            dialog.destroy()


class SystemTrayApp:
    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self.load_settings()
        if 'language' not in self.visibility_settings or not self.visibility_settings['language']:
            detected_lang = detect_system_language()
            self.visibility_settings['language'] = detected_lang
            self.save_settings()
        global current_lang
        current_lang = self.visibility_settings['language']

        self.indicator = AppInd.Indicator.new(
            "SystemMonitor",
            "system-run-symbolic",
            AppInd.IndicatorCategory.SYSTEM_SERVICES
        )
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        try:
            if os.path.exists(icon_path):
                if hasattr(self.indicator, "set_icon_full"):
                    self.indicator.set_icon_full(icon_path, "SyMo")
                else:
                    self.indicator.set_icon(icon_path)
            else:
                self.indicator.set_icon("system-run-symbolic")
        except Exception as e:
            print(f"Не удалось установить иконку: {e}")
            self.indicator.set_icon("system-run-symbolic")
        self.indicator.set_status(AppInd.IndicatorStatus.ACTIVE)

        signal.signal(signal.SIGTERM, self.quit)
        signal.signal(signal.SIGINT, self.quit)

        self.power_control = PowerControl(self)
        self.power_control.set_parent_window(None)
        self.create_menu()

        self.prev_net_data = {
            'recv': psutil.net_io_counters().bytes_recv,
            'sent': psutil.net_io_counters().bytes_sent,
            'time': time.time()
        }

        self.keyboard_listener = None
        self.mouse_listener = None
        self._notify_no_global_hooks = False
        self.init_listeners()

        self.telegram_notifier = TelegramNotifier()
        self.discord_notifier = DiscordNotifier()
        self.last_telegram_notification_time = 0
        self.last_discord_notification_time = 0
        self.settings_dialog = None

        if self.visibility_settings.get('logging_enabled', True) and not os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception as e:
                print("Не удалось создать файл лога:", e)

    def _send_async(self, func, *args, **kwargs):
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
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

    def on_key_press(self, key):
        global keyboard_clicks
        with _clicks_lock:
            keyboard_clicks += 1

    def on_mouse_click(self, x, y, button, pressed):
        global mouse_clicks
        if pressed:
            with _clicks_lock:
                mouse_clicks += 1

    # ---------- Ping ----------
    def on_ping_click(self, *_):
        """Обработчик пункта меню Ping — запускает ping в фоне и показывает результат."""
        host = "8.8.8.8"  # можно вынести в настройки при желании
        count = 4
        timeout = 5  # сек общий лимит (через -w)

        def worker():
            GLib.idle_add(lambda: self._show_message(tr('ping_network'), tr('ping_running')))
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
            GLib.idle_add(lambda: self._show_message(title, msg))

        self._send_async(worker)

    def create_menu(self):
        self.menu = Gtk.Menu()
        # Динамические элементы-индикаторы
        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.keyboard_item = Gtk.MenuItem(label=f"{tr('keyboard_clicks')}: 0")
        self.mouse_item = Gtk.MenuItem(label=f"{tr('mouse_clicks')}: 0")

        # Кнопка Ping и разделители вокруг неё (будут добавляться условно)
        self.ping_item = Gtk.MenuItem(label=tr('ping_network'))
        self.ping_item.connect("activate", self.on_ping_click)
        self.ping_top_sep = Gtk.SeparatorMenuItem()
        self.ping_bottom_sep = Gtk.SeparatorMenuItem()

        # Блок кнопок питания/таймер
        self.power_separator = Gtk.SeparatorMenuItem()
        self.power_off_item = Gtk.MenuItem(label=tr('power_off'))
        self.power_off_item.connect("activate", self.power_control._confirm_action, self.power_control._shutdown, tr('confirm_text_power_off'))
        self.reboot_item = Gtk.MenuItem(label=tr('reboot'))
        self.reboot_item.connect("activate", self.power_control._confirm_action, self.power_control._reboot, tr('confirm_text_reboot'))
        self.lock_item = Gtk.MenuItem(label=tr('lock'))
        self.lock_item.connect("activate", self.power_control._confirm_action, self.power_control._lock_screen, tr('confirm_text_lock'))
        self.timer_item = Gtk.MenuItem(label=tr('settings'))
        self.timer_item.connect("activate", self.power_control._open_settings)

        self.main_separator = Gtk.SeparatorMenuItem()
        self.exit_separator = Gtk.SeparatorMenuItem()

        self.settings_item = Gtk.MenuItem(label=tr('settings_label'))
        self.settings_item.connect("activate", self.show_settings)

        # Меню выбора языка
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

        # Сначала обновим «индикаторы»
        self.update_menu_visibility()

        # Блок питания/таймер (если включено хоть что-то)
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

        # Хвост меню — сначала разделитель основного блока
        self.menu.append(self.main_separator)

        # --- ПИНГ НАД ЯЗЫКОМ, С РАЗДЕЛИТЕЛЯМИ ВЕРХ/НИЗ ---
        if self.visibility_settings.get('ping_network', True):
            self.menu.append(self.ping_top_sep)
            self.menu.append(self.ping_item)
            self.menu.append(self.ping_bottom_sep)

        # Далее язык, настройки и выход
        self.menu.append(self.language_menu_item)
        self.menu.append(self.settings_item)
        self.menu.append(self.exit_separator)
        self.menu.append(self.quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def _on_language_selected(self, widget, lang_code):
        global current_lang
        if widget.get_active() and current_lang != lang_code:
            current_lang = lang_code
            self.visibility_settings['language'] = current_lang
            self.save_settings()
            self.create_menu()

    def load_settings(self):
        default = {
            'cpu': True, 'ram': True, 'swap': True, 'disk': True, 'net': True, 'uptime': True,
            'tray_cpu': True, 'tray_ram': True, 'keyboard_clicks': True,
            'mouse_clicks': True, 'language': None, 'logging_enabled': True,
            'show_power_off': True, 'show_reboot': True, 'show_lock': True, 'show_timer': True,
            'max_log_mb': 5,
            'ping_network': True,
        }
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default.update(saved)
        except Exception:
            pass
        return default

    def save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.visibility_settings, f, indent=4)
        except Exception as e:
            print("Ошибка сохранения настроек:", e)

    def update_menu_visibility(self):
        """Перестраиваем верхнюю, «индикаторную» часть меню с учётом чекбоксов."""
        children = self.menu.get_children() if hasattr(self, 'menu') else []
        # Сохраняем «хвост»: разделители и статические элементы
        keep = [
            getattr(self, 'main_separator', None),
            getattr(self, 'power_separator', None),
            getattr(self, 'exit_separator', None),
            getattr(self, 'language_menu_item', None),
            getattr(self, 'settings_item', None),
            getattr(self, 'quit_item', None),
        ]

        # Если Ping включён — тоже сохраняем его и его разделители
        if getattr(self, 'ping_item', None) and self.visibility_settings.get('ping_network', True):
            keep.extend([self.ping_item, getattr(self, 'ping_top_sep', None), getattr(self, 'ping_bottom_sep', None)])

        keep = [x for x in keep if x is not None]

        for child in list(children):
            if child not in keep:
                try:
                    self.menu.remove(child)
                except Exception:
                    pass

        # Добавляем элементы-индикаторы по флагам
        if self.visibility_settings.get('mouse_clicks', True):
            self.menu.prepend(self.mouse_item)
        if self.visibility_settings.get('keyboard_clicks', True):
            self.menu.prepend(self.keyboard_item)
        if self.visibility_settings.get('uptime', True):
            self.menu.prepend(self.uptime_item)
        if self.visibility_settings.get('net', True):
            self.menu.prepend(self.net_item)
        if self.visibility_settings.get('disk', True):
            self.menu.prepend(self.disk_item)
        if self.visibility_settings.get('swap', True):
            self.menu.prepend(self.swap_item)
        if self.visibility_settings.get('ram', True):
            self.menu.prepend(self.ram_item)
        if self.visibility_settings.get('cpu', True):
            self.menu.prepend(self.cpu_temp_item)

        self.menu.show_all()

    def show_settings(self, widget):
        if self.settings_dialog is not None and self.settings_dialog.get_mapped():
            self.settings_dialog.present()
            return

        dialog = SettingsDialog(None, self.visibility_settings)
        self.power_control.set_parent_window(dialog)
        self.settings_dialog = dialog

        try:
            response = dialog.run()

            if response == Gtk.ResponseType.OK:
                self.visibility_settings['cpu'] = dialog.cpu_check.get_active()
                self.visibility_settings['ram'] = dialog.ram_check.get_active()
                self.visibility_settings['swap'] = dialog.swap_check.get_active()
                self.visibility_settings['disk'] = dialog.disk_check.get_active()
                self.visibility_settings['net'] = dialog.net_check.get_active()
                self.visibility_settings['uptime'] = dialog.uptime_check.get_active()
                self.visibility_settings['tray_cpu'] = dialog.tray_cpu_check.get_active()
                self.visibility_settings['tray_ram'] = dialog.tray_ram_check.get_active()
                self.visibility_settings['keyboard_clicks'] = dialog.keyboard_check.get_active()
                self.visibility_settings['mouse_clicks'] = dialog.mouse_check.get_active()
                self.visibility_settings['show_power_off'] = dialog.power_off_check.get_active()
                self.visibility_settings['show_reboot'] = dialog.reboot_check.get_active()
                self.visibility_settings['show_lock'] = dialog.lock_check.get_active()
                self.visibility_settings['show_timer'] = dialog.timer_check.get_active()
                self.visibility_settings['logging_enabled'] = dialog.logging_check.get_active()
                self.visibility_settings['ping_network'] = dialog.ping_check.get_active()

                # Сохранение нового размера лога
                self.visibility_settings['max_log_mb'] = int(dialog.logsize_spin.get_value())

                tel_enabled_before = self.telegram_notifier.enabled
                if self.telegram_notifier.save_config(
                        dialog.token_entry.get_text().strip(),
                        dialog.chat_id_entry.get_text().strip(),
                        dialog.telegram_enable_check.get_active(),
                        int(dialog.interval_spin.get_value())
                ):
                    self.telegram_notifier.load_config()
                    if self.telegram_notifier.enabled and not tel_enabled_before:
                        self.last_telegram_notification_time = 0

                disc_enabled_before = self.discord_notifier.enabled
                if self.discord_notifier.save_config(
                        dialog.webhook_entry.get_text().strip(),
                        dialog.discord_enable_check.get_active(),
                        int(dialog.discord_interval_spin.get_value())
                ):
                    self.discord_notifier.load_config()
                    if self.discord_notifier.enabled and not disc_enabled_before:
                        self.last_discord_notification_time = 0

                self.save_settings()
                self.create_menu()

        finally:
            self.power_control.set_parent_window(None)
            if self.settings_dialog is not None:
                try:
                    self.settings_dialog.destroy()
                except Exception:
                    pass
            self.settings_dialog = None

    def update_info(self):
        try:
            with _clicks_lock:
                kbd = keyboard_clicks
                ms = mouse_clicks

            cpu_temp = SystemUsage.get_cpu_temp()
            cpu_usage = SystemUsage.get_cpu_usage()
            ram_used, ram_total = SystemUsage.get_ram_usage()
            disk_used, disk_total = SystemUsage.get_disk_usage()
            swap_used, swap_total = SystemUsage.get_swap_usage()
            net_recv_speed, net_sent_speed = SystemUsage.get_network_speed(self.prev_net_data)
            uptime = SystemUsage.get_uptime()

            self._update_ui(
                cpu_temp, cpu_usage,
                ram_used, ram_total,
                disk_used, disk_total,
                swap_used, swap_total,
                net_recv_speed, net_sent_speed,
                uptime, kbd, ms
            )

            current_time = time.time()
            if (self.telegram_notifier.enabled and
                    current_time - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval):
                self._send_async(
                    self.send_telegram_notification,
                    cpu_temp, cpu_usage,
                    ram_used, ram_total,
                    disk_used, disk_total,
                    swap_used, swap_total,
                    net_recv_speed, net_sent_speed,
                    uptime, kbd, ms
                )
                self.last_telegram_notification_time = current_time

            if (self.discord_notifier.enabled and
                    current_time - self.last_discord_notification_time >= self.discord_notifier.notification_interval):
                self._send_async(
                    self.send_discord_notification,
                    cpu_temp, cpu_usage,
                    ram_used, ram_total,
                    disk_used, disk_total,
                    swap_used, swap_total,
                    net_recv_speed, net_sent_speed,
                    uptime, kbd, ms
                )
                self.last_discord_notification_time = current_time

            if self.visibility_settings.get('logging_enabled', True):
                # Используем значение из настроек
                max_mb = int(self.visibility_settings.get('max_log_mb', 5))
                max_mb = max(1, min(max_mb, 1024))  # границы безопасности
                _rotate_log_if_needed(max_mb * 1024 * 1024)
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                                f"CPU: {cpu_usage:.0f}% {cpu_temp}°C | "
                                f"RAM: {ram_used:.1f}/{ram_total:.1f} GB | "
                                f"SWAP: {swap_used:.1f}/{swap_total:.1f} GB | "
                                f"Disk: {disk_used:.1f}/{disk_total:.1f} GB | "
                                f"Net: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s | "
                                f"Uptime: {uptime} | "
                                f"Keys: {kbd} | "
                                f"Clicks: {ms}\n")
                except Exception as e:
                    print("Ошибка записи в лог:", e)
            return True
        except Exception as e:
            print(f"Ошибка в update_info: {e}")
            return True

    def send_telegram_notification(self, cpu_temp, cpu_usage, ram_used, ram_total,
                                   disk_used, disk_total, swap_used, swap_total,
                                   net_recv_speed, net_sent_speed, uptime,
                                   keyboard_clicks_val, mouse_clicks_val):
        message = (
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
        self.telegram_notifier.send_message(message)

    def send_discord_notification(self, cpu_temp, cpu_usage, ram_used, ram_total,
                                  disk_used, disk_total, swap_used, swap_total,
                                  net_recv_speed, net_sent_speed, uptime,
                                  keyboard_clicks_val, mouse_clicks_val):
        message = (
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
        self.discord_notifier.send_message(message)

    def _show_message(self, title: str, message: str):
        """Показывает инфодиалог (в главном потоке)."""
        parent = self.settings_dialog if (self.settings_dialog and self.settings_dialog.get_mapped()) else None
        dialog = Gtk.MessageDialog(
            transient_for=parent,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.set_title(title)
        dialog.run()
        dialog.destroy()

    def _update_ui(self, cpu_temp, cpu_usage, ram_used, ram_total,
                   disk_used, disk_total, swap_used, swap_total,
                   net_recv_speed, net_sent_speed, uptime,
                   keyboard_clicks_val, mouse_clicks_val):
        try:
            if self.visibility_settings['cpu']:
                self.cpu_temp_item.set_label(f"{tr('cpu_info')}: {cpu_usage:.0f}%  🌡{cpu_temp}°C")
            if self.visibility_settings['ram']:
                self.ram_item.set_label(f"{tr('ram_loading')}: {ram_used:.1f}/{ram_total:.1f} GB")
            if self.visibility_settings['swap']:
                self.swap_item.set_label(f"{tr('swap_loading')}: {swap_used:.1f}/{swap_total:.1f} GB")
            if self.visibility_settings['disk']:
                self.disk_item.set_label(f"{tr('disk_loading')}: {disk_used:.1f}/{disk_total:.1f} GB")
            if self.visibility_settings['net']:
                self.net_item.set_label(f"{tr('lan_speed')}: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s")
            if self.visibility_settings['uptime']:
                self.uptime_item.set_label(f"{tr('uptime_label')}: {uptime}")
            if self.visibility_settings['keyboard_clicks']:
                self.keyboard_item.set_label(f"{tr('keyboard_clicks')}: {keyboard_clicks_val}")
            if self.visibility_settings['mouse_clicks']:
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

    def quit(self, *args):
        if getattr(self.power_control, 'current_dialog', None):
            if isinstance(self.power_control.current_dialog, Gtk.Widget):
                self.power_control.current_dialog.destroy()
            self.power_control.current_dialog = None
        if getattr(self.power_control, '_update_timer_id', None):
            GLib.source_remove(self.power_control._update_timer_id)
        if getattr(self.power_control, '_notify_timer_id', None):
            GLib.source_remove(self.power_control._notify_timer_id)
        if getattr(self.power_control, '_action_timer_id', None):
            GLib.source_remove(self.power_control._action_timer_id)

        if self.settings_dialog is not None:
            self.settings_dialog.destroy()
            self.settings_dialog = None

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

    def run(self):
        GLib.timeout_add_seconds(time_update, self.update_info)
        Gtk.main()


if __name__ == "__main__":
    Gtk.init([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()
