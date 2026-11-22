"""Загрузка, нормализация и атомарное сохранение настроек приложения."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .constants import (
    ALERT_DEFAULTS,
    LOG_INTERVAL_DEFAULT_SEC,
    LOG_INTERVAL_MAX_SEC,
    LOG_INTERVAL_MIN_SEC,
    PING_HOST_DEFAULT,
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
    SUPPORTED_LANGS,
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


def _set_aside_corrupted(path: Path) -> None:
    """Сохранить испорченный файл рядом, чтобы следующая запись его не затёрла."""
    backup = path.with_name(f"{path.name}.bad-{int(time.time())}")
    try:
        os.replace(path, backup)
        logger.warning("Испорченный файл %s сохранён как %s", path, backup)
    except OSError as e:
        logger.warning("Не удалось сохранить испорченный файл %s: %s", path, e)


def read_json(path: Path) -> Dict[str, Any]:
    """Прочитать JSON-объект; при отсутствии файла или ошибке вернуть {}.

    Файл, который не разбирается как JSON-объект, переименовывается в
    <имя>.bad-<время>: иначе его молча перезаписали бы значения по умолчанию.
    Так же откладывается файл, который не удалось прочитать (например, без прав).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as e:
        logger.warning("Не удалось прочитать %s: %s", path, e)
        _set_aside_corrupted(path)
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        logger.warning("Не удалось разобрать %s: %s", path, e)
        data = None
    if not isinstance(data, dict):
        _set_aside_corrupted(path)
        return {}
    return data


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


def sanitize_log_interval(value: object) -> int:
    return _clamp_int(value, LOG_INTERVAL_DEFAULT_SEC, LOG_INTERVAL_MIN_SEC, LOG_INTERVAL_MAX_SEC)


def sanitize_alert_threshold(key: str, value: object) -> int:
    high = 150 if key == 'alert_cpu_temp_c' else 100
    return _clamp_int(value, ALERT_DEFAULTS.get(key, 0), 0, high)


_HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}")


def sanitize_ping_host(value: object) -> str:
    """Имя хоста или IP-адрес. Начало с «-» не допускается: ping принял бы его за параметр."""
    host = str(value or "").strip()
    return host if _HOST_RE.fullmatch(host) else PING_HOST_DEFAULT


def sanitize_disk_path(value: object) -> str:
    path = str(value or "").strip()
    return path if path.startswith("/") else "/"


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
        'battery': True, 'gpu': True,
        'disk_path': '/', 'ping_host': PING_HOST_DEFAULT,
        'log_interval_sec': LOG_INTERVAL_DEFAULT_SEC,
        # Проверка обновлений: включена, время последней проверки и найденная версия.
        'check_updates': True, 'update_last_check': 0.0, 'update_latest_version': '',
        'update_notified_version': '',
    }
    settings.update(ALERT_DEFAULTS)
    for key in POLL_INTERVAL_SETTING_KEYS:
        settings[key] = POLL_INTERVAL_DEFAULT_SEC
    settings.update(GRAPH_COLOR_DEFAULTS)
    return settings


def normalize_settings(raw: Dict[str, Any]) -> Dict[str, Any]:
    settings = default_settings()
    settings.update(raw or {})
    settings['graph_history_minutes'] = sanitize_graph_history_minutes(settings.get('graph_history_minutes'))
    settings['max_log_mb'] = sanitize_log_size_mb(settings.get('max_log_mb'))
    settings['log_interval_sec'] = sanitize_log_interval(settings.get('log_interval_sec'))
    settings['ping_host'] = sanitize_ping_host(settings.get('ping_host'))
    settings['disk_path'] = sanitize_disk_path(settings.get('disk_path'))
    for key in ALERT_DEFAULTS:
        settings[key] = sanitize_alert_threshold(key, settings.get(key))
    settings['check_updates'] = bool(settings.get('check_updates'))
    try:
        settings['update_last_check'] = max(0.0, float(settings.get('update_last_check') or 0.0))
    except (TypeError, ValueError):
        settings['update_last_check'] = 0.0
    for key in ('update_latest_version', 'update_notified_version'):
        settings[key] = str(settings.get(key) or '')
    # Старые версии хранили один общий цвет 'graph_line_color'.
    legacy_color = raw.get('graph_line_color') if raw else None
    for key, fallback in GRAPH_COLOR_DEFAULTS.items():
        source = (raw or {}).get(key, legacy_color if legacy_color is not None else fallback)
        settings[key] = sanitize_hex_color(source)
    settings['menu_order'] = normalize_menu_order(settings.get('menu_order'))
    language = str(settings.get('language') or '').strip().lower()
    settings['language'] = language if language in SUPPORTED_LANGS else None
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
