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
from queue import Full, Queue
from typing import Callable, Iterable, Optional, TYPE_CHECKING

import requests
from requests import Response
from gi.repository import GLib

from app_core.constants import TELEGRAM_CONFIG_FILE
from app_core.graph_math import decimate_samples
from app_core.graph_render import build_graph_specs, render_graph
from app_core.localization import tr
from app_core.power_control import Action, action_label
from app_core.settings import atomic_write_json, read_json
from notifications.base import format_status_message, normalize_interval, post_with_retries, truncate_message

if TYPE_CHECKING:
    from app_core.power_control import PowerControl
    from app_core.app import SystemTrayApp

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


# Команда → ключ графика. Температура рисуется на графике CPU, как и в окне.
GRAPH_COMMANDS = {
    '/cpu_graph': 'cpu',
    '/temp_graph': 'cpu',
    '/ram_graph': 'ram',
    '/net_graph': 'net',
    '/disk_graph': 'disk',
    '/swap_graph': 'swap',
    '/keyboard_graph': 'keyboard',
    '/mouse_graph': 'mouse',
}


# Только ASCII-цифры: \d и isdigit() пропускают «²» и полноширинные цифры, на которых падает int().
_CHAT_ID_RE = re.compile(r"-?[0-9]+|@[A-Za-z0-9_]{5,}")
_DIGITS_RE = re.compile(r"[0-9]+")
_USER_ID_SEPARATORS_RE = re.compile(r"[\s,;]+")
# Служебные отправители Telegram: уведомления, анонимный админ группы, сообщения от имени канала.
# Их from.id общий для многих людей, поэтому доверять ему нельзя.
_SERVICE_SENDER_IDS = frozenset({777000, 1087968824, 136817688})

# Команды, которые меняют состояние компьютера или показывают экран. В личном чате
# их может выполнять владелец чата, в группе — только пользователи из allowed_user_ids.
PRIVILEGED_COMMANDS = frozenset({'/poweroff', '/reboot', '/cancel', '/lock', '/screenshot'})
POWER_COMMANDS = {'/poweroff': Action.POWER_OFF, '/reboot': Action.REBOOT}
REMOTE_POWER_DELAY_MIN = 1
REMOTE_POWER_DELAY_MAX = 1440


def is_valid_chat_id(value: object) -> bool:
    """Числовой ID чата (123456789, -1001234567890) или @имя публичного канала. С @именем
    работают только уведомления: в обновлениях бота чат приходит с числовым ID."""
    return bool(_CHAT_ID_RE.fullmatch(str(value or "").strip()))


def parse_user_ids(text: object) -> Optional[list[int]]:
    """ID пользователей через запятую или пробел; None, если есть не число."""
    ids: list[int] = []
    for part in _USER_ID_SEPARATORS_RE.split(str(text or "").strip()):
        if not part:
            continue
        if not _DIGITS_RE.fullmatch(part):
            return None
        if int(part) not in ids:
            ids.append(int(part))
    return ids


def _normalize_user_ids(values: object) -> list[int]:
    if not isinstance(values, (list, tuple)):
        return []
    ids: list[int] = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in ids:
            ids.append(number)
    return ids


def _parse_delay_minutes(args: list[str]) -> Optional[int]:
    """Задержка удалённого выключения: без аргумента — 1 минута; None, если аргумент неверный."""
    if not args:
        return REMOTE_POWER_DELAY_MIN
    if not _DIGITS_RE.fullmatch(args[0]):
        return None
    minutes = int(args[0])
    return minutes if REMOTE_POWER_DELAY_MIN <= minutes <= REMOTE_POWER_DELAY_MAX else None


class _BotRun:
    """Состояние одного запуска бота: у каждого потока опроса своё."""

    def __init__(self, started_at: float, reply: Callable[..., None],
                 submit_slow: Callable[[Callable[[], None]], bool]) -> None:
        self.started_at = started_at
        self.bot_username: Optional[str] = None
        self.reply = reply
        self.submit_slow = submit_slow
        self.last_denial: dict[object, float] = {}


