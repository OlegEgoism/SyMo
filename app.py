import gi
import psutil
import signal
import time
import os
import json
from datetime import timedelta

gi.require_version('Gtk', '3.0')
gi.require_version('GLib', '2.0')
gi.require_version('AppIndicator3', '0.1')

from gi.repository import Gtk, GLib, AppIndicator3

LANGUAGES = {
    'ru': {
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
        'language_label': "Язык интерфейса",
        'language_name': "Русский",
        'enable_logging': "Логирование"
    },
    'en': {
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
        'language_label': "Interface Language",
        'language_name': "English",
        'enable_logging': "Enable logging"
    },
    'cn': {
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
        'language_label': "界面语言          ",
        'language_name': "中文",
        'enable_logging': "启用日志记录"
    },
    'de': {
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
        'language_label': "Sprache                ",
        'language_name': "Deutsch",
        'enable_logging': "Protokolle"
    }
}

current_lang = 'ru'
time_update = 1
LOG_FILE = os.path.join(os.path.expanduser("~"), "symo_log.txt")


def tr(key):
    """Перевод"""
    return LANGUAGES[current_lang].get(key, key)


class SystemUsage:
    """Мониторинг ресурсов системы"""

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


class SettingsDialog(Gtk.Dialog):
    """Диалоговое окно настроек"""

    def __init__(self, parent, visibility_settings):
        super().__init__(title=tr('settings_label'), transient_for=parent, flags=0)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL, tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility_settings
        box = self.get_content_area()

        self.tray_cpu_check = Gtk.CheckButton(label=tr('cpu_tray'))
        self.tray_cpu_check.set_active(self.visibility_settings.get('tray_cpu', True))
        box.add(self.tray_cpu_check)

        self.tray_ram_check = Gtk.CheckButton(label=tr('ram_tray'))
        self.tray_ram_check.set_active(self.visibility_settings.get('tray_ram', True))
        box.add(self.tray_ram_check)

        # separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        # separator.set_margin_top(4)
        # separator.set_margin_bottom(4)
        # box.add(separator)

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


        logging_box = Gtk.Box(spacing=0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(4)
        separator.set_margin_bottom(4)
        box.add(separator)

        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        logging_box.pack_start(self.logging_check, False, False, 0)

        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        logging_box.pack_end(self.download_button, False, False, 0)

        box.add(logging_box)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(4)
        separator.set_margin_bottom(4)
        box.add(separator)

        lang_box = Gtk.Box(spacing=4)
        lang_label = Gtk.Label(label=tr('language_label'))
        lang_label.set_margin_start(24)
        lang_box.pack_start(lang_label, False, False, 0)

        self.lang_combo = Gtk.ComboBoxText()
        self.lang_combo.append('ru', LANGUAGES['ru']['language_name'])
        self.lang_combo.append('en', LANGUAGES['en']['language_name'])
        self.lang_combo.append('cn', LANGUAGES['cn']['language_name'])
        self.lang_combo.append('de', LANGUAGES['de']['language_name'])
        self.lang_combo.set_active_id(current_lang)
        lang_box.pack_start(self.lang_combo, False, False, 0)
        box.add(lang_box)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(4)
        box.add(separator)

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
                print("Ошибка при сохранении лога:", e)
        dialog.destroy()


class SystemTrayApp:
    """Приложение для системного трея"""

    def __init__(self):
        global current_lang

        self.indicator = AppIndicator3.Indicator.new("SyMo", "", AppIndicator3.IndicatorCategory.SYSTEM_SERVICES)
        icon_path = os.path.join(os.path.dirname(__file__), "logo.png")
        self.indicator.set_icon_full(icon_path, "SyMo")
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self.settings_file = os.path.join(os.path.expanduser("~"), ".system_tray_settings.json")
        self.visibility_settings = self.load_settings()

        current_lang = self.visibility_settings.get('language', 'ru')

        self.create_menu()
        self.prev_net_data = {
            'recv': psutil.net_io_counters().bytes_recv,
            'sent': psutil.net_io_counters().bytes_sent,
            'time': time.time()
        }

    def create_menu(self):
        """Создать или воссоздать меню с текущим языком """
        self.menu = Gtk.Menu()

        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.separator = Gtk.SeparatorMenuItem()
        self.settings_item = Gtk.MenuItem(label=tr('settings_label'))
        self.quit_item = Gtk.MenuItem(label=tr('exit_app'))

        self.settings_item.connect("activate", self.show_settings)
        self.quit_item.connect("activate", self.quit)

        self.update_menu_visibility()
        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def load_settings(self):
        default = {
            'cpu': True, 'ram': True, 'swap': True, 'disk': True, 'net': True, 'uptime': True,
            'tray_cpu': True, 'tray_ram': True, 'language': 'ru', 'logging_enabled': True
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
            print("Ошибка при сохранении настроек:", e)

    def update_menu_visibility(self):
        for item in self.menu.get_children():
            self.menu.remove(item)

        if self.visibility_settings['cpu']:
            self.menu.append(self.cpu_temp_item)

        if self.visibility_settings['ram']:
            self.menu.append(self.ram_item)

        if self.visibility_settings['swap']:
            self.menu.append(self.swap_item)

        if self.visibility_settings['disk']:
            self.menu.append(self.disk_item)

        if self.visibility_settings['net']:
            self.menu.append(self.net_item)

        if self.visibility_settings['uptime']:
            self.menu.append(self.uptime_item)

        self.menu.append(self.separator)
        self.menu.append(self.settings_item)
        self.menu.append(self.quit_item)

        self.menu.show_all()

    def show_settings(self, widget):
        global current_lang

        dialog = SettingsDialog(None, self.visibility_settings)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            new_lang = dialog.lang_combo.get_active_id()
            lang_changed = (new_lang != current_lang)

            self.visibility_settings['cpu'] = dialog.cpu_check.get_active()
            self.visibility_settings['ram'] = dialog.ram_check.get_active()
            self.visibility_settings['swap'] = dialog.swap_check.get_active()
            self.visibility_settings['disk'] = dialog.disk_check.get_active()
            self.visibility_settings['net'] = dialog.net_check.get_active()
            self.visibility_settings['uptime'] = dialog.uptime_check.get_active()
            self.visibility_settings['tray_cpu'] = dialog.tray_cpu_check.get_active()
            self.visibility_settings['tray_ram'] = dialog.tray_ram_check.get_active()
            self.visibility_settings['language'] = new_lang
            self.visibility_settings['logging_enabled'] = dialog.logging_check.get_active()

            current_lang = new_lang

            if lang_changed:
                self.create_menu()
            else:
                self.update_menu_visibility()

            self.save_settings()

        dialog.destroy()

    def update_info(self):
        cpu_temp = SystemUsage.get_cpu_temp()
        cpu_usage = SystemUsage.get_cpu_usage()
        ram_used, ram_total = SystemUsage.get_ram_usage()
        disk_used, disk_total = SystemUsage.get_disk_usage()
        swap_used, swap_total = SystemUsage.get_swap_usage()
        net_recv_speed, net_sent_speed = SystemUsage.get_network_speed(self.prev_net_data)
        uptime = SystemUsage.get_uptime()

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

        tray_parts = []
        if self.visibility_settings.get('tray_cpu', True):
            tray_parts.append(f"  {tr('cpu_info')}: {cpu_usage:.0f}%")
        if self.visibility_settings.get('tray_ram', True):
            tray_parts.append(f"{tr('ram_loading')}: {ram_used:.1f}GB")

        tray_text = "" + "  ".join(tray_parts)
        self.indicator.set_label(tray_text, "")
        self.indicator.set_label(tray_text, "")

        """Логирование"""
        if self.visibility_settings.get('logging_enabled', True):
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"CPU: {cpu_usage:.0f}% {cpu_temp}°C | "
                            f"RAM: {ram_used:.1f}/{ram_total:.1f} GB | "
                            f"SWAP: {swap_used:.1f}/{swap_total:.1f} GB | "
                            f"Disk: {disk_used:.1f}/{disk_total:.1f} GB | "
                            f"Net: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s | "
                            f"Uptime: {uptime}\n")
            except Exception as e:
                print("Ошибка записи в лог:", e)
        return True

    def quit(self, *args):
        Gtk.main_quit()

    def run(self):
        GLib.timeout_add_seconds(time_update, self.update_info)
        Gtk.main()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()