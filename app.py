#!/usr/bin/env python3
"""
SyMo — System Monitor (Tray) • graphs with left legend & hover info shifted by LEGEND_W
- Realtime Cairo-графики: cpu_temp, cpu_usage, ram%, swap%, disk%, net_recv, net_sent
- Легенда вынесена влево (отдельная колонка шириной LEGEND_W)
- Наведение: маркер+гайдлайн на графике, а текстовая информация показывается в левой колонке (сдвиг на LEGEND_W)
- Пункт меню "Graphs" открывает окно графиков
"""

import os
import json
import time
import locale
import signal
import psutil
import requests
import threading
import subprocess
from enum import Enum
from datetime import timedelta
from collections import deque
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk

try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppInd

try:
    from pynput import keyboard, mouse
except Exception:  # make hooks optional
    keyboard = None
    mouse = None

from language import LANGUAGES

SUPPORTED_LANGS = ["ru", "en", "cn", "de", "it", "es", "tr", "fr"]

LOG_FILE = os.path.join(os.path.expanduser("~"), ".symo_log.txt")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".symo_settings.json")
TELEGRAM_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".symo_telegram.json")
DISCORD_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".symo_discord.json")

TIME_UPDATE_SECONDS = 1

# ===== Graph settings =====
HISTORY_SECONDS = 300  # ~5 минут истории (1 точка/сек)
GRAPH_REFRESH_MS = 500  # перерисовка окна графиков (мс)
LEGEND_W = 60.0  # Ширина левой колонки под легенду инфо
GRAPH_COLORS = {
    "cpu_temp": (0.93, 0.36, 0.36),  # RGB 0..1
    "cpu_usage": (0.23, 0.62, 0.95),
    "ram": (0.31, 0.78, 0.47),
    "swap": (0.60, 0.49, 0.80),
    "disk": (0.90, 0.90, 0.90),
    "net_recv": (0.00, 0.75, 1.00),
    "net_sent": (1.00, 0.65, 0.00),
}
HOVER_RADIUS_PX = 8.0  # радиус попадания курсора для подсветки точки

DEFAULT_VISIBILITY = {
    "cpu": True,
    "ram": True,
    "swap": True,
    "disk": True,
    "net": True,
    "uptime": True,
    "tray_cpu": True,
    "tray_ram": True,
    "keyboard_clicks": True,
    "mouse_clicks": True,
    "language": None,
    "logging_enabled": True,
    "show_power_off": True,
    "show_reboot": True,
    "show_lock": True,
    "show_timer": True,
    "show_graphs": True,
    "max_log_mb": 5,
    "ping_network": True,
}

_clicks_lock = threading.Lock()
keyboard_clicks = 0
mouse_clicks = 0
current_lang = "ru"


# ---------------------------
# Helpers
# ---------------------------

def tr(key: str) -> str:
    """Get localized string for current language; fallback to EN; else key."""
    lang_map = LANGUAGES.get(current_lang) or LANGUAGES.get("en", {})
    return lang_map.get(key, key)


def detect_system_language() -> str:
    try:
        env = os.environ.get("LANG", "")
        if env:
            code = env.split(".")[0].split("_")[0].lower()
            return code if code in SUPPORTED_LANGS else "ru"
        code = (locale.getlocale()[0] or "").split("_")[0].lower()
        return code if code in SUPPORTED_LANGS else "ru"
    except Exception:
        return "ru"


def rotate_log_if_needed(max_size_bytes: int) -> None:
    """Simple rotation: if log > max_size_bytes -> rename to .1 (overwrite old .1)."""
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > max_size_bytes:
            bak = LOG_FILE + ".1"
            try:
                if os.path.exists(bak):
                    os.remove(bak)
            except Exception:
                pass
            os.rename(LOG_FILE, bak)
    except Exception as e:
        print("Log rotation error:", e)


# ---------------------------
# System readings
# ---------------------------
class SystemUsage:
    @staticmethod
    def get_cpu_temp() -> int:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return 0
            preferred_keys = ("coretemp", "k10temp", "cpu-thermal", "soc_thermal", "acpitz")
            for key in preferred_keys:
                arr = temps.get(key)
                if arr:
                    for t in arr:
                        if getattr(t, "label", "").lower().startswith("package"):
                            return int(t.current)
                    return int(arr[0].current)
            first_list = next(iter(temps.values()))
            return int(first_list[0].current) if first_list else 0
        except Exception:
            return 0

    @staticmethod
    def get_cpu_usage() -> float:
        return psutil.cpu_percent()

    @staticmethod
    def get_ram_usage():
        m = psutil.virtual_memory()
        return m.used / (1024 ** 3), m.total / (1024 ** 3)

    @staticmethod
    def get_swap_usage():
        s = psutil.swap_memory()
        return s.used / (1024 ** 3), s.total / (1024 ** 3)

    @staticmethod
    def get_disk_usage():
        d = psutil.disk_usage("/")
        return d.used / (1024 ** 3), d.total / (1024 ** 3)

    @staticmethod
    def get_network_speed(prev):
        net = psutil.net_io_counters()
        now = time.time()
        elapsed = now - prev["time"]
        # handle counters reset
        if net.bytes_recv < prev["recv"] or net.bytes_sent < prev["sent"]:
            prev.update({"recv": net.bytes_recv, "sent": net.bytes_sent, "time": now})
            return 0.0, 0.0
        if elapsed <= 0:
            recv_speed = sent_speed = 0.0
        else:
            recv_speed = (net.bytes_recv - prev["recv"]) / elapsed / 1024 / 1024
            sent_speed = (net.bytes_sent - prev["sent"]) / elapsed / 1024 / 1024
        prev.update({"recv": net.bytes_recv, "sent": net.bytes_sent, "time": now})
        return recv_speed, sent_speed

    @staticmethod
    def get_uptime() -> str:
        seconds = time.time() - psutil.boot_time()
        return str(timedelta(seconds=int(seconds)))


# ---------------------------
# Graph window (left legend + hover info in legend)
# ---------------------------
class TimeSeries:
    """Буфер фиксированной длины (в точках). По 1 точке/сек держим HISTORY_SECONDS секунд."""

    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self.data = deque(maxlen=self.capacity)

    def add(self, value: float):
        self.data.append(float(value))

    def values(self):
        return list(self.data)

    def __len__(self):
        return len(self.data)

    def is_empty(self):
        return len(self.data) == 0


