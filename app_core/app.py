from __future__ import annotations

import dataclasses
import logging
import os
import platform
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import gi

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppInd

gi.require_version("Gtk", "3.0")

import psutil
from gi.repository import Gtk, GLib
from pynput import keyboard, mouse

from .constants import (
    APP_ID,
    APP_NAME,
    ICON_FALLBACK,
    LOG_FILE,
    SETTINGS_FILE,
    TIME_UPDATE_SEC,
    SUPPORTED_LANGS,
    POLL_INTERVAL_DEFAULT_SEC,
)
from .click_tracker import increment_keyboard, increment_mouse, get_counts
from .dialogs import SettingsDialog
from .graphs import GraphWindow, build_graph_specs
from .history import MetricsHistory
from .language import LANGUAGES
from .localization import tr, detect_system_language, set_language, get_language
from .logging_utils import MetricsLogWriter, setup_logging
from .power_control import PowerControl
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
from .system_usage import MetricsSampler, MetricsSnapshot
from .ui import mapped_or_none, show_message
from notifications import TelegramNotifier, DiscordNotifier
from notifications.base import NotificationDispatcher, format_status_message

logger = logging.getLogger(__name__)

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
        self.power_control = PowerControl(self)
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

        self.create_menu()

        net = psutil.net_io_counters()
        self.prev_net_data = {'recv': net.bytes_recv, 'sent': net.bytes_sent, 'time': time.time()}
        self.metrics_sampler = MetricsSampler()

        self.keyboard_listener = None
        self.mouse_listener = None
        self.init_listeners()

        self.telegram_notifier = TelegramNotifier()
        self.discord_notifier = DiscordNotifier()
        self.last_telegram_notification_time = 0.0
        self.last_discord_notification_time = 0.0
        self.telegram_dispatcher = NotificationDispatcher(self.telegram_notifier.send_message, "Telegram")
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

    # ---------- Инициализация ----------

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

    def init_listeners(self):
        hooks_ok = True
        try:
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press, daemon=True)
            self.keyboard_listener.start()
        except Exception as e:
            logger.warning("Не удалось запустить keyboard listener: %s", e)
            self.keyboard_listener = None
            hooks_ok = False
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click, daemon=True)
            self.mouse_listener.start()
        except Exception as e:
            logger.warning("Не удалось запустить mouse listener: %s", e)
            self.mouse_listener = None
            hooks_ok = False
        if hooks_ok and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            logger.warning("Сессия Wayland: счётчики клавиш и кликов видят только события XWayland-приложений")

    def on_key_press(self, _key):
        increment_keyboard()

    def on_mouse_click(self, _x, _y, _button, pressed):
        if pressed:
            increment_mouse()

    # ---------- Настройки ----------

    @staticmethod
    def _graph_history_points(minutes: int) -> int:
        return max(1, minutes * 60 // TIME_UPDATE_SEC)

    def _set_graph_history_window(self, minutes) -> None:
        sanitized_minutes = sanitize_graph_history_minutes(minutes)
        self.visibility_settings['graph_history_minutes'] = sanitized_minutes
        self.metrics_history.resize(self._graph_history_points(sanitized_minutes))

    def save_settings(self) -> None:
        save_settings(self.settings_file, self.visibility_settings)

    def graph_line_color(self, key: str) -> tuple[float, float, float]:
        return graph_line_color_rgb(self.visibility_settings, key)

    # ---------- Меню ----------

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
        self._new_item('keyboard_clicks', f"{tr('keyboard_clicks')}: 0", open_graph('keyboard'))
        self._new_item('mouse_clicks', f"{tr('mouse_clicks')}: 0", open_graph('mouse'))
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

        if any(key in visible for key in POWER_MENU_KEYS):
            menu.append(Gtk.SeparatorMenuItem())
        for key in visible:
            if key == 'ping_network':
                menu.append(Gtk.SeparatorMenuItem())
                menu.append(self.menu_items[key])
                menu.append(Gtk.SeparatorMenuItem())
            else:
                menu.append(self.menu_items[key])

        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._build_language_menu_item())
        settings_item = Gtk.MenuItem(label=tr('settings_label'))
        settings_item.connect("activate", self.show_settings)
        menu.append(settings_item)
        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label=tr('exit_app'))
        quit_item.connect("activate", self.quit)
        menu.append(quit_item)

        menu.show_all()
        self.menu = menu
        self.indicator.set_menu(menu)

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
            self.save_settings()
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

    # ---------- Диалоги ----------

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

        tel = self.telegram_notifier
        tel_before = (tel.token, tel.chat_id, tel.enabled)
        if tel.save_config(
                dialog.token_entry.get_text().strip(),
                dialog.chat_id_entry.get_text().strip(),
                dialog.telegram_enable_check.get_active(),
                int(dialog.interval_spin.get_value()),
                dialog.screenshot_quality_combo.get_active_id() or "medium",
        ):
            tel_after = (tel.token, tel.chat_id, tel.enabled)
            if tel.enabled and not tel_before[2]:
                self.last_telegram_notification_time = 0.0
            if tel_after != tel_before:
                # Не ждём завершения старого потока: он сам выйдет после long-poll.
                tel.stop_bot()
            tel.start_bot()
        else:
            self._show_message(tr('error'), tr('setting_telegram_error'))

        disc = self.discord_notifier
        disc_enabled_before = disc.enabled
        if disc.save_config(
                dialog.webhook_entry.get_text().strip(),
                dialog.discord_enable_check.get_active(),
                int(dialog.discord_interval_spin.get_value()),
        ):
            if disc.enabled and not disc_enabled_before:
                self.last_discord_notification_time = 0.0
        else:
            self._show_message(tr('error'), tr('setting_discord_error'))

        self.save_settings()
        self.create_menu()

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

    # ---------- Графики ----------

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

    # ---------- Основной цикл ----------

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
            kbd, ms = get_counts()
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
        now = time.time()
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
                f"CPU: {s.cpu_usage:.0f}% {s.cpu_temp}°C | "
                f"RAM: {s.ram_used:.1f}/{s.ram_total:.1f} GB | "
                f"SWAP: {s.swap_used:.1f}/{s.swap_total:.1f} GB | "
                f"Disk: {s.disk_used:.1f}/{s.disk_total:.1f} GB | "
                f"Net: ↓{s.net_recv:.1f}/↑{s.net_sent:.1f} {tr('mbps')} | "
                f"Uptime: {s.uptime} | "
                f"Keys: {s.keyboard_clicks} | "
                f"Clicks: {s.mouse_clicks}\n")
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
        if now - self._last_item_update_ts.get(item_key, 0.0) >= interval:
            self._last_item_update_ts[item_key] = now
            return True
        return False

    def _throttled_text(self, item_key: str, interval_key: str, now: float, text: str) -> str:
        """Текст обновляется не чаще заданного для пункта интервала."""
        if self._due(item_key, interval_key, now) or item_key not in self._item_display_cache:
            self._item_display_cache[item_key] = text
        return self._item_display_cache[item_key]

    def _update_ui(self, s: MetricsSnapshot) -> None:
        now = time.time()
        vs = self.visibility_settings
        gb = tr('gb')

        for window in self.graph_windows.values():
            window.queue_draw()

        throttled = {
            'cpu': ('cpu_interval_sec', f"{tr('cpu_info')}: {s.cpu_usage:.0f}%  🌡{s.cpu_temp}°C"),
            'ram': ('ram_interval_sec', f"{tr('ram_loading')}: {s.ram_used:.1f}/{s.ram_total:.1f} {gb}"),
            'swap': ('swap_interval_sec', f"{tr('swap_loading')}: {s.swap_used:.1f}/{s.swap_total:.1f} {gb}"),
            'disk': ('disk_interval_sec', f"{tr('disk_loading')}: {s.disk_used:.1f}/{s.disk_total:.1f} {gb}"),
            'net': ('net_interval_sec', f"{tr('lan_speed')}: ↓{s.net_recv:.1f}/↑{s.net_sent:.1f} {tr('mbps')}"),
        }
        for key, (interval_key, text) in throttled.items():
            if vs.get(key, True):
                self._set_label(self.menu_items[key], self._throttled_text(key, interval_key, now, text))

        immediate = {
            'uptime': f"{tr('uptime_label')}: {s.uptime}",
            'keyboard_clicks': f"{tr('keyboard_clicks')}: {s.keyboard_clicks}",
            'mouse_clicks': f"{tr('mouse_clicks')}: {s.mouse_clicks}",
        }
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

    # ---------- Завершение ----------

    def _on_unix_signal(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def quit(self, *_args):
        if self._quitting:
            return
        self._quitting = True

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

        for listener in (self.keyboard_listener, self.mouse_listener):
            try:
                if listener:
                    listener.stop()
            except Exception:
                pass

        self.metrics_log.close()
        Gtk.main_quit()

    def run(self):
        # Сигналы через GLib: обработчик срабатывает сразу, а не на следующем тике таймера.
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_unix_signal)
        # Начальный снимок, чтобы графики не открывались полностью пустыми.
        self.update_info()
        GLib.timeout_add_seconds(TIME_UPDATE_SEC, self.update_info)
        Gtk.main()


def main() -> None:
    setup_logging()
    Gtk.init([])
    SystemTrayApp().run()


if __name__ == "__main__":
    main()
