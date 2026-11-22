from __future__ import annotations

import ctypes
import dataclasses
import fcntl
import importlib
import logging
import os
import signal
import sys
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Dict, Optional

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gio, Gtk, GLib

from .constants import (
    APP_ID,
    APP_NAME,
    APP_VERSION,
    DBUS_NAME,
    ICON_FALLBACK,
    LOG_FILE,
    SETTINGS_FILE,
    TIME_UPDATE_SEC,
    SUPPORTED_LANGS,
    POLL_INTERVAL_DEFAULT_SEC,
)
from . import autostart, updates
from .alerts import AlertMonitor, show_desktop_notification
from .click_tracker import increment_keyboard, increment_mouse, get_counts
from .graphs import GraphWindow, build_graph_specs
from .history import MetricsHistory
from .language import LANGUAGES
from .localization import tr, detect_system_language, format_uptime, set_language, get_language
from .logging_utils import MetricsLogWriter, setup_logging
from .power_control import PowerControl, action_label
from .settings import (
    graph_line_color_rgb,
    load_settings,
    normalize_menu_order,
    sanitize_graph_history_minutes,
    sanitize_hex_color,
    sanitize_alert_threshold,
    sanitize_disk_path,
    sanitize_log_interval,
    sanitize_log_size_mb,
    sanitize_ping_host,
    sanitize_poll_interval,
    save_settings,
)
from .system_info import build_system_info_text
from .system_usage import MetricsSampler, MetricsSnapshot, format_count, format_temp, initial_network_state
from .ui import mapped_or_none, show_message
from notifications import TelegramNotifier, DiscordNotifier
from notifications.telegram import is_valid_chat_id, parse_user_ids

if TYPE_CHECKING:
    # Окно настроек импортируется при первом открытии: при запуске оно не нужно.
    from .dialogs import SettingsDialog
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

POWER_MENU_KEYS = ('show_power_off', 'show_reboot', 'show_lock', 'show_timer')
INPUT_COUNTER_KINDS = ('keyboard', 'mouse')


def _is_wayland_session() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


