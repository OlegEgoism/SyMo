"""Проверка новых версий SyMo на GitHub: раз в день, если включено в настройках."""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Optional

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