class TelegramNotifier:
    MAX_MESSAGE_LENGTH = 4096
    _MAX_SEND_RETRIES = 3
    _MAX_PHOTO_SEND_RETRIES = 3
    _PHOTO_OPTIMIZE_THRESHOLD_BYTES = 2 * 1024 * 1024
    _POLL_TIMEOUT_SEC = 30
    _MAX_RETRY_AFTER_SEC = 30.0
    # Скриншоты и графики выполняются отдельным потоком, чтобы не задерживать
    # /cancel и /lock; больше стольких запросов в очереди не держим.
    _MAX_PENDING_SLOW_COMMANDS = 2
    # Ответы на команды отправляет отдельный поток: пауза по HTTP 429 не должна
    # задерживать опрос и, значит, /cancel.
    _MAX_PENDING_REPLIES = 10
    # Команды с последствиями старше этого не выполняются: они могли накопиться,
    # пока компьютер спал или был без сети.
    _MAX_PRIVILEGED_COMMAND_AGE_SEC = 120
    _DENIAL_REPLY_INTERVAL_SEC = 60
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
        # Причина последней неудачной отправки — для окна настроек («Проверить»).
        self.last_error: Optional[str] = None
        self.allowed_user_ids: list[int] = []
        self.allow_remote_power: bool = False
        self.allow_remote_screenshot: bool = False
        self.bot_thread: Optional[threading.Thread] = None
        self._bot_stop_event: Optional[threading.Event] = None
        self.power_control_ref: Optional["PowerControl"] = None
        self.app_ref: Optional["SystemTrayApp"] = None
        if autoload:
            self.load_config()

    def configure(self, token: str, chat_id: str, enabled: bool, interval: int,
                  screenshot_quality: str = "medium", *, allowed_user_ids: Iterable[int] = (),
                  allow_remote_power: bool = False, allow_remote_screenshot: bool = False) -> None:
        """Задать параметры в памяти, не трогая файл конфигурации."""
        self.token = (token or '').strip() or None
        self.chat_id = str(chat_id or '').strip() or None
        self.enabled = bool(enabled)
        self.notification_interval = normalize_interval(interval)
        self.screenshot_quality = self._normalize_screenshot_quality(screenshot_quality)
        self.allowed_user_ids = _normalize_user_ids(list(allowed_user_ids))
        self.allow_remote_power = bool(allow_remote_power)
        self.allow_remote_screenshot = bool(allow_remote_screenshot)

    def load_config(self) -> None:
        config = read_json(TELEGRAM_CONFIG_FILE)
        if config:
            self.configure(
                config.get('TELEGRAM_BOT_TOKEN') or '',
                config.get('TELEGRAM_CHAT_ID') or '',
                config.get('enabled', False),
                config.get('notification_interval', 3600),
                config.get('screenshot_quality', "medium"),
                allowed_user_ids=_normalize_user_ids(config.get('allowed_user_ids')),
                allow_remote_power=config.get('allow_remote_power', False),
                allow_remote_screenshot=config.get('allow_remote_screenshot', False),
            )

    def save_config(self, token: str, chat_id: str, enabled: bool, interval: int,
                    screenshot_quality: str = "medium", *, allowed_user_ids: Iterable[int] = (),
                    allow_remote_power: bool = False, allow_remote_screenshot: bool = False) -> bool:
        self.configure(token, chat_id, enabled, interval, screenshot_quality,
                       allowed_user_ids=allowed_user_ids, allow_remote_power=allow_remote_power,
                       allow_remote_screenshot=allow_remote_screenshot)
        try:
            atomic_write_json(TELEGRAM_CONFIG_FILE, {
                'TELEGRAM_BOT_TOKEN': self.token,
                'TELEGRAM_CHAT_ID': self.chat_id,
                'enabled': self.enabled,
                'notification_interval': self.notification_interval,
                'screenshot_quality': self.screenshot_quality,
                'allowed_user_ids': self.allowed_user_ids,
                'allow_remote_power': self.allow_remote_power,
                'allow_remote_screenshot': self.allow_remote_screenshot,
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
    def _prepare_text(cls, message: str, html_markup: bool) -> tuple[str, Optional[str]]:
        """Вернуть (текст, parse_mode). Обычный текст уходит без разметки, поэтому
        символы < и & в переводах не ломают сообщение. Слишком длинный HTML отправляется
        простым текстом, чтобы обрезка не разрезала тег."""
        text = str(message or "")
        if not html_markup:
            return truncate_message(text, cls.MAX_MESSAGE_LENGTH), None
        if len(text) <= cls.MAX_MESSAGE_LENGTH:
            return text, 'HTML'
        plain = html.unescape(_HTML_TAG_RE.sub("", text))
        return truncate_message(plain, cls.MAX_MESSAGE_LENGTH), None

    def send_message(self, message: str, force: bool = False, html_markup: bool = False) -> bool:
        if (not force and not self.enabled) or not self.token or not self.chat_id:
            return False

        text, parse_mode = self._prepare_text(message, html_markup)
        payload = {'chat_id': self.chat_id, 'text': text}
        if parse_mode:
            payload['parse_mode'] = parse_mode
        url = self._api_url("sendMessage")

        try:
            response = post_with_retries(
                lambda: requests.post(url, data=payload, timeout=(3, 7)),
                channel="Telegram",
                max_attempts=self._MAX_SEND_RETRIES,
                retry_after=self._extract_retry_after,
            )
            return self._check_response(response, "сообщения")
        except Exception as e:
            self.last_error = e.__class__.__name__
            logger.exception("Ошибка отправки сообщения в Telegram: %s", e.__class__.__name__)
            return False

    def send_message_async(self, message: str) -> None:
        """Отправить из главного потока, не дожидаясь сети."""
        threading.Thread(target=self.send_message, args=(message,), name="telegram-send", daemon=True).start()

    @classmethod
    def _extract_retry_after(cls, response: Response) -> float:
        """Пауза, которую Telegram просит при HTTP 429: parameters.retry_after."""
        try:
            retry_after = float((response.json().get("parameters") or {}).get("retry_after", 1.0))
        except (TypeError, ValueError, AttributeError):
            return 1.0
        return max(0.1, min(cls._MAX_RETRY_AFTER_SEC, retry_after))

    def _check_response(self, response: Optional[Response], what: str) -> bool:
        self.last_error = self._response_error(response)
        if self.last_error:
            logger.error("Ошибка отправки %s в Telegram: %s", what, self.last_error)
            return False
        return True

    @staticmethod
    def _response_error(response: Optional[Response]) -> Optional[str]:
        """Понятная причина ошибки: описание Telegram API (например, «chat not found») или код HTTP."""
        if response is None:
            return "no connection to api.telegram.org"
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 200 and data.get('ok', False):
            return None
        description = data.get('description') if isinstance(data, dict) else None
        return f"HTTP {response.status_code}: {description}" if description else f"HTTP {response.status_code}"

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
            response = post_with_retries(send, channel="Telegram", max_attempts=self._MAX_PHOTO_SEND_RETRIES,
                                         retry_after=self._extract_retry_after)
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
        # Разрешение могли снять, пока запрос ждал в очереди.
        if not self.allow_remote_screenshot or not self.enabled:
            return
        self.send_message(tr('bot_screenshot_processing'))
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

    def _render_metric_graph_to_temp(self, metric: str) -> Optional[tuple[str, str]]:
        """Тот же график, что в окне SyMo, за всю историю из настроек, в PNG-файл."""
        app = self.app_ref
        spec = build_graph_specs().get(metric)
        if spec is None or app is None:
            return None
        samples = app.metrics_history.samples(metric)
        if not samples:
            return None
        try:
            import cairo  # type: ignore
        except Exception:
            logger.warning("cairo недоступен: не удалось построить изображение графика")
            return None

        width, height = 980, 440
        caption = tr('graph_caption').format(spec.title().strip())
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        render_graph(cairo.Context(surface), spec, decimate_samples(samples, width * 2), width, height,
                     app.graph_line_color, title=caption)

        fd, path = tempfile.mkstemp(prefix=f"symo-graph-{metric}-", suffix=".png")
        os.close(fd)
        try:
            surface.write_to_png(path)
        except Exception:
            _remove_quietly(path)
            raise
        return path, caption

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

    def _skip_pending_updates(self) -> Optional[int]:
        """Подтвердить все накопившиеся обновления, не выполняя их; вернуть последний update_id."""
        try:
            response = requests.get(self._api_url("getUpdates"), params={'offset': -1, 'timeout': 0}, timeout=10)
            if response.status_code != 200:
                return None
            data = response.json()
            if not data.get('ok'):
                return None
            result = data.get('result') or []
            return int(result[-1]['update_id']) if result else 0
        except Exception as e:
            logger.warning("Не удалось пропустить старые обновления Telegram: %s", e.__class__.__name__)
            return None

    def _fetch_bot_username(self) -> Optional[str]:
        try:
            response = requests.get(self._api_url("getMe"), timeout=10)
            username = (response.json().get('result') or {}).get('username')
            return str(username).lower() if username else None
        except Exception as e:
            logger.warning("Не удалось узнать имя бота Telegram: %s", e.__class__.__name__)
            return None

    def _bot_worker(self, stop_event: threading.Event) -> None:
        # Смещение — своё у каждого запуска: после смены токена или долгого простоя
        # старое значение могло бы оказаться больше новых update_id, и все команды
        # молча отбрасывались бы.
        started_at = time.time()
        last_update_id = self._skip_pending_updates() or 0
        slow_jobs: Queue[Optional[Callable[[], None]]] = Queue(maxsize=self._MAX_PENDING_SLOW_COMMANDS)
        replies: Queue[Optional[Callable[[], None]]] = Queue(maxsize=self._MAX_PENDING_REPLIES)
        threading.Thread(target=self._run_jobs, args=(slow_jobs,), name="telegram-media", daemon=True).start()
        threading.Thread(target=self._run_jobs, args=(replies,), name="telegram-reply", daemon=True).start()

        def reply(text: str, html_markup: bool = False) -> None:
            try:
                replies.put_nowait(lambda: self.send_message(text, html_markup=html_markup))
            except Full:
                logger.warning("Очередь ответов Telegram переполнена: ответ отброшен")

        def submit_slow(job: Callable[[], None]) -> bool:
            try:
                slow_jobs.put_nowait(job)
                return True
            except Full:
                reply(tr('bot_busy'))
                return False

        run = _BotRun(started_at, reply, submit_slow)
        backoff_seconds = 1.0

        def pause(seconds: Optional[float] = None) -> None:
            nonlocal backoff_seconds
            stop_event.wait(seconds if seconds is not None else min(backoff_seconds, 30.0))
            backoff_seconds = min(backoff_seconds * 2, 30.0)

        try:
            while not stop_event.is_set() and self.enabled and self.token:
                try:
                    if run.bot_username is None:
                        run.bot_username = self._fetch_bot_username()
                    params = {'timeout': self._POLL_TIMEOUT_SEC, 'offset': last_update_id + 1}
                    response = requests.get(self._api_url("getUpdates"), params=params,
                                            timeout=self._POLL_TIMEOUT_SEC + 5)
                    if stop_event.is_set():
                        break

                    if response.status_code == 200:
                        data = response.json()
                        if data.get('ok'):
                            for update in data.get('result', []):
                                last_update_id = int(update['update_id'])
                                self._process_update(update, run)
                        backoff_seconds = 1.0
                    elif response.status_code == 409:
                        logger.warning("Другой экземпляр бота уже получает обновления")
                        pause()
                    elif response.status_code == 429:
                        pause(self._extract_retry_after(response))
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
        finally:
            slow_jobs.put(None)
            replies.put(None)

    @staticmethod
    def _run_jobs(jobs: "Queue[Optional[Callable[[], None]]]") -> None:
        while True:
            job = jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception as e:
                logger.exception("Ошибка выполнения команды Telegram: %s", e)

    @staticmethod
    def _is_trusted_sender(message: dict, allowed_user_ids: list[int]) -> bool:
        chat = message.get('chat') or {}
        if chat.get('type') == 'private':
            return True
        sender = message.get('from') or {}
        # Анонимный админ и сообщение от имени канала приходят с общим служебным from.id.
        if message.get('sender_chat') or sender.get('is_bot') or sender.get('id') in _SERVICE_SENDER_IDS:
            return False
        return sender.get('id') in allowed_user_ids

    def _process_update(self, update: dict, run: _BotRun) -> None:
        message = update.get('message') or {}
        chat = message.get('chat') or {}
        if str(chat.get('id', '')) != self.chat_id:
            return
        try:
            sent_at = float(message.get('date', 0))
        except (TypeError, ValueError):
            sent_at = 0.0
        if sent_at < run.started_at - self._STALE_MESSAGE_GRACE_SEC:
            logger.info("Пропущена устаревшая команда Telegram")
            return
        parts = (message.get('text') or '').split()
        if not parts or not parts[0].startswith('/'):
            return
        command, _, addressee = parts[0].lower().partition('@')
        # В группе с несколькими ботами /status@other_bot адресована не нам. Пока имя
        # бота неизвестно (getMe не ответил), такие команды не выполняются вовсе.
        if addressee and addressee != run.bot_username:
            return
        is_private = chat.get('type') == 'private'
        if command in PRIVILEGED_COMMANDS:
            sender_id = (message.get('from') or {}).get('id')
            if not self._is_trusted_sender(message, self.allowed_user_ids):
                self._deny(run, command, sender_id, message)
                return
            if time.time() - sent_at > self._MAX_PRIVILEGED_COMMAND_AGE_SEC:
                logger.info("Команда Telegram %s устарела и не выполнена", command)
                run.reply(tr('bot_command_stale'))
                return
        self._handle_command(command, parts[1:], run, reply_unknown=is_private or bool(addressee))

    def _deny(self, run: _BotRun, command: str, sender_id: object, message: dict) -> None:
        logger.warning("Команда Telegram %s от пользователя %s отклонена: нет в списке разрешённых",
                       command, sender_id)
        # Ответ одному отправителю — не чаще раза в минуту, служебным отправителям — никогда:
        # их ID общий, и добавлять его в разрешённые нельзя.
        if (message.get('sender_chat') or (message.get('from') or {}).get('is_bot')
                or sender_id in _SERVICE_SENDER_IDS or sender_id is None):
            return
        now = time.monotonic()
        if now - run.last_denial.get(sender_id, float("-inf")) < self._DENIAL_REPLY_INTERVAL_SEC:
            return
        run.last_denial[sender_id] = now
        run.reply(tr('bot_command_not_allowed').format(sender_id))

    def _handle_command(self, command: str, args: list[str], run: _BotRun, reply_unknown: bool = True) -> None:
        power = self.power_control_ref
        reply = run.reply
        if command in POWER_COMMANDS:
            if not self.allow_remote_power:
                reply(tr('bot_command_disabled'))
                return
            minutes = _parse_delay_minutes(args)
            if minutes is None:
                reply(tr('bot_minutes_invalid').format(REMOTE_POWER_DELAY_MAX))
                return
            if power is None:
                reply(f"❌ {tr('error')}")
                return
            act = POWER_COMMANDS[command]
            # Через таймер: на компьютере видно предупреждение с кнопкой отмены, а здесь — /cancel.
            GLib.idle_add(self._schedule_power_action, act, minutes)
            reply(f"⏳ {tr('bot_action_scheduled').format(action_label(act), minutes)}")
        elif command == '/cancel':
            if power is not None:
                GLib.idle_add(self._cancel_power_action)
        elif command == '/lock':
            if power is not None:
                reply(tr('bot_lock_message'))
                GLib.idle_add(self._run_lock)
        elif command == '/status':
            self._send_system_status(reply)
        elif command == '/screenshot':
            if not self.allow_remote_screenshot:
                reply(tr('bot_command_disabled'))
                return
            run.submit_slow(self._send_screenshot)
        elif command == '/help':
            reply(self._help_text())
        elif command in GRAPH_COMMANDS:
            metric = GRAPH_COMMANDS[command]
            run.submit_slow(lambda: self._send_metric_graph(metric))
        elif reply_unknown:
            reply(f"{tr('unknown_command')}. {tr('unknown_command_help')}")

    # Эти три метода выполняются в главном потоке GTK (через GLib.idle_add).
    def _schedule_power_action(self, act: Action, minutes: int) -> bool:
        self.power_control_ref.schedule(act, minutes, notify_remote=self.send_message_async)
        return False

    def _cancel_power_action(self) -> bool:
        cancelled = self.power_control_ref.cancel_schedule()
        if cancelled is None:
            self.send_message_async(tr('bot_nothing_to_cancel'))
        else:
            self.send_message_async(f"✅ {tr('bot_action_cancelled').format(action_label(cancelled))}")
        return False

    def _run_lock(self) -> bool:
        self.power_control_ref.run_action(Action.LOCK, notify_remote=self.send_message_async)
        return False

    @staticmethod
    def _help_text() -> str:
        return (
            tr('bot_help_message')
            + f"\n\n📊 {tr('graph_commands_title')}:"
            + f"\n/cpu_graph - {tr('cpu')}"
            + f"\n/temp_graph - {tr('cpu')}, {tr('temperature_label')}"
            + f"\n/ram_graph - {tr('ram')}"
            + f"\n/net_graph - {tr('network')}"
            + f"\n/disk_graph - {tr('disk')}"
            + f"\n/swap_graph - {tr('swap')}"
            + f"\n/keyboard_graph - {tr('keyboard_clicks')}"
            + f"\n/mouse_graph - {tr('mouse_clicks')}"
        )

    def _send_system_status(self, reply: Callable[..., None]) -> None:
        # Берём срез из основного цикла: вызов psutil.cpu_percent() из этого
        # потока сбил бы замер загрузки CPU.
        snapshot = getattr(self.app_ref, "latest_snapshot", None)
        if snapshot is None:
            reply(f"❌ {tr('error')}")
            return
        reply(format_status_message(snapshot, "html"), html_markup=True)


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
