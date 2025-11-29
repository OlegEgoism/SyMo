from __future__ import annotations

import locale
import os
from typing import Dict

from language import LANGUAGES

from constants import SUPPORTED_LANGS

current_lang = 'ru'


def tr(key: str) -> str:
    lang_map: Dict[str, str] = LANGUAGES.get(current_lang) or LANGUAGES.get('en', {})
    return lang_map.get(key, key)


def detect_system_language() -> str:
    try:
        env = os.environ.get('LANG', '')
        if env:
            code = env.split('.')[0].split('_')[0].lower()
            return code if code in SUPPORTED_LANGS else 'ru'
        code = (locale.getlocale()[0] or '').split('_')[0].lower()
        return code if code in SUPPORTED_LANGS else 'ru'
    except Exception:
        return 'ru'


def set_language(lang_code: str) -> None:
    global current_lang
    current_lang = lang_code


def get_language() -> str:
    return current_lang
