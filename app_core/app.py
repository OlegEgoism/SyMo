from __future__ import annotations

import json
import logging
import platform
from collections import deque
from datetime import datetime
from queue import Empty, Full, Queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

import gi

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppInd

gi.require_version("Gtk", "3.0")

import psutil
from gi.repository import Gtk, GLib, Gdk
from pynput import keyboard, mouse

from .constants import (
    APP_ID,
    APP_NAME,
    ICON_FALLBACK,
    LOG_FILE,
    SETTINGS_FILE,
    TIME_UPDATE_SEC,
    GRAPH_HISTORY_MINUTES_DEFAULT,
    GRAPH_HISTORY_MINUTES_MIN,
    GRAPH_HISTORY_MINUTES_MAX,
    SUPPORTED_LANGS,
    MENU_ORDER_DEFAULT,
)
from .dialogs import SettingsDialog
from .localization import tr, detect_system_language, set_language, get_language
from .logging_utils import rotate_log_if_needed
from notifications import TelegramNotifier, DiscordNotifier
from .power_control import PowerControl
from .system_usage import SystemUsage
from .click_tracker import increment_keyboard, increment_mouse, get_counts

logger = logging.getLogger(__name__)



def _text_width(text_extents) -> float:
    """Return cairo text extents width for both object- and tuple-based APIs."""
    width = getattr(text_extents, "width", None)
    if width is not None:
        return float(width)
    try:
        # tuple API: (x_bearing, y_bearing, width, height, x_advance, y_advance)
        return float(text_extents[2])
    except Exception:
        return 0.0

LANGUAGE_FLAGS = {
    'ru': '🇷🇺',
    'en': '🇬🇧',
    'cn': '🇨🇳',
    'de': '🇩🇪',
    'it': '🇮🇹',
    'es': '🇪🇸',
    'tr': '🇹🇷',
    'fr': '🇫🇷',
}

