from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional, TYPE_CHECKING

import requests
import psutil
from requests import Response
from gi.repository import GLib

from app_core.constants import TELEGRAM_CONFIG_FILE
from app_core.localization import tr
from app_core.system_usage import SystemUsage
from app_core.click_tracker import get_counts

if TYPE_CHECKING:
    from app_core.power_control import PowerControl
    from app_core.app import SystemTrayApp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    MAX_MESSAGE_LENGTH = 4096
    _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    _MAX_SEND_RETRIES = 3
    _MAX_PHOTO_SEND_RETRIES = 3
    _PHOTO_OPTIMIZE_THRESHOLD_BYTES = 2 * 1024 * 1024

    def __init__(self):
        self.token: Optional[str] = None
        self.chat_id: Optional[str] = None
        self.enabled: bool = False
        self.notification_interval: int = 3600
        self.screenshot_quality: str = "medium"
        self.last_update_id: int = 0
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_running: bool = False
        self.power_control_ref: Optional["PowerControl"] = None
        self.app_ref: Optional["SystemTrayApp"] = None
        self.load_config()

    def load_config(self) -> None:
        try:
            if TELEGRAM_CONFIG_FILE.exists():
                config = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                self.token = (config.get('TELEGRAM_BOT_TOKEN') or '').strip() or None
                self.chat_id = (str(config.get('TELEGRAM_CHAT_ID') or '').strip() or None)
                self.enabled = bool(config.get('enabled', False))
                self.notification_interval = self._normalize_interval(config.get('notification_interval', 3600))
                self.screenshot_quality = self._normalize_screenshot_quality(config.get('screenshot_quality', "medium"))
        except Exception as e:
            logger.exception("Ошибка загрузки конфигурации Telegram: %s", e)

    def save_config(
            self,
            token: str,
            chat_id: str,
            enabled: bool,
            interval: int,
            screenshot_quality: str = "medium",
    ) -> bool:
        try:
            self.token = token.strip() if token else None
            self.chat_id = chat_id.strip() if chat_id else None
            self.enabled = bool(enabled)
            self.notification_interval = self._normalize_interval(interval)
            self.screenshot_quality = self._normalize_screenshot_quality(screenshot_quality)
            TELEGRAM_CONFIG_FILE.write_text(json.dumps({
                'TELEGRAM_BOT_TOKEN': self.token,
                'TELEGRAM_CHAT_ID': self.chat_id,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval,
                'screenshot_quality': self.screenshot_quality,
            }, indent=2), encoding="utf-8")
            try:
                import os
                os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.exception("Ошибка сохранения конфигурации Telegram: %s", e)
            return False

    @staticmethod
    def _normalize_interval(interval: object) -> int:
        try:
            value = int(interval)
        except (TypeError, ValueError):
            value = 3600
        return max(10, min(86400, value))

    @staticmethod
    def _normalize_screenshot_quality(value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"low", "medium", "max"}:
            return normalized
        return "medium"

    def send_message(self, message: str, force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.token or not self.chat_id:
            return False

        text = self._truncate_message(message, self.MAX_MESSAGE_LENGTH)
        payload = {'chat_id': self.chat_id, 'text': text, 'parse_mode': 'HTML'}
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        try:
            response = self._post_with_retries(url, payload)
            if response is None:
                return False
            if response.status_code != 200:
                logger.error("Ошибка отправки в Telegram: HTTP %s", response.status_code)
                return False
            data = response.json()
            if not data.get('ok', False):
                logger.error("Ошибка Telegram API: %s", data.get('description', 'unknown error'))
                return False
            return True
        except ValueError:
            logger.error("Ошибка отправки в Telegram: некорректный JSON в ответе API")
            return False
        except Exception as e:
            logger.exception("Ошибка отправки сообщения в Telegram: %s", e)
            return False

    @staticmethod
    def _truncate_message(message: str, max_length: int) -> str:
        text = str(message or "")
        if len(text) <= max_length:
            return text
        return text[: max_length - 1] + "…"

    def _post_with_retries(self, url: str, payload: dict[str, str]) -> Optional[Response]:
        backoff_seconds = 1.0
        last_response: Optional[Response] = None
        for _attempt in range(self._MAX_SEND_RETRIES):
            try:
                response = requests.post(url, data=payload, timeout=(3, 7))
                last_response = response
                if response.status_code in self._RETRYABLE_STATUS_CODES:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue
                return response
            except requests.exceptions.RequestException as e:
                logger.warning("Ошибка связи с Telegram API: %s", e)
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 8.0)
        return last_response

    def send_photo(self, photo_path: str, caption: str = "", force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.token or not self.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        data = {'chat_id': self.chat_id, 'caption': self._truncate_message(caption, 1024)}
        upload_path, temp_optimized = self._optimize_photo_for_upload(photo_path)

        try:
            response = self._post_photo_with_retries(url, data, upload_path)
            if response is None:
                return False
            if response.status_code != 200:
                logger.error("Ошибка отправки фото в Telegram: HTTP %s", response.status_code)
                return False
            payload = response.json()
            if not payload.get('ok', False):
                logger.error("Ошибка Telegram API при отправке фото: %s", payload.get('description', 'unknown error'))
                return False
            return True
        except FileNotFoundError:
            logger.error("Файл скриншота не найден: %s", photo_path)
            return False
        except ValueError:
            logger.error("Ошибка отправки фото в Telegram: некорректный JSON в ответе API")
            return False
        except Exception as e:
            logger.exception("Ошибка отправки фото в Telegram: %s", e)
            return False
        finally:
            if temp_optimized and os.path.exists(temp_optimized):
                try:
                    os.remove(temp_optimized)
                except Exception:
                    pass

    def _post_photo_with_retries(self, url: str, data: dict[str, str], photo_path: str) -> Optional[Response]:
        backoff_seconds = 1.0
        last_response: Optional[Response] = None
        for _attempt in range(self._MAX_PHOTO_SEND_RETRIES):
            try:
                with open(photo_path, 'rb') as photo_file:
                    files = {'photo': photo_file}
                    response = requests.post(url, data=data, files=files, timeout=(5, 60))
                last_response = response
                if response.status_code in self._RETRYABLE_STATUS_CODES:
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 8.0)
                    continue
                return response
            except requests.exceptions.RequestException as e:
                logger.warning("Ошибка связи с Telegram API при отправке фото: %s", e)
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 8.0)
        return last_response

    def _optimize_photo_for_upload(self, photo_path: str) -> tuple[str, Optional[str]]:
        profile = self._screenshot_quality_profile()
        optimize_threshold = int(profile["threshold"])
        max_side_limit = int(profile["max_side"])
        jpeg_quality = int(profile["jpeg_quality"])

        try:
            if os.path.getsize(photo_path) <= optimize_threshold:
                return photo_path, None
        except OSError:
            return photo_path, None

        try:
            from gi.repository import GdkPixbuf  # type: ignore

            pixbuf = GdkPixbuf.Pixbuf.new_from_file(photo_path)
            width = pixbuf.get_width()
            height = pixbuf.get_height()
            max_side = max(width, height)

            if max_side > max_side_limit:
                scale = max_side_limit / float(max_side)
                new_width = max(1, int(width * scale))
                new_height = max(1, int(height * scale))
                pixbuf = pixbuf.scale_simple(new_width, new_height, GdkPixbuf.InterpType.BILINEAR)

            fd, optimized_path = tempfile.mkstemp(prefix="symo-screen-optimized-", suffix=".jpg")
            os.close(fd)
            pixbuf.savev(optimized_path, "jpeg", ["quality"], [str(jpeg_quality)])
            if os.path.exists(optimized_path) and os.path.getsize(optimized_path) > 0:
                return optimized_path, optimized_path
            return photo_path, None
        except Exception as e:
            logger.warning("Не удалось оптимизировать скриншот перед отправкой: %s", e)
            return photo_path, None

    def _screenshot_quality_profile(self) -> dict[str, int]:
        quality = self._normalize_screenshot_quality(self.screenshot_quality)
        profiles = {
            "low": {"threshold": 0, "max_side": 1280, "jpeg_quality": 60},
            "medium": {"threshold": self._PHOTO_OPTIMIZE_THRESHOLD_BYTES, "max_side": 1920, "jpeg_quality": 82},
            "max": {"threshold": 8 * 1024 * 1024, "max_side": 2560, "jpeg_quality": 92},
        }
        return profiles[quality]

    def _capture_screenshot_to_temp(self) -> Optional[str]:
        fd, temp_path = tempfile.mkstemp(prefix="symo-screen-", suffix=".png")
        os.close(fd)

        try:
            if self._capture_screenshot_with_gdk(temp_path):
                return temp_path

            screenshot_tools = [
                ["gnome-screenshot", "-f"],
                ["scrot"],
                ["grim"],
                ["import", "-window", "root"],
            ]
            for tool in screenshot_tools:
                if not shutil.which(tool[0]):
                    continue
                try:
                    command = [*tool, temp_path]
                    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
                    if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        return temp_path
                    logger.warning("Команда скриншота завершилась с кодом %s: %s", result.returncode, " ".join(command))
                except Exception as e:
                    logger.warning("Не удалось выполнить команду скриншота %s: %s", tool[0], e)
            return None
        except Exception as e:
            logger.exception("Ошибка получения скриншота: %s", e)
            return None
        finally:
            if not os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    @staticmethod
    def _capture_screenshot_with_gdk(target_path: str) -> bool:
        try:
            from gi.repository import Gdk, GdkPixbuf  # type: ignore
        except Exception:
            return False

        try:
            root_window = Gdk.get_default_root_window()
            if root_window is None:
                return False

            width = root_window.get_width()
            height = root_window.get_height()
            if width <= 0 or height <= 0:
                return False

            pixbuf = Gdk.pixbuf_get_from_window(root_window, 0, 0, width, height)
            if pixbuf is None:
                return False

            pixbuf.savev(target_path, "png", [], [])
            return os.path.exists(target_path) and os.path.getsize(target_path) > 0
        except Exception as e:
            logger.warning("Не удалось сделать скриншот через GDK: %s", e)
            return False

    def _send_screenshot(self) -> None:
        screenshot_path = self._capture_screenshot_to_temp()
        if not screenshot_path:
            self.send_message(f"❌ {tr('bot_screenshot_failed')}")
            self.send_message(tr('bot_screenshot_howto'))
            return
        try:
            if self.send_photo(screenshot_path, tr('bot_screenshot_caption')):
                self.send_message(f"✅ {tr('bot_screenshot_sent')}")
            else:
                self.send_message(f"❌ {tr('bot_screenshot_send_error')}")
        finally:
            try:
                os.remove(screenshot_path)
            except Exception:
                pass

    def set_power_control(self, power_control: "PowerControl") -> None:
        self.power_control_ref = power_control

    def set_app_context(self, app: "SystemTrayApp") -> None:
        self.app_ref = app

    def _metric_samples_for_graph(self, metric: str) -> tuple[str, list[tuple[float, float]], str]:
        app = self.app_ref
        if app is None:
            return "metric", [], ""

        metric_key = (metric or "").strip().lower()
        mapping = {
            "cpu": (tr("cpu"), list(getattr(app, "cpu_history", [])), lambda s: float(s[1]) if len(s) > 1 else 0.0, "%"),
            "top": (tr("cpu"), list(getattr(app, "cpu_history", [])), lambda s: float(s[1]) if len(s) > 1 else 0.0, "%"),
            "temp": (f"{tr('cpu')} {tr('temperature')}", list(getattr(app, "cpu_history", [])), lambda s: float(s[2]) if len(s) > 2 else 0.0, tr("temperature")),
            "temperature": (f"{tr('cpu')} {tr('temperature')}", list(getattr(app, "cpu_history", [])), lambda s: float(s[2]) if len(s) > 2 else 0.0, tr("temperature")),
            "ram": (tr("ram"), list(getattr(app, "ram_history", [])), lambda s: float(s[3]) if len(s) > 3 else 0.0, "%"),
            "swap": (tr("swap"), list(getattr(app, "swap_history", [])), lambda s: float(s[3]) if len(s) > 3 else 0.0, "%"),
            "disk": (tr("disk"), list(getattr(app, "disk_history", [])), lambda s: float(s[3]) if len(s) > 3 else 0.0, "%"),
            "net": (tr("network"), list(getattr(app, "net_history", [])), lambda s: float(s[1]) + float(s[2]), tr("mbps")),
            "keyboard": (tr("keyboard_clicks"), list(getattr(app, "keyboard_history", [])), lambda s: float(s[1]) if len(s) > 1 else 0.0, tr("clicks")),
            "mouse": (tr("mouse_clicks"), list(getattr(app, "mouse_history", [])), lambda s: float(s[1]) if len(s) > 1 else 0.0, tr("clicks")),
        }
        if metric_key == "uptime":
            cpu_samples = list(getattr(app, "cpu_history", []))
            boot_ts = float(psutil.boot_time())
            points = [(float(s[0]), max(0.0, (float(s[0]) - boot_ts) / 3600.0)) for s in cpu_samples if s]
            return tr("uptime"), points, "h"

        title, samples, extractor, unit = mapping.get(metric_key, ("", [], lambda _s: 0.0, ""))
        points: list[tuple[float, float]] = []
        for sample in samples:
            try:
                ts = float(sample[0])
                value = max(0.0, float(extractor(sample)))
                points.append((ts, value))
            except Exception:
                continue
        return title, points, unit

    def _render_metric_graph_to_temp(self, metric: str) -> Optional[tuple[str, str]]:
        title, points, unit = self._metric_samples_for_graph(metric)
        if not points or not title:
            return None
        if len(points) > 180:
            points = points[-180:]

        try:
            import cairo  # type: ignore
        except Exception:
            logger.warning("cairo недоступен: не удалось построить изображение графика")
            return None

        width, height = 980, 420
        margin_left, margin_right = 56, 24
        margin_top, margin_bottom = 36, 46
        plot_w = max(10, width - margin_left - margin_right)
        plot_h = max(10, height - margin_top - margin_bottom)

        values = [p[1] for p in points]
        v_min = min(values)
        v_max = max(values)
        if abs(v_max - v_min) < 1e-6:
            v_min = max(0.0, v_min - 1.0)
            v_max = v_max + 1.0

        fd, path = tempfile.mkstemp(prefix=f"symo-graph-{metric}-", suffix=".png")
        os.close(fd)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)

        cr.set_source_rgb(0.09, 0.09, 0.09)
        cr.paint()
        cr.set_source_rgb(0.18, 0.18, 0.18)
        cr.rectangle(margin_left, margin_top, plot_w, plot_h)
        cr.stroke()

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(16)
        cr.set_source_rgb(0.92, 0.92, 0.92)
        cr.move_to(margin_left, 24)
        cr.show_text(f"{title} graph")

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(12)
        cr.set_source_rgb(0.65, 0.65, 0.65)
        cr.move_to(margin_left, height - 16)
        cr.show_text(f"Samples: {len(points)}")

        for i in range(1, len(points)):
            x1 = margin_left + (i - 1) * (plot_w / max(1, len(points) - 1))
            x2 = margin_left + i * (plot_w / max(1, len(points) - 1))
            y1 = margin_top + plot_h - ((points[i - 1][1] - v_min) / (v_max - v_min)) * plot_h
            y2 = margin_top + plot_h - ((points[i][1] - v_min) / (v_max - v_min)) * plot_h
            cr.set_source_rgb(0.21, 0.78, 0.93)
            cr.set_line_width(2.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        cr.set_source_rgb(0.82, 0.82, 0.82)
        cr.move_to(8, margin_top + 6)
        cr.show_text(f"{v_max:.1f}{unit}")
        cr.move_to(8, margin_top + plot_h)
        cr.show_text(f"{v_min:.1f}{unit}")

        surface.write_to_png(path)
        return path, title

    def _send_metric_graph(self, metric: str) -> None:
        render_result = self._render_metric_graph_to_temp(metric)
        if render_result is None:
            self.send_message(f"❌ {tr('graph_unavailable')}. /graph cpu|ram|swap|disk|net|keyboard|mouse|uptime|top|temp")
            return
        path, title = render_result
        try:
            caption = f"{title} graph"
            if not self.send_photo(path, caption):
                self.send_message(f"❌ {tr('graph_send_failed')}")
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def start_bot(self) -> None:
        if not self.enabled or not self.token or self.bot_running:
            return

        self.bot_running = True
        self.bot_thread = threading.Thread(target=self._bot_worker, daemon=True)
        self.bot_thread.start()
        logger.info("Telegram бот запущен")

    def stop_bot(self) -> None:
        self.bot_running = False
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=2.0)
        logger.info("Telegram бот остановлен")

    def _bot_worker(self) -> None:
        backoff_seconds = 1.0
        while self.bot_running and self.enabled and self.token:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {'timeout': 30, 'offset': self.last_update_id + 1}
                response = requests.get(url, params=params, timeout=35)

                if response.status_code == 200:
                    data = response.json()
                    if data.get('ok'):
                        for update in data.get('result', []):
                            self.last_update_id = update['update_id']

                            message = update.get('message', {})
                            chat_id = str(message.get('chat', {}).get('id', ''))

                            if chat_id != self.chat_id:
                                continue

                            text = message.get('text', '').strip()
                            if not text:
                                continue

                            parts = text.split(maxsplit=1)
                            raw_command = parts[0].strip().lower()
                            command = raw_command.split('@', 1)[0]
                            arg = parts[1].strip().lower() if len(parts) > 1 else ""

                            if command == '/poweroff' and self.power_control_ref:
                                self.send_message(tr('bot_shutdown_message'))
                                GLib.idle_add(self.power_control_ref._shutdown)

                            elif command == '/reboot' and self.power_control_ref:
                                self.send_message(tr('bot_reboot_message'))
                                GLib.idle_add(self.power_control_ref._reboot)

                            elif command == '/lock' and self.power_control_ref:
                                self.send_message(tr('bot_lock_message'))
                                GLib.idle_add(self.power_control_ref._lock_screen)

                            elif command == '/status':
                                self._send_system_status()

                            elif command == '/screenshot':
                                self.send_message(tr('bot_screenshot_processing'))
                                self._send_screenshot()

                            elif command == '/help':
                                help_text = tr('bot_help_message')
                                help_text += (
                                    f"\n\n📊 {tr('graph_commands_title')}:"
                                    f"\n/graph [metric] - {tr('graph_command_hint')}"
                                    f"\n/uptime_graph - {tr('uptime')}"
                                    f"\n/cpu_graph - {tr('cpu')}"
                                    f"\n/temp_graph - {tr('cpu')} {tr('temperature')}"
                                    f"\n/ram_graph - {tr('ram')}"
                                    f"\n/net_graph - {tr('network')}"
                                    f"\n/disk_graph - {tr('disk')}"
                                    f"\n/swap_graph - {tr('swap')}"
                                    f"\n/keyboard_graph - {tr('keyboard_clicks')}"
                                    f"\n/mouse_graph - {tr('mouse_clicks')}"
                                )
                                self.send_message(help_text)

                            elif command == '/graph':
                                metric = arg or "cpu"
                                self._send_metric_graph(metric)

                            elif command in {'/uptime', '/disk', '/top', '/cpu', '/ram', '/swap', '/net', '/keyboard', '/mouse', '/temp', '/temperature'}:
                                self._send_metric_graph(command.lstrip('/'))

                            elif command in {
                                '/uptime_graph',
                                '/cpu_graph',
                                '/temp_graph',
                                '/ram_graph',
                                '/net_graph',
                                '/disk_graph',
                                '/swap_graph',
                                '/keyboard_graph',
                                '/mouse_graph',
                            }:
                                metric_alias_map = {
                                    '/uptime_graph': 'uptime',
                                    '/cpu_graph': 'cpu',
                                    '/temp_graph': 'temp',
                                    '/ram_graph': 'ram',
                                    '/net_graph': 'net',
                                    '/disk_graph': 'disk',
                                    '/swap_graph': 'swap',
                                    '/keyboard_graph': 'keyboard',
                                    '/mouse_graph': 'mouse',
                                }
                                self._send_metric_graph(metric_alias_map.get(command, 'cpu'))

                            else:
                                self.send_message(f"{tr('unknown_command')}. {tr('unknown_command_help')}")
                    backoff_seconds = 1.0

                elif response.status_code == 409:
                    logger.warning("Предупреждение: Другой экземпляр бота уже получает обновления")
                    time.sleep(min(backoff_seconds, 30.0))
                    backoff_seconds = min(backoff_seconds * 2, 30.0)
                else:
                    logger.warning("Ошибка Telegram getUpdates: HTTP %s", response.status_code)
                    time.sleep(min(backoff_seconds, 30.0))
                    backoff_seconds = min(backoff_seconds * 2, 30.0)

            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException as e:
                logger.warning("Ошибка связи с Telegram API: %s", e)
                time.sleep(min(backoff_seconds, 30.0))
                backoff_seconds = min(backoff_seconds * 2, 30.0)
            except Exception as e:
                logger.exception("Неожиданная ошибка в боте: %s", e)
                time.sleep(min(backoff_seconds, 30.0))
                backoff_seconds = min(backoff_seconds * 2, 30.0)

    def _send_system_status(self) -> None:
        try:
            cpu_temp = SystemUsage.get_cpu_temp()
            cpu_usage = SystemUsage.get_cpu_usage()
            ram_used, ram_total = SystemUsage.get_ram_usage()
            disk_used, disk_total = SystemUsage.get_disk_usage()
            swap_used, swap_total = SystemUsage.get_swap_usage()
            uptime = SystemUsage.get_uptime()

            kbd, ms = get_counts()

            status_msg = (
                f"🖥 <b>{tr('system_status')}</b>\n"
                f"🔹 <b>{tr('cpu')}:</b> {cpu_usage:.0f}% ({cpu_temp}{tr('temperature')})\n"
                f"🔹 <b>{tr('ram')}:</b> {ram_used:.1f}/{ram_total:.1f} {tr('gb')}\n"
                f"🔹 <b>{tr('swap')}:</b> {swap_used:.1f}/{swap_total:.1f} {tr('gb')}\n"
                f"🔹 <b>{tr('disk')}:</b> {disk_used:.1f}/{disk_total:.1f} {tr('gb')}\n"
                f"🔹 <b>{tr('uptime')}:</b> {uptime}\n"
                f"🔹 <b>{tr('keyboard')}:</b> {kbd} {tr('presses')}\n"
                f"🔹 <b>{tr('mouse')}:</b> {ms} {tr('clicks')}"
            )

            self.send_message(status_msg)
        except Exception as e:
            self.send_message(f"❌ {tr('error')}: {e}")
