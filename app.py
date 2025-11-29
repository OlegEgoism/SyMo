from __future__ import annotations

import json
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import gi
# --- GTK / Indicator ---
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppInd  # type: ignore

gi.require_version("Gtk", "3.0")


import psutil
from gi.repository import Gtk, GLib
from pynput import keyboard, mouse

from constants import (
    APP_ID,
    APP_NAME,
    ICON_FALLBACK,
    LOG_FILE,
    SETTINGS_FILE,
    TIME_UPDATE_SEC,
    SUPPORTED_LANGS,
)
from dialogs import SettingsDialog
from localization import tr, detect_system_language, set_language, get_language
from logging_utils import rotate_log_if_needed
from notifications import TelegramNotifier, DiscordNotifier
from power_control import PowerControl
from system_usage import SystemUsage
from click_tracker import increment_keyboard, increment_mouse, get_counts



class SystemTrayApp:
    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self.load_settings()

        if not self.visibility_settings.get('language'):
            self.visibility_settings['language'] = detect_system_language()
            self.save_settings()
        set_language(self.visibility_settings['language'])

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

        signal.signal(signal.SIGTERM, self.quit)
        signal.signal(signal.SIGINT, self.quit)

        self.power_control = PowerControl(self)
        self.power_control.set_parent_window(None)

        self.create_menu()

        net = psutil.net_io_counters()
        self.prev_net_data = {'recv': net.bytes_recv, 'sent': net.bytes_sent, 'time': time.time()}

        self.keyboard_listener = None
        self.mouse_listener = None
        self._notify_no_global_hooks = False
        self.init_listeners()

        self.telegram_notifier = TelegramNotifier()
        self.discord_notifier = DiscordNotifier()
        self.last_telegram_notification_time = 0.0
        self.last_discord_notification_time = 0.0

        self.telegram_notifier.set_power_control(self.power_control)
        if self.telegram_notifier.enabled:
            self.telegram_notifier.start_bot()

        self.settings_dialog: Optional[SettingsDialog] = None
        self._progress_dialog: Optional[Gtk.MessageDialog] = None

        if self.visibility_settings.get('logging_enabled', True) and not LOG_FILE.exists():
            try:
                LOG_FILE.write_text("", encoding="utf-8")
            except Exception as e:
                print("Не удалось создать файл лога:", e)

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

    def _close_progress_dialog(self):
        if self._progress_dialog:
            try:
                self._progress_dialog.destroy()
            except Exception:
                pass
            self._progress_dialog = None

    def on_key_press(self, _key):
        increment_keyboard()

    def on_mouse_click(self, _x, _y, _button, pressed):
        if pressed:
            increment_mouse()

    def on_ping_click(self, *_):
        host = "8.8.8.8"
        count = 4
        timeout = 5

        def show_progress():
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
            d.show()
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

            def finish():
                self._close_progress_dialog()
                self._show_message(title, msg)
                return False

            GLib.idle_add(finish)

        self._thread(worker)

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

        self.ping_item = Gtk.MenuItem(label=tr('ping_network'))
        self.ping_item.connect("activate", self.on_ping_click)
        self.ping_top_sep = Gtk.SeparatorMenuItem()
        self.ping_bottom_sep = Gtk.SeparatorMenuItem()

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

        from language import LANGUAGES

        self.language_menu = Gtk.Menu()
        group_root = None
        for code in SUPPORTED_LANGS:
            label = (LANGUAGES.get(code) or LANGUAGES.get('en', {})).get('language_name', code)
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group_root, label)
            if group_root is None:
                group_root = item
            item.set_active(code == get_language())
            item.connect("activate", self._on_language_selected, code)
            self.language_menu.append(item)
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
        if widget.get_active() and get_language() != lang_code:
            set_language(lang_code)
            self.visibility_settings['language'] = lang_code
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
                        self.telegram_notifier.stop_bot()
                        self.telegram_notifier.start_bot()

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

    def update_info(self) -> bool:
        try:
            kbd, ms = get_counts()

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
            if (self.telegram_notifier.enabled and
                    now - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval):
                self._thread(self.send_telegram_notification,
                             cpu_temp, cpu_usage, ram_used, ram_total,
                             disk_used, disk_total, swap_used, swap_total,
                             net_recv_speed, net_sent_speed, uptime, kbd, ms)
                self.last_telegram_notification_time = now

            if (self.discord_notifier.enabled and
                    now - self.last_discord_notification_time >= self.discord_notifier.notification_interval):
                self._thread(self.send_discord_notification,
                             cpu_temp, cpu_usage, ram_used, ram_total,
                             disk_used, disk_total, swap_used, swap_total,
                             net_recv_speed, net_sent_speed, uptime, kbd, ms)
                self.last_discord_notification_time = now

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
            return True

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
        d.set_title(title)
        d.run()
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

    def quit(self, *args):
        if self.telegram_notifier:
            self.telegram_notifier.stop_bot()

        for tid in ("_update_timer_id", "_notify_timer_id", "_action_timer_id"):
            _id = getattr(self.power_control, tid, None)
            if _id:
                GLib.source_remove(_id)
                setattr(self.power_control, tid, None)

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
        GLib.timeout_add_seconds(TIME_UPDATE_SEC, self.update_info)
        Gtk.main()


if __name__ == "__main__":
    Gtk.init([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()