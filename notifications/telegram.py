from __future__ import annotations

import html
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable, NamedTuple, Optional, TYPE_CHECKING

import requests
from requests import Response
from gi.repository import GLib

from app_core.constants import TELEGRAM_CONFIG_FILE
from app_core.localization import tr
from app_core.settings import atomic_write_json, graph_line_color_rgb, read_json
from notifications.base import format_status_message, normalize_interval, post_with_retries, truncate_message

if TYPE_CHECKING:
    from app_core.power_control import PowerControl
    from app_core.app import SystemTrayApp

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class _GraphMetric(NamedTuple):
    history_key: str
    title: Callable[[], str]
    value: Callable[[tuple], float]
    unit: Callable[[], str]
    color_key: str


def _percent(sample: tuple) -> float:
    return float(sample[3])


_GRAPH_METRICS: dict[str, _GraphMetric] = {
    "cpu": _GraphMetric("cpu", lambda: tr("cpu"), lambda s: float(s[1]), lambda: "%", "graph_line_color_cpu"),
    "temp": _GraphMetric("cpu", lambda: f"{tr('cpu')} {tr('temperature')}", lambda s: float(s[2]),
                         lambda: tr("temperature"), "graph_line_color_temp"),
    "ram": _GraphMetric("ram", lambda: tr("ram"), _percent, lambda: "%", "graph_line_color_ram"),
    "swap": _GraphMetric("swap", lambda: tr("swap"), _percent, lambda: "%", "graph_line_color_swap"),
    "disk": _GraphMetric("disk", lambda: tr("disk"), _percent, lambda: "%", "graph_line_color_disk"),
    "net": _GraphMetric("net", lambda: tr("network"), lambda s: float(s[1]) + float(s[2]),
                        lambda: tr("mbps"), "graph_line_color_net_recv"),
    "keyboard": _GraphMetric("keyboard", lambda: tr("keyboard_clicks"), lambda s: float(s[1]),
                             lambda: "", "graph_line_color_keyboard"),
    "mouse": _GraphMetric("mouse", lambda: tr("mouse_clicks"), lambda s: float(s[1]),
                          lambda: "", "graph_line_color_mouse"),
}

GRAPH_COMMANDS = {
    '/cpu_graph': 'cpu',
    '/temp_graph': 'temp',
    '/ram_graph': 'ram',
    '/net_graph': 'net',
    '/disk_graph': 'disk',
    '/swap_graph': 'swap',
    '/keyboard_graph': 'keyboard',
    '/mouse_graph': 'mouse',
}