class SystemTrayApp:
    def __init__(self, application: Optional[Gtk.Application] = None):
        self.application = application
        self.settings_file = SETTINGS_FILE
        self.visibility_settings: Dict[str, Any] = load_settings(self.settings_file)

        if not self.visibility_settings.get('language'):
            self.visibility_settings['language'] = detect_system_language()
            self.save_settings()
        set_language(self.visibility_settings['language'])
        # Версия, найденная прошлой проверкой, показывается в меню сразу после запуска.
        latest = self.visibility_settings.get('update_latest_version', '')
        self.available_update: Optional[str] = latest if updates.is_newer(latest) else None

        self.indicator = AppInd.Indicator.new(APP_ID, ICON_FALLBACK, AppInd.IndicatorCategory.SYSTEM_SERVICES)
        self._set_indicator_icon()
        self.indicator.set_status(AppInd.IndicatorStatus.ACTIVE)

        self._quitting = False
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
        self.metrics_sampler.disk_path = self.visibility_settings['disk_path']
        self.alert_monitor = AlertMonitor()
        self._last_log_write = float("-inf")

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
        self._new_item('battery', f"{tr('battery_label')}: N/A", open_graph('battery'))
        self._new_item('gpu', f"{tr('gpu_label')}: N/A", open_graph('gpu'))
        self._new_item('show_power_off', tr('power_off'),
                       lambda w: pc.confirm_action(w, pc.power_off, tr('confirm_text_power_off')))
        self._new_item('show_reboot', tr('reboot'),
                       lambda w: pc.confirm_action(w, pc.reboot, tr('confirm_text_reboot')))
        self._new_item('show_lock', tr('lock'),
                       lambda w: pc.confirm_action(w, pc.lock_screen, tr('confirm_text_lock')))
        self._new_item('show_timer', tr('scheduler'), pc.open_scheduler)
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
        update_item = Gtk.MenuItem(label=tr('update_menu_item').format(self.available_update or ''))
        update_item.connect("activate", self._open_releases_page)
        self.menu_items['update'] = update_item
        entries += [None, update_item, self._build_language_menu_item(), settings_item, None, quit_item]

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
        # Батарея и GPU появятся при первом обновлении, если они есть.
        for key in ('battery', 'gpu'):
            self.menu_items[key].set_visible(False)
        update_item.set_visible(self.available_update is not None)
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
            flag = (LANGUAGES.get(code) or {}).get('language_flag', '🏳️')
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
            self.telegram_notifier.publish_commands_async()
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
        from .dialogs import SettingsDialog
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
        vs['log_interval_sec'] = sanitize_log_interval(dialog.log_interval_spin.get_value_as_int())
        vs['ping_host'] = sanitize_ping_host(dialog.ping_host_entry.get_text())
        vs['disk_path'] = sanitize_disk_path(dialog.disk_combo.get_active_id())
        self.metrics_sampler.disk_path = vs['disk_path']
        for key, spin in dialog.alert_spins.items():
            vs[key] = sanitize_alert_threshold(key, spin.get_value_as_int())
        self._set_graph_history_window(dialog.graph_history_spin.get_value_as_int())
        for key, spin in dialog.poll_interval_spins().items():
            vs[key] = sanitize_poll_interval(spin.get_value_as_int())
        if not vs['logging_enabled']:
            self.metrics_log.close()
        self.sync_input_listeners()

        enable_updates = dialog.check_updates_check.get_active() and not vs.get('check_updates')
        vs['check_updates'] = dialog.check_updates_check.get_active()
        if enable_updates:
            self._check_updates(force=True)

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
        # Флажки разрешений меняют список команд в меню Telegram.
        tel.publish_commands_async()

    def _first_update_check(self) -> bool:
        self._check_updates()
        return GLib.SOURCE_REMOVE

    def _hourly_update_check(self) -> bool:
        self._check_updates()
        return GLib.SOURCE_CONTINUE

    def _check_updates(self, force: bool = False) -> None:
        """Раз в сутки спросить GitHub о новой версии; сеть — в фоновом потоке."""
        vs = self.visibility_settings
        due = time.time() - vs.get('update_last_check', 0.0) >= updates.CHECK_INTERVAL_SEC
        if vs.get('check_updates') and (force or due):
            vs['update_last_check'] = time.time()
            threading.Thread(target=lambda: GLib.idle_add(self._on_update_checked, updates.fetch_latest_version()),
                             name="update-check", daemon=True).start()

    def _on_update_checked(self, version: Optional[str]) -> bool:
        vs = self.visibility_settings
        if version:
            vs['update_latest_version'] = version
        if version and updates.is_newer(version):
            self.available_update = version
            self.menu_items['update'].set_label(tr('update_menu_item').format(version))
            self.menu_items['update'].set_visible(True)
            if vs.get('update_notified_version') != version:
                vs['update_notified_version'] = version
                show_desktop_notification(tr('update_available').format(version), title=APP_NAME)
        self.save_settings()
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _open_releases_page(*_args) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(updates.RELEASES_PAGE_URL, None)
        except GLib.Error as e:
            logger.warning("Не удалось открыть %s: %s", updates.RELEASES_PAGE_URL, e.message)

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
        host = sanitize_ping_host(self.visibility_settings.get('ping_host'))
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

    def on_system_info_click(self, *_):
        try:
            info_text = build_system_info_text(self.visibility_settings.get('disk_path', '/'))
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
            'battery': 10,
            'gpu': 2,
        }

    def update_info(self) -> bool:
        cycle_start = time.perf_counter()
        try:
            kbd, ms = self._input_counts()
            raw = self.metrics_sampler.snapshot(self.prev_net_data, self._metric_intervals(), kbd, ms)
            snapshot = dataclasses.replace(raw, uptime=format_uptime(raw.uptime))
            self.latest_snapshot = snapshot
            self.metrics_history.append_snapshot(snapshot)

            self._update_ui(snapshot)
            self._send_periodic_notifications(snapshot)
            self._check_alerts(snapshot)
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

    def _check_alerts(self, snapshot: MetricsSnapshot) -> None:
        for text in self.alert_monitor.check(snapshot, self.visibility_settings, time.monotonic()):
            logger.warning("Оповещение: %s", text)
            show_desktop_notification(text)
            if self.telegram_notifier.enabled:
                self.telegram_notifier.send_message_async(f"⚠️ {text}")
            if self.discord_notifier.enabled:
                threading.Thread(target=self.discord_notifier.send_message, args=(f"⚠️ {text}",),
                                 name="discord-alert", daemon=True).start()

    def _write_metrics_log(self, s: MetricsSnapshot) -> None:
        if not self.visibility_settings.get('logging_enabled', True):
            return
        now = time.monotonic()
        if now - self._last_log_write < sanitize_log_interval(self.visibility_settings.get('log_interval_sec')):
            return
        self._last_log_write = now
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
        optional = {
            'battery': None if s.battery_percent is None else
            f"{tr('battery_label')}: {s.battery_percent:.0f}%" + (" ⚡" if s.battery_plugged else ""),
            'gpu': None if s.gpu_usage is None else f"{tr('gpu_label')}: {s.gpu_usage:.0f}%",
        }
        for key, text in optional.items():
            item = self.menu_items[key]
            # Нет батареи или GPU не опрашивается — пункта нет в меню.
            item.set_visible(text is not None and bool(vs.get(key, True)))
            if text is not None:
                self._set_label(item, text)
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
        self.metrics_log.close()
        if self.application is not None:
            self.application.quit()
        else:
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

    def start(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            _add_unix_signal_handler(sig, self._on_unix_signal)
        # Начальный снимок, чтобы графики не открывались полностью пустыми.
        self.update_info()
        GLib.timeout_add_seconds(TIME_UPDATE_SEC, self.update_info)
        GLib.timeout_add_seconds(updates.FIRST_CHECK_DELAY_SEC, self._first_update_check)
        # Раз в час проверяем, не прошли ли сутки с прошлой проверки.
        GLib.timeout_add_seconds(3600, self._hourly_update_check)


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
    if "--version" in sys.argv[1:]:
        print(f"{APP_NAME} {APP_VERSION}")
        return
    setup_logging()
    logger.info("%s %s", APP_NAME, APP_VERSION)

    # Gtk.Application владеет именем DBUS_NAME на сессионной шине: по нему расширение
    # SyMo Launcher видит, что SyMo запущен. Повторный запуск (из меню, командой symo)
    # не стартует второй экземпляр, а передаёт «activate» уже работающему — тот
    # открывает настройки.
    application = Gtk.Application(
        application_id=DBUS_NAME,
        flags=getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE))
    state: Dict[str, Any] = {}

    def on_startup(app: Gtk.Application) -> None:
        # Файл блокировки — на случай второго графического сеанса того же пользователя:
        # у него своя шина D-Bus, но второй Telegram-бот не нужен.
        lock = _acquire_single_instance_lock()
        if lock is None:
            logger.info("%s уже запущен в другом сеансе", APP_NAME)
            return
        if AppInd is None:
            _report_missing_app_indicator()
            state['exit_code'] = 1
            return
        tray = SystemTrayApp(app)
        state.update(lock=lock, tray=tray)
        app.hold()
        tray.start()

    def on_activate(_app: Gtk.Application) -> None:
        tray = state.get('tray')
        if tray is None:
            return
        if not state.get('started'):
            state['started'] = True  # первая активация — это сам запуск
            return
        logger.info("Повторный запуск %s: открываю настройки", APP_NAME)
        tray.show_settings()

    application.connect("startup", on_startup)
    application.connect("activate", on_activate)
    status = application.run([sys.argv[0]])
    if state.get('lock'):
        state['lock'].close()
    if state.get('exit_code') or status:
        raise SystemExit(state.get('exit_code') or status)


if __name__ == "__main__":
    main()
