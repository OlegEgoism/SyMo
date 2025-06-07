import gi
import os
import signal
import json
import psutil
import time
from datetime import timedelta
from pynput import keyboard, mouse

gi.require_version('Gtk', '3.0')
gi.require_version('GLib', '2.0')
gi.require_version('AppIndicator3', '0.1')

from gi.repository import Gtk, GLib, AppIndicator3, GObject

LANGUAGES = {
    'ru': {
        # System Monitor translations
        'cpu_tray': "ЦПУ в трее",
        'ram_tray': "ОЗУ в трее",
        'cpu_info': "ЦПУ",
        'ram_loading': "ОЗУ",
        'swap_loading': "Подкачка",
        'disk_loading': "Диск",
        'lan_speed': "Сеть",
        'uptime_label': "Время работы",
        'settings_label': "Настройки",
        'exit_app': "Выход",
        'apply_label': "Применить",
        'cancel_label': "Отмена",
        'download_log': " Скачать ",
        'language': "Язык",
        'language_name': "Русский",
        'enable_logging': "Логирование",
        'keyboard_clicks': "Нажатия клавиш",
        'mouse_clicks': "Клики мыши",
        'clicks_tray': "Клики в трее",

        # Power Control translations
        'power_off': "Выключение",
        'reboot': "Перезагрузка",
        'lock': "Блокировка",
        'settings': "Таймер",
        'minutes': "Минуты:",
        'action': "",
        'apply': "Применить",
        'cancel': "Отмена",
        'reset': "Сбросить",
        'confirm_title': "Подтверждение действия",
        'confirm_text_power_off': "Выключить компьютер?",
        'confirm_text_reboot': "Перезагрузить компьютер?",
        'confirm_text_lock': "Заблокировать экран?",
        'scheduled': "Запланировано",
        'error': "Ошибка",
        'error_minutes_positive': "Введите значение больше 0.",
        'notification': "Предупреждение",
        'action_in_1_min': "{} через 1 минуту.",
        'action_in_time': "{} через {} минут.",
        'cancelled': "Отменено",
        'cancelled_text': "Запланированное действие сброшено.",
    },
    'en': {
        # System Monitor translations
        'cpu_tray': "CPU in tray",
        'ram_tray': "RAM in tray",
        'cpu_info': "CPU",
        'ram_loading': "RAM",
        'swap_loading': "Swap",
        'disk_loading': "Disk",
        'lan_speed': "Network",
        'uptime_label': "Uptime",
        'settings_label': "Settings",
        'exit_app': "Exit",
        'apply_label': "Apply",
        'cancel_label': "Cancel",
        'download_log': "Download",
        'language': "Language",
        'language_name': "English",
        'enable_logging': "Enable logging",
        'keyboard_clicks': "Keyboard clicks",
        'mouse_clicks': "Mouse clicks",
        'clicks_tray': "Clicks in tray",

        # Power Control translations
        'power_off': "Power Off",
        'reboot': "Reboot",
        'lock': "Lock",
        'settings': "Settings",
        'minutes': "Minutes:",
        'action': "",
        'apply': "Apply",
        'cancel': "Cancel",
        'reset': "Reset",
        'confirm_title': "Confirm Action",
        'confirm_text_power_off': "Power off the computer?",
        'confirm_text_reboot': "Reboot the computer?",
        'confirm_text_lock': "Lock the screen?",
        'scheduled': "Scheduled",
        'error': "Error",
        'error_minutes_positive': "Please enter a value greater than 0.",
        'notification': "Notification",
        'action_in_1_min': "{} in 1 minute.",
        'action_in_time': "{} in {} minutes.",
        'cancelled': "Cancelled",
        'cancelled_text': "Scheduled action cancelled.",
    },
    'cn': {
        # System Monitor translations
        'cpu_tray': "CPU在托盘",
        'ram_tray': "内存托盘显示",
        'cpu_info': "处理器",
        'ram_loading': "内存",
        'swap_loading': "交换分区",
        'disk_loading': "磁盘",
        'lan_speed': "网络",
        'uptime_label': "运行时间",
        'settings_label': "设置",
        'exit_app': "退出",
        'apply_label': "    应用    ",
        'cancel_label': "取消",
        'download_log': "下载日志",
        'language': "语言",
        'language_name': "中文",
        'enable_logging': "启用日志记录",
        'keyboard_clicks': "键盘点击",
        'mouse_clicks': "鼠标点击",
        'clicks_tray': "托盘点击",

        # Power Control translations
        'power_off': "关闭电源",
        'reboot': "重启",
        'lock': "锁屏",
        'settings': "设置",
        'minutes': "分钟:",
        'action': "",
        'apply': "应用",
        'cancel': "取消",
        'reset': "重置",
        'confirm_title': "确认操作",
        'confirm_text_power_off': "关闭计算机？",
        'confirm_text_reboot': "重启计算机？",
        'confirm_text_lock': "锁定屏幕？",
        'scheduled': "已安排",
        'error': "错误",
        'error_minutes_positive': "请输入大于0的值。",
        'notification': "通知",
        'action_in_1_min': "{} 还有1分钟。",
        'action_in_time': "{} 还有{}分钟。",
        'cancelled': "已取消",
        'cancelled_text': "已取消计划操作。",
    },
    'de': {
        # System Monitor translations
        'cpu_tray': "CPU im Tray",
        'ram_tray': "RAM im Tray",
        'cpu_info': "CPU",
        'ram_loading': "RAM",
        'swap_loading': "Auslagerung",
        'disk_loading': "Festplatte",
        'lan_speed': "Netzwerk",
        'uptime_label': "Betriebszeit",
        'settings_label': "Einstellungen",
        'exit_app': "Beenden",
        'apply_label': "Übernehmen",
        'cancel_label': "Abbrechen",
        'download_log': "Herunterladen",
        'language': "Sprache",
        'language_name': "Deutsch",
        'enable_logging': "Protokolle",
        'keyboard_clicks': "Tastenklicks",
        'mouse_clicks': "Mausklicks",
        'clicks_tray': "Klicks im Tray",

        # Power Control translations
        'power_off': "Herunterfahren",
        'reboot': "Neustart",
        'lock': "Sperren",
        'settings': "Einstellungen",
        'minutes': "Minuten:",
        'action': "",
        'apply': "Übernehmen",
        'cancel': "Abbrechen",
        'reset': "Zurücksetzen",
        'confirm_title': "Aktion bestätigen",
        'confirm_text_power_off': "Computer ausschalten?",
        'confirm_text_reboot': "Computer neu starten?",
        'confirm_text_lock': "Bildschirm sperren?",
        'scheduled': "Geplant",
        'error': "Fehler",
        'error_minutes_positive': "Bitte geben Sie einen Wert größer als 0 ein.",
        'notification': "Benachrichtigung",
        'action_in_1_min': "{} in 1 Minute.",
        'action_in_time': "{} in {} Minuten.",
        'cancelled': "Abgebrochen",
        'cancelled_text': "Geplante Aktion abgebrochen.",
    }
}