class GraphWindow(Gtk.Window):
    """
    График 7 рядов:
      - cpu_temp (°C)
      - cpu_usage (%)
      - ram_usage (%)
      - swap_usage (%)
      - disk_usage (%)
      - net_recv (MB/s)
      - net_sent (MB/s)
    Сетка, легенда слева, авто-масштаб по Y, hover-подсказки выводятся в левой колонке.
    """

    def __init__(self, app: "SystemTrayApp"):
        super().__init__(title=tr("graphs") if "graphs" in (LANGUAGES.get(current_lang) or {}) else "Graphs")
        self.set_default_size(900, 360)
        self.set_keep_above(False)
        try:
            self.set_position(Gtk.WindowPosition.CENTER)
        except Exception:
            pass

        self.app = app
        self.series = {
            "cpu_temp": TimeSeries(HISTORY_SECONDS),
            "cpu_usage": TimeSeries(HISTORY_SECONDS),
            "ram": TimeSeries(HISTORY_SECONDS),
            "swap": TimeSeries(HISTORY_SECONDS),
            "disk": TimeSeries(HISTORY_SECONDS),
            "net_recv": TimeSeries(HISTORY_SECONDS),
            "net_sent": TimeSeries(HISTORY_SECONDS),
        }

        # состояние наведения
        self.hover = None  # dict(series, idx, value, x, y, sec_ago)
        self._last_mouse_xy = None
        self._timer = None  # Инициализируем таймер как None

        self.area = Gtk.DrawingArea()
        events = self.area.get_events()
        self.area.set_events(events
                             | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.LEAVE_NOTIFY_MASK
                             | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", self.on_leave)

        self.add(self.area)

        # Запускаем таймер только когда окно показано
        self.connect("show", self._on_show)
        self.connect("hide", self._on_hide)
        self.connect("destroy", self._on_destroy)

        self.show_all()

    def _on_show(self, *_):
        """Запускаем таймер когда окно показывается"""
        if self._timer is None:
            self._timer = GLib.timeout_add(GRAPH_REFRESH_MS, self._tick)

    def _on_hide(self, *_):
        """Останавливаем таймер когда окно скрывается"""
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _on_destroy(self, *_):
        """Останавливаем таймер при уничтожении окна"""
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def update_title(self):
        """Обновляет заголовок окна в соответствии с текущим языком."""
        self.set_title(tr("graphs") if "graphs" in (LANGUAGES.get(current_lang) or {}) else "Graphs")

    def _tick(self):
        """Таймер обновления графика"""
        try:
            if self.get_visible():  # Обновляем только если окно видимо
                self.area.queue_draw()
            return True  # Продолжаем таймер
        except Exception:
            return False  # Останавливаем таймер при ошибке

    def _on_close(self, widget, event):
        """Обработчик закрытия окна - скрываем вместо уничтожения"""
        self.hide()
        return True  # Предотвращаем уничтожение окна

    def push_sample(self, cpu_temp, cpu_usage, ram_used, ram_total, swap_used, swap_total, disk_used, disk_total, net_recv_speed, net_sent_speed):
        try:
            ram_pct = (ram_used / max(1e-9, ram_total)) * 100.0
            swap_pct = (swap_used / max(1e-9, swap_total)) * 100.0
            disk_pct = (disk_used / max(1e-9, disk_total)) * 100.0

            self.series["cpu_temp"].add(cpu_temp or 0.0)
            self.series["cpu_usage"].add(cpu_usage or 0.0)
            self.series["ram"].add(ram_pct)
            self.series["swap"].add(swap_pct)
            self.series["disk"].add(disk_pct)
            self.series["net_recv"].add(net_recv_speed or 0.0)
            self.series["net_sent"].add(net_sent_speed or 0.0)
        except Exception as e:
            print("push_sample error:", e)

    # ===== Mouse handling =====
    def on_motion(self, _widget, event):
        self._last_mouse_xy = (event.x, event.y)
        self._recompute_hover()
        self.area.queue_draw()
        return True

    def on_leave(self, *_):
        self._last_mouse_xy = None
        self.hover = None
        self.area.queue_draw()
        return True

    def _recompute_hover(self):
        if not self._last_mouse_xy:
            self.hover = None
            return

        x_mouse, y_mouse = self._last_mouse_xy
        # Геометрия должна совпадать с on_draw
        alloc = self.area.get_allocation()
        W, H = float(alloc.width), float(alloc.height)
        # Отступы: слева выделена зона легенды шириной LEGEND_W
        L, T, R, B = 100.0 + LEGEND_W, 20.0, 15.0, 30.0
        plot_w, plot_h = max(1.0, W - L - R), max(1.0, H - T - B)

        # соберём значения
        all_vals = []
        for s in self.series.values():
            all_vals += s.values()
        if not all_vals:
            self.hover = None
            return

        ymin = min(all_vals)
        ymax = max(all_vals)
        if abs(ymax - ymin) < 1e-6:
            ymin -= 1.0
            ymax += 1.0
        pad = 0.05 * (ymax - ymin)
        ymin -= pad
        ymax += pad

        def xy_for(idx, val):
            step = plot_w / max(1, HISTORY_SECONDS - 1)
            x = L + idx * step
            y = T + (1.0 - (val - ymin) / (ymax - ymin)) * plot_h
            return x, y

        # ищем ближайшую точку к курсору во всех сериях
        best = None
        best_dist2 = (HOVER_RADIUS_PX + 1.0) ** 2
        for key, ts in self.series.items():
            vals = ts.values()[-HISTORY_SECONDS:]
            for idx, v in enumerate(vals):
                x, y = xy_for(idx, v)
                if x < L or x > L + plot_w or y < T or y > T + plot_h:
                    continue
                dx = x - x_mouse
                dy = y - y_mouse
                d2 = dx * dx + dy * dy
                if d2 <= best_dist2:
                    best_dist2 = d2
                    best = (key, idx, v, x, y, len(vals) - 1 - idx)  # sec_ago

        if best:
            key, idx, v, x, y, sec_ago = best
            self.hover = {
                "series": key,
                "idx": idx,
                "value": v,
                "x": x,
                "y": y,
                "sec_ago": sec_ago
            }
        else:
            self.hover = None

    # ===== Drawing =====
    def on_draw(self, widget, cr):
        try:
            alloc = widget.get_allocation()
            W, H = float(alloc.width), float(alloc.height)

            # ЛЕВАЯ КОЛОНКА ПОД ЛЕГЕНДУ
            legend_x = 0.0
            legend_y = 0.0
            legend_w = LEGEND_W
            legend_h = H

            # Область графика
            L, T, R, B = 100.0 + LEGEND_W, 20.0, 15.0, 30.0
            plot_w, plot_h = max(1.0, W - L - R), max(1.0, H - T - B)

            # фон
            cr.set_source_rgb(0.1, 0.1, 0.12)
            cr.rectangle(0, 0, W, H)
            cr.fill()

            # собрать данные для масштаба
            all_vals = []
            for s in self.series.values():
                all_vals += s.values()
            if not all_vals:
                return False

            ymin = min(all_vals)
            ymax = max(all_vals)
            if abs(ymax - ymin) < 1e-6:
                ymin -= 1.0
                ymax += 1.0
            pad = 0.05 * (ymax - ymin)
            ymin -= pad
            ymax += pad

            # сетка
            cr.set_source_rgba(1, 1, 1, 0.08)
            cr.set_line_width(1.0)
            grid_lines = 5
            for i in range(grid_lines + 1):
                y = T + plot_h * (i / grid_lines)
                cr.move_to(L, y)
                cr.line_to(L + plot_w, y)
                cr.stroke()

            # оси
            cr.set_source_rgba(1, 1, 1, 0.25)
            cr.set_line_width(1.2)
            cr.move_to(L, T)
            cr.line_to(L, T + plot_h)
            cr.stroke()
            cr.move_to(L, T + plot_h)
            cr.line_to(L + plot_w, T + plot_h)
            cr.stroke()

            # подписи Y (слева от графика, но справа от легенды)
            cr.select_font_face("Monospace", 0, 0)
            cr.set_font_size(10)
            for val in [ymin, (ymin + ymax) / 2.0, ymax]:
                y = T + (1.0 - (val - ymin) / (ymax - ymin)) * plot_h
                # Форматирование в зависимости от типа данных
                if val < 1:  # для сетевых скоростей (обычно меньше 1 MB/s)
                    text = f"{val:.1f}"
                else:
                    text = f"{val:.0f}"
                cr.set_source_rgba(1, 1, 1, 0.7)
                cr.move_to(L - 20, y + 4)
                cr.show_text(text)

            # линии
            def draw_series(vals, rgb_tuple):
                if not vals:
                    return
                step = plot_w / max(1, HISTORY_SECONDS - 1)
                cr.set_source_rgba(*rgb_tuple, 0.95)
                cr.set_line_width(1.8)
                for idx, v in enumerate(vals[-HISTORY_SECONDS:]):
                    x = L + idx * step
                    y = T + (1.0 - (v - ymin) / (ymax - ymin)) * plot_h
                    if idx == 0:
                        cr.move_to(x, y)
                    else:
                        cr.line_to(x, y)
                cr.stroke()

            draw_series(self.series["cpu_temp"].values(), GRAPH_COLORS["cpu_temp"])
            draw_series(self.series["cpu_usage"].values(), GRAPH_COLORS["cpu_usage"])
            draw_series(self.series["ram"].values(), GRAPH_COLORS["ram"])
            draw_series(self.series["swap"].values(), GRAPH_COLORS["swap"])
            draw_series(self.series["disk"].values(), GRAPH_COLORS["disk"])
            draw_series(self.series["net_recv"].values(), GRAPH_COLORS["net_recv"])
            draw_series(self.series["net_sent"].values(), GRAPH_COLORS["net_sent"])

            # вертикальная направляющая и маркер, если наведено
            if self.hover:
                hx, hy = self.hover["x"], self.hover["y"]
                s_key = self.hover["series"]

                # гайдлайн
                cr.set_source_rgba(1, 1, 1, 0.18)
                cr.set_line_width(1.0)
                cr.move_to(hx, T)
                cr.line_to(hx, T + plot_h)
                cr.stroke()

                # маркер
                col = GRAPH_COLORS.get(s_key, (1, 1, 1))
                cr.set_source_rgba(*col, 1.0)
                cr.arc(hx, hy, 3.5, 0, 6.28318)
                cr.fill()

            # ЛЕГЕНДА СЛЕВА (и hover-информация тут же)
            legend_items = [
                (tr("cpu"), GRAPH_COLORS["cpu_temp"], "cpu_temp", "°C"),
                (tr("cpu"), GRAPH_COLORS["cpu_usage"], "cpu_usage", "%"),
                (tr("ram"), GRAPH_COLORS["ram"], "ram", "%"),
                (tr("swap"), GRAPH_COLORS["swap"], "swap", "%"),
                (tr("disk"), GRAPH_COLORS["disk"], "disk", "%"),
                (tr("network") + " ↓", GRAPH_COLORS["net_recv"], "net_recv", "MB/s"),
                (tr("network") + " ↑", GRAPH_COLORS["net_sent"], "net_sent", "MB/s"),
            ]
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(11)
            base_x = 12.0
            base_y = T + 20.0
            row_h = 22.0
            for i, (name, col, key, unit) in enumerate(legend_items):
                y = base_y + i * row_h
                # цветной квадратик
                cr.set_source_rgba(*col, 0.95)
                cr.rectangle(base_x, y - 9, 14, 14)
                cr.fill()
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.move_to(base_x + 20, y + 2)
                cr.show_text(name)

            if self.hover:
                s_key = self.hover["series"]
                val = self.hover["value"]
                sec_ago = self.hover["sec_ago"]
                when = f"{sec_ago}s ago" if sec_ago > 0 else "now"

                # Определяем единицы измерения и форматирование
                unit_map = {
                    "cpu_temp": "°C",
                    "cpu_usage": "%",
                    "ram": "%",
                    "swap": "%",
                    "disk": "%",
                    "net_recv": "MB/s",
                    "net_sent": "MB/s"
                }
                unit = unit_map.get(s_key, "")

                # Форматирование значения
                if s_key in ["net_recv", "net_sent"]:  # сетевые скорости - 2 знака после запятой
                    formatted_val = f"{val:.2f}"
                elif s_key in ["cpu_usage", "ram", "swap", "disk"]:  # проценты - 1 знак
                    formatted_val = f"{val:.1f}"
                else:  # температура - целое число
                    formatted_val = f"{val:.0f}"

                # Определяем название метрики для отображения
                metric_name_map = {
                    "cpu_temp": tr("cpu") + " (°C)",
                    "cpu_usage": tr("cpu") + " (%)",
                    "ram": tr("ram") + " (%)",
                    "swap": tr("swap") + " (%)",
                    "disk": tr("disk") + " (%)",
                    "net_recv": tr("network") + " ↓",
                    "net_sent": tr("network") + " ↑"
                }
                metric_name = metric_name_map.get(s_key, s_key)

                info_text = f"{metric_name}: {formatted_val}{unit} • {when}"

                cr.set_font_size(14)
                text_extents = cr.text_extents(info_text)
                text_width = text_extents.width
                text_height = text_extents.height

                text_x = (W - text_width) / 2
                text_y = H - B / 2

                cr.set_source_rgba(1, 1, 1, 0.85)
                cr.move_to(text_x, text_y)
                cr.show_text(info_text)
            return False
        except Exception as e:
            print("Drawing error:", e)
            return False


# ---------------------------
# Notifiers
# ---------------------------
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
                with open(TELEGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.token = (cfg.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
                self.chat_id = (str(cfg.get("TELEGRAM_CHAT_ID") or "").strip() or None)
                self.enabled = bool(cfg.get("enabled", False))
                self.notification_interval = int(cfg.get("notification_interval", 3600))
        except Exception as e:
            print("Telegram config load error:", e)

    def save_config(self, token, chat_id, enabled, interval) -> bool:
        try:
            self.token = token.strip() if token else None
            self.chat_id = chat_id.strip() if chat_id else None
            self.enabled = bool(enabled)
            self.notification_interval = int(interval)
            with open(TELEGRAM_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "TELEGRAM_BOT_TOKEN": self.token,
                        "TELEGRAM_CHAT_ID": self.chat_id,
                        "enabled": self.enabled,
                        "notification_interval": self.notification_interval,
                    },
                    f,
                    indent=2,
                )
            try:
                os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            print("Telegram config save error:", e)
            return False

    def send_message(self, message: str) -> bool:
        if not (self.enabled and self.token and self.chat_id):
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            r = requests.post(url, data=payload, timeout=(3, 7))
            return r.status_code == 200
        except Exception as e:
            print("Telegram send error:", e)
            return False


class DiscordNotifier:
    def __init__(self):
        self.webhook_url = None
        self.enabled = False
        self.notification_interval = 3600
        self.load_config()

    def load_config(self):
        try:
            if os.path.exists(DISCORD_CONFIG_FILE):
                with open(DISCORD_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.webhook_url = (cfg.get("DISCORD_WEBHOOK_URL") or "").strip()
                self.enabled = bool(cfg.get("enabled", False))
                self.notification_interval = int(cfg.get("notification_interval", 3600))
        except Exception as e:
            print("Discord config load error:", e)

    def save_config(self, webhook_url, enabled, interval) -> bool:
        try:
            self.webhook_url = (webhook_url or "").strip()
            self.enabled = bool(enabled)
            self.notification_interval = int(interval)
            with open(DISCORD_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "DISCORD_WEBHOOK_URL": self.webhook_url,
                        "enabled": self.enabled,
                        "notification_interval": self.notification_interval,
                    },
                    f,
                    indent=2,
                )
            try:
                os.chmod(DISCORD_CONFIG_FILE, 0.600)
            except Exception:
                pass
            return True
        except Exception as e:
            print("Discord config save error:", e)
            return False

    def send_message(self, message: str) -> bool:
        if not (self.enabled and self.webhook_url):
            return False
        try:
            payload = {"content": message, "username": "System Monitor"}
            r = requests.post(self.webhook_url, json=payload, timeout=(3, 7))
            return r.status_code in (200, 204)
        except Exception as e:
            print("Discord send error:", e)
            return False


# ---------------------------
# Power control
# ---------------------------
class Action(Enum):
    POWER_OFF = "power_off"
    REBOOT = "reboot"
    LOCK = "lock"


def action_label(act: Action) -> str:
    return {
        Action.POWER_OFF: tr("power_off"),
        Action.REBOOT: tr("reboot"),
        Action.LOCK: tr("lock"),
    }.get(act, act.value)


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
        self.parent_window = parent if isinstance(parent, Gtk.Widget) and parent.get_mapped() else None

    def _confirm_action(self, _widget, action_callback, message):
        self._destroy_current_dialog()
        dlg = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=message or tr("confirm_title"),
        )
        dlg.set_title(tr("confirm_title"))
        self.current_dialog = dlg

        def on_resp(d, rid):
            if rid == Gtk.ResponseType.OK and action_callback:
                action_callback()
            self._destroy_current_dialog()

        dlg.connect("response", on_resp)
        dlg.show()

    def _shutdown(self):
        if os.system("loginctl poweroff") != 0:
            os.system("systemctl poweroff")

    def _reboot(self):
        if os.system("loginctl reboot") != 0:
            os.system("systemctl reboot")

    def _lock_screen(self):
        for c in (
                "loginctl lock-session",
                "gnome-screensaver-command -l",
                "xdg-screensaver lock",
                "dm-tool lock",
        ):
            if os.system(c) == 0:
                return

    def _open_settings(self, *_):
        # Small dialog to schedule power/reboot/lock after N minutes
        self._destroy_current_dialog()

        dlg = Gtk.Dialog(title=tr("settings"), transient_for=self.parent_window, flags=0)
        self.current_dialog = dlg
        content = dlg.get_content_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        content.add(box)

        # time
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_time = Gtk.Label(label=tr("minutes"));
        lbl_time.set_xalign(0)
        sp = Gtk.SpinButton.new_with_range(1, 1440, 1)
        sp.set_value(1)
        time_box.pack_start(lbl_time, True, True, 0)
        time_box.pack_start(sp, False, False, 0)

        # action
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_act = Gtk.Label(label=tr("action"));
        lbl_act.set_xalign(0)
        combo = Gtk.ComboBoxText()
        combo.append(Action.POWER_OFF.value, action_label(Action.POWER_OFF))
        combo.append(Action.REBOOT.value, action_label(Action.REBOOT))
        combo.append(Action.LOCK.value, action_label(Action.LOCK))
        combo.set_active(0)
        action_box.pack_start(lbl_act, True, True, 0)
        action_box.pack_start(combo, False, False, 0)

        # buttons
        btn_apply = Gtk.Button(label=tr("apply"))
        btn_cancel = Gtk.Button(label=tr("cancel"))
        btn_reset = Gtk.Button(label=tr("reset"))
        btn_apply.connect("clicked", lambda *_: dlg.response(Gtk.ResponseType.OK))
        btn_cancel.connect("clicked", lambda *_: dlg.response(Gtk.ResponseType.CANCEL))
        btn_reset.connect("clicked", self._reset_action_button)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)
        for b in (btn_reset, btn_cancel, btn_apply):
            btn_box.pack_start(b, False, False, 0)

        # pack
        box.pack_start(time_box, False, False, 0)
        box.pack_start(action_box, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 6)
        box.pack_start(btn_box, False, False, 0)

        dlg.show_all()
        resp = dlg.run()

        if resp == Gtk.ResponseType.OK:
            minutes = sp.get_value_as_int()
            act = Action(combo.get_active_id())
            if minutes <= 0:
                self._info(tr("error"), tr("error_minutes_positive"))
                self._destroy_current_dialog()
                return
            self.scheduled_action = act
            self.remaining_seconds = minutes * 60
            if minutes > 1:
                self._notify_timer_id = GLib.timeout_add_seconds((minutes - 1) * 60, self._notify_before_action, act)
            self._action_timer_id = GLib.timeout_add_seconds(self.remaining_seconds, self._delayed_action, act)
            if self._update_timer_id:
                GLib.source_remove(self._update_timer_id)
            self._update_timer_id = GLib.timeout_add_seconds(1, self._update_indicator_label)
            self._info(tr("scheduled"), tr("action_in_time").format(action_label(act), minutes))

        self._destroy_current_dialog()

    def _reset_action_button(self, *_):
        for tid_attr in ("_update_timer_id", "_notify_timer_id", "_action_timer_id"):
            tid = getattr(self, tid_attr)
            if tid:
                GLib.source_remove(tid)
                setattr(self, tid_attr, None)
        self.scheduled_action = None
        self.remaining_seconds = 0
        self.app.indicator.set_label("", "")
        self._info(tr("cancelled"), tr("cancelled_text"))

    def _notify_before_action(self, act: Action):
        self._notify_timer_id = None
        self._info(tr("notification"), tr("action_in_1_min").format(action_label(act)))
        return False

    def _update_indicator_label(self):
        if self.remaining_seconds <= 0:
            self.app.indicator.set_label("", "")
            return False
        h = self.remaining_seconds // 3600
        m = (self.remaining_seconds % 3600) // 60
        s = self.remaining_seconds % 60
        self.app.indicator.set_label(f"{action_label(self.scheduled_action)} — {h:02d}:{m:02d}:{s:02d}", "")
        self.remaining_seconds -= 1
        return True

    def _delayed_action(self, act: Action):
        self._action_timer_id = None
        self.app.indicator.set_label("", "")
        self.scheduled_action = None
        self.remaining_seconds = 0
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id)
            self._update_timer_id = None
        {Action.POWER_OFF: self._shutdown, Action.REBOOT: self._reboot, Action.LOCK: self._lock_screen}[act]()
        return False

    # small helpers
    def _info(self, title: str, message: str):
        parent = self.parent_window if (self.parent_window and self.parent_window.get_mapped()) else None
        dlg = Gtk.MessageDialog(transient_for=parent, flags=0, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK, text=message)
        dlg.set_title(title)
        dlg.run()
        dlg.destroy()

    def _destroy_current_dialog(self):
        if self.current_dialog and isinstance(self.current_dialog, Gtk.Widget):
            self.current_dialog.destroy()
        self.current_dialog = None


