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
    current_lang = normalized if normalized in SUPPORTED_LANGS else 'ru'


def get_language() -> str:
    return current_lang