current_lang = 'ru'
time_update = 1
LOG_FILE = os.path.join(os.path.expanduser("~"), "system_monitor_log.txt")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".system_monitor_settings.json")

# Global variables for click counting
keyboard_clicks = 0
mouse_clicks = 0


def tr(key):
    """Translation function"""
    return LANGUAGES.get(current_lang, LANGUAGES['en']).get(key, key)


class SystemUsage:
    """System resource monitoring"""

    @staticmethod
    def get_cpu_temp():
        temps = psutil.sensors_temperatures()
        if 'coretemp' in temps:
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


class PowerControl:
    """Power control functionality"""

    def __init__(self, app):
        self.app = app
        self.scheduled_action = None
        self.remaining_seconds = 0
        self._update_timer_id = None
        self._notify_timer_id = None
        self._action_timer_id = None
        self.current_dialog = None

    def _confirm_action(self, widget, action_callback, message):
        if self.current_dialog:
            self.current_dialog.destroy()

        dialog = Gtk.MessageDialog(
            transient_for=None,
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
        if self.current_dialog:
            self.current_dialog.destroy()

        dialog = Gtk.Dialog(title=tr('settings'), flags=0)
        self.current_dialog = dialog
        content = dialog.get_content_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        content.add(box)
        content.set_border_width(10)

        # Time input
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

        # Action selection
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

        # Buttons
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
        self._notify_timer_id = None
        self._show_message(tr('notification'), tr('action_in_1_min').format(action))
        return False

    def _update_indicator_label(self):
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
        if self.current_dialog:
            self.current_dialog.destroy()

        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.set_title(title)
        self.current_dialog = dialog

        def on_response(dialog, response_id):
            dialog.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()


class SettingsDialog(Gtk.Dialog):
    """Settings dialog"""

    def __init__(self, parent, visibility_settings):
        super().__init__(title=tr('settings_label'), transient_for=parent, flags=0)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL, tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility_settings
        box = self.get_content_area()
        box.set_border_width(10)

        # Info
        monitor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        monitor_box.set_halign(Gtk.Align.END)
        monitor_label = Gtk.Label(label="<b>SyMo Ⓡ</b>")
        monitor_label.set_use_markup(True)
        monitor_box.pack_end(monitor_label, False, False, 0)
        box.add(monitor_box)

        # # System monitor settings
        # monitor_label = Gtk.Label(label="<b>System Monitor</b>")
        # monitor_label.set_use_markup(True)
        # box.add(monitor_label)

        self.tray_cpu_check = Gtk.CheckButton(label=tr('cpu_tray'))
        self.tray_cpu_check.set_active(self.visibility_settings.get('tray_cpu', True))
        box.add(self.tray_cpu_check)

        self.tray_ram_check = Gtk.CheckButton(label=tr('ram_tray'))
        self.tray_ram_check.set_active(self.visibility_settings.get('tray_ram', True))
        box.add(self.tray_ram_check)

        self.tray_clicks_check = Gtk.CheckButton(label=tr('clicks_tray'))
        self.tray_clicks_check.set_active(self.visibility_settings.get('tray_clicks', True))
        box.add(self.tray_clicks_check)

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

        # Power control settings
        power_separator = Gtk.SeparatorMenuItem()
        power_separator.set_margin_top(6)
        power_separator.set_margin_bottom(6)
        power_separator.set_size_request(0, 3)
        box.add(power_separator)

        # power_label = Gtk.Label(label="<b>Power Control</b>")
        # power_label.set_use_markup(True)
        # box.add(power_label)

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

        # Logging settings
        logging_box = Gtk.Box(spacing=0)
        separator = Gtk.SeparatorMenuItem()
        separator.set_margin_top(6)
        separator.set_margin_bottom(6)
        separator.set_size_request(0, 3)
        box.add(separator)

        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        logging_box.pack_start(self.logging_check, False, False, 0)

        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        logging_box.pack_end(self.download_button, False, False, 0)

        box.add(logging_box)

        self.show_all()

    def download_log_file(self, widget):
        dialog = Gtk.FileChooserDialog(
            title=tr('download_log'),
            parent=self,
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
                print("Error saving log:", e)
        dialog.destroy()


class SystemTrayApp:
    """System tray application with combined functionality"""

    def __init__(self):
        global current_lang

        # Initialize GTK
        if not Gtk.init_check()[0]:
            Gtk.init([])

        # Initialize indicator with a default icon
        self.indicator = AppIndicator3.Indicator.new(
            "SystemMonitor",
            "system-run-symbolic",
            AppIndicator3.IndicatorCategory.SYSTEM_SERVICES
        )

        # Try to set custom icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        if os.path.exists(icon_path):
            try:
                self.indicator.set_icon_full(icon_path, "System Monitor")
            except Exception as e:
                print(f"Couldn't set custom icon: {e}")
                self.indicator.set_icon("system-run-symbolic")
        else:
            self.indicator.set_icon("system-run-symbolic")

        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self.load_settings()

        current_lang = self.visibility_settings.get('language', 'ru')

        # Initialize power control
        self.power_control = PowerControl(self)

        # Create menu
        self.create_menu()
        self.prev_net_data = {
            'recv': psutil.net_io_counters().bytes_recv,
            'sent': psutil.net_io_counters().bytes_sent,
            'time': time.time()
        }

        # Initialize listeners
        self.keyboard_listener = None
        self.mouse_listener = None
        self.init_listeners()

    def init_listeners(self):
        """Initialize event listeners"""
        try:
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
            self.keyboard_listener.start()
            self.mouse_listener.start()
        except Exception as e:
            print(f"Error initializing listeners: {e}")

    def on_key_press(self, key):
        """Key press handler"""
        global keyboard_clicks
        keyboard_clicks += 1

    def on_mouse_click(self, x, y, button, pressed):
        """Mouse click handler"""
        global mouse_clicks
        if pressed:
            mouse_clicks += 1

    def create_menu(self):
        """Create or recreate menu with current language"""
        self.menu = Gtk.Menu()

        # System monitor items
        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.keyboard_item = Gtk.MenuItem(label=f"{tr('keyboard_clicks')}: 0")
        self.mouse_item = Gtk.MenuItem(label=f"{tr('mouse_clicks')}: 0")

        # Power control items
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

        # Other menu items
        self.main_separator = Gtk.SeparatorMenuItem()
        self.exit_separator = Gtk.SeparatorMenuItem()

        # Settings item
        self.settings_item = Gtk.MenuItem(label=tr('settings_label'))
        self.settings_item.connect("activate", self.show_settings)

        # Language selection submenu
        self.language_menu = Gtk.Menu()
        for code in ['ru', 'en', 'cn', 'de']:
            lang_item = Gtk.RadioMenuItem.new_with_label_from_widget(
                None, LANGUAGES[code]['language_name']
            )
            lang_item.set_active(code == current_lang)
            lang_item.connect("activate", self._on_language_selected, code)
            self.language_menu.append(lang_item)

        self.language_menu_item = Gtk.MenuItem(label=tr('language'))
        self.language_menu_item.set_submenu(self.language_menu)

        # Exit item
        self.quit_item = Gtk.MenuItem(label=tr('exit_app'))
        self.quit_item.connect("activate", self.quit)

        # Update menu visibility
        self.update_menu_visibility()

        # Add power control items if they are enabled
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

        # Add other items
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
            'tray_cpu': True, 'tray_ram': True, 'tray_clicks': True, 'keyboard_clicks': True,
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
            print("Error saving settings:", e)

    def update_menu_visibility(self):
        """Update menu item visibility"""
        children = self.menu.get_children()
        for child in children:
            if child not in [self.main_separator, self.power_separator, self.exit_separator,
                             self.language_menu_item, self.settings_item, self.quit_item]:
                self.menu.remove(child)

        # Add items in correct order
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
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            # System monitor settings
            self.visibility_settings['cpu'] = dialog.cpu_check.get_active()
            self.visibility_settings['ram'] = dialog.ram_check.get_active()
            self.visibility_settings['swap'] = dialog.swap_check.get_active()
            self.visibility_settings['disk'] = dialog.disk_check.get_active()
            self.visibility_settings['net'] = dialog.net_check.get_active()
            self.visibility_settings['uptime'] = dialog.uptime_check.get_active()
            self.visibility_settings['tray_cpu'] = dialog.tray_cpu_check.get_active()
            self.visibility_settings['tray_ram'] = dialog.tray_ram_check.get_active()
            self.visibility_settings['tray_clicks'] = dialog.tray_clicks_check.get_active()
            self.visibility_settings['keyboard_clicks'] = dialog.keyboard_check.get_active()
            self.visibility_settings['mouse_clicks'] = dialog.mouse_check.get_active()

            # Power control settings
            self.visibility_settings['show_power_off'] = dialog.power_off_check.get_active()
            self.visibility_settings['show_reboot'] = dialog.reboot_check.get_active()
            self.visibility_settings['show_lock'] = dialog.lock_check.get_active()
            self.visibility_settings['show_timer'] = dialog.timer_check.get_active()

            # Logging settings
            self.visibility_settings['logging_enabled'] = dialog.logging_check.get_active()

            self.save_settings()
            self.create_menu()  # Recreate menu with new settings

        dialog.destroy()

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

            # Use GLib.idle_add to safely update the UI from another thread
            GLib.idle_add(self._update_ui,
                          cpu_temp, cpu_usage,
                          ram_used, ram_total,
                          disk_used, disk_total,
                          swap_used, swap_total,
                          net_recv_speed, net_sent_speed,
                          uptime,
                          keyboard_clicks, mouse_clicks)

            # Logging
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
                    print("Error writing to log:", e)
            return True

        except Exception as e:
            print(f"Error in update_info: {e}")
            return True

    def _update_ui(self, cpu_temp, cpu_usage, ram_used, ram_total,
                   disk_used, disk_total, swap_used, swap_total,
                   net_recv_speed, net_sent_speed, uptime,
                   keyboard_clicks, mouse_clicks):
        """Update UI elements safely from the main thread"""
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
            if self.visibility_settings.get('tray_clicks', True):
                tray_parts.append(f"K:{keyboard_clicks} M:{mouse_clicks}")

            tray_text = "" + "  ".join(tray_parts)
            self.indicator.set_label(tray_text, "")

        except Exception as e:
            print(f"Error in _update_ui: {e}")

    def quit(self, *args):
        # Stop listeners before quitting
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        Gtk.main_quit()

    def run(self):
        GLib.timeout_add_seconds(time_update, self.update_info)
        Gtk.main()


if __name__ == "__main__":
    if not Gtk.init_check()[0]:
        Gtk.init([])

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()