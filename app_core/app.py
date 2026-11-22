from __future__ import annotations

import ctypes
import dataclasses
import fcntl
import importlib
import logging
import os
import platform
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Dict, Optional

import gi

gi.require_version("Gtk", "3.0")

import psutil
from gi.repository import Gio, Gtk, GLib

from .constants import (
    APP_ID,
    APP_NAME,
    DBUS_NAME,
    ICON_FALLBACK,
    LOG_FILE,
    SETTINGS_FILE,
    TIME_UPDATE_SEC,
    SUPPORTED_LANGS,
    POLL_INTERVAL_DEFAULT_SEC,
)
from . import autostart
from .click_tracker import increment_keyboard, increment_mouse, get_counts
from .dialogs import SettingsDialog
from .graphs import GraphWindow, build_graph_specs
from .history import MetricsHistory
from .language import LANGUAGES
from .localization import tr, detect_system_language, set_language, get_language
from .logging_utils import MetricsLogWriter, setup_logging
from .power_control import PowerControl, action_label
from .settings import (
    graph_line_color_rgb,
    load_settings,
    normalize_menu_order,
    sanitize_graph_history_minutes,
    sanitize_hex_color,
    sanitize_log_size_mb,
    sanitize_poll_interval,
    save_settings,
)
from .system_usage import MetricsSampler, MetricsSnapshot, format_count, format_temp, initial_network_state
from .ui import mapped_or_none, show_message
from notifications import TelegramNotifier, DiscordNotifier
from notifications.telegram import is_valid_chat_id, parse_user_ids
from notifications.base import NotificationDispatcher, format_status_message

logger = logging.getLogger(__name__)

# Пространство имён GI → библиотека, которую оно загружает. Ayatana первой:
# старый AppIndicator3 в Ubuntu 24.04 и новее уже не поставляется.
_APP_INDICATOR_LIBS = (
    ("AyatanaAppIndicator3", "libayatana-appindicator3.so.1"),
    ("AppIndicator3", "libappindicator3.so.1"),
)
APP_INDICATOR_PACKAGE = "gir1.2-ayatanaappindicator3-0.1"


def _load_app_indicator():
    """Модуль AppIndicator, чья библиотека действительно загружается.

    typelib может быть установлен без самой библиотеки: тогда импорт проходит,
    а падение случается только при создании значка.
    """
    for namespace, library in _APP_INDICATOR_LIBS:
        try:
            gi.require_version(namespace, "0.1")
            module = importlib.import_module(f"gi.repository.{namespace}")
            ctypes.CDLL(library)
            return module
        except (ValueError, ImportError, OSError) as e:
            logger.debug("%s недоступен: %s", namespace, e)
    return None


AppInd = _load_app_indicator()


def _add_unix_signal_handler(signum: int, handler) -> None:
    """GLib 2.80+ перенёс unix_signal_add в GLibUnix.signal_add, а старые версии
    PyGObject не дают доступа к прежнему имени."""
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signum, handler)
        return
    except (ValueError, ImportError, AttributeError):
        pass
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, handler)

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

POWER_MENU_KEYS = ('show_power_off', 'show_reboot', 'show_lock', 'show_timer')
INPUT_COUNTER_KINDS = ('keyboard', 'mouse')


def _is_wayland_session() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


class SystemTrayApp:
    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.visibility_settings: Dict[str, Any] = load_settings(self.settings_file)

        if not self.visibility_settings.get('language'):
            self.visibility_settings['language'] = detect_system_language()
            self.save_settings()
        set_language(self.visibility_settings['language'])

        self.indicator = AppInd.Indicator.new(APP_ID, ICON_FALLBACK, AppInd.IndicatorCategory.SYSTEM_SERVICES)
        self._set_indicator_icon()
        self.indicator.set_status(AppInd.IndicatorStatus.ACTIVE)

        self._quitting = False
        self._bus_name_id = 0
        self.power_control = PowerControl()
        self.settings_dialog: Optional[SettingsDialog] = None
        self._progress_dialog: Optional[Gtk.MessageDialog] = None

        self.graph_specs = build_graph_specs()
        self.graph_windows: Dict[str, GraphWindow] = {}
        self.metrics_history = MetricsHistory(self._graph_history_points(self.visibility_settings['graph_history_minutes']))
        self.latest_snapshot: Optional[MetricsSnapshot] = None

        # Кэши, чтобы не отправлять одинаковые подписи в AppIndicator (D-Bus) каждую секунду.
        self._label_cache: Dict[Gtk.MenuItem, str] = {}
        self._indicator_label: Optional[str] = None
        self._item_display_cache: Dict[str, str] = {}
        self._last_item_update_ts: Dict[str, float] = {}

        # Wayland не отдаёт приложениям чужие нажатия: глобальный хук увидел бы только
        # окна XWayland, и счётчики показывали бы заниженные числа как настоящие.
        self.input_counters_available = not _is_wayland_session()
        if not self.input_counters_available:
            logger.info("Сессия Wayland: счётчики клавиш и кликов отключены")
        self.keyboard_listener = None
        self.mouse_listener = None
        self.sync_input_listeners()

        self.create_menu()

        self.prev_net_data = initial_network_state()
        self.metrics_sampler = MetricsSampler()

        self.telegram_notifier = TelegramNotifier()
        self.discord_notifier = DiscordNotifier()
        # Интервалы уведомлений — по монотонным часам; -inf — «отправить при первом обновлении».
        self.last_telegram_notification_time = float("-inf")
        self.last_discord_notification_time = float("-inf")
        self.telegram_dispatcher = NotificationDispatcher(
            lambda text: self.telegram_notifier.send_message(text, html_markup=True), "Telegram")
        self.discord_dispatcher = NotificationDispatcher(self.discord_notifier.send_message, "Discord")

        self.telegram_notifier.set_power_control(self.power_control)
        self.telegram_notifier.set_app_context(self)
        self.telegram_notifier.start_bot()

        self._profiling_cycle_count = 0
        self._profiling_total_ms = 0.0
        self._profiling_max_ms = 0.0

        self.metrics_log = MetricsLogWriter(LOG_FILE)
        if self.visibility_settings.get('logging_enabled', True):
            try:
                self.metrics_log.ensure_exists()
            except OSError as e:
                logger.warning("Не удалось создать файл лога: %s", e)

    def _set_indicator_icon(self) -> None:
        icon_candidates = [
            Path(__file__).resolve().parent / "logo.png",
            Path(__file__).resolve().parent.parent / "logo.png",
            Path.cwd() / "logo.png",
        ]
        icon_path = next((path for path in icon_candidates if path.exists()), None)
        try:
            if icon_path and hasattr(self.indicator, "set_icon_full"):
                self.indicator.set_icon_full(str(icon_path), APP_NAME)
            elif icon_path:
                self.indicator.set_icon(str(icon_path))
            else:
                self.indicator.set_icon(ICON_FALLBACK)
        except Exception as e:
            logger.warning("Не удалось установить иконку: %s", e)
            self.indicator.set_icon(ICON_FALLBACK)

    def sync_input_listeners(self) -> None:
        """Глобальный хук клавиатуры или мыши работает, только пока его счётчик показан в меню."""
        for kind in INPUT_COUNTER_KINDS:
            attr = f'{kind}_listener'
            wanted = self.input_counters_available and self.visibility_settings.get(f'{kind}_clicks', True)
            listener = getattr(self, attr)
            if wanted and listener is None:
                setattr(self, attr, self._start_input_listener(kind))
            elif not wanted and listener is not None:
                self._stop_input_listener(listener)
                setattr(self, attr, None)
        if not self.input_counters_available:
            self._stop_input_listeners()

    def _start_input_listener(self, kind: str):
        # pynput падает уже при импорте, если нет X-дисплея: тогда отключаются
        # только счётчики, а не всё приложение.
        try:
            from pynput import keyboard, mouse
            if kind == 'keyboard':
                listener = keyboard.Listener(on_press=self.on_key_press, daemon=True)
            else:
                listener = mouse.Listener(on_click=self.on_mouse_click, daemon=True)
            listener.start()
            return listener
        except Exception as e:
            logger.warning("Счётчики клавиш и кликов недоступны: %s", e)
            self.input_counters_available = False
            return None

    @staticmethod
    def _stop_input_listener(listener) -> None:
        # stop() ждёт готовности хука и зависает навсегда, если поток pynput упал
        # при запуске, поэтому главный поток GTK его не ждёт.
        threading.Thread(target=listener.stop, name="pynput-stop", daemon=True).start()

    def _stop_input_listeners(self) -> None:
        for kind in INPUT_COUNTER_KINDS:
            attr = f'{kind}_listener'
            listener = getattr(self, attr)
            if listener is not None:
                self._stop_input_listener(listener)
                setattr(self, attr, None)

    def _input_counts(self) -> tuple[Optional[int], Optional[int]]:
        """Значения счётчиков; None — счётчик недоступен или скрыт (хук не работает)."""
        kbd, ms = get_counts()
        return (kbd if self.keyboard_listener is not None else None,
                ms if self.mouse_listener is not None else None)

    def _input_counter_unavailable_text(self, title_key: str) -> str:
        reason = " (Wayland)" if _is_wayland_session() else ""
        return f"{tr(title_key)}: N/A{reason}"

    def on_key_press(self, _key):
        increment_keyboard()

    def on_mouse_click(self, _x, _y, _button, pressed):
        if pressed:
            increment_mouse()

    @staticmethod
    def _graph_history_points(minutes: int) -> int:
        return max(1, minutes * 60 // TIME_UPDATE_SEC)

    def _set_graph_history_window(self, minutes) -> None:
        sanitized_minutes = sanitize_graph_history_minutes(minutes)
        self.visibility_settings['graph_history_minutes'] = sanitized_minutes
        self.metrics_history.resize(self._graph_history_points(sanitized_minutes))

    def save_settings(self) -> bool:
        return save_settings(self.settings_file, self.visibility_settings)

    def graph_line_color(self, key: str) -> tuple[float, float, float]:
        return graph_line_color_rgb(self.visibility_settings, key)

    def _new_item(self, key: str, label: str, callback) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=label)
        if callback is not None:
            item.connect("activate", callback)
        self.menu_items[key] = item
        return item

    def create_menu(self):
        self._label_cache.clear()
        self._item_display_cache.clear()
        self._last_item_update_ts.clear()
        self.menu_items: Dict[str, Gtk.MenuItem] = {}
        pc = self.power_control

        def open_graph(graph_key: str):
            return lambda *_: self.show_graph(graph_key)

        self._new_item('cpu', f"{tr('cpu_info')}: N/A", open_graph('cpu'))
        self._new_item('ram', f"{tr('ram_loading')}: N/A", open_graph('ram'))
        self._new_item('swap', f"{tr('swap_loading')}: N/A", open_graph('swap'))
        self._new_item('disk', f"{tr('disk_loading')}: N/A", open_graph('disk'))
        self._new_item('net', f"{tr('lan_speed')}: N/A", open_graph('net'))
        for kind in INPUT_COUNTER_KINDS:
            key = f'{kind}_clicks'
            if self.input_counters_available:
                self._new_item(key, f"{tr(key)}: 0", open_graph(kind))
            else:
                self._new_item(key, self._input_counter_unavailable_text(key), None)
        self._new_item('uptime', f"{tr('uptime_label')}: N/A", None)
        self._new_item('show_power_off', tr('power_off'),
                       lambda w: pc.confirm_action(w, pc.power_off, tr('confirm_text_power_off')))
        self._new_item('show_reboot', tr('reboot'),
                       lambda w: pc.confirm_action(w, pc.reboot, tr('confirm_text_reboot')))
        self._new_item('show_lock', tr('lock'),
                       lambda w: pc.confirm_action(w, pc.lock_screen, tr('confirm_text_lock')))
        self._new_item('show_timer', tr('settings'), pc.open_scheduler)
        self._new_item('ping_network', tr('ping_network'), self.on_ping_click)
        self._new_item('show_system_info', tr('system_info'), self.on_system_info_click)

        menu = Gtk.Menu()
        order = normalize_menu_order(self.visibility_settings.get('menu_order'))
        self.visibility_settings['menu_order'] = order
        visible = [key for key in order if self.visibility_settings.get(key, True)]

        settings_item = Gtk.MenuItem(label=tr('settings_label'))
        settings_item.connect("activate", self.show_settings)
        quit_item = Gtk.MenuItem(label=tr('exit_app'))
        quit_item.connect("activate", self.quit)

        # None — разделитель; лишние (в начале и подряд) отбрасываются ниже.
        entries: list[Optional[Gtk.MenuItem]] = []
        power_started = False
        for key in visible:
            if key in POWER_MENU_KEYS and not power_started:
                power_started = True
                entries.append(None)
            if key == 'ping_network':
                entries += [None, self.menu_items[key], None]
            else:
                entries.append(self.menu_items[key])
        entries += [None, self._build_language_menu_item(), settings_item, None, quit_item]

        prev_is_separator = True
        for entry in entries:
            if entry is None:
                if not prev_is_separator:
                    menu.append(Gtk.SeparatorMenuItem())
                prev_is_separator = True
            else:
                menu.append(entry)
                prev_is_separator = False

        menu.show_all()
        old_menu = getattr(self, 'menu', None)
        self.menu = menu
        self.indicator.set_menu(menu)
        if old_menu is not None:
            # Меню пересоздаётся и из обработчика его же пункта (выбор языка),
            # поэтому старое уничтожается после выхода из обработчика.
            GLib.idle_add(old_menu.destroy)

    def _build_language_menu_item(self) -> Gtk.MenuItem:
        language_menu = Gtk.Menu()
        group_root = None
        for code in SUPPORTED_LANGS:
            language_name = (LANGUAGES.get(code) or LANGUAGES.get('en', {})).get('language_name', code)
            flag = LANGUAGE_FLAGS.get(code, '🏳️')
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group_root, f"{flag} {language_name}")
            group_root = group_root or item
            item.set_active(code == get_language())
            item.connect("activate", self._on_language_selected, code)
            language_menu.append(item)
        language_item = Gtk.MenuItem(label=tr('language'))
        language_item.set_submenu(language_menu)
        return language_item

    def _on_language_selected(self, widget, lang_code: str):
        if widget.get_active() and get_language() != lang_code:
            set_language(lang_code)
            self.visibility_settings['language'] = lang_code
            if not self.save_settings():
                show_message(tr('error'), tr('settings_save_error'))
            self.create_menu()
            for window in self.graph_windows.values():
                window.refresh_texts()

    def _set_label(self, item: Gtk.MenuItem, text: str) -> None:
        if self._label_cache.get(item) != text:
            item.set_label(text)
            self._label_cache[item] = text

    def _set_indicator_label(self, text: str) -> None:
        if self._indicator_label != text:
            self.indicator.set_label(text, "")
            self._indicator_label = text

    def show_settings(self, _w=None):
        if self.settings_dialog and self.settings_dialog.get_mapped():
            self.settings_dialog.present()
            return
        dialog = SettingsDialog(None, self.visibility_settings)
        self.settings_dialog = dialog
        self.power_control.set_parent_window(dialog)
        dialog.connect("response", self._on_settings_response)
        dialog.show()

    def _on_settings_response(self, dialog: SettingsDialog, response: int) -> None:
        # Неверные поля Telegram: окно остаётся открытым с введёнными значениями.
        if response == Gtk.ResponseType.OK:
            error = self._telegram_settings_error(dialog)
            if error:
                show_message(tr('error'), error, dialog)
                return
        try:
            if response == Gtk.ResponseType.OK:
                self._apply_settings(dialog)
        except Exception as e:
            logger.exception("Ошибка применения настроек: %s", e)
        finally:
            self.power_control.set_parent_window(None)
            dialog.destroy()
            if self.settings_dialog is dialog:
                self.settings_dialog = None

    def _apply_settings(self, dialog: SettingsDialog) -> None:
        vs = self.visibility_settings
        vs.update(dialog.get_menu_visibility())
        vs['tray_cpu'] = dialog.tray_cpu_check.get_active()
        vs['tray_ram'] = dialog.tray_ram_check.get_active()
        vs['logging_enabled'] = dialog.logging_check.get_active()
        vs['show_graph_zoom_controls'] = dialog.show_zoom_controls_check.get_active()
        for color_key, color_value in dialog.get_graph_line_colors().items():
            vs[color_key] = sanitize_hex_color(color_value)
        vs['menu_order'] = dialog.get_menu_order()
        vs['max_log_mb'] = sanitize_log_size_mb(dialog.logsize_spin.get_value_as_int())
        self._set_graph_history_window(dialog.graph_history_spin.get_value_as_int())
        for key, spin in dialog.poll_interval_spins().items():
            vs[key] = sanitize_poll_interval(spin.get_value_as_int())
        if not vs['logging_enabled']:
            self.metrics_log.close()
        self.sync_input_listeners()

        want_autostart = dialog.autostart_check.get_active()
        if want_autostart != autostart.is_enabled() and not autostart.set_enabled(want_autostart):
            self._show_message(tr('error'), tr('autostart_error'))

        self._apply_telegram_settings(dialog)

        disc = self.discord_notifier
        disc_enabled_before = disc.enabled
        if disc.save_config(
                dialog.webhook_entry.get_text().strip(),
                dialog.discord_enable_check.get_active(),
                int(dialog.discord_interval_spin.get_value()),
        ):
            if disc.enabled and not disc_enabled_before:
                self.last_discord_notification_time = float("-inf")
        else:
            self._show_message(tr('error'), tr('setting_discord_error'))

        if not self.save_settings():
            self._show_message(tr('error'), tr('settings_save_error'))
        self.create_menu()

    @staticmethod
    def _telegram_settings_error(dialog: SettingsDialog) -> Optional[str]:
        chat_id = dialog.chat_id_entry.get_text().strip()
        if chat_id and not is_valid_chat_id(chat_id):
            return tr('telegram_chat_id_invalid')
        if parse_user_ids(dialog.allowed_users_entry.get_text()) is None:
            return tr('telegram_allowed_users_invalid')
        return None

    def _apply_telegram_settings(self, dialog: SettingsDialog) -> None:
        chat_id = dialog.chat_id_entry.get_text().strip()
        allowed_user_ids = parse_user_ids(dialog.allowed_users_entry.get_text()) or []

        tel = self.telegram_notifier
        tel_before = (tel.token, tel.chat_id, tel.enabled)
        if not tel.save_config(
                dialog.token_entry.get_text().strip(),
                chat_id,
                dialog.telegram_enable_check.get_active(),
                int(dialog.interval_spin.get_value()),
                dialog.screenshot_quality_combo.get_active_id() or "medium",
                allowed_user_ids=allowed_user_ids,
                allow_remote_power=dialog.allow_remote_power_check.get_active(),
                allow_remote_screenshot=dialog.allow_remote_screenshot_check.get_active(),
        ):
            self._show_message(tr('error'), tr('setting_telegram_error'))
            return
        tel_after = (tel.token, tel.chat_id, tel.enabled)
        if tel.enabled and not tel_before[2]:
            self.last_telegram_notification_time = float("-inf")
        if tel_after != tel_before:
            tel.stop_bot()
        tel.start_bot()

    def _show_message(self, title: str, message: str) -> None:
        show_message(title, message, self.settings_dialog)

    def _close_progress_dialog(self):
        if self._progress_dialog:
            try:
                self._progress_dialog.destroy()
            except Exception:
                pass
            self._progress_dialog = None

    def on_ping_click(self, *_):
        host = "8.8.8.8"
        count = 4
        timeout = 5

        if not (self._progress_dialog and self._progress_dialog.get_mapped()):
            d = Gtk.MessageDialog(
                transient_for=mapped_or_none(self.settings_dialog),
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text=tr('ping_running'),
            )
            d.set_title(tr('ping_network'))
            d.set_modal(True)
            d.show()
            self._progress_dialog = d

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

        threading.Thread(target=worker, name="ping", daemon=True).start()

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
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        boot_dt = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
        gb = 1024 ** 3

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
            f"{tr('ram_total_label')}: {ram.total / gb:.2f} {tr('gb')}",
            f"{tr('ram_available_label')}: {ram.available / gb:.2f} {tr('gb')}",
            f"{tr('swap_total_label')}: {swap.total / gb:.2f} {tr('gb')}",
            f"{tr('disk_total_label')}: {disk.total / gb:.2f} {tr('gb')}",
            f"{tr('disk_free_label')}: {disk.free / gb:.2f} {tr('gb')}",
            f"{tr('boot_time_label')}: {boot_dt}",
            f"{tr('python_version_label')}: {platform.python_version()}",
        ])

    def on_system_info_click(self, *_):
        try:
            info_text = self._build_system_info_text()
        except Exception as e:
            self._show_message(tr('error'), f"{tr('system_info_error')}: {e}")
            return
        self._show_message(tr('system_info_title'), info_text)

    def show_graph(self, graph_key: str) -> None:
        window = self.graph_windows.get(graph_key)
        if window is not None and window.is_visible():
            window.present()
            return
        self.graph_windows[graph_key] = GraphWindow(
            self.graph_specs[graph_key],
            get_samples=lambda: self.metrics_history.samples(graph_key),
            get_color=self.graph_line_color,
            show_zoom_controls=bool(self.visibility_settings.get('show_graph_zoom_controls', True)),
            on_destroy=self._on_graph_destroyed,
        )

    def _on_graph_destroyed(self, window: GraphWindow) -> None:
        if self.graph_windows.get(window.spec.key) is window:
            del self.graph_windows[window.spec.key]

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
        plural_key = self._plural_ru(days) if get_language() == 'ru' else ('one' if days == 1 else 'many')
        day_label = tr(f'uptime_day_{plural_key}')
        if day_label == f'uptime_day_{plural_key}':
            day_label = 'day' if days == 1 else 'days'
        return f"{days} {day_label}, {time_part}"

    def _metric_intervals(self) -> Dict[str, int]:
        vs = self.visibility_settings
        cpu = int(vs.get('cpu_interval_sec', POLL_INTERVAL_DEFAULT_SEC))
        return {
            'cpu_temp': max(2, cpu),
            'cpu_usage': cpu,
            'ram': int(vs.get('ram_interval_sec', POLL_INTERVAL_DEFAULT_SEC)),
            'disk': int(vs.get('disk_interval_sec', POLL_INTERVAL_DEFAULT_SEC)),
            'swap': int(vs.get('swap_interval_sec', POLL_INTERVAL_DEFAULT_SEC)),
            'net': int(vs.get('net_interval_sec', POLL_INTERVAL_DEFAULT_SEC)),
            'uptime': POLL_INTERVAL_DEFAULT_SEC,
        }

    def update_info(self) -> bool:
        cycle_start = time.perf_counter()
        try:
            kbd, ms = self._input_counts()
            raw = self.metrics_sampler.snapshot(self.prev_net_data, self._metric_intervals(), kbd, ms)
            snapshot = dataclasses.replace(raw, uptime=self._format_uptime_localized(raw.uptime))
            self.latest_snapshot = snapshot
            self.metrics_history.append_snapshot(snapshot)

            self._update_ui(snapshot)
            self._send_periodic_notifications(snapshot)
            self._write_metrics_log(snapshot)
            self._record_profiling(cycle_start)
        except Exception as e:
            logger.exception("Ошибка в update_info: %s", e)
        return True

    def _send_periodic_notifications(self, snapshot: MetricsSnapshot) -> None:
        now = time.monotonic()
        if (self.telegram_notifier.enabled and
                now - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval):
            self.telegram_dispatcher.submit(format_status_message(snapshot, "html"))
            self.last_telegram_notification_time = now

        if (self.discord_notifier.enabled and
                now - self.last_discord_notification_time >= self.discord_notifier.notification_interval):
            self.discord_dispatcher.submit(format_status_message(snapshot, "markdown"))
            self.last_discord_notification_time = now

    def _write_metrics_log(self, s: MetricsSnapshot) -> None:
        if not self.visibility_settings.get('logging_enabled', True):
            return
        line = (f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"CPU: {s.cpu_usage:.0f}% {format_temp(s.cpu_temp)} | "
                f"RAM: {s.ram_used:.1f}/{s.ram_total:.1f} GB | "
                f"SWAP: {s.swap_used:.1f}/{s.swap_total:.1f} GB | "
                f"Disk: {s.disk_used:.1f}/{s.disk_total:.1f} GB | "
                f"Net: ↓{s.net_recv:.1f}/↑{s.net_sent:.1f} {tr('mbps')} | "
                f"Uptime: {s.uptime} | "
                f"Keys: {format_count(s.keyboard_clicks)} | "
                f"Clicks: {format_count(s.mouse_clicks)}\n")
        max_bytes = sanitize_log_size_mb(self.visibility_settings.get('max_log_mb', 5)) * 1024 * 1024
        try:
            self.metrics_log.write(line, max_bytes)
        except OSError as e:
            logger.warning("Ошибка записи в лог: %s", e)

    def _record_profiling(self, cycle_start: float) -> None:
        if not self.visibility_settings.get('profiling_enabled', False):
            return
        cycle_ms = (time.perf_counter() - cycle_start) * 1000.0
        self._profiling_cycle_count += 1
        self._profiling_total_ms += cycle_ms
        self._profiling_max_ms = max(self._profiling_max_ms, cycle_ms)
        if self._profiling_cycle_count >= 60:
            avg_ms = self._profiling_total_ms / float(self._profiling_cycle_count)
            logger.info(
                "Profiling update_info: avg=%.2fms max=%.2fms samples=%d",
                avg_ms,
                self._profiling_max_ms,
                self._profiling_cycle_count,
            )
            self._profiling_cycle_count = 0
            self._profiling_total_ms = 0.0
            self._profiling_max_ms = 0.0

    def _due(self, item_key: str, interval_key: str, now: float) -> bool:
        interval = sanitize_poll_interval(self.visibility_settings.get(interval_key, POLL_INTERVAL_DEFAULT_SEC))
        if now - self._last_item_update_ts.get(item_key, float("-inf")) >= interval:
            self._last_item_update_ts[item_key] = now
            return True
        return False

    def _throttled_text(self, item_key: str, interval_key: str, now: float, text: str) -> str:
        """Текст обновляется не чаще заданного для пункта интервала."""
        if self._due(item_key, interval_key, now) or item_key not in self._item_display_cache:
            self._item_display_cache[item_key] = text
        return self._item_display_cache[item_key]

    def _update_ui(self, s: MetricsSnapshot) -> None:
        now = time.monotonic()
        vs = self.visibility_settings
        gb = tr('gb')

        for window in self.graph_windows.values():
            window.queue_draw()

        throttled = {
            'cpu': ('cpu_interval_sec', f"{tr('cpu_info')}: {s.cpu_usage:.0f}%  🌡{format_temp(s.cpu_temp)}"),
            'ram': ('ram_interval_sec', f"{tr('ram_loading')}: {s.ram_used:.1f}/{s.ram_total:.1f} {gb}"),
            'swap': ('swap_interval_sec', f"{tr('swap_loading')}: {s.swap_used:.1f}/{s.swap_total:.1f} {gb}"),
            'disk': ('disk_interval_sec', f"{tr('disk_loading')}: {s.disk_used:.1f}/{s.disk_total:.1f} {gb}"),
            'net': ('net_interval_sec', f"{tr('lan_speed')}: ↓{s.net_recv:.1f}/↑{s.net_sent:.1f} {tr('mbps')}"),
        }
        for key, (interval_key, text) in throttled.items():
            if vs.get(key, True):
                self._set_label(self.menu_items[key], self._throttled_text(key, interval_key, now, text))

        immediate = {'uptime': f"{tr('uptime_label')}: {s.uptime}"}
        if self.input_counters_available:
            immediate['keyboard_clicks'] = f"{tr('keyboard_clicks')}: {format_count(s.keyboard_clicks)}"
            immediate['mouse_clicks'] = f"{tr('mouse_clicks')}: {format_count(s.mouse_clicks)}"
        for key, text in immediate.items():
            if vs.get(key, True):
                self._set_label(self.menu_items[key], text)

        tray_parts = []
        if vs.get('tray_cpu', True):
            tray_parts.append(self._throttled_text('tray_cpu', 'tray_cpu_interval_sec', now,
                                                   f"{tr('cpu_info')}: {s.cpu_usage:.0f}%"))
        if vs.get('tray_ram', True):
            tray_parts.append(self._throttled_text('tray_ram', 'tray_ram_interval_sec', now,
                                                   f"{tr('ram_loading')}: {s.ram_used:.1f}{gb}"))
        # Обратный отсчёт планировщика — часть той же подписи, чтобы не было двух
        # источников, перетирающих друг друга.
        countdown = self.power_control.countdown_text()
        if countdown:
            tray_parts.append(f"⏻ {countdown}")
        tray_text = "  ".join(tray_parts)
        if self.telegram_notifier.enabled or self.discord_notifier.enabled:
            tray_text = "⤴  " + tray_text
        self._set_indicator_label(tray_text)

    def _on_unix_signal(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def quit(self, *_args):
        if self._quitting:
            return
        self._quitting = True

        self._report_remote_action_cancelled_on_exit()
        self.telegram_dispatcher.stop()
        self.discord_dispatcher.stop()
        self.telegram_notifier.stop_bot()
        self.power_control.dispose()
        self._close_progress_dialog()

        for window in list(self.graph_windows.values()):
            try:
                window.destroy()
            except Exception:
                pass
        self.graph_windows.clear()

        if self.settings_dialog:
            try:
                self.settings_dialog.destroy()
            except Exception:
                pass
            self.settings_dialog = None

        self._stop_input_listeners()

        if self._bus_name_id:
            Gio.bus_unown_name(self._bus_name_id)
            self._bus_name_id = 0
        self.metrics_log.close()
        Gtk.main_quit()

    def _report_remote_action_cancelled_on_exit(self) -> None:
        """Таймер живёт в процессе SyMo: при выходе удалённо запланированное действие
        пропадает, и тот, кто его запросил, должен об этом узнать."""
        act = self.power_control.remote_scheduled_action()
        if act is None:
            return
        text = tr('bot_action_cancelled_on_exit').format(action_label(act))
        sender = threading.Thread(target=self.telegram_notifier.send_message, args=(text,),
                                  name="telegram-exit", daemon=True)
        sender.start()
        # Выход ждёт отправку недолго: сеть может быть недоступна.
        sender.join(timeout=3.0)

    def run(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            _add_unix_signal_handler(sig, self._on_unix_signal)
        self._bus_name_id = Gio.bus_own_name(
            Gio.BusType.SESSION, DBUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None, None)
        # Начальный снимок, чтобы графики не открывались полностью пустыми.
        self.update_info()
        GLib.timeout_add_seconds(TIME_UPDATE_SEC, self.update_info)
        Gtk.main()


def _acquire_single_instance_lock() -> Optional[IO[str]]:
    """Не дать запустить второй экземпляр (второй значок в трее и второй Telegram-бот)."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        lock_path = Path(runtime_dir) / f"{APP_NAME.lower()}.lock"
    else:
        # Общий /tmp: файл с uid, чтобы не столкнуться с блокировкой другого пользователя.
        lock_path = Path(tempfile.gettempdir()) / f"{APP_NAME.lower()}-{os.getuid()}.lock"
    try:
        lock_file = open(lock_path, "w")
    except OSError as e:
        logger.warning("Не удалось открыть файл блокировки %s: %s", lock_path, e)
        # Работаем без защиты от второго экземпляра, но запускаемся.
        return open(os.devnull, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def _report_missing_app_indicator() -> None:
    set_language(load_settings(SETTINGS_FILE).get('language') or detect_system_language())
    command = f"sudo apt install {APP_INDICATOR_PACKAGE}"
    logger.error("Не найдена библиотека AppIndicator. Установите: %s", command)
    dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                               text=tr('appindicator_missing').format(command))
    dialog.set_title(APP_NAME)
    dialog.run()
    dialog.destroy()


def main() -> None:
    setup_logging()
    lock = _acquire_single_instance_lock()
    if lock is None:
        logger.info("%s уже запущен", APP_NAME)
        return
    Gtk.init([])
    if AppInd is None:
        _report_missing_app_indicator()
        raise SystemExit(1)
    SystemTrayApp().run()
    lock.close()


if __name__ == "__main__":
    main()