# ---------------------------
# Settings dialog
# ---------------------------
class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, visibility):
        super().__init__(title=tr("settings_label"), transient_for=parent if isinstance(parent, Gtk.Widget) else None, flags=0)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.add_buttons(tr("cancel_label"), Gtk.ResponseType.CANCEL, tr("apply_label"), Gtk.ResponseType.OK)
        self.visibility_settings = visibility

        box = self.get_content_area()
        box.set_border_width(10)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_halign(Gtk.Align.END)
        header.pack_start(Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ"), False, False, 0)
        box.add(header)

        # Tray toggles
        self.tray_cpu_check = self._add_check(box, "cpu_tray", key="tray_cpu", default=True)
        self.tray_ram_check = self._add_check(box, "ram_tray", key="tray_ram", default=True)

        box.add(self._sep())

        # UI / Menu toggles
        self.graphs_check = self._add_check(box, "graphs", key="show_graphs", default=True)

        box.add(self._sep())

        # Info toggles
        self.cpu_check = self._add_check(box, "cpu_info", key="cpu")
        self.ram_check = self._add_check(box, "ram_loading", key="ram")
        self.swap_check = self._add_check(box, "swap_loading", key="swap")
        self.disk_check = self._add_check(box, "disk_loading", key="disk")
        self.net_check = self._add_check(box, "lan_speed", key="net")
        self.uptime_check = self._add_check(box, "uptime_label", key="uptime")
        self.keyboard_check = self._add_check(box, "keyboard_clicks", key="keyboard_clicks")
        self.mouse_check = self._add_check(box, "mouse_clicks", key="mouse_clicks")

        box.add(self._sep())

        # Power toggles
        self.power_off_check = self._add_check(box, "power_off", key="show_power_off")
        self.reboot_check = self._add_check(box, "reboot", key="show_reboot")
        self.lock_check = self._add_check(box, "lock", key="show_lock")
        self.timer_check = self._add_check(box, "settings", key="show_timer")

        box.add(self._sep())

        # Ping
        self.ping_check = self._add_check(box, "ping_network", key="ping_network")

        box.add(self._sep())

        # Logging controls
        logging_box = Gtk.Box(spacing=6)
        self.logging_check = Gtk.CheckButton(label=tr("enable_logging"))
        self.logging_check.set_active(self.visibility_settings.get("logging_enabled", True))
        self.logging_check.set_margin_bottom(3)
        logging_box.pack_start(self.logging_check, False, False, 0)

        self.download_button = Gtk.Button(label=tr("download_log"))
        self.download_button.connect("clicked", self.download_log_file)
        self.download_button.set_margin_bottom(3)
        logging_box.pack_end(self.download_button, False, False, 0)
        box.add(logging_box)

        logsize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        logsize_label = Gtk.Label(label=tr("max_log_size_mb"));
        logsize_label.set_xalign(0)
        self.logsize_spin = Gtk.SpinButton.new_with_range(1, 1024, 1)
        self.logsize_spin.set_value(int(self.visibility_settings.get("max_log_mb", 1000)))
        logsize_box.pack_start(logsize_label, False, False, 0)
        logsize_box.pack_start(self.logsize_spin, False, False, 0)
        box.add(logsize_box)

        box.add(self._sep())

        # Telegram
        tele_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.telegram_enable_check = Gtk.CheckButton(label=tr("telegram_notification"))
        tele_row.pack_start(self.telegram_enable_check, False, False, 0)
        test_btn = Gtk.Button(label=tr("check_telegram"))
        test_btn.set_halign(Gtk.Align.END)
        test_btn.connect("clicked", self.test_telegram)
        tele_row.pack_end(test_btn, False, False, 0)
        box.add(tele_row)

        self.token_entry = self._secret_entry(box, tr("token_bot"), "123...:ABC...")
        self.chat_id_entry = self._secret_entry(box, tr("id_chat"), "123456789")

        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        interval_label = Gtk.Label(label=tr("time_send"));
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
        disc_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.discord_enable_check = Gtk.CheckButton(label=tr("discord_notification"))
        disc_row.pack_start(self.discord_enable_check, False, False, 0)
        disc_test = Gtk.Button(label=tr("check_discord"))
        disc_test.set_halign(Gtk.Align.END)
        disc_test.connect("clicked", self.test_discord)
        disc_row.pack_end(disc_test, False, False, 0)
        box.add(disc_row)

        self.webhook_entry = self._secret_entry(box, tr("webhook_url"), "https://discord.com/api/webhooks/...")

        disc_int_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        disc_int_label = Gtk.Label(label=tr("time_send"));
        disc_int_label.set_xalign(0)
        self.discord_interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1);
        self.discord_interval_spin.set_value(3600)
        disc_int_box.pack_start(disc_int_label, False, False, 0)
        disc_int_box.pack_start(self.discord_interval_spin, True, True, 0)
        disc_int_box.set_margin_top(3);
        disc_int_box.set_margin_bottom(30);
        disc_int_box.set_margin_end(50)
        box.add(disc_int_box)

        # preload configs
        try:
            if os.path.exists(TELEGRAM_CONFIG_FILE):
                with open(TELEGRAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.token_entry.set_text(cfg.get("TELEGRAM_BOT_TOKEN", "") or "")
                self.chat_id_entry.set_text(str(cfg.get("TELEGRAM_CHAT_ID", "") or ""))
                self.telegram_enable_check.set_active(bool(cfg.get("enabled", False)))
                self.interval_spin.set_value(int(cfg.get("notification_interval", 3600)))
        except Exception as e:
            print("Telegram config preload error:", e)

        try:
            if os.path.exists(DISCORD_CONFIG_FILE):
                with open(DISCORD_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.webhook_entry.set_text(cfg.get("DISCORD_WEBHOOK_URL", "") or "")
                self.discord_enable_check.set_active(bool(cfg.get("enabled", False)))
                self.discord_interval_spin.set_value(int(cfg.get("notification_interval", 3600)))
        except Exception as e:
            print("Discord config preload error:", e)

        self.show_all()

    # small UI builders
    def _sep(self):
        s = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        s.set_margin_top(6)
        s.set_margin_bottom(6)
        return s

    def _add_check(self, box, label_key, key=None, default=None):
        chk = Gtk.CheckButton(label=tr(label_key))
        if key is None:
            chk.set_active(self.visibility_settings.get(label_key, True if default is None else default))
        else:
            chk.set_active(self.visibility_settings.get(key, True if default is None else default))
        box.add(chk)
        return chk

    def _secret_entry(self, box, label, placeholder):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl = Gtk.Label(label=label);
        lbl.set_xalign(0)
        entry = Gtk.Entry();
        entry.set_placeholder_text(placeholder);
        entry.set_visibility(False)
        row.pack_start(lbl, False, False, 0)
        row.pack_start(entry, True, True, 0)
        toggle = Gtk.ToggleButton(label="👁");
        toggle.set_relief(Gtk.ReliefStyle.NONE)
        toggle.connect("toggled", lambda btn: entry.set_visibility(btn.get_active()))
        row.pack_end(toggle, False, False, 0)
        box.add(row)
        return entry

    # actions
    def test_telegram(self, _w):
        token = self.token_entry.get_text().strip()
        chat_id = self.chat_id_entry.get_text().strip()
        enabled = self.telegram_enable_check.get_active()
        interval = int(self.interval_spin.get_value())
        if not token or not chat_id:
            self._info(tr("error"), tr("bot_message"))
            return
        notifier = TelegramNotifier()
        if notifier.save_config(token, chat_id, enabled, interval):
            ok = notifier.send_message(tr("test_message"))
            self._info(tr("ok") if ok else tr("error"), tr("test_message_ok") if ok else tr("test_message_error"))
        else:
            self._info(tr("error"), tr("setting_telegram_error"))

    def test_discord(self, _w):
        webhook_url = self.webhook_entry.get_text().strip()
        enabled = self.discord_enable_check.get_active()
        interval = int(self.discord_interval_spin.get_value())
        if not webhook_url:
            self._info(tr("error"), tr("webhook_required"))
            return
        notifier = DiscordNotifier()
        if notifier.save_config(webhook_url, enabled, interval):
            ok = notifier.send_message(tr("test_message"))
            self._info(tr("ok") if ok else tr("error"), tr("test_message_ok") if ok else tr("test_message_error"))
        else:
            self._info(tr("error"), tr("setting_discord_error"))

    def _info(self, title, message):
        dlg = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK, text=message)
        dlg.set_title(title)
        dlg.run()
        dlg.destroy()

    def download_log_file(self, _w):
        dlg = Gtk.FileChooserDialog(title=tr("download_log"), parent=self if self.get_mapped() else None,
                                    action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons(tr("cancel_label"), Gtk.ResponseType.CANCEL, tr("apply_label"), Gtk.ResponseType.OK)
        dlg.set_current_name("info_log.txt")
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            dest = dlg.get_filename()
            try:
                if not os.path.exists(LOG_FILE):
                    raise FileNotFoundError(LOG_FILE)
                with open(LOG_FILE, "r", encoding="utf-8") as src, open(dest, "w", encoding="utf-8") as dst:
                    dst.write(src.read())
            except Exception as e:
                print("Save log error:", e)
        dlg.destroy()


# ---------------------------
# Main App
# ---------------------------
class SystemTrayApp:
    def __init__(self):
        self.settings_file = SETTINGS_FILE
        self.visibility_settings = self._load_settings()

        # init language
        global current_lang
        if not self.visibility_settings.get("language"):
            self.visibility_settings["language"] = detect_system_language()
            self._save_settings()
        current_lang = self.visibility_settings["language"]

        # indicator
        self.indicator = AppInd.Indicator.new("SystemMonitor", "system-run-symbolic", AppInd.IndicatorCategory.SYSTEM_SERVICES)
        self._set_icon()
        self.indicator.set_status(AppInd.IndicatorStatus.ACTIVE)

        # signals
        signal.signal(signal.SIGTERM, self.quit)
        signal.signal(signal.SIGINT, self.quit)

        # power
        self.power_control = PowerControl(self)
        self.power_control.set_parent_window(None)

        # menu
        self.graph_window = None
        self._build_menu()

        # net counters
        io = psutil.net_io_counters()
        self.prev_net_data = {"recv": io.bytes_recv, "sent": io.bytes_sent, "time": time.time()}

        # hooks
        self.keyboard_listener = None
        self.mouse_listener = None
        self._init_listeners()

        # notifiers
        self.telegram_notifier = TelegramNotifier()
        self.discord_notifier = DiscordNotifier()
        self.last_telegram_notification_time = 0
        self.last_discord_notification_time = 0

        # logging file ensure
        if self.visibility_settings.get("logging_enabled", True) and not os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "w", encoding="utf-8"):
                    pass
            except Exception as e:
                print("Cannot create log file:", e)

        self.settings_dialog = None

    # ---- init helpers
    def _set_icon(self):
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
            print("Icon setup failed:", e)
            self.indicator.set_icon("system-run-symbolic")

    def _init_listeners(self):
        if keyboard is not None:
            try:
                self.keyboard_listener = keyboard.Listener(on_press=self._on_key_press, daemon=True)
                self.keyboard_listener.start()
            except Exception as e:
                print("Keyboard listener error:", e)
        if mouse is not None:
            try:
                self.mouse_listener = mouse.Listener(on_click=self._on_mouse_click, daemon=True)
                self.mouse_listener.start()
            except Exception as e:
                print("Mouse listener error:", e)

    # ---- menu & UI
    def _build_menu(self):
        self.menu = Gtk.Menu()
        # indicator items
        self.cpu_temp_item = Gtk.MenuItem(label=f"{tr('cpu_info')}: N/A")
        self.ram_item = Gtk.MenuItem(label=f"{tr('ram_loading')}: N/A")
        self.swap_item = Gtk.MenuItem(label=f"{tr('swap_loading')}: N/A")
        self.disk_item = Gtk.MenuItem(label=f"{tr('disk_loading')}: N/A")
        self.net_item = Gtk.MenuItem(label=f"{tr('lan_speed')}: N/A")
        self.uptime_item = Gtk.MenuItem(label=f"{tr('uptime_label')}: N/A")
        self.keyboard_item = Gtk.MenuItem(label=f"{tr('keyboard_clicks')}: 0")
        self.mouse_item = Gtk.MenuItem(label=f"{tr('mouse_clicks')}: 0")

        # ping
        self.ping_item = Gtk.MenuItem(label=tr("ping_network"))
        self.ping_item.connect("activate", self._on_ping_click)
        self.ping_top_sep = Gtk.SeparatorMenuItem()
        self.ping_bottom_sep = Gtk.SeparatorMenuItem()

        # graphs
        self.graphs_item = Gtk.MenuItem(label=(tr("graphs") if "graphs" in (LANGUAGES.get(current_lang) or {}) else "Graphs"))
        self.graphs_item.connect("activate", self._open_graphs)

        # power block
        self.power_separator = Gtk.SeparatorMenuItem()
        self.power_off_item = Gtk.MenuItem(label=tr("power_off"))
        self.power_off_item.connect("activate", self.power_control._confirm_action, self.power_control._shutdown, tr("confirm_text_power_off"))
        self.reboot_item = Gtk.MenuItem(label=tr("reboot"))
        self.reboot_item.connect("activate", self.power_control._confirm_action, self.power_control._reboot, tr("confirm_text_reboot"))
        self.lock_item = Gtk.MenuItem(label=tr("lock"))
        self.lock_item.connect("activate", self.power_control._confirm_action, self.power_control._lock_screen, tr("confirm_text_lock"))
        self.timer_item = Gtk.MenuItem(label=tr("settings"))
        self.timer_item.connect("activate", self.power_control._open_settings)

        self.main_separator = Gtk.SeparatorMenuItem()
        self.exit_separator = Gtk.SeparatorMenuItem()

        self.settings_item = Gtk.MenuItem(label=tr("settings_label"))
        self.settings_item.connect("activate", self._show_settings)

        # language submenu
        self.language_menu = Gtk.Menu()
        group_root = None
        for code in SUPPORTED_LANGS:
            label = (LANGUAGES.get(code) or LANGUAGES.get("en", {})).get("language_name", code)
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group_root, label)
            if group_root is None:
                group_root = item
            item.set_active(code == current_lang)
            item.connect("activate", self._on_language_selected, code)
            self.language_menu.append(item)
        self.language_menu_item = Gtk.MenuItem(label=tr("language"))
        self.language_menu_item.set_submenu(self.language_menu)

        self.quit_item = Gtk.MenuItem(label=tr("exit_app"))
        self.quit_item.connect("activate", self.quit)

        self._update_menu_visibility()

        # вставляем графики (только если включены)
        if self.visibility_settings.get("show_graphs", True):
            self.menu.append(self.graphs_item)

        if any(
                [
                    self.visibility_settings.get("show_power_off", True),
                    self.visibility_settings.get("show_reboot", True),
                    self.visibility_settings.get("show_lock", True),
                    self.visibility_settings.get("show_timer", True),
                ]
        ):
            self.menu.append(self.power_separator)
            if self.visibility_settings.get("show_power_off", True):
                self.menu.append(self.power_off_item)
            if self.visibility_settings.get("show_reboot", True):
                self.menu.append(self.reboot_item)
            if self.visibility_settings.get("show_lock", True):
                self.menu.append(self.lock_item)
            if self.visibility_settings.get("show_timer", True):
                self.menu.append(self.timer_item)

        self.menu.append(self.main_separator)

        if self.visibility_settings.get("ping_network", True):
            self.menu.append(self.ping_top_sep)
            self.menu.append(self.ping_item)
            self.menu.append(self.ping_bottom_sep)

        self.menu.append(self.language_menu_item)
        self.menu.append(self.settings_item)
        self.menu.append(self.exit_separator)
        self.menu.append(self.quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def _on_language_selected(self, widget, lang_code):
        """Смена языка: сохраняем и пересобираем меню с локализованными подписями."""
        global current_lang
        try:
            if hasattr(widget, "get_active") and widget.get_active():
                if lang_code != current_lang:
                    current_lang = lang_code
                    self.visibility_settings["language"] = current_lang
                    self._save_settings()
                    self._build_menu()  # пересборка меню для обновления всех надписей

                    # Обновить заголовок окна графиков, если оно открыто
                    if self.graph_window and isinstance(self.graph_window, GraphWindow):
                        self.graph_window.update_title()
                        self.graph_window.queue_draw()  # перерисовка на случай локализации текста
        except Exception as e:
            print("language switch error:", e)

    def _update_menu_visibility(self):
        children = self.menu.get_children() if hasattr(self, "menu") else []
        keep = [
            getattr(self, "main_separator", None),
            getattr(self, "power_separator", None),
            getattr(self, "exit_separator", None),
            getattr(self, "language_menu_item", None),
            getattr(self, "settings_item", None),
            getattr(self, "quit_item", None),
        ]
        # учитывать show_graphs при фиксации элементов, которые нельзя удалять
        if self.visibility_settings.get("show_graphs", True):
            keep.append(getattr(self, "graphs_item", None))

        if getattr(self, "ping_item", None) and self.visibility_settings.get("ping_network", True):
            keep.extend([self.ping_item, getattr(self, "ping_top_sep", None), getattr(self, "ping_bottom_sep", None)])
        keep = [x for x in keep if x is not None]

        for ch in list(children):
            if ch not in keep:
                try:
                    self.menu.remove(ch)
                except Exception:
                    pass

        # prepend в обратном порядке
        def maybe_prepend(flag_key, item):
            if self.visibility_settings.get(flag_key, True):
                self.menu.prepend(item)

        maybe_prepend("mouse_clicks", self.mouse_item)
        maybe_prepend("keyboard_clicks", self.keyboard_item)
        maybe_prepend("uptime", self.uptime_item)
        maybe_prepend("net", self.net_item)
        maybe_prepend("disk", self.disk_item)
        maybe_prepend("swap", self.swap_item)
        maybe_prepend("ram", self.ram_item)
        maybe_prepend("cpu", self.cpu_temp_item)

        self.menu.show_all()

    def _open_graphs(self, *_):
        try:
            if self.graph_window and self.graph_window.get_visible():
                self.graph_window.present()
                return
            if not self.graph_window:
                self.graph_window = GraphWindow(self)
                # Подключаем обработчик закрытия окна
                self.graph_window.connect("delete-event", self._on_graph_window_close)
            self.graph_window.show_all()
        except Exception as e:
            print("open_graphs error:", e)

    def _on_graph_window_close(self, widget, event):
        """Обработчик закрытия окна графиков - скрываем вместо уничтожения"""
        if self.graph_window:
            self.graph_window.hide()
        return True  # Предотвращаем уничтожение окна

    # ---- actions
    def _on_key_press(self, _key):
        global keyboard_clicks
        with _clicks_lock:
            keyboard_clicks += 1

    def _on_mouse_click(self, _x, _y, _button, pressed):
        global mouse_clicks
        if pressed:
            with _clicks_lock:
                mouse_clicks += 1

    def _on_ping_click(self, *_):
        host = "8.8.8.8"
        count = 4
        timeout = 5

        def worker():
            GLib.idle_add(lambda: self._info(tr("ping_network"), tr("ping_running")))
            try:
                proc = subprocess.run(["ping", "-c", str(count), "-w", str(timeout), host], capture_output=True, text=True)
                ok = proc.returncode == 0
                out = proc.stdout.strip() or proc.stderr.strip() or tr("ping_error")
                title = tr("ok") if ok else tr("error")
                msg = f"{tr('ping_done')} {host}\n\n{out}"
            except Exception as e:
                title = tr("error")
                msg = f"{tr('ping_error')}: {e}"
            GLib.idle_add(lambda: self._info(title, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _show_settings(self, _w):
        if getattr(self, "settings_dialog", None) and self.settings_dialog.get_mapped():
            self.settings_dialog.present()
            return

        dlg = SettingsDialog(None, self.visibility_settings)
        self.power_control.set_parent_window(dlg)
        self.settings_dialog = dlg

        try:
            resp = dlg.run()
            if resp == Gtk.ResponseType.OK:
                # sync toggles
                vis = self.visibility_settings
                vis["cpu"] = dlg.cpu_check.get_active()
                vis["ram"] = dlg.ram_check.get_active()
                vis["swap"] = dlg.swap_check.get_active()
                vis["disk"] = dlg.disk_check.get_active()
                vis["net"] = dlg.net_check.get_active()
                vis["uptime"] = dlg.uptime_check.get_active()
                vis["tray_cpu"] = dlg.tray_cpu_check.get_active()
                vis["tray_ram"] = dlg.tray_ram_check.get_active()
                vis["keyboard_clicks"] = dlg.keyboard_check.get_active()
                vis["mouse_clicks"] = dlg.mouse_check.get_active()
                vis["show_power_off"] = dlg.power_off_check.get_active()
                vis["show_reboot"] = dlg.reboot_check.get_active()
                vis["show_lock"] = dlg.lock_check.get_active()
                vis["show_timer"] = dlg.timer_check.get_active()
                vis["logging_enabled"] = dlg.logging_check.get_active()
                vis["ping_network"] = dlg.ping_check.get_active()
                vis["max_log_mb"] = int(dlg.logsize_spin.get_value())
                vis["show_graphs"] = dlg.graphs_check.get_active()

                # notifiers
                tel_enabled_before = self.telegram_notifier.enabled
                if self.telegram_notifier.save_config(
                        dlg.token_entry.get_text().strip(),
                        dlg.chat_id_entry.get_text().strip(),
                        dlg.telegram_enable_check.get_active(),
                        int(dlg.interval_spin.get_value()),
                ):
                    self.telegram_notifier.load_config()
                    if self.telegram_notifier.enabled and not tel_enabled_before:
                        self.last_telegram_notification_time = 0

                disc_enabled_before = self.discord_notifier.enabled
                if self.discord_notifier.save_config(
                        dlg.webhook_entry.get_text().strip(),
                        dlg.discord_enable_check.get_active(),
                        int(dlg.discord_interval_spin.get_value()),
                ):
                    self.discord_notifier.load_config()
                    if self.discord_notifier.enabled and not disc_enabled_before:
                        self.last_discord_notification_time = 0

                self._save_settings()
                self._build_menu()  # refresh labels in chosen language etc.
        finally:
            self.power_control.set_parent_window(None)
            if getattr(self, "settings_dialog", None):
                try:
                    self.settings_dialog.destroy()
                except Exception:
                    pass
            self.settings_dialog = None

    # ---- periodic update
    def update_info(self):
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

            # push to graphs
            if getattr(self, "graph_window", None):
                try:
                    self.graph_window.push_sample(cpu_temp, cpu_usage, ram_used, ram_total, swap_used, swap_total, disk_used, disk_total, net_recv_speed, net_sent_speed)
                except Exception as e:
                    print("graph push error:", e)

            self._update_ui(
                cpu_temp, cpu_usage,
                ram_used, ram_total,
                disk_used, disk_total,
                swap_used, swap_total,
                net_recv_speed, net_sent_speed,
                uptime, kbd, ms,
            )

            now = time.time()
            if self.telegram_notifier.enabled and now - self.last_telegram_notification_time >= self.telegram_notifier.notification_interval:
                threading.Thread(
                    target=self._send_telegram,
                    args=(cpu_temp, cpu_usage, ram_used, ram_total, disk_used, disk_total, swap_used, swap_total, net_recv_speed, net_sent_speed, uptime, kbd, ms),
                    daemon=True,
                ).start()
                self.last_telegram_notification_time = now

            if self.discord_notifier.enabled and now - self.last_discord_notification_time >= self.discord_notifier.notification_interval:
                threading.Thread(
                    target=self._send_discord,
                    args=(cpu_temp, cpu_usage, ram_used, ram_total, disk_used, disk_total, swap_used, swap_total, net_recv_speed, net_sent_speed, uptime, kbd, ms),
                    daemon=True,
                ).start()
                self.last_discord_notification_time = now

            if self.visibility_settings.get("logging_enabled", True):
                max_mb = int(self.visibility_settings.get("max_log_mb", 5))
                max_mb = max(1, min(max_mb, 1024))
                rotate_log_if_needed(max_mb * 1024 * 1024)
                try:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(
                            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"CPU: {cpu_usage:.0f}% {cpu_temp}°C | "
                            f"RAM: {ram_used:.1f}/{ram_total:.1f} GB | "
                            f"SWAP: {swap_used:.1f}/{swap_total:.1f} GB | "
                            f"Disk: {disk_used:.1f}/{disk_total:.1f} GB | "
                            f"Net: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s | "
                            f"Uptime: {uptime} | "
                            f"Keys: {kbd} | "
                            f"Clicks: {ms}\n"
                        )
                except Exception as e:
                    print("Log write error:", e)
            return True
        except Exception as e:
            print("update_info error:", e)
            return True

    def _send_telegram(self, *args):
        cpu_temp, cpu_usage, ram_used, ram_total, disk_used, disk_total, swap_used, swap_total, net_recv_speed, net_sent_speed, uptime, keyboard_clicks_val, mouse_clicks_val = args
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

    def _send_discord(self, *args):
        cpu_temp, cpu_usage, ram_used, ram_total, disk_used, disk_total, swap_used, swap_total, net_recv_speed, net_sent_speed, uptime, keyboard_clicks_val, mouse_clicks_val = args
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

    def _info(self, title: str, message: str):
        parent = self.settings_dialog if (self.settings_dialog and self.settings_dialog.get_mapped()) else None
        dlg = Gtk.MessageDialog(transient_for=parent, flags=0, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK, text=message)
        dlg.set_title(title)
        dlg.run()
        dlg.destroy()

    def _update_ui(self, cpu_temp, cpu_usage, ram_used, ram_total, disk_used, disk_total, swap_used, swap_total, net_recv_speed, net_sent_speed, uptime, keyboard_clicks_val, mouse_clicks_val):
        try:
            if self.visibility_settings["cpu"]:
                self.cpu_temp_item.set_label(f"{tr('cpu_info')}: {cpu_usage:.0f}%  🌡{cpu_temp}°C")
            if self.visibility_settings["ram"]:
                self.ram_item.set_label(f"{tr('ram_loading')}: {ram_used:.1f}/{ram_total:.1f} GB")
            if self.visibility_settings["swap"]:
                self.swap_item.set_label(f"{tr('swap_loading')}: {swap_used:.1f}/{swap_total:.1f} GB")
            if self.visibility_settings["disk"]:
                self.disk_item.set_label(f"{tr('disk_loading')}: {disk_used:.1f}/{disk_total:.1f} GB")
            if self.visibility_settings["net"]:
                self.net_item.set_label(f"{tr('lan_speed')}: ↓{net_recv_speed:.1f}/↑{net_sent_speed:.1f} MB/s")
            if self.visibility_settings["uptime"]:
                self.uptime_item.set_label(f"{tr('uptime_label')}: {uptime}")
            if self.visibility_settings["keyboard_clicks"]:
                self.keyboard_item.set_label(f"{tr('keyboard_clicks')}: {keyboard_clicks_val}")
            if self.visibility_settings["mouse_clicks"]:
                self.mouse_item.set_label(f"{tr('mouse_clicks')}: {mouse_clicks_val}")

            tray_parts = []
            if self.visibility_settings.get("tray_cpu", True):
                tray_parts.append(f"{tr('cpu_info')}: {cpu_usage:.0f}%")
            if self.visibility_settings.get("tray_ram", True):
                tray_parts.append(f"{tr('ram_loading')}: {ram_used:.1f}GB")
            tray_text = "  ".join(tray_parts)
            if self.telegram_notifier.enabled or self.discord_notifier.enabled:
                tray_text = "⤴  " + tray_text
            self.indicator.set_label(tray_text, "")
        except Exception as e:
            print("_update_ui error:", e)

    # ---- settings persistence
    def _load_settings(self):
        vis = DEFAULT_VISIBILITY.copy()
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                vis.update(json.load(f))
            # миграция старых ключей, если встречаются
            if "cpu_tray" in vis and "tray_cpu" not in vis:
                vis["tray_cpu"] = bool(vis.pop("cpu_tray"))
            if "ram_tray" in vis and "tray_ram" not in vis:
                vis["tray_ram"] = bool(vis.pop("ram_tray"))
        except Exception:
            pass
        return vis

    def _save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.visibility_settings, f, indent=4)
        except Exception as e:
            print("Settings save error:", e)

    # ---- lifecycle
    def quit(self, *args):
        # timers from power control
        for tid_attr in ("_update_timer_id", "_notify_timer_id", "_action_timer_id"):
            tid = getattr(self.power_control, tid_attr, None)
            if tid:
                GLib.source_remove(tid)
        # dialogs
        if self.power_control.current_dialog and isinstance(self.power_control.current_dialog, Gtk.Widget):
            self.power_control.current_dialog.destroy()
            self.power_control.current_dialog = None
        if self.settings_dialog is not None:
            self.settings_dialog.destroy()
            self.settings_dialog = None
        # graph window - правильно уничтожаем
        if getattr(self, "graph_window", None):
            try:
                # Удаляем обработчики и уничтожаем окно
                if hasattr(self.graph_window, 'disconnect_by_func'):
                    self.graph_window.disconnect_by_func(self._on_graph_window_close)
                self.graph_window.destroy()
            except Exception as e:
                print("Error destroying graph window:", e)
            finally:
                self.graph_window = None
        # hooks
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

    # ---- main run method
    def run(self):
        """Запуск основного цикла приложения"""
        # Запускаем периодическое обновление информации
        GLib.timeout_add_seconds(TIME_UPDATE_SECONDS, self.update_info)
        # Запускаем главный цикл GTK
        Gtk.main()


# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == "__main__":
    Gtk.init([])
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = SystemTrayApp()
    app.run()