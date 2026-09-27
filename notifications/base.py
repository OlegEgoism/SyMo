"""Общие помощники для Telegram и Discord."""
from __future__ import annotations

import html
import logging
import threading
import time
from queue import Empty, Full, Queue
from typing import Callable, Collection, Optional

import requests
from requests import Response

from app_core.localization import tr
from app_core.system_usage import MetricsSnapshot

logger = logging.getLogger(__name__)

INTERVAL_DEFAULT_SEC = 3600
INTERVAL_MIN_SEC = 10
INTERVAL_MAX_SEC = 86400
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def normalize_interval(interval: object) -> int:
    try:
        value = int(interval)
    except (TypeError, ValueError):
        value = INTERVAL_DEFAULT_SEC
    return max(INTERVAL_MIN_SEC, min(INTERVAL_MAX_SEC, value))


def truncate_message(message: object, max_length: int) -> str:
    text = str(message or "")
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def post_with_retries(
        send: Callable[[], Response],
        *,
        channel: str,
        max_attempts: int = 3,
        retryable_status: Collection[int] = RETRYABLE_STATUS_CODES,
        retry_after: Optional[Callable[[Response], Optional[float]]] = None,
        max_backoff: float = 8.0,
) -> Optional[Response]:
    """Выполнить запрос с экспоненциальной паузой между попытками.

    После последней попытки пауза не делается. ``retry_after`` может вернуть
    задержку, которую сервер попросил явно (HTTP 429).
    """
    backoff = 1.0
    last_response: Optional[Response] = None
    for attempt in range(1, max_attempts + 1):
        delay: Optional[float] = None
        try:
            response = send()
            last_response = response
            if response.status_code not in retryable_status:
                return response
            if retry_after is not None and response.status_code == 429:
                delay = retry_after(response)
        except requests.exceptions.RequestException as e:
            # Только тип ошибки: текст исключения содержит URL, а в URL Telegram — токен бота.
            logger.warning("Ошибка связи с %s API: %s", channel, e.__class__.__name__)
        if attempt == max_attempts:
            break
        time.sleep(delay if delay is not None else backoff)
        backoff = min(backoff * 2, max_backoff)
    return last_response


def format_status_message(snapshot: MetricsSnapshot, markup: str = "html") -> str:
    """Текст статуса системы для уведомлений: markup — 'html' (Telegram) или 'markdown' (Discord)."""
    if markup == "html":
        def bold(text: str) -> str:
            return f"<b>{html.escape(text)}</b>"

        def value(text: str) -> str:
            return html.escape(text)
    else:
        def bold(text: str) -> str:
            return f"**{text}**"

        def value(text: str) -> str:
            return text

    s = snapshot
    rows = [
        (tr('cpu'), f"{s.cpu_usage:.0f}% ({s.cpu_temp}{tr('temperature')})"),
        (tr('ram'), f"{s.ram_used:.1f}/{s.ram_total:.1f} {tr('gb')}"),
        (tr('swap'), f"{s.swap_used:.1f}/{s.swap_total:.1f} {tr('gb')}"),
        (tr('disk'), f"{s.disk_used:.1f}/{s.disk_total:.1f} {tr('gb')}"),
        (tr('network'), f"↓{s.net_recv:.1f}/↑{s.net_sent:.1f} {tr('mbps')}"),
        (tr('uptime'), s.uptime),
        (tr('keyboard'), f"{s.keyboard_clicks} {tr('presses')}"),
        (tr('mouse'), f"{s.mouse_clicks} {tr('clicks')}"),
    ]
    lines = [f"🖥 {bold(tr('system_status'))}"]
    lines.extend(f"🔹 {bold(label + ':')} {value(text)}" for label, text in rows)
    return "\n".join(lines)


class NotificationDispatcher:
    """Фоновый отправитель с очередью на одно сообщение: хранится только последнее.

    Сетевые задержки не блокируют главный поток, а устаревший статус
    заменяется свежим, не накапливаясь.
    """

    def __init__(self, sender: Callable[[str], object], channel: str) -> None:
        self._sender = sender
        self._channel = channel
        self._queue: Queue[Optional[str]] = Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"notify-{channel}", daemon=True)
        self._thread.start()

    def submit(self, message: Optional[str]) -> None:
        payload = None if message is None else str(message)
        while True:
            try:
                self._queue.put_nowait(payload)
                return
            except Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except Empty:
                    pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                message = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                if message is None:
                    return
                self._sender(message)
            except Exception as e:
                logger.exception("Ошибка отправки уведомления (%s): %s", self._channel, e)
            finally:
                self._queue.task_done()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        self.submit(None)
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
