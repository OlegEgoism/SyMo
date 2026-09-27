"""Загрузка, нормализация и атомарное сохранение настроек приложения."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .constants import (
    GRAPH_COLOR_DEFAULTS,
    GRAPH_HISTORY_MINUTES_DEFAULT,
    GRAPH_HISTORY_MINUTES_MAX,
    GRAPH_HISTORY_MINUTES_MIN,
    GRAPH_LINE_COLOR_FALLBACK,
    LOG_MAX_MB_MAX,
    LOG_MAX_MB_MIN,
    MENU_ORDER_DEFAULT,
    POLL_INTERVAL_DEFAULT_SEC,
    POLL_INTERVAL_MAX_SEC,
    POLL_INTERVAL_MIN_SEC,
    POLL_INTERVAL_SETTING_KEYS,
)

logger = logging.getLogger(__name__)


def atomic_write_json(path: Path, data: Any, mode: Optional[int] = None) -> None:
    """Записать JSON через временный файл и os.replace.

    Файл никогда не остаётся полузаписанным. Если задан ``mode``, права
    выставляются до того, как в файл попадают данные.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_json(path: Path) -> Dict[str, Any]:
    """Прочитать JSON-объект; при отсутствии файла или ошибке вернуть {}."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Не удалось прочитать %s: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def sanitize_graph_history_minutes(value: object) -> int:
    return _clamp_int(value, GRAPH_HISTORY_MINUTES_DEFAULT, GRAPH_HISTORY_MINUTES_MIN, GRAPH_HISTORY_MINUTES_MAX)


def sanitize_poll_interval(value: object) -> int:
    return _clamp_int(value, POLL_INTERVAL_DEFAULT_SEC, POLL_INTERVAL_MIN_SEC, POLL_INTERVAL_MAX_SEC)


def sanitize_log_size_mb(value: object) -> int:
    return _clamp_int(value, 5, LOG_MAX_MB_MIN, LOG_MAX_MB_MAX)


def sanitize_hex_color(value: object, fallback: str = GRAPH_LINE_COLOR_FALLBACK) -> str:
    raw = str(value or "").strip()
    if len(raw) == 7 and raw.startswith('#'):
        hex_part = raw[1:]
        if all(ch in "0123456789abcdefABCDEF" for ch in hex_part):
            return f"#{hex_part.lower()}"
    return fallback


def hex_to_rgb(value: object) -> tuple[float, float, float]:
    hex_color = sanitize_hex_color(value)
    return (
        int(hex_color[1:3], 16) / 255.0,
        int(hex_color[3:5], 16) / 255.0,
        int(hex_color[5:7], 16) / 255.0,
    )


def graph_line_color_rgb(settings: Dict[str, Any], key: str) -> tuple[float, float, float]:
    return hex_to_rgb(settings.get(key, GRAPH_COLOR_DEFAULTS.get(key, GRAPH_LINE_COLOR_FALLBACK)))


def normalize_menu_order(order: Optional[Iterable[str]]) -> list[str]:
    """Оставить только известные ключи без повторов и дописать недостающие."""
    unique: list[str] = []
    for key in order or []:
        if key in MENU_ORDER_DEFAULT and key not in unique:
            unique.append(key)
    for key in MENU_ORDER_DEFAULT:
        if key not in unique:
            unique.append(key)
    return unique


def default_settings() -> Dict[str, Any]:
    settings: Dict[str, Any] = {
        'cpu': True, 'ram': True, 'swap': True, 'disk': True, 'net': True, 'uptime': True,
        'tray_cpu': True, 'tray_ram': True, 'keyboard_clicks': True, 'mouse_clicks': True,
        'language': None, 'logging_enabled': True, 'show_graph_zoom_controls': True,
        'show_power_off': True, 'show_reboot': True, 'show_lock': True, 'show_timer': True,
        'max_log_mb': 5, 'ping_network': True, 'show_system_info': True,
        'graph_history_minutes': GRAPH_HISTORY_MINUTES_DEFAULT,
        'menu_order': MENU_ORDER_DEFAULT.copy(),
        'profiling_enabled': False,
    }
    for key in POLL_INTERVAL_SETTING_KEYS:
        settings[key] = POLL_INTERVAL_DEFAULT_SEC
    settings.update(GRAPH_COLOR_DEFAULTS)
    return settings


def normalize_settings(raw: Dict[str, Any]) -> Dict[str, Any]:
    settings = default_settings()
    settings.update(raw or {})
    settings['graph_history_minutes'] = sanitize_graph_history_minutes(settings.get('graph_history_minutes'))
    settings['max_log_mb'] = sanitize_log_size_mb(settings.get('max_log_mb'))
    # Старые версии хранили один общий цвет 'graph_line_color'.
    legacy_color = raw.get('graph_line_color') if raw else None
    for key, fallback in GRAPH_COLOR_DEFAULTS.items():
        source = (raw or {}).get(key, legacy_color if legacy_color is not None else fallback)
        settings[key] = sanitize_hex_color(source)
    settings['menu_order'] = normalize_menu_order(settings.get('menu_order'))
    for key in POLL_INTERVAL_SETTING_KEYS:
        settings[key] = sanitize_poll_interval(settings.get(key))
    return settings


def load_settings(path: Path) -> Dict[str, Any]:
    return normalize_settings(read_json(path))


def save_settings(path: Path, settings: Dict[str, Any]) -> bool:
    try:
        atomic_write_json(path, settings)
        return True
    except Exception as e:
        logger.error("Ошибка сохранения настроек в %s: %s", path, e)
        return False