class SystemTrayApp:
    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self.load_settings()

        if not self.visibility_settings.get('language'):
            self.visibility_settings['language'] = detect_system_language()
            self.save_settings()
        set_language(self.visibility_settings['language'])

        self.indicator = AppInd.Indicator.new(APP_ID, ICON_FALLBACK, AppInd.IndicatorCategory.SYSTEM_SERVICES)
        icon_candidates = [
            Path(__file__).resolve().parent / "logo.png",
            Path(__file__).resolve().parent.parent / "logo.png",
            Path.cwd() / "logo.png",
        ]
        icon_path = next((path for path in icon_candidates if path.exists()), None)
        try:
            if icon_path:
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
        self._notification_stop_event = threading.Event()
        self._telegram_queue: Queue[Optional[str]] = Queue(maxsize=1)
        self._discord_queue: Queue[Optional[str]] = Queue(maxsize=1)
        self._telegram_worker = threading.Thread(
            target=self._notification_worker,
            args=(self._telegram_queue, self.telegram_notifier.send_message, "Telegram"),
            daemon=True,
        )
        self._discord_worker = threading.Thread(
            target=self._notification_worker,
            args=(self._discord_queue, self.discord_notifier.send_message, "Discord"),
            daemon=True,
        )
        self._telegram_worker.start()
        self._discord_worker.start()

        self.telegram_notifier.set_power_control(self.power_control)
        if self.telegram_notifier.enabled:
            self.telegram_notifier.start_bot()

        self.settings_dialog: Optional[SettingsDialog] = None
        self._progress_dialog: Optional[Gtk.MessageDialog] = None

        self.cpu_graph_window: Optional[Gtk.Window] = None
        self.cpu_graph_area: Optional[Gtk.DrawingArea] = None
        self.cpu_graph_hint_label: Optional[Gtk.Label] = None
        graph_points = self._graph_history_points(self.visibility_settings['graph_history_minutes'])
        self.cpu_history = deque(maxlen=graph_points)

        self.ram_graph_window: Optional[Gtk.Window] = None
        self.ram_graph_area: Optional[Gtk.DrawingArea] = None
        self.ram_graph_hint_label: Optional[Gtk.Label] = None
        self.ram_history = deque(maxlen=graph_points)

        self.swap_graph_window: Optional[Gtk.Window] = None
        self.swap_graph_area: Optional[Gtk.DrawingArea] = None
        self.swap_graph_hint_label: Optional[Gtk.Label] = None
        self.swap_history = deque(maxlen=graph_points)

        self.disk_graph_window: Optional[Gtk.Window] = None
        self.disk_graph_area: Optional[Gtk.DrawingArea] = None
        self.disk_graph_hint_label: Optional[Gtk.Label] = None
        self.disk_history = deque(maxlen=graph_points)

        self.net_graph_window: Optional[Gtk.Window] = None
        self.net_graph_area: Optional[Gtk.DrawingArea] = None
        self.net_graph_hint_label: Optional[Gtk.Label] = None
        self.net_history = deque(maxlen=graph_points)

        self.keyboard_graph_window: Optional[Gtk.Window] = None
        self.keyboard_graph_area: Optional[Gtk.DrawingArea] = None
        self.keyboard_graph_hint_label: Optional[Gtk.Label] = None
        self.keyboard_history = deque(maxlen=graph_points)

        self.mouse_graph_window: Optional[Gtk.Window] = None
        self.mouse_graph_area: Optional[Gtk.DrawingArea] = None
        self.mouse_graph_hint_label: Optional[Gtk.Label] = None
        self.mouse_history = deque(maxlen=graph_points)

        self.graph_zoom_state: Dict[str, Dict[str, float]] = {
            'cpu': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
            'ram': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
            'swap': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
            'disk': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
            'net': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
            'keyboard': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
            'mouse': {'scale': 1.0, 'center': 1.0, 'dragging': 0.0, 'last_x': 0.0, 'hovering': 0.0, 'hover_x': 0.0, 'hover_y': 0.0},
        }

        if self.visibility_settings.get('logging_enabled', True) and not LOG_FILE.exists():
            try:
                LOG_FILE.write_text("", encoding="utf-8")
            except Exception as e:
                print("Не удалось создать файл лога:", e)

    @staticmethod
    def _thread(target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()

    def _enqueue_latest_notification(self, queue: Queue[Optional[str]], message: Optional[str]) -> None:
        payload = None if message is None else str(message)
        while True:
            try:
                queue.put_nowait(payload)
                return
            except Full:
                try:
                    queue.get_nowait()
                    queue.task_done()
                except Empty:
                    return

    def _notification_worker(self, queue: Queue[Optional[str]], sender, channel_name: str) -> None:
        while not self._notification_stop_event.is_set():
            try:
                message = queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                if message is None:
                    return
                sender(message)
            except Exception as e:
                logger.exception("Ошибка отправки уведомления (%s): %s", channel_name, e)
            finally:
                queue.task_done()

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


    def _detect_cpu_model(self) -> str:
        try:
            proc_info = Path("/proc/cpuinfo")
            if proc_info.exists():
                for line in proc_info.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if ":" in line and line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass

        return platform.processor() or tr('unknown_value')

    def _build_system_info_text(self) -> str:
        uname = platform.uname()
        cpu_count = psutil.cpu_count(logical=False) or 0
        cpu_threads = psutil.cpu_count(logical=True) or 0
        cpu_freq = psutil.cpu_freq()
        ram = psutil.virtual_memory()

        freq_text = tr('unknown_value')
        if cpu_freq and cpu_freq.max:
            freq_text = f"{cpu_freq.max / 1000:.2f} GHz"
        elif cpu_freq and cpu_freq.current:
            freq_text = f"{cpu_freq.current / 1000:.2f} GHz"

        return "\n".join([
            f"{tr('system_label')}: {uname.system} {uname.release}",
            f"{tr('hostname_label')}: {uname.node}",
            f"{tr('architecture_label')}: {uname.machine}",
            "",
            f"{tr('cpu_label')}: {self._detect_cpu_model()}",
            f"{tr('cores_label')}: {cpu_count}",
            f"{tr('threads_label')}: {cpu_threads}",
            f"{tr('cpu_frequency_label')}: {freq_text}",
            "",
            f"{tr('ram_total_label')}: {ram.total / (1024 ** 3):.2f} {tr('gb')}",
        ])

    def on_system_info_click(self, *_):
        try:
            info_text = self._build_system_info_text()
        except Exception as e:
            self._show_message(tr('error'), f"{tr('system_info_error')}: {e}")
            return

        self._show_message(tr('system_info_title'), info_text)

    def create_menu(self):
        self.menu = Gtk.Menu()

        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.cpu_temp_item.connect("activate", self.show_cpu_graph)
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.ram_item.connect("activate", self.show_ram_graph)
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.swap_item.connect("activate", self.show_swap_graph)
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.disk_item.connect("activate", self.show_disk_graph)
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.net_item.connect("activate", self.show_net_graph)
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.keyboard_item = Gtk.MenuItem(label=f"{tr('keyboard_clicks')}: 0")
        self.keyboard_item.connect("activate", self.show_keyboard_graph)
        self.mouse_item = Gtk.MenuItem(label=f"{tr('mouse_clicks')}: 0")
        self.mouse_item.connect("activate", self.show_mouse_graph)

        self.ping_item = Gtk.MenuItem(label=tr('ping_network'))
        self.ping_item.connect("activate", self.on_ping_click)
        self.system_info_item = Gtk.MenuItem(label=tr('system_info'))
        self.system_info_item.connect("activate", self.on_system_info_click)
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

        from .language import LANGUAGES

        self.language_menu = Gtk.Menu()
        group_root = None
        for code in SUPPORTED_LANGS:
            language_name = (LANGUAGES.get(code) or LANGUAGES.get('en', {})).get('language_name', code)
            flag = LANGUAGE_FLAGS.get(code, '🏳️')
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group_root, f"{flag} {language_name}")
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

        self.menu.append(self.main_separator)
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
            self._refresh_cpu_graph_texts()
            self._refresh_ram_graph_texts()
            self._refresh_swap_graph_texts()
            self._refresh_disk_graph_texts()
            self._refresh_net_graph_texts()
            self._refresh_keyboard_graph_texts()
            self._refresh_mouse_graph_texts()

    def load_settings(self) -> Dict:
        default = {
            'cpu': True, 'ram': True, 'swap': True, 'disk': True, 'net': True, 'uptime': True,
            'tray_cpu': True, 'tray_ram': True, 'keyboard_clicks': True, 'mouse_clicks': True,
            'language': None, 'logging_enabled': True,
            'show_power_off': True, 'show_reboot': True, 'show_lock': True, 'show_timer': True,
            'max_log_mb': 5, 'ping_network': True, 'show_system_info': True,
            'graph_history_minutes': GRAPH_HISTORY_MINUTES_DEFAULT,
            'menu_order': MENU_ORDER_DEFAULT.copy(),
        }
        try:
            if self.settings_file.exists():
                saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
                default.update(saved)
        except Exception as e:
            print(f"Ошибка загрузки настроек из {self.settings_file}: {e}")
        default['graph_history_minutes'] = self._sanitize_graph_history_minutes(default.get('graph_history_minutes'))
        default['menu_order'] = self._normalize_menu_order(default.get('menu_order'))
        return default

    @staticmethod
    def _sanitize_graph_history_minutes(value) -> int:
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            minutes = GRAPH_HISTORY_MINUTES_DEFAULT
        return max(GRAPH_HISTORY_MINUTES_MIN, min(GRAPH_HISTORY_MINUTES_MAX, minutes))

    @staticmethod
    def _graph_history_points(minutes: int) -> int:
        return max(1, minutes * 60 // TIME_UPDATE_SEC)

    def _set_graph_history_window(self, minutes) -> None:
        sanitized_minutes = self._sanitize_graph_history_minutes(minutes)
        self.visibility_settings['graph_history_minutes'] = sanitized_minutes
        maxlen = self._graph_history_points(sanitized_minutes)

        self.cpu_history = deque(self.cpu_history, maxlen=maxlen)
        self.ram_history = deque(self.ram_history, maxlen=maxlen)
        self.swap_history = deque(self.swap_history, maxlen=maxlen)
        self.disk_history = deque(self.disk_history, maxlen=maxlen)
        self.net_history = deque(self.net_history, maxlen=maxlen)
        self.keyboard_history = deque(self.keyboard_history, maxlen=maxlen)
        self.mouse_history = deque(self.mouse_history, maxlen=maxlen)

    def save_settings(self) -> None:
        try:
            self.settings_file.write_text(json.dumps(self.visibility_settings, indent=2), encoding="utf-8")
        except Exception as e:
            print("Ошибка сохранения настроек:", e)

    def _normalize_menu_order(self, order) -> list[str]:
        unique = []
        for key in order or []:
            if key in MENU_ORDER_DEFAULT and key not in unique:
                unique.append(key)
        for key in MENU_ORDER_DEFAULT:
            if key not in unique:
                unique.append(key)
        return unique

    def update_menu_visibility(self) -> None:
        children = list(self.menu.get_children()) if hasattr(self, 'menu') else []
        keep = [
            getattr(self, 'main_separator', None),
            getattr(self, 'power_separator', None),
            getattr(self, 'exit_separator', None),
            getattr(self, 'language_menu_item', None),
            getattr(self, 'settings_item', None),
            getattr(self, 'quit_item', None),
            getattr(self, 'ping_top_sep', None),
            getattr(self, 'ping_bottom_sep', None),
        ]
        keep = [x for x in keep if x is not None]

        for ch in children:
            if ch not in keep:
                try:
                    self.menu.remove(ch)
                except Exception:
                    pass

        ordered_items = {
            'cpu': self.cpu_temp_item,
            'ram': self.ram_item,
            'swap': self.swap_item,
            'disk': self.disk_item,
            'net': self.net_item,
            'keyboard_clicks': self.keyboard_item,
            'mouse_clicks': self.mouse_item,
            'uptime': self.uptime_item,
            'show_power_off': self.power_off_item,
            'show_reboot': self.reboot_item,
            'show_lock': self.lock_item,
            'show_timer': self.timer_item,
            'ping_network': self.ping_item,
            'show_system_info': self.system_info_item,
        }

        menu_order = self._normalize_menu_order(self.visibility_settings.get('menu_order'))
        self.visibility_settings['menu_order'] = menu_order

        visible_order = [key for key in menu_order if self.visibility_settings.get(key, True)]

        power_shown = any(key in visible_order for key in ('show_power_off', 'show_reboot', 'show_lock', 'show_timer'))
        if power_shown and getattr(self, 'power_separator', None) is not None:
            self.menu.append(self.power_separator)

        inserted_ping_sep = False
        for key in visible_order:
            if key == 'ping_network':
                if not inserted_ping_sep and getattr(self, 'ping_top_sep', None) is not None:
                    self.menu.append(self.ping_top_sep)
                self.menu.append(self.ping_item)
                if getattr(self, 'ping_bottom_sep', None) is not None:
                    self.menu.append(self.ping_bottom_sep)
                inserted_ping_sep = True
                continue
            self.menu.append(ordered_items[key])

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
                menu_visibility = dialog.get_menu_visibility()
                vs.update(menu_visibility)
                vs['tray_cpu'] = dialog.tray_cpu_check.get_active()
                vs['tray_ram'] = dialog.tray_ram_check.get_active()
                vs['logging_enabled'] = dialog.logging_check.get_active()
                vs['menu_order'] = dialog.get_menu_order()
                vs['max_log_mb'] = int(dialog.logsize_spin.get_value())
                self._set_graph_history_window(dialog.graph_history_spin.get_value_as_int())

                tel_enabled_before = getattr(self, 'telegram_notifier', TelegramNotifier()).enabled
                if self.telegram_notifier.save_config(
                        dialog.token_entry.get_text().strip(),
                        dialog.chat_id_entry.get_text().strip(),
                        dialog.telegram_enable_check.get_active(),
                        int(dialog.interval_spin.get_value()),
                        dialog.screenshot_quality_combo.get_active_id() or "medium"
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


    @staticmethod
    def _safe_call(func, default):
        try:
            return func()
        except Exception:
            return default

    @staticmethod
    def _plural_ru(value: int) -> str:
        value = abs(int(value))
        if value % 10 == 1 and value % 100 != 11:
            return 'one'
        if 2 <= value % 10 <= 4 and (value % 100 < 10 or value % 100 >= 20):
            return 'few'
        return 'many'

    def _format_uptime_localized(self, raw_uptime: str) -> str:
        parts = (raw_uptime or "").split(", ", 1)
        if len(parts) != 2:
            return raw_uptime

        day_part, time_part = parts
        day_tokens = day_part.split()
        if len(day_tokens) != 2 or not day_tokens[0].isdigit():
            return raw_uptime

        days = int(day_tokens[0])
        lang = get_language()
        plural_key = self._plural_ru(days) if lang == 'ru' else ('one' if days == 1 else 'many')
        day_label = tr(f'uptime_day_{plural_key}')
        if day_label == f'uptime_day_{plural_key}':
            day_label = 'day' if days == 1 else 'days'
        return f"{days} {day_label}, {time_part}"

    def update_info(self) -> bool:
        try:
            kbd, ms = self._safe_call(get_counts, (0, 0))

            cpu_temp = self._safe_call(SystemUsage.get_cpu_temp, 0)
            cpu_usage = self._safe_call(SystemUsage.get_cpu_usage, 0.0)
            ram_used, ram_total = self._safe_call(SystemUsage.get_ram_usage, (0.0, 0.0))
            disk_used, disk_total = self._safe_call(SystemUsage.get_disk_usage, (0.0, 0.0))
            swap_used, swap_total = self._safe_call(SystemUsage.get_swap_usage, (0.0, 0.0))
            net_recv_speed, net_sent_speed = self._safe_call(
                lambda: SystemUsage.get_network_speed(self.prev_net_data),
                (0.0, 0.0),
            )
            uptime = self._safe_call(SystemUsage.get_uptime, "00:00:00")
            uptime_display = self._format_uptime_localized(uptime)

            self._update_ui(cpu_temp, cpu_usage,
                            ram_used, ram_total,
                            disk_used, disk_total,
                            swap_used, swap_total,
                            net_recv_speed, net_sent_speed,
                            uptime_display, kbd, ms)

            now = time.time()
            if (self.telegram_notifier.enabled and
                    now - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval):
                self._thread(self.send_telegram_notification,
                             cpu_temp, cpu_usage, ram_used, ram_total,
                             disk_used, disk_total, swap_used, swap_total,
                             net_recv_speed, net_sent_speed, uptime_display, kbd, ms)
                self.last_telegram_notification_time = now

            if (self.discord_notifier.enabled and
                    now - self.last_discord_notification_time >= self.discord_notifier.notification_interval):
                self._thread(self.send_discord_notification,
                             cpu_temp, cpu_usage, ram_used, ram_total,
                             disk_used, disk_total, swap_used, swap_total,
                             net_recv_speed, net_sent_speed, uptime_display, kbd, ms)
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
                            f"Uptime: {uptime_display} | "
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
        self._enqueue_latest_notification(self._telegram_queue, msg)

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
        self._enqueue_latest_notification(self._discord_queue, msg)

    @staticmethod
    def _normalize_cpu_sample(cpu_usage: object, cpu_temp: object) -> tuple[float, float]:
        try:
            usage = float(cpu_usage)
        except (TypeError, ValueError):
            usage = 0.0
        try:
            temp = float(cpu_temp)
        except (TypeError, ValueError):
            temp = 0.0
        return max(0.0, min(100.0, usage)), max(0.0, min(150.0, temp))

    def _append_cpu_sample(self, cpu_usage: object, cpu_temp: object) -> None:
        usage, temp = self._normalize_cpu_sample(cpu_usage, cpu_temp)
        self.cpu_history.append((time.time(), usage, temp))

    def show_cpu_graph(self, _w=None):
        if self.cpu_graph_window and self.cpu_graph_window.get_visible():
            self.cpu_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('cpu_info')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_cpu_graph)
        self._connect_graph_zoom(area, 'cpu')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_cpu_graph_destroy)

        self.cpu_graph_window = window
        self.cpu_graph_area = area
        self._refresh_cpu_graph_texts()

        window.show_all()

    def _on_cpu_graph_destroy(self, _w):
        self.cpu_graph_window = None
        self.cpu_graph_area = None
        self.cpu_graph_hint_label = None

    def _refresh_cpu_graph_texts(self) -> None:
        if self.cpu_graph_window:
            self.cpu_graph_window.set_title(f"{tr('cpu_info')} — {tr('system_status')}")
        if self.cpu_graph_area:
            self.cpu_graph_area.queue_draw()


    @staticmethod
    def _draw_no_data(widget, cr, message: str) -> None:
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(14)
        cr.set_source_rgb(0.78, 0.78, 0.78)
        ext = cr.text_extents(message)
        x = max(8, (width - _text_width(ext)) / 2)
        y = max(20, height / 2)
        cr.move_to(x, y)
        cr.show_text(message)

    @staticmethod
    def _clamp(value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    def _visible_samples(self, graph_key: str, samples: list[tuple]) -> list[tuple]:
        if len(samples) <= 2:
            return samples
        state = self.graph_zoom_state.get(graph_key)
        if not state:
            return samples

        scale = self._clamp(float(state.get('scale', 1.0)), 1.0, 40.0)
        if scale <= 1.0:
            return samples

        total = len(samples)
        window_len = max(2, int(round(total / scale)))
        center = self._clamp(float(state.get('center', 1.0)), 0.0, 1.0)
        center_idx = int(round(center * (total - 1)))

        start = center_idx - (window_len // 2)
        max_start = max(0, total - window_len)
        start = min(max(0, start), max_start)
        end = start + window_len
        return samples[start:end]

    def _connect_graph_zoom(self, area: Gtk.DrawingArea, graph_key: str) -> None:
        area.set_events(
            area.get_events()
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        area.connect('scroll-event', self._on_graph_scroll_event, graph_key)
        area.connect('button-press-event', self._on_graph_button_press_event, graph_key)
        area.connect('motion-notify-event', self._on_graph_motion_notify_event, graph_key)
        area.connect('button-release-event', self._on_graph_button_release_event, graph_key)
        area.connect('leave-notify-event', self._on_graph_leave_notify_event, graph_key)

    def _on_graph_scroll_event(self, widget, event, graph_key: str):
        state = self.graph_zoom_state.get(graph_key)
        if state is None:
            return False

        width = max(1, widget.get_allocated_width())
        anchor_x = self._clamp(float(getattr(event, 'x', width / 2)), 0.0, float(width))
        anchor_ratio = anchor_x / width

        old_scale = self._clamp(float(state.get('scale', 1.0)), 1.0, 40.0)
        zoom_factor = 1.0
        if event.direction == Gdk.ScrollDirection.UP:
            zoom_factor = 1.2
        elif event.direction == Gdk.ScrollDirection.DOWN:
            zoom_factor = 1 / 1.2
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            delta_y = float(getattr(event, 'delta_y', 0.0))
            zoom_factor = 1.2 if delta_y < 0 else (1 / 1.2 if delta_y > 0 else 1.0)

        if zoom_factor == 1.0:
            return False

        new_scale = self._clamp(old_scale * zoom_factor, 1.0, 40.0)
        old_span = 1.0 / old_scale
        new_span = 1.0 / new_scale
        old_center = self._clamp(float(state.get('center', 1.0)), 0.0, 1.0)
        old_left = self._clamp(old_center - old_span / 2, 0.0, max(0.0, 1.0 - old_span))
        anchor_global = old_left + anchor_ratio * old_span

        new_left = anchor_global - anchor_ratio * new_span
        new_left = self._clamp(new_left, 0.0, max(0.0, 1.0 - new_span))
        new_center = new_left + new_span / 2

        state['scale'] = new_scale
        state['center'] = self._clamp(new_center, 0.0, 1.0)
        widget.queue_draw()
        return True

    def _on_graph_button_press_event(self, _widget, event, graph_key: str):
        if event.button != Gdk.BUTTON_PRIMARY:
            return False
        state = self.graph_zoom_state.get(graph_key)
        if state is None:
            return False
        state['dragging'] = 1.0
        state['last_x'] = float(getattr(event, 'x', 0.0))
        return True

    def _on_graph_motion_notify_event(self, widget, event, graph_key: str):
        state = self.graph_zoom_state.get(graph_key)
        if state is None:
            return False

        state['hovering'] = 1.0
        state['hover_x'] = float(getattr(event, 'x', 0.0))
        state['hover_y'] = float(getattr(event, 'y', 0.0))

        if state.get('dragging', 0.0) < 0.5:
            widget.queue_draw()
            return False

        width = max(1, widget.get_allocated_width())
        old_scale = self._clamp(float(state.get('scale', 1.0)), 1.0, 40.0)
        span = 1.0 / old_scale
        if span >= 1.0:
            state['last_x'] = float(getattr(event, 'x', 0.0))
            return False

        current_x = self._clamp(float(getattr(event, 'x', 0.0)), 0.0, float(width))
        prev_x = self._clamp(float(state.get('last_x', current_x)), 0.0, float(width))
        delta_x = current_x - prev_x
        state['last_x'] = current_x

        old_center = self._clamp(float(state.get('center', 1.0)), 0.0, 1.0)
        new_center = old_center - (delta_x / width) * span
        state['center'] = self._clamp(new_center, span / 2, 1.0 - span / 2)
        widget.queue_draw()
        return True

    def _on_graph_button_release_event(self, _widget, event, graph_key: str):
        if event.button != Gdk.BUTTON_PRIMARY:
            return False
        state = self.graph_zoom_state.get(graph_key)
        if state is None:
            return False
        state['dragging'] = 0.0
        return True

    def _on_graph_leave_notify_event(self, widget, _event, graph_key: str):
        state = self.graph_zoom_state.get(graph_key)
        if state is None:
            return False
        state['hovering'] = 0.0
        widget.queue_draw()
        return False

    def _draw_graph_hover_info(self,
                              widget,
                              cr,
                              graph_key: str,
                              samples: list[tuple],
                              margin_left: float,
                              margin_top: float,
                              plot_w: float,
                              plot_h: float,
                              formatter: Callable[[tuple], list[str]]) -> None:
        state = self.graph_zoom_state.get(graph_key)
        if not state or state.get('hovering', 0.0) < 0.5 or not samples:
            return

        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        hover_x = self._clamp(float(state.get('hover_x', 0.0)), 0.0, float(width))
        hover_y = self._clamp(float(state.get('hover_y', 0.0)), 0.0, float(height))

        left = margin_left
        right = margin_left + plot_w
        top = margin_top
        bottom = margin_top + plot_h
        if hover_x < left or hover_x > right or hover_y < top or hover_y > bottom:
            return

        if len(samples) <= 1:
            idx = 0
            point_x = left
        else:
            ratio = self._clamp((hover_x - left) / max(1.0, plot_w), 0.0, 1.0)
            idx = int(round(ratio * (len(samples) - 1)))
            idx = max(0, min(len(samples) - 1, idx))
            point_x = left + plot_w * idx / (len(samples) - 1)

        sample = samples[idx]
        lines = formatter(sample)
        if not lines:
            return

        cr.set_source_rgba(1.0, 1.0, 1.0, 0.22)
        cr.set_line_width(1)
        cr.move_to(point_x, top)
        cr.line_to(point_x, bottom)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(11)
        padding = 6
        line_height = 14
        max_w = 0.0
        for line in lines:
            max_w = max(max_w, _text_width(cr.text_extents(line)))

        box_w = max_w + padding * 2
        box_h = line_height * len(lines) + padding * 2
        box_x = self._clamp(hover_x + 12, 4.0, max(4.0, width - box_w - 4))
        box_y = self._clamp(hover_y + 12, 4.0, max(4.0, height - box_h - 4))

        cr.set_source_rgba(0.05, 0.05, 0.05, 0.88)
        cr.rectangle(box_x, box_y, box_w, box_h)
        cr.fill()

        cr.set_source_rgb(0.96, 0.96, 0.96)
        for i, line in enumerate(lines):
            cr.move_to(box_x + padding, box_y + padding + line_height * (i + 1) - 3)
            cr.show_text(line)

    def _draw_cpu_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 48
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        # Left-side numeric Y axis labels for CPU load (%)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.72, 0.82, 0.9)
        for i in range(5):
            cpu_mark = 100 - (25 * i)
            y = margin_top + (plot_h * i / 4)
            label = f"{cpu_mark}%"
            text_extents = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(text_extents) - 6), y + 4)
            cr.show_text(label)

        samples = self._visible_samples('cpu', list(self.cpu_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        max_temp = max(100.0, max(temp for _, _, temp in samples) + 5.0)

        def draw_line(selector, color, max_value):
            cr.set_source_rgb(*color)
            cr.set_line_width(2)
            for idx, sample in enumerate(samples):
                x = margin_left + plot_w * idx / (len(samples) - 1)
                value = selector(sample)
                y = margin_top + plot_h * (1.0 - (value / max_value))
                if idx == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()

        draw_line(lambda s: s[1], (0.1, 0.8, 1.0), 100.0)
        draw_line(lambda s: s[2], (1.0, 0.4, 0.2), max_temp)

        # Legend/signatures for displayed data
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)

        cr.set_source_rgb(0.1, 0.8, 1.0)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(0.88, 0.92, 1.0)
        cr.move_to(margin_left + 18, 12)
        cr.show_text(f"{tr('cpu')} (%)")

        cr.set_source_rgb(1.0, 0.4, 0.2)
        cr.rectangle(margin_left + 150, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(1.0, 0.88, 0.82)
        cr.move_to(margin_left + 168, 12)
        cr.show_text(f"{tr('temperature')}")

        last_usage = samples[-1][1]
        last_temp = samples[-1][2]
        values_text = f"{tr('cpu')}: {last_usage:.0f}%   {tr('temperature')}: {last_temp:.1f}°C"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'cpu',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"{tr('cpu')}: {sample[1]:.1f}%",
                f"{tr('temperature')}: {sample[2]:.1f}°C",
            ],
        )

        # Start and end time at the bottom
        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

    def _append_ram_sample(self, ram_used: object, ram_total: object) -> None:
        try:
            used = float(ram_used)
            total = float(ram_total)
            percent = (used / total * 100.0) if total > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            used, total, percent = 0.0, 0.0, 0.0
        percent = max(0.0, min(100.0, percent))
        self.ram_history.append((time.time(), used, total, percent))

    def show_ram_graph(self, _w=None):
        if self.ram_graph_window and self.ram_graph_window.get_visible():
            self.ram_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('ram_loading')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_ram_graph)
        self._connect_graph_zoom(area, 'ram')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_ram_graph_destroy)

        self.ram_graph_window = window
        self.ram_graph_area = area
        self._refresh_ram_graph_texts()

        window.show_all()

    def _on_ram_graph_destroy(self, _w):
        self.ram_graph_window = None
        self.ram_graph_area = None
        self.ram_graph_hint_label = None

    def _refresh_ram_graph_texts(self) -> None:
        if self.ram_graph_window:
            self.ram_graph_window.set_title(f"{tr('ram_loading')} — {tr('system_status')}")
        if self.ram_graph_area:
            self.ram_graph_area.queue_draw()

    def _draw_ram_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 48
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.72, 0.9, 0.72)
        for i in range(5):
            mark = 100 - (25 * i)
            y = margin_top + (plot_h * i / 4)
            label = f"{mark}%"
            text_extents = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(text_extents) - 6), y + 4)
            cr.show_text(label)

        samples = self._visible_samples('ram', list(self.ram_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        cr.set_source_rgb(0.35, 1.0, 0.35)
        cr.set_line_width(2)
        for idx, sample in enumerate(samples):
            x = margin_left + plot_w * idx / (len(samples) - 1)
            value = sample[3]
            y = margin_top + plot_h * (1.0 - (value / 100.0))
            if idx == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.set_source_rgb(0.35, 1.0, 0.35)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(0.9, 1.0, 0.9)
        cr.move_to(margin_left + 18, 12)
        cr.show_text(f"{tr('ram_loading')} (%)")

        last_used = samples[-1][1]
        last_total = samples[-1][2]
        last_percent = samples[-1][3]
        values_text = f"{tr('ram_loading')}: {last_used:.1f}/{last_total:.1f} GB ({last_percent:.0f}%)"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'ram',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"{tr('ram_loading')}: {sample[3]:.1f}%",
                f"{sample[1]:.1f}/{sample[2]:.1f} GB",
            ],
        )

        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

    def _append_swap_sample(self, swap_used: object, swap_total: object) -> None:
        try:
            used = float(swap_used)
            total = float(swap_total)
            percent = (used / total * 100.0) if total > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            used, total, percent = 0.0, 0.0, 0.0
        percent = max(0.0, min(100.0, percent))
        self.swap_history.append((time.time(), used, total, percent))

    def show_swap_graph(self, _w=None):
        if self.swap_graph_window and self.swap_graph_window.get_visible():
            self.swap_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('swap_loading')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_swap_graph)
        self._connect_graph_zoom(area, 'swap')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_swap_graph_destroy)

        self.swap_graph_window = window
        self.swap_graph_area = area
        self._refresh_swap_graph_texts()

        window.show_all()

    def _on_swap_graph_destroy(self, _w):
        self.swap_graph_window = None
        self.swap_graph_area = None
        self.swap_graph_hint_label = None

    def _refresh_swap_graph_texts(self) -> None:
        if self.swap_graph_window:
            self.swap_graph_window.set_title(f"{tr('swap_loading')} — {tr('system_status')}")
        if self.swap_graph_area:
            self.swap_graph_area.queue_draw()

    def _draw_swap_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 48
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.9, 0.72, 0.95)
        for i in range(5):
            mark = 100 - (25 * i)
            y = margin_top + (plot_h * i / 4)
            label = f"{mark}%"
            text_extents = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(text_extents) - 6), y + 4)
            cr.show_text(label)

        samples = self._visible_samples('swap', list(self.swap_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        cr.set_source_rgb(0.95, 0.55, 1.0)
        cr.set_line_width(2)
        for idx, sample in enumerate(samples):
            x = margin_left + plot_w * idx / (len(samples) - 1)
            value = sample[3]
            y = margin_top + plot_h * (1.0 - (value / 100.0))
            if idx == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.set_source_rgb(0.95, 0.55, 1.0)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(0.98, 0.88, 1.0)
        cr.move_to(margin_left + 18, 12)
        cr.show_text(f"{tr('swap_loading')} (%)")

        last_used = samples[-1][1]
        last_total = samples[-1][2]
        last_percent = samples[-1][3]
        values_text = f"{tr('swap_loading')}: {last_used:.1f}/{last_total:.1f} GB ({last_percent:.0f}%)"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'swap',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"{tr('swap_loading')}: {sample[3]:.1f}%",
                f"{sample[1]:.1f}/{sample[2]:.1f} GB",
            ],
        )

        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

    def _append_disk_sample(self, disk_used: object, disk_total: object) -> None:
        try:
            used = float(disk_used)
            total = float(disk_total)
            percent = (used / total * 100.0) if total > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            used, total, percent = 0.0, 0.0, 0.0
        percent = max(0.0, min(100.0, percent))
        self.disk_history.append((time.time(), used, total, percent))

    def show_disk_graph(self, _w=None):
        if self.disk_graph_window and self.disk_graph_window.get_visible():
            self.disk_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('disk_loading')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_disk_graph)
        self._connect_graph_zoom(area, 'disk')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_disk_graph_destroy)

        self.disk_graph_window = window
        self.disk_graph_area = area
        self._refresh_disk_graph_texts()

        window.show_all()

    def _on_disk_graph_destroy(self, _w):
        self.disk_graph_window = None
        self.disk_graph_area = None
        self.disk_graph_hint_label = None

    def _refresh_disk_graph_texts(self) -> None:
        if self.disk_graph_window:
            self.disk_graph_window.set_title(f"{tr('disk_loading')} — {tr('system_status')}")
        if self.disk_graph_area:
            self.disk_graph_area.queue_draw()

    def _draw_disk_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 48
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.7, 0.85, 1.0)
        for i in range(5):
            mark = 100 - (25 * i)
            y = margin_top + (plot_h * i / 4)
            label = f"{mark}%"
            text_extents = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(text_extents) - 6), y + 4)
            cr.show_text(label)

        samples = self._visible_samples('disk', list(self.disk_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        cr.set_source_rgb(0.35, 0.72, 1.0)
        cr.set_line_width(2)
        for idx, sample in enumerate(samples):
            x = margin_left + plot_w * idx / (len(samples) - 1)
            value = sample[3]
            y = margin_top + plot_h * (1.0 - (value / 100.0))
            if idx == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.set_source_rgb(0.35, 0.72, 1.0)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(0.88, 0.95, 1.0)
        cr.move_to(margin_left + 18, 12)
        cr.show_text(f"{tr('disk_loading')} (%)")

        last_used = samples[-1][1]
        last_total = samples[-1][2]
        last_percent = samples[-1][3]
        values_text = f"{tr('disk_loading')}: {last_used:.1f}/{last_total:.1f} GB ({last_percent:.0f}%)"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'disk',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"{tr('disk_loading')}: {sample[3]:.1f}%",
                f"{sample[1]:.1f}/{sample[2]:.1f} GB",
            ],
        )

        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

    def _append_net_sample(self, recv_speed: object, sent_speed: object) -> None:
        try:
            recv = max(0.0, float(recv_speed))
        except (TypeError, ValueError):
            recv = 0.0
        try:
            sent = max(0.0, float(sent_speed))
        except (TypeError, ValueError):
            sent = 0.0
        self.net_history.append((time.time(), recv, sent))

    def show_net_graph(self, _w=None):
        if self.net_graph_window and self.net_graph_window.get_visible():
            self.net_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('lan_speed')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_net_graph)
        self._connect_graph_zoom(area, 'net')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_net_graph_destroy)

        self.net_graph_window = window
        self.net_graph_area = area
        self._refresh_net_graph_texts()

        window.show_all()

    def _on_net_graph_destroy(self, _w):
        self.net_graph_window = None
        self.net_graph_area = None
        self.net_graph_hint_label = None

    def _refresh_net_graph_texts(self) -> None:
        if self.net_graph_window:
            self.net_graph_window.set_title(f"{tr('lan_speed')} — {tr('system_status')}")
        if self.net_graph_area:
            self.net_graph_area.queue_draw()

    def _draw_net_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 58
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        samples = self._visible_samples('net', list(self.net_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        max_speed = max(1.0, max(max(s[1], s[2]) for s in samples) * 1.15)

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.8, 0.8, 0.8)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            mark = max_speed * (1 - i / 4)
            label = f"{mark:.1f}"
            ext = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(ext) - 8), y + 4)
            cr.show_text(label)

        def draw_line(selector, color):
            cr.set_source_rgb(*color)
            cr.set_line_width(2)
            for idx, sample in enumerate(samples):
                x = margin_left + plot_w * idx / (len(samples) - 1)
                value = selector(sample)
                y = margin_top + plot_h * (1.0 - (value / max_speed))
                if idx == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()

        draw_line(lambda s: s[1], (0.25, 0.9, 0.35))
        draw_line(lambda s: s[2], (1.0, 0.75, 0.2))

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)

        cr.set_source_rgb(0.25, 0.9, 0.35)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(0.85, 1.0, 0.87)
        cr.move_to(margin_left + 18, 12)
        cr.show_text("↓ MB/s")

        cr.set_source_rgb(1.0, 0.75, 0.2)
        cr.rectangle(margin_left + 95, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(1.0, 0.94, 0.8)
        cr.move_to(margin_left + 113, 12)
        cr.show_text("↑ MB/s")

        last_recv = samples[-1][1]
        last_sent = samples[-1][2]
        values_text = f"{tr('lan_speed')}: ↓{last_recv:.1f} / ↑{last_sent:.1f} MB/s"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'net',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"↓ {sample[1]:.2f} MB/s",
                f"↑ {sample[2]:.2f} MB/s",
            ],
        )

        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

    def _append_keyboard_sample(self, keyboard_clicks: object) -> None:
        try:
            count = max(0, int(keyboard_clicks))
        except (TypeError, ValueError):
            count = 0
        self.keyboard_history.append((time.time(), count))

    def show_keyboard_graph(self, _w=None):
        if self.keyboard_graph_window and self.keyboard_graph_window.get_visible():
            self.keyboard_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('keyboard_clicks')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_keyboard_graph)
        self._connect_graph_zoom(area, 'keyboard')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_keyboard_graph_destroy)

        self.keyboard_graph_window = window
        self.keyboard_graph_area = area
        self._refresh_keyboard_graph_texts()

        window.show_all()

    def _on_keyboard_graph_destroy(self, _w):
        self.keyboard_graph_window = None
        self.keyboard_graph_area = None
        self.keyboard_graph_hint_label = None

    def _refresh_keyboard_graph_texts(self) -> None:
        if self.keyboard_graph_window:
            self.keyboard_graph_window.set_title(f"{tr('keyboard_clicks')} — {tr('system_status')}")
        if self.keyboard_graph_area:
            self.keyboard_graph_area.queue_draw()

    def _draw_keyboard_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 58
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        samples = self._visible_samples('keyboard', list(self.keyboard_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        max_count = max(1, max(s[1] for s in samples))
        y_max = max_count * 1.05

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.85, 0.85, 0.85)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            mark = int(y_max * (1 - i / 4))
            label = f"{mark}"
            ext = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(ext) - 8), y + 4)
            cr.show_text(label)

        cr.set_source_rgb(1.0, 0.86, 0.25)
        cr.set_line_width(2)
        for idx, sample in enumerate(samples):
            x = margin_left + plot_w * idx / (len(samples) - 1)
            value = sample[1]
            y = margin_top + plot_h * (1.0 - (value / y_max))
            if idx == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.set_source_rgb(1.0, 0.86, 0.25)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(1.0, 0.96, 0.78)
        cr.move_to(margin_left + 18, 12)
        cr.show_text(tr('keyboard_clicks'))

        last_count = samples[-1][1]
        values_text = f"{tr('keyboard_clicks')}: {last_count}"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'keyboard',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"{tr('keyboard_clicks')}: {sample[1]}",
            ],
        )

        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

    def _append_mouse_sample(self, mouse_clicks: object) -> None:
        try:
            count = max(0, int(mouse_clicks))
        except (TypeError, ValueError):
            count = 0
        self.mouse_history.append((time.time(), count))

    def show_mouse_graph(self, _w=None):
        if self.mouse_graph_window and self.mouse_graph_window.get_visible():
            self.mouse_graph_window.present()
            return

        window = Gtk.Window(title=f"{tr('mouse_clicks')} — {tr('system_status')}")
        window.set_default_size(720, 380)
        window.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area = Gtk.DrawingArea()
        area.set_size_request(680, 320)
        area.connect("draw", self._draw_mouse_graph)
        self._connect_graph_zoom(area, 'mouse')
        box.pack_start(area, True, True, 0)

        window.add(box)
        window.connect("destroy", self._on_mouse_graph_destroy)

        self.mouse_graph_window = window
        self.mouse_graph_area = area
        self._refresh_mouse_graph_texts()

        window.show_all()

    def _on_mouse_graph_destroy(self, _w):
        self.mouse_graph_window = None
        self.mouse_graph_area = None
        self.mouse_graph_hint_label = None

    def _refresh_mouse_graph_texts(self) -> None:
        if self.mouse_graph_window:
            self.mouse_graph_window.set_title(f"{tr('mouse_clicks')} — {tr('system_status')}")
        if self.mouse_graph_area:
            self.mouse_graph_area.queue_draw()

    def _draw_mouse_graph(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        margin_left = 58
        margin_right = 16
        margin_top = 16
        margin_bottom = 36

        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()

        cr.set_source_rgb(0.2, 0.2, 0.2)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            cr.move_to(margin_left, y)
            cr.line_to(margin_left + plot_w, y)
        cr.stroke()

        samples = self._visible_samples('mouse', list(self.mouse_history))
        if not samples:
            self._draw_no_data(widget, cr, 'No data yet…')
            return
        if len(samples) == 1:
            samples = [samples[0], samples[0]]

        max_count = max(1, max(s[1] for s in samples))
        y_max = max_count * 1.05

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgb(0.85, 0.85, 0.85)
        for i in range(5):
            y = margin_top + (plot_h * i / 4)
            mark = int(y_max * (1 - i / 4))
            label = f"{mark}"
            ext = cr.text_extents(label)
            cr.move_to(max(2, margin_left - _text_width(ext) - 8), y + 4)
            cr.show_text(label)

        cr.set_source_rgb(0.4, 0.9, 1.0)
        cr.set_line_width(2)
        for idx, sample in enumerate(samples):
            x = margin_left + plot_w * idx / (len(samples) - 1)
            value = sample[1]
            y = margin_top + plot_h * (1.0 - (value / y_max))
            if idx == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(12)
        cr.set_source_rgb(0.4, 0.9, 1.0)
        cr.rectangle(margin_left, 4, 12, 8)
        cr.fill()
        cr.set_source_rgb(0.85, 0.98, 1.0)
        cr.move_to(margin_left + 18, 12)
        cr.show_text(tr('mouse_clicks'))

        last_count = samples[-1][1]
        values_text = f"{tr('mouse_clicks')}: {last_count}"
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.set_font_size(12)
        ext = cr.text_extents(values_text)
        cr.move_to(width - margin_right - _text_width(ext), 12)
        cr.show_text(values_text)

        self._draw_graph_hover_info(
            widget,
            cr,
            'mouse',
            samples,
            margin_left,
            margin_top,
            plot_w,
            plot_h,
            lambda sample: [
                datetime.fromtimestamp(sample[0]).strftime("%H:%M:%S"),
                f"{tr('mouse_clicks')}: {sample[1]}",
            ],
        )

        start_ts = datetime.fromtimestamp(samples[0][0]).strftime("%H:%M:%S")
        end_ts = datetime.fromtimestamp(samples[-1][0]).strftime("%H:%M:%S")

        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_font_size(11)
        cr.move_to(margin_left, height - 10)
        cr.show_text(f"◀ {start_ts}")

        end_text = f"{end_ts} ▶"
        text_extents = cr.text_extents(end_text)
        cr.move_to(width - margin_right - _text_width(text_extents), height - 10)
        cr.show_text(end_text)

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
            self._append_cpu_sample(cpu_usage, cpu_temp)
            self._append_ram_sample(ram_used, ram_total)
            self._append_swap_sample(swap_used, swap_total)
            self._append_disk_sample(disk_used, disk_total)
            self._append_net_sample(net_recv_speed, net_sent_speed)
            self._append_keyboard_sample(keyboard_clicks_val)
            self._append_mouse_sample(mouse_clicks_val)
            if self.cpu_graph_area:
                self.cpu_graph_area.queue_draw()
            if self.ram_graph_area:
                self.ram_graph_area.queue_draw()
            if self.swap_graph_area:
                self.swap_graph_area.queue_draw()
            if self.disk_graph_area:
                self.disk_graph_area.queue_draw()
            if self.net_graph_area:
                self.net_graph_area.queue_draw()
            if self.keyboard_graph_area:
                self.keyboard_graph_area.queue_draw()
            if self.mouse_graph_area:
                self.mouse_graph_area.queue_draw()

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
        self._notification_stop_event.set()
        self._enqueue_latest_notification(self._telegram_queue, None)
        self._enqueue_latest_notification(self._discord_queue, None)
        for worker in (getattr(self, "_telegram_worker", None), getattr(self, "_discord_worker", None)):
            if worker and worker.is_alive():
                worker.join(timeout=1.0)

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

        if self.cpu_graph_window:
            try:
                self.cpu_graph_window.destroy()
            except Exception:
                pass
            self.cpu_graph_window = None
            self.cpu_graph_area = None
            self.cpu_graph_hint_label = None

        if self.ram_graph_window:
            try:
                self.ram_graph_window.destroy()
            except Exception:
                pass
            self.ram_graph_window = None
            self.ram_graph_area = None
            self.ram_graph_hint_label = None

        if self.swap_graph_window:
            try:
                self.swap_graph_window.destroy()
            except Exception:
                pass
            self.swap_graph_window = None
            self.swap_graph_area = None
            self.swap_graph_hint_label = None

        if self.disk_graph_window:
            try:
                self.disk_graph_window.destroy()
            except Exception:
                pass
            self.disk_graph_window = None
            self.disk_graph_area = None
            self.disk_graph_hint_label = None

        if self.net_graph_window:
            try:
                self.net_graph_window.destroy()
            except Exception:
                pass
            self.net_graph_window = None
            self.net_graph_area = None
            self.net_graph_hint_label = None

        if self.keyboard_graph_window:
            try:
                self.keyboard_graph_window.destroy()
            except Exception:
                pass
            self.keyboard_graph_window = None
            self.keyboard_graph_area = None
            self.keyboard_graph_hint_label = None

        if self.mouse_graph_window:
            try:
                self.mouse_graph_window.destroy()
            except Exception:
                pass
            self.mouse_graph_window = None
            self.mouse_graph_area = None
            self.mouse_graph_hint_label = None

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
        # Начальный снимок, чтобы графики не открывались полностью пустыми.
        self.update_info()
        GLib.timeout_add_seconds(TIME_UPDATE_SEC, self.update_info)
        Gtk.main()


if __name__ == "__main__":
    Gtk.init([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()
