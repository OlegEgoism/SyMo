"""Токены и адреса webhook — в системной связке ключей (Secret Service: GNOME Keyring,
KWallet), а не открытым текстом в ~/.symo_*.json.

Если libsecret (gir1.2-secret-1) не установлен или служба недоступна, вызывающий код
хранит значение в файле настроек с правами 0600, как раньше.
"""
from __future__ import annotations

import logging
from typing import Optional

from .constants import APP_NAME, DBUS_NAME

logger = logging.getLogger(__name__)

try:
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import GLib, Secret
except (ImportError, ValueError):
    Secret = None

_SCHEMA = None if Secret is None else Secret.Schema.new(
    DBUS_NAME, Secret.SchemaFlags.NONE, {"key": Secret.SchemaAttributeType.STRING})


def available() -> bool:
    return _SCHEMA is not None


def store(key: str, value: str) -> bool:
    """Сохранить значение; False, если связки ключей нет и нужно хранить в файле."""
    if _SCHEMA is None:
        return False
    try:
        return bool(Secret.password_store_sync(_SCHEMA, {"key": key}, Secret.COLLECTION_DEFAULT,
                                               f"{APP_NAME}: {key}", value, None))
    except GLib.Error as e:
        logger.warning("Связка ключей недоступна, %s останется в файле настроек: %s", key, e.message)
        return False


def lookup(key: str) -> Optional[str]:
    if _SCHEMA is None:
        return None
    try:
        return Secret.password_lookup_sync(_SCHEMA, {"key": key}, None)
    except GLib.Error as e:
        logger.warning("Не удалось прочитать %s из связки ключей: %s", key, e.message)
        return None


def clear(key: str) -> None:
    if _SCHEMA is None:
        return
    try:
        Secret.password_clear_sync(_SCHEMA, {"key": key}, None)
    except GLib.Error as e:
        logger.warning("Не удалось удалить %s из связки ключей: %s", key, e.message)


def load_secret(config: dict, file_key: str, secret_key: str) -> Optional[str]:
    """Значение из конфигурации: из связки ключей, если там помечено, иначе из файла."""
    if config.get(f"{file_key}_in_keyring"):
        value = lookup(secret_key)
        if value is None:
            logger.warning("%s нет в связке ключей: введите его заново в настройках", file_key)
        return value
    return config.get(file_key) or None


def save_secret(file_key: str, secret_key: str, value: Optional[str]) -> dict:
    """Поля для файла конфигурации: пометка «в связке ключей» или само значение,
    если связки нет."""
    if not value:
        clear(secret_key)
        return {file_key: None}
    if store(secret_key, value):
        return {file_key: None, f"{file_key}_in_keyring": True}
    return {file_key: value}
