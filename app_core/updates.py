"""Проверка новых версий SyMo на GitHub: раз в день, если включено в настройках."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from typing import Callable, Optional

from gi.repository import GLib

from .constants import APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)

RELEASES_API_URL = "https://api.github.com/repos/OlegEgoism/SyMo/releases/latest"
RELEASES_PAGE_URL = "https://github.com/OlegEgoism/SyMo/releases/latest"
CHECK_INTERVAL_SEC = 24 * 3600
# Первая проверка — не сразу при входе в систему, когда сеть часто ещё не поднялась.
FIRST_CHECK_DELAY_SEC = 60
_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


def parse_version(text: object) -> Optional[tuple[int, ...]]:
    """«v1.2.10» → (1, 2, 10); None, если это не номер версии."""
    match = _VERSION_RE.fullmatch(str(text or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(candidate: object, current: str = APP_VERSION) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def fetch_latest_version(timeout: float = 10.0) -> Optional[str]:
    """Номер последнего релиза (без «v») или None, если узнать не удалось.

    Черновики и предварительные релизы этот адрес GitHub API не возвращает.
    """
    request = urllib.request.Request(RELEASES_API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            tag = json.load(response).get("tag_name")
    except Exception as e:
        logger.info("Не удалось проверить обновления: %s", e.__class__.__name__)
        return None
    version = parse_version(tag)
    return ".".join(map(str, version)) if version else None


class UpdateChecker:
    """Раз в сутки спрашивает GitHub о новой версии; сеть — в фоновом потоке.

    Состояние хранится в настройках: включена ли проверка, когда была последняя,
    какая версия найдена и о какой уже сообщили.
    """

    def __init__(self, settings: dict, save: Callable[[], object],
                 on_found: Callable[[str, bool], None]) -> None:
        self._settings = settings
        self._save = save
        # on_found(версия, впервые): «впервые» — о ней ещё не сообщали уведомлением.
        self._on_found = on_found

    def known_update(self) -> Optional[str]:
        latest = self._settings.get('update_latest_version', '')
        return latest if is_newer(latest) else None

    def start(self) -> None:
        GLib.timeout_add_seconds(FIRST_CHECK_DELAY_SEC, self._first_check)
        # Раз в час проверяем, не прошли ли сутки с прошлой проверки.
        GLib.timeout_add_seconds(3600, self._hourly_check)

    def _first_check(self) -> bool:
        self.check()
        return GLib.SOURCE_REMOVE

    def _hourly_check(self) -> bool:
        self.check()
        return GLib.SOURCE_CONTINUE

    def check(self, force: bool = False) -> None:
        settings = self._settings
        due = time.time() - settings.get('update_last_check', 0.0) >= CHECK_INTERVAL_SEC
        if settings.get('check_updates') and (force or due):
            settings['update_last_check'] = time.time()
            threading.Thread(target=lambda: GLib.idle_add(self._on_checked, fetch_latest_version()),
                             name="update-check", daemon=True).start()

    def _on_checked(self, version: Optional[str]) -> bool:
        settings = self._settings
        if version:
            settings['update_latest_version'] = version
        if version and is_newer(version):
            first_time = settings.get('update_notified_version') != version
            settings['update_notified_version'] = version
            self._on_found(version, first_time)
        self._save()
        return GLib.SOURCE_REMOVE