class TelegramNotifier:
    MAX_MESSAGE_LENGTH = 4096
    _MAX_SEND_RETRIES = 3
    _MAX_PHOTO_SEND_RETRIES = 3
    _PHOTO_OPTIMIZE_THRESHOLD_BYTES = 2 * 1024 * 1024
    _POLL_TIMEOUT_SEC = 30
    _MAIN_THREAD_CAPTURE_TIMEOUT_SEC = 10.0
    # Сообщения старше запуска бота не выполняются: иначе, например, /poweroff,
    # отправленный пока компьютер был выключен, сработал бы сразу после загрузки.
    _STALE_MESSAGE_GRACE_SEC = 2

    def __init__(self, autoload: bool = True):
        self.token: Optional[str] = None
        self.chat_id: Optional[str] = None
        self.enabled: bool = False
        self.notification_interval: int = 3600
        self.screenshot_quality: str = "medium"
        self.last_update_id: int = 0
        self.bot_thread: Optional[threading.Thread] = None
        self._bot_stop_event: Optional[threading.Event] = None
        self.power_control_ref: Optional["PowerControl"] = None
        self.app_ref: Optional["SystemTrayApp"] = None
        if autoload:
            self.load_config()

    def configure(self, token: str, chat_id: str, enabled: bool, interval: int,
                  screenshot_quality: str = "medium") -> None:
        """Задать параметры в памяти, не трогая файл конфигурации."""
        self.token = (token or '').strip() or None
        self.chat_id = str(chat_id or '').strip() or None
        self.enabled = bool(enabled)
        self.notification_interval = normalize_interval(interval)
        self.screenshot_quality = self._normalize_screenshot_quality(screenshot_quality)

    def load_config(self) -> None:
        config = read_json(TELEGRAM_CONFIG_FILE)
        if config:
            self.configure(
                config.get('TELEGRAM_BOT_TOKEN') or '',
                config.get('TELEGRAM_CHAT_ID') or '',
                config.get('enabled', False),
                config.get('notification_interval', 3600),
                config.get('screenshot_quality', "medium"),
            )

    def save_config(self, token: str, chat_id: str, enabled: bool, interval: int,
                    screenshot_quality: str = "medium") -> bool:
        self.configure(token, chat_id, enabled, interval, screenshot_quality)
        try:
            atomic_write_json(TELEGRAM_CONFIG_FILE, {
                'TELEGRAM_BOT_TOKEN': self.token,
                'TELEGRAM_CHAT_ID': self.chat_id,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval,
                'screenshot_quality': self.screenshot_quality,
            }, mode=0o600)
            return True
        except Exception as e:
            logger.exception("Ошибка сохранения конфигурации Telegram: %s", e)
            return False

    @staticmethod
    def _normalize_screenshot_quality(value: object) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in {"low", "medium", "max"} else "medium"

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    @classmethod
    def _prepare_text(cls, message: str) -> tuple[str, Optional[str]]:
        """Вернуть (текст, parse_mode). Слишком длинный HTML отправляется простым текстом,
        чтобы обрезка не разрезала тег."""
        text = str(message or "")
        if len(text) <= cls.MAX_MESSAGE_LENGTH:
            return text, 'HTML'
        plain = html.unescape(_HTML_TAG_RE.sub("", text))
        return truncate_message(plain, cls.MAX_MESSAGE_LENGTH), None

    def send_message(self, message: str, force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.token or not self.chat_id:
            return False

        text, parse_mode = self._prepare_text(message)
        payload = {'chat_id': self.chat_id, 'text': text}
        if parse_mode:
            payload['parse_mode'] = parse_mode
        url = self._api_url("sendMessage")

        try:
            response = post_with_retries(
                lambda: requests.post(url, data=payload, timeout=(3, 7)),
                channel="Telegram",
                max_attempts=self._MAX_SEND_RETRIES,
            )
            return self._check_response(response, "сообщения")
        except Exception as e:
            logger.exception("Ошибка отправки сообщения в Telegram: %s", e)
            return False

    @staticmethod
    def _check_response(response: Optional[Response], what: str) -> bool:
        if response is None:
            return False
        if response.status_code != 200:
            logger.error("Ошибка отправки %s в Telegram: HTTP %s", what, response.status_code)
            return False
        try:
            data = response.json()
        except ValueError:
            logger.error("Ошибка отправки %s в Telegram: некорректный JSON в ответе API", what)
            return False
        if not data.get('ok', False):
            logger.error("Ошибка Telegram API при отправке %s: %s", what, data.get('description', 'unknown error'))
            return False
        return True

    def send_photo(self, photo_path: str, caption: str = "", force: bool = False) -> bool:
        if (not force and not self.enabled) or not self.token or not self.chat_id:
            return False

        url = self._api_url("sendPhoto")
        data = {'chat_id': self.chat_id, 'caption': truncate_message(caption, 1024)}
        upload_path, temp_optimized = self._optimize_photo_for_upload(photo_path)

        def send() -> Response:
            with open(upload_path, 'rb') as photo_file:
                return requests.post(url, data=data, files={'photo': photo_file}, timeout=(5, 60))

        try:
            response = post_with_retries(send, channel="Telegram", max_attempts=self._MAX_PHOTO_SEND_RETRIES)
            return self._check_response(response, "фото")
        except FileNotFoundError:
            logger.error("Файл скриншота не найден: %s", photo_path)
            return False
        except Exception as e:
            logger.exception("Ошибка отправки фото в Telegram: %s", e)
            return False
        finally:
            if temp_optimized:
                _remove_quietly(temp_optimized)

    def _optimize_photo_for_upload(self, photo_path: str) -> tuple[str, Optional[str]]:
        profile = self._screenshot_quality_profile()
        try:
            if os.path.getsize(photo_path) <= profile["threshold"]:
                return photo_path, None
        except OSError:
            return photo_path, None

        optimized_path: Optional[str] = None
        try:
            from gi.repository import GdkPixbuf  # type: ignore

            pixbuf = GdkPixbuf.Pixbuf.new_from_file(photo_path)
            width, height = pixbuf.get_width(), pixbuf.get_height()
            max_side = max(width, height)
            if max_side > profile["max_side"]:
                scale = profile["max_side"] / float(max_side)
                pixbuf = pixbuf.scale_simple(max(1, int(width * scale)), max(1, int(height * scale)),
                                             GdkPixbuf.InterpType.BILINEAR)

            fd, optimized_path = tempfile.mkstemp(prefix="symo-screen-optimized-", suffix=".jpg")
            os.close(fd)
            pixbuf.savev(optimized_path, "jpeg", ["quality"], [str(profile["jpeg_quality"])])
            if os.path.getsize(optimized_path) > 0:
                return optimized_path, optimized_path
        except Exception as e:
            logger.warning("Не удалось оптимизировать скриншот перед отправкой: %s", e)
        if optimized_path:
            _remove_quietly(optimized_path)
        return photo_path, None

    def _screenshot_quality_profile(self) -> dict[str, int]:
        profiles = {
            "low": {"threshold": 0, "max_side": 1280, "jpeg_quality": 60},
            "medium": {"threshold": self._PHOTO_OPTIMIZE_THRESHOLD_BYTES, "max_side": 1920, "jpeg_quality": 82},
            "max": {"threshold": 8 * 1024 * 1024, "max_side": 2560, "jpeg_quality": 92},
        }
        return profiles[self._normalize_screenshot_quality(self.screenshot_quality)]

    def _capture_screenshot_to_temp(self) -> Optional[str]:
        fd, temp_path = tempfile.mkstemp(prefix="symo-screen-", suffix=".png")
        os.close(fd)
        captured = False
        try:
            if self._capture_screenshot_with_gdk(temp_path):
                captured = True
                return temp_path

            screenshot_tools = [
                ["gnome-screenshot", "-f"],
                ["scrot", "-o"],
                ["grim"],
                ["import", "-window", "root"],
            ]
            for tool in screenshot_tools:
                if not shutil.which(tool[0]):
                    continue
                command = [*tool, temp_path]
                try:
                    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
                except Exception as e:
                    logger.warning("Не удалось выполнить команду скриншота %s: %s", tool[0], e)
                    continue
                if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    captured = True
                    return temp_path
                logger.warning("Команда скриншота завершилась с кодом %s: %s", result.returncode, " ".join(command))
            return None
        except Exception as e:
            logger.exception("Ошибка получения скриншота: %s", e)
            return None
        finally:
            if not captured:
                _remove_quietly(temp_path)

    def _capture_screenshot_with_gdk(self, target_path: str) -> bool:
        """Снять экран через GDK. GTK не потокобезопасен, поэтому из фонового
        потока съёмка передаётся в главный цикл. Под Wayland корневого окна нет."""
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            return False
        if threading.current_thread() is threading.main_thread():
            return self._capture_gdk_now(target_path)

        done = threading.Event()
        result = {"ok": False}

        def run_in_main_loop() -> bool:
            try:
                result["ok"] = self._capture_gdk_now(target_path)
            finally:
                done.set()
            return False

        GLib.idle_add(run_in_main_loop)
        if not done.wait(self._MAIN_THREAD_CAPTURE_TIMEOUT_SEC):
            logger.warning("Главный цикл не ответил вовремя на запрос скриншота")
            return False
        return result["ok"]

    @staticmethod
    def _capture_gdk_now(target_path: str) -> bool:
        try:
            from gi.repository import Gdk  # type: ignore
        except Exception:
            return False
        try:
            root_window = Gdk.get_default_root_window()
            if root_window is None:
                return False
            width, height = root_window.get_width(), root_window.get_height()
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
            _remove_quietly(screenshot_path)

    def set_power_control(self, power_control: "PowerControl") -> None:
        self.power_control_ref = power_control

    def set_app_context(self, app: "SystemTrayApp") -> None:
        self.app_ref = app

    @staticmethod
    def _resolve_graph_metric(metric: str) -> Optional[_GraphMetric]:
        return _GRAPH_METRICS.get((metric or "").strip().lower())

    def _metric_samples_for_graph(self, metric: str) -> tuple[str, list[tuple[float, float]], str]:
        spec = self._resolve_graph_metric(metric)
        app = self.app_ref
        if spec is None or app is None:
            return "", [], ""
        points: list[tuple[float, float]] = []
        for sample in app.metrics_history.samples(spec.history_key):
            try:
                points.append((float(sample[0]), max(0.0, spec.value(sample))))
            except (TypeError, ValueError, IndexError):
                continue
        return spec.title(), points, spec.unit()

    def _graph_line_color_rgb(self, metric: str) -> tuple[float, float, float]:
        spec = self._resolve_graph_metric(metric) or _GRAPH_METRICS["cpu"]
        settings = getattr(self.app_ref, "visibility_settings", None) or {}
        return graph_line_color_rgb(settings, spec.color_key)

    def _render_metric_graph_to_temp(self, metric: str) -> Optional[tuple[str, str]]:
        title, points, unit = self._metric_samples_for_graph(metric)
        if not points or not title:
            return None
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
        v_min, v_max = min(values), max(values)
        if abs(v_max - v_min) < 1e-6:
            v_min = max(0.0, v_min - 1.0)
            v_max = v_max + 1.0
        caption = tr('graph_caption').format(title)

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
        cr.show_text(caption)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(12)
        cr.set_source_rgb(0.65, 0.65, 0.65)
        cr.move_to(margin_left, height - 16)
        cr.show_text(f"{tr('samples_label')}: {len(points)}")

        time_start_label = self._format_graph_time(points[0][0])
        time_end_label = self._format_graph_time(points[-1][0])
        cr.set_source_rgb(0.70, 0.70, 0.70)
        cr.move_to(margin_left, margin_top + plot_h + 16)
        cr.show_text(time_start_label)
        extents = cr.text_extents(time_end_label)
        cr.move_to(margin_left + plot_w - extents[2], margin_top + plot_h + 16)
        cr.show_text(time_end_label)

        step_x = plot_w / max(1, len(points) - 1)
        cr.set_source_rgb(*self._graph_line_color_rgb(metric))
        cr.set_line_width(2.0)
        for i, (_ts, value) in enumerate(points):
            x = margin_left + i * step_x
            y = margin_top + plot_h - ((value - v_min) / (v_max - v_min)) * plot_h
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        cr.set_source_rgb(0.82, 0.82, 0.82)
        cr.move_to(8, margin_top + 6)
        cr.show_text(f"{v_max:.1f}{unit}")
        cr.move_to(8, margin_top + plot_h)
        cr.show_text(f"{v_min:.1f}{unit}")

        fd, path = tempfile.mkstemp(prefix=f"symo-graph-{metric}-", suffix=".png")
        os.close(fd)
        try:
            surface.write_to_png(path)
        except Exception:
            _remove_quietly(path)
            raise
        return path, caption

    @staticmethod
    def _format_graph_time(timestamp: float) -> str:
        try:
            return time.strftime("%H:%M:%S", time.localtime(float(timestamp)))
        except Exception:
            return "--:--:--"

    def _send_metric_graph(self, metric: str) -> None:
        render_result = self._render_metric_graph_to_temp(metric)
        if render_result is None:
            self.send_message(f"❌ {tr('graph_unavailable')}. " + "|".join(GRAPH_COMMANDS))
            return
        path, caption = render_result
        try:
            if not self.send_photo(path, caption):
                self.send_message(f"❌ {tr('graph_send_failed')}")
        finally:
            _remove_quietly(path)

    @property
    def bot_running(self) -> bool:
        return self._bot_stop_event is not None and not self._bot_stop_event.is_set()

    def start_bot(self) -> None:
        if not self.enabled or not self.token or self.bot_running:
            return
        # Своё событие у каждого потока: старый, ещё висящий в long-poll, после
        # возврата увидит его и завершится, а не будет работать рядом с новым.
        stop_event = threading.Event()
        self._bot_stop_event = stop_event
        self.bot_thread = threading.Thread(target=self._bot_worker, args=(stop_event,),
                                           name="telegram-bot", daemon=True)
        self.bot_thread.start()
        logger.info("Telegram бот запущен")

    def stop_bot(self, timeout: float = 0.0) -> None:
        """Остановить бота. Ждать поток не обязательно: он висит в long-poll до
        30 секунд и сам завершится, увидев своё событие остановки."""
        if self._bot_stop_event is not None:
            self._bot_stop_event.set()
        if timeout > 0 and self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=timeout)
        logger.info("Telegram бот остановлен")

    def _skip_pending_updates(self) -> bool:
        """Подтвердить все накопившиеся обновления, не выполняя их."""
        try:
            response = requests.get(self._api_url("getUpdates"), params={'offset': -1, 'timeout': 0}, timeout=10)
            if response.status_code != 200:
                return False
            data = response.json()
            if not data.get('ok'):
                return False
            result = data.get('result') or []
            if result:
                self.last_update_id = max(self.last_update_id, int(result[-1]['update_id']))
            return True
        except Exception as e:
            logger.warning("Не удалось пропустить старые обновления Telegram: %s", e.__class__.__name__)
            return False

    def _bot_worker(self, stop_event: threading.Event) -> None:
        started_at = time.time()
        self._skip_pending_updates()
        backoff_seconds = 1.0

        def pause() -> None:
            nonlocal backoff_seconds
            stop_event.wait(min(backoff_seconds, 30.0))
            backoff_seconds = min(backoff_seconds * 2, 30.0)

        while not stop_event.is_set() and self.enabled and self.token:
            try:
                params = {'timeout': self._POLL_TIMEOUT_SEC, 'offset': self.last_update_id + 1}
                response = requests.get(self._api_url("getUpdates"), params=params,
                                        timeout=self._POLL_TIMEOUT_SEC + 5)
                if stop_event.is_set():
                    break

                if response.status_code == 200:
                    data = response.json()
                    if data.get('ok'):
                        for update in data.get('result', []):
                            self.last_update_id = max(self.last_update_id, int(update['update_id']))
                            self._process_update(update, started_at)
                    backoff_seconds = 1.0
                elif response.status_code == 409:
                    logger.warning("Другой экземпляр бота уже получает обновления")
                    pause()
                else:
                    logger.warning("Ошибка Telegram getUpdates: HTTP %s", response.status_code)
                    pause()
            except requests.exceptions.Timeout:
                continue
            except requests.exceptions.RequestException as e:
                logger.warning("Ошибка связи с Telegram API: %s", e.__class__.__name__)
                pause()
            except Exception as e:
                logger.exception("Неожиданная ошибка в боте: %s", e)
                pause()

    def _process_update(self, update: dict, started_at: float) -> None:
        message = update.get('message') or {}
        if str((message.get('chat') or {}).get('id', '')) != self.chat_id:
            return
        try:
            sent_at = float(message.get('date', 0))
        except (TypeError, ValueError):
            sent_at = 0.0
        if sent_at < started_at - self._STALE_MESSAGE_GRACE_SEC:
            logger.info("Пропущена устаревшая команда Telegram")
            return
        text = (message.get('text') or '').strip()
        if not text:
            return
        raw_command = text.split(maxsplit=1)[0].strip().lower()
        command = raw_command.split('@', 1)[0]
        self._handle_command(command)

    def _handle_command(self, command: str) -> None:
        power = self.power_control_ref
        power_commands = {
            '/poweroff': (lambda: tr('bot_shutdown_message'), 'power_off'),
            '/reboot': (lambda: tr('bot_reboot_message'), 'reboot'),
            '/lock': (lambda: tr('bot_lock_message'), 'lock_screen'),
        }
        if command in power_commands and power is not None:
            message, method_name = power_commands[command]
            self.send_message(message())
            # Команды питания выполняются в главном потоке GTK.
            GLib.idle_add(getattr(power, method_name))
        elif command == '/status':
            self._send_system_status()
        elif command == '/screenshot':
            self.send_message(tr('bot_screenshot_processing'))
            self._send_screenshot()
        elif command == '/help':
            self.send_message(self._help_text())
        elif command in GRAPH_COMMANDS:
            self._send_metric_graph(GRAPH_COMMANDS[command])
        else:
            self.send_message(f"{tr('unknown_command')}. {tr('unknown_command_help')}")

    @staticmethod
    def _help_text() -> str:
        return (
            tr('bot_help_message')
            + f"\n\n📊 {tr('graph_commands_title')}:"
            + f"\n/cpu_graph - {tr('cpu')}"
            + f"\n/temp_graph - {tr('cpu')} {tr('temperature')}"
            + f"\n/ram_graph - {tr('ram')}"
            + f"\n/net_graph - {tr('network')}"
            + f"\n/disk_graph - {tr('disk')}"
            + f"\n/swap_graph - {tr('swap')}"
            + f"\n/keyboard_graph - {tr('keyboard_clicks')}"
            + f"\n/mouse_graph - {tr('mouse_clicks')}"
        )

    def _send_system_status(self) -> None:
        # Берём срез из основного цикла: вызов psutil.cpu_percent() из этого
        # потока сбил бы замер загрузки CPU.
        snapshot = getattr(self.app_ref, "latest_snapshot", None)
        if snapshot is None:
            self.send_message(f"❌ {html.escape(tr('error'))}")
            return
        self.send_message(format_status_message(snapshot, "html"))


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
