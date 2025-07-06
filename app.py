import gi
import os
import signal
import json
import psutil
import time
import requests
from datetime import timedelta
from pynput import keyboard, mouse

from language import LANGUAGES

gi.require_version('Gtk', '3.0')
gi.require_version('GLib', '2.0')
gi.require_version('AppIndicator3', '0.1')

from gi.repository import Gtk, GLib, AppIndicator3

current_lang = 'ru'
time_update = 1
LOG_FILE = os.path.join(os.path.expanduser("~"), "system_monitor_log.txt")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".system_monitor_settings.json")
TELEGRAM_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".system_monitor_telegram.json")

keyboard_clicks = 0
mouse_clicks = 0


def tr(key):
    return LANGUAGES.get(current_lang, LANGUAGES['en']).get(key, key)


class SystemUsage:

    @staticmethod
    def get_cpu_temp():
        temps = psutil.sensors_temperatures()
        if 'coretemp' in temps and temps['coretemp']:
            return int(temps['coretemp'][0].current)
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
        return str(timedelta(seconds=seconds)).split(".")[0]


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
                    self.token = config.get('TELEGRAM_BOT_TOKEN')
                    self.chat_id = config.get('TELEGRAM_CHAT_ID')
                    self.enabled = config.get('enabled', False)
                    self.notification_interval = config.get('notification_interval', 3600)
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

    def save_config(self, token, chat_id, enabled, interval):
        try:
            self.token = token
            self.chat_id = chat_id
            self.enabled = enabled
            self.notification_interval = int(interval)

            with open(TELEGRAM_CONFIG_FILE, "w") as f:
                json.dump({
                    'TELEGRAM_BOT_TOKEN': token,
                    'TELEGRAM_CHAT_ID': chat_id,
                    'enabled': enabled,
                    'notification_interval': self.notification_interval
                }, f)
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
            response = requests.post(url, data=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Ошибка отправки сообщения в Telegram: {e}")
            return False


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
        self.parent_window = parent if isinstance(parent, Gtk.Widget) else None

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

        def on_response(dialog, response_id):
            if response_id == Gtk.ResponseType.OK and action_callback:
                action_callback()
            if isinstance(dialog, Gtk.Widget):
                dialog.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()

    def _shutdown(self):
        os.system("systemctl poweroff")

    def _reboot(self):
        os.system("systemctl reboot")

    def _lock_screen(self):
        os.system("loginctl lock-session")

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

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_label = Gtk.Label(label=tr('minutes'))
        time_label.set_xalign(0)
        adjustment = Gtk.Adjustment(value=1, lower=1, upper=1440, step_increment=1)
        time_spin = Gtk.SpinButton()
        time_spin.set_adjustment(adjustment)
        time_spin.set_numeric(True)
        time_spin.set_value(1)
        time_spin.set_size_request(150, -1)
        time_box.pack_start(time_label, True, True, 0)
        time_box.pack_start(time_spin, False, False, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_label = Gtk.Label(label=tr('action'))
        action_label.set_xalign(0)
        action_combo = Gtk.ComboBoxText()
        action_combo.append_text(tr('power_off'))
        action_combo.append_text(tr('reboot'))
        action_combo.append_text(tr('lock'))
        action_combo.set_active(0)
        action_combo.set_size_request(150, -1)
        action_box.pack_start(action_label, True, True, 0)
        action_box.pack_start(action_combo, False, False, 0)

        apply_button = Gtk.Button(label=tr('apply'))
        cancel_button = Gtk.Button(label=tr('cancel'))
        reset_button = Gtk.Button(label=tr('reset'))

        apply_button.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.OK))
        cancel_button.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.CANCEL))

        def on_reset_clicked(*_):
            time_spin.set_value(1)
            action_combo.set_active(0)
            self._reset_action_button()

        reset_button.connect("clicked", on_reset_clicked)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        button_box.pack_start(reset_button, False, False, 0)
        button_box.pack_start(cancel_button, False, False, 0)
        button_box.pack_start(apply_button, False, False, 0)

        box.pack_start(time_box, False, False, 0)
        box.pack_start(action_box, False, False, 0)
        box.pack_start(button_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            minutes = time_spin.get_value_as_int()
            action = action_combo.get_active_text()

            if minutes <= 0:
                self._show_message(tr('error'), tr('error_minutes_positive'))
                if isinstance(dialog, Gtk.Widget):
                    dialog.destroy()
                self.current_dialog = None
                return

            self.scheduled_action = action
            self.remaining_seconds = minutes * 60

            if minutes > 1:
                self._notify_timer_id = GLib.timeout_add_seconds((minutes - 1) * 60, self._notify_before_action, action)
            self._action_timer_id = GLib.timeout_add_seconds(self.remaining_seconds, self._delayed_action, action)

            if self._update_timer_id:
                GLib.source_remove(self._update_timer_id)
            self._update_timer_id = GLib.timeout_add_seconds(1, self._update_indicator_label)

            self._show_message(tr('scheduled'), tr('action_in_time').format(action, minutes))

        if isinstance(dialog, Gtk.Widget):
            dialog.destroy()
        self.current_dialog = None

    def _reset_action_button(self, *_):
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id)
            self._update_timer_id = None

        if self._notify_timer_id:
            GLib.source_remove(self._notify_timer_id)
            self._notify_timer_id = None

        if self._action_timer_id:
            GLib.source_remove(self._action_timer_id)
            self._action_timer_id = None

        self.scheduled_action = None
        self.remaining_seconds = 0
        self.app.indicator.set_label("", "")
        self._show_message(tr('cancelled'), tr('cancelled_text'))

    def _notify_before_action(self, action):
        if not self.app:
            return False
        self._notify_timer_id = None
        self._show_message(tr('notification'), tr('action_in_1_min').format(action))
        return False

    def _update_indicator_label(self):
        if not self.app:
            return False
        if self.remaining_seconds <= 0:
            self.app.indicator.set_label("", "")
            return False
        hours = self.remaining_seconds // 3600
        minutes = (self.remaining_seconds % 3600) // 60
        seconds = self.remaining_seconds % 60
        label = f"  {self.scheduled_action} {tr('action')} {hours:02d}:{minutes:02d}:{seconds:02d}"
        self.app.indicator.set_label(label, "")
        self.remaining_seconds -= 1
        return True

    def _delayed_action(self, action):
        if not self.app:
            return False
        self._action_timer_id = None
        self.app.indicator.set_label("", "")
        self.scheduled_action = None
        self.remaining_seconds = 0
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id)
            self._update_timer_id = None

        if action == tr('power_off'):
            self._shutdown()
        elif action == tr('reboot'):
            self._reboot()
        elif action == tr('lock'):
            self._lock_screen()
        return False

    def _show_message(self, title, message):
        if self.current_dialog and isinstance(self.current_dialog, Gtk.Widget):
            self.current_dialog.destroy()
            self.current_dialog = None

        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.set_title(title)
        self.current_dialog = dialog

        def on_response(dialog, response_id):
            if isinstance(dialog, Gtk.Widget):
                dialog.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, visibility_settings):
        super().__init__(title=tr('settings_label'), transient_for=parent if isinstance(parent, Gtk.Widget) else None, flags=0)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL, tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility_settings
        box = self.get_content_area()
        box.set_border_width(10)

        monitor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        monitor_box.set_halign(Gtk.Align.END)
        monitor_link = Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ")
        monitor_link.set_halign(Gtk.Align.END)
        monitor_box.pack_end(monitor_link, False, False, 0)
        box.add(monitor_box)

        self.tray_cpu_check = Gtk.CheckButton(label=tr('cpu_tray'))
        self.tray_cpu_check.set_active(self.visibility_settings.get('tray_cpu', True))
        box.add(self.tray_cpu_check)

        self.tray_ram_check = Gtk.CheckButton(label=tr('ram_tray'))
        self.tray_ram_check.set_active(self.visibility_settings.get('tray_ram', True))
        box.add(self.tray_ram_check)

        separator = Gtk.SeparatorMenuItem()
        separator.set_margin_top(6)
        separator.set_margin_bottom(6)
        separator.set_size_request(0, 3)
        box.add(separator)

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

        power_separator = Gtk.SeparatorMenuItem()
        power_separator.set_margin_top(6)
        power_separator.set_margin_bottom(6)
        power_separator.set_size_request(0, 3)
        box.add(power_separator)

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

        logging_box = Gtk.Box(spacing=0)
        separator = Gtk.SeparatorMenuItem()
        separator.set_margin_top(6)
        separator.set_margin_bottom(6)
        separator.set_size_request(0, 3)
        box.add(separator)

        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        self.logging_check.set_margin_bottom(3)
        logging_box.pack_start(self.logging_check, False, False, 0)
        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        self.download_button.set_margin_bottom(3)
        logging_box.pack_end(self.download_button, False, False, 0)
        box.add(logging_box)

        telegram_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.telegram_enable_check = Gtk.CheckButton(label=tr('telegram_notification'))
        self.telegram_enable_check.set_margin_top(3)
        self.telegram_enable_check.set_margin_bottom(3)
        telegram_box.pack_start(self.telegram_enable_check, False, False, 0)

        test_button = Gtk.Button(label=tr('check_telegram'))
        test_button.set_margin_top(3)
        test_button.set_margin_bottom(3)
        test_button.set_halign(Gtk.Align.END)
        test_button.connect("clicked", self.test_telegram)
        telegram_box.pack_end(test_button, False, False, 0)
        box.add(telegram_box)

        token_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        token_label = Gtk.Label(label=tr('token_bot'))
        token_label.set_xalign(0)
        self.token_entry = Gtk.Entry()
        self.token_entry.set_placeholder_text("123...:ABC...")
        token_box.pack_start(token_label, False, False, 0)
        token_box.pack_start(self.token_entry, True, True, 0)
        token_box.set_margin_top(3)
        token_box.set_margin_bottom(3)
        box.add(token_box)

        chat_id_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chat_id_label = Gtk.Label(label=tr('id_chat'))
        chat_id_label.set_xalign(0)
        self.chat_id_entry = Gtk.Entry()
        self.chat_id_entry.set_placeholder_text("123456789")
        chat_id_box.pack_start(chat_id_label, False, False, 0)
        chat_id_box.pack_start(self.chat_id_entry, True, True, 0)
        chat_id_box.set_margin_top(3)
        chat_id_box.set_margin_bottom(3)
        box.add(chat_id_box)

        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        interval_label = Gtk.Label(label=tr('time_send'))
        interval_label.set_xalign(0)
        self.interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.interval_spin.set_value(3600)
        interval_box.pack_start(interval_label, False, False, 0)
        interval_box.pack_start(self.interval_spin, True, True, 0)
        interval_box.set_margin_top(3)
        interval_box.set_margin_bottom(3)
        box.add(interval_box)

        try:
            if os.path.exists(TELEGRAM_CONFIG_FILE):
                with open(TELEGRAM_CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.token_entry.set_text(config.get('TELEGRAM_BOT_TOKEN', ''))
                    self.chat_id_entry.set_text(str(config.get('TELEGRAM_CHAT_ID', '')))
                    self.telegram_enable_check.set_active(config.get('enabled', False))
                    self.interval_spin.set_value(config.get('notification_interval', 3600))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")
        self.show_all()

    def test_telegram(self, widget):
        token = self.token_entry.get_text().strip()
        chat_id = self.chat_id_entry.get_text().strip()
        enabled = self.telegram_enable_check.get_active()
        interval = self.interval_spin.get_value()

        if not token or not chat_id:
            self._show_message(title=tr('error'), message=tr('bot_message'))
            return
        notifier = TelegramNotifier()
        if notifier.save_config(token, chat_id, enabled, interval):
            test_message = tr('test_message')
            if notifier.send_message(test_message):
                self._show_message(title=tr('ok'), message=tr('test_message_ok'))
            else:
                self._show_message(title=tr('error'), message=tr('test_message_error'))
        else:
            self._show_message(title=tr('error'), message=tr('setting_telegram_error'))

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
        parent = self if isinstance(self, Gtk.Widget) and self.get_mapped() else None
        dialog = Gtk.FileChooserDialog(
            title=tr('download_log'),
            parent=parent,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_current_name("info_log.txt")

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dest_path = dialog.get_filename()
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as src, open(dest_path, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            except Exception as e:
                print("Ошибка сохранения лога:", e)
        if isinstance(dialog, Gtk.Widget):
            dialog.destroy()


class SystemTrayApp:
    def __init__(self):
        global current_lang

        if not Gtk.init_check()[0]:
            Gtk.init([])

        self.indicator = AppIndicator3.Indicator.new(
            "SystemMonitor",
            "system-run-symbolic",
            AppIndicator3.IndicatorCategory.SYSTEM_SERVICES
        )

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        if os.path.exists(icon_path):
            try:
                self.indicator.set_icon_full(icon_path, "System Monitor")
            except Exception as e:
                print(f"Не удалось установить иконку: {e}")
                self.indicator.set_icon("system-run-symbolic")
        else:
            self.indicator.set_icon("system-run-symbolic")

        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self.load_settings()

        current_lang = self.visibility_settings.get('language', 'ru')

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
        self.init_listeners()

        self.telegram_notifier = TelegramNotifier()
        self.last_telegram_notification_time = 0

    def init_listeners(self):
        try:
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
            self.keyboard_listener.daemon = True
            self.keyboard_listener.start()
        except Exception as e:
            print(f"Ошибка инициализации слушателя клавиатуры: {e}")
            self.keyboard_listener = None
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
            self.mouse_listener.daemon = True
            self.mouse_listener.start()
        except Exception as e:
            print(f"Ошибка инициализации слушателя мыши: {e}")
            self.mouse_listener = None

    def on_key_press(self, key):
        global keyboard_clicks
        keyboard_clicks += 1

    def on_mouse_click(self, x, y, button, pressed):
        global mouse_clicks
        if pressed:
            mouse_clicks += 1

    def create_menu(self):
        self.menu = Gtk.Menu()

        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.keyboard_item = Gtk.MenuItem(label=f"{tr('keyboard_clicks')}: 0")
        self.mouse_item = Gtk.MenuItem(label=f"{tr('mouse_clicks')}: 0")

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

        self.language_menu = Gtk.Menu()
        for code in ['ru', 'en', 'cn', 'de']:
            lang_item = Gtk.RadioMenuItem.new_with_label_from_widget(None, LANGUAGES[code]['language_name'])
            lang_item.set_active(code == current_lang)
            lang_item.connect("activate", self._on_language_selected, code)
            self.language_menu.append(lang_item)

        self.language_menu_item = Gtk.MenuItem(label=tr('language'))
        self.language_menu_item.set_submenu(self.language_menu)

        self.quit_item = Gtk.MenuItem(label=tr('exit_app'))
        self.quit_item.connect("activate", self.quit)

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
        self.menu.append(self.language_menu_item)
        self.menu.append(self.settings_item)
        self.menu.append(self.exit_separator)
        self.menu.append(self.quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def _on_language_selected(self, widget, lang_code):
        global current_lang
        if widget.get_active():
            if current_lang != lang_code:
                current_lang = lang_code
                self.visibility_settings['language'] = current_lang
                self.save_settings()
                self.create_menu()

    def load_settings(self):
        default = {
            'cpu': True, 'ram': True, 'swap': True, 'disk': True, 'net': True, 'uptime': True,
            'tray_cpu': True, 'tray_ram': True, 'keyboard_clicks': True,
            'mouse_clicks': True, 'language': 'ru', 'logging_enabled': True,
            'show_power_off': True, 'show_reboot': True, 'show_lock': True, 'show_timer': True
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
        children = self.menu.get_children()
        for child in children:
            if child not in [self.main_separator, self.power_separator, self.exit_separator,
                             self.language_menu_item, self.settings_item, self.quit_item]:
                self.menu.remove(child)

        if self.visibility_settings['mouse_clicks']:
            self.menu.prepend(self.mouse_item)

        if self.visibility_settings['keyboard_clicks']:
            self.menu.prepend(self.keyboard_item)

        if self.visibility_settings['uptime']:
            self.menu.prepend(self.uptime_item)

        if self.visibility_settings['net']:
            self.menu.prepend(self.net_item)

        if self.visibility_settings['disk']:
            self.menu.prepend(self.disk_item)

        if self.visibility_settings['swap']:
            self.menu.prepend(self.swap_item)

        if self.visibility_settings['ram']:
            self.menu.prepend(self.ram_item)

        if self.visibility_settings['cpu']:
            self.menu.prepend(self.cpu_temp_item)

        self.menu.show_all()

    def show_settings(self, widget):
        dialog = SettingsDialog(None, self.visibility_settings)
        self.power_control.set_parent_window(dialog)
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

            self.telegram_notifier.save_config(
                dialog.token_entry.get_text().strip(),
                dialog.chat_id_entry.get_text().strip(),
                dialog.telegram_enable_check.get_active(),
                dialog.interval_spin.get_value()
            )
            self.telegram_notifier.load_config()

            self.save_settings()
            self.create_menu()

        if isinstance(dialog, Gtk.Widget):
            dialog.destroy()
        self.power_control.set_parent_window(None)

    def update_info(self):
        try:
            global keyboard_clicks, mouse_clicks

            cpu_temp = SystemUsage.get_cpu_temp()
            cpu_usage = SystemUsage.get_cpu_usage()
            ram_used, ram_total = SystemUsage.get_ram_usage()
            disk_used, disk_total = SystemUsage.get_disk_usage()
            swap_used, swap_total = SystemUsage.get_swap_usage()
            net_recv_speed, net_sent_speed = SystemUsage.get_network_speed(self.prev_net_data)
            uptime = SystemUsage.get_uptime()

            GLib.idle_add(self._update_ui,
                          cpu_temp, cpu_usage,
                          ram_used, ram_total,
                          disk_used, disk_total,
                          swap_used, swap_total,
                          net_recv_speed, net_sent_speed,
                          uptime,
                          keyboard_clicks, mouse_clicks)

            current_time = time.time()
            if (self.telegram_notifier.enabled and
                    current_time - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval):
                self.send_telegram_notification(
                    cpu_temp, cpu_usage,
                    ram_used, ram_total,
                    disk_used, disk_total,
                    swap_used, swap_total,
                    net_recv_speed, net_sent_speed,
                    uptime,
                    keyboard_clicks, mouse_clicks
                )
                self.last_telegram_notification_time = current_time

            if self.visibility_settings.get('logging_enabled', True):
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                                f"CPU: {cpu_usage:.0f}% {cpu_temp}°C | "
                                f"RAM: {ram_used:.1f}/{ram_total:.1f} GB | "
                                f"SWAP: {swap_used:.1f}/{swap_total:.1f} GB | "
                                f"Disk: {disk_used:.1f}/{disk_total:.1f} GB | "
                                f"Net: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s | "
                                f"Uptime: {uptime} | "
                                f"Keys: {keyboard_clicks} | "
                                f"Clicks: {mouse_clicks}\n")
                except Exception as e:
                    print("Ошибка записи в лог:", e)
            return True

        except Exception as e:
            print(f"Ошибка в update_info: {e}")
            return True

    def send_telegram_notification(self, cpu_temp, cpu_usage, ram_used, ram_total,
                                   disk_used, disk_total, swap_used, swap_total,
                                   net_recv_speed, net_sent_speed, uptime,
                                   keyboard_clicks, mouse_clicks):
        message = (
            f"<b>Статус системы</b>\n\n"
            f"<b>CPU:</b> {cpu_usage:.0f}% ({cpu_temp}°C)\n"
            f"<b>RAM:</b> {ram_used:.1f}/{ram_total:.1f} GB\n"
            f"<b>Swap:</b> {swap_used:.1f}/{swap_total:.1f} GB\n"
            f"<b>Диск:</b> {disk_used:.1f}/{disk_total:.1f} GB\n"
            f"<b>Сеть:</b> ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s\n"
            f"<b>Время работы:</b> {uptime}\n"
            f"<b>Клавиши:</b> {keyboard_clicks} нажатий\n"
            f"<b>Мышь:</b> {mouse_clicks} кликов"
        )
        self.telegram_notifier.send_message(message)

    def _update_ui(self, cpu_temp, cpu_usage, ram_used, ram_total,
                   disk_used, disk_total, swap_used, swap_total,
                   net_recv_speed, net_sent_speed, uptime,
                   keyboard_clicks, mouse_clicks):
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
                self.keyboard_item.set_label(f"{tr('keyboard_clicks')}: {keyboard_clicks}")

            if self.visibility_settings['mouse_clicks']:
                self.mouse_item.set_label(f"{tr('mouse_clicks')}: {mouse_clicks}")

            tray_parts = []
            if self.visibility_settings.get('tray_cpu', True):
                tray_parts.append(f"  {tr('cpu_info')}: {cpu_usage:.0f}%")
            if self.visibility_settings.get('tray_ram', True):
                tray_parts.append(f"{tr('ram_loading')}: {ram_used:.1f}GB")

            tray_text = "" + "  ".join(tray_parts)
            self.indicator.set_label(tray_text, "")

        except Exception as e:
            print(f"Ошибка в _update_ui: {e}")

    def quit(self, *args):
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        if hasattr(self.power_control, 'current_dialog') and self.power_control.current_dialog:
            if isinstance(self.power_control.current_dialog, Gtk.Widget):
                self.power_control.current_dialog.destroy()
            self.power_control.current_dialog = None
        if hasattr(self.power_control, '_update_timer_id') and self.power_control._update_timer_id:
            GLib.source_remove(self.power_control._update_timer_id)
        if hasattr(self.power_control, '_notify_timer_id') and self.power_control._notify_timer_id:
            GLib.source_remove(self.power_control._notify_timer_id)
        if hasattr(self.power_control, '_action_timer_id') and self.power_control._action_timer_id:
            GLib.source_remove(self.power_control._action_timer_id)
        Gtk.main_quit()
        os._exit(0)

    def run(self):
        GLib.timeout_add_seconds(time_update, self.update_info)
        Gtk.main()


if __name__ == "__main__":
    # if not Gtk.init_check()[0]:
    #     Gtk.init([])
    #
    # signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()
