from __future__ import annotations

import locale
import os
from typing import Dict

from .language import LANGUAGES

from .constants import SUPPORTED_LANGS

current_lang = 'ru'

_LOCALE_ALIASES = {'zh': 'cn'}
_SYSTEM_FALLBACK_LANG = 'en'


def tr(key: str) -> str:
    lang_map: Dict[str, str] = LANGUAGES.get(current_lang) or LANGUAGES.get('en', {})
    return lang_map.get(key, key)


def _normalize_locale_code(raw: str) -> str:
    code = (raw or '').split('.')[0].split('@')[0].split('_')[0].split('-')[0].strip().lower()
    return _LOCALE_ALIASES.get(code, code)


def detect_system_language() -> str:
    candidates = [os.environ.get(name, '') for name in ('LC_ALL', 'LC_MESSAGES', 'LANG')]
    # LANGUAGE — список через двоеточие в порядке предпочтения.
    candidates = [part for part in os.environ.get('LANGUAGE', '').split(':') if part] + candidates
    try:
        candidates.append(locale.getlocale()[0] or '')
    except Exception:
        pass

    for raw in candidates:
        if not raw or raw in ('C', 'POSIX'):
            continue
        code = _normalize_locale_code(raw)
        if code in SUPPORTED_LANGS:
            return code
    return _SYSTEM_FALLBACK_LANG


def set_language(lang_code: str) -> None:
    global current_lang
    normalized = (lang_code or '').strip().lower()
    current_lang = normalized if normalized in SUPPORTED_LANGS else _SYSTEM_FALLBACK_LANG


def get_language() -> str:
    return current_lang


def _plural_ru(value: int) -> str:
    value = abs(int(value))
    if value % 10 == 1 and value % 100 != 11:
        return 'one'
    if 2 <= value % 10 <= 4 and (value % 100 < 10 or value % 100 >= 20):
        return 'few'
    return 'many'


def format_uptime(raw_uptime: str) -> str:
    """«3 days, 4:05:06» из timedelta → «3 дня, 4:05:06» на текущем языке."""
    parts = (raw_uptime or "").split(", ", 1)
    if len(parts) != 2:
        return raw_uptime
    day_part, time_part = parts
    day_tokens = day_part.split()
    if len(day_tokens) != 2 or not day_tokens[0].isdigit():
        return raw_uptime
    days = int(day_tokens[0])
    plural_key = _plural_ru(days) if current_lang == 'ru' else ('one' if days == 1 else 'many')
    day_label = tr(f'uptime_day_{plural_key}')
    if day_label == f'uptime_day_{plural_key}':
        day_label = 'day' if days == 1 else 'days'
    return f"{days} {day_label}, {time_part}"
