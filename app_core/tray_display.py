from __future__ import annotations

from typing import Iterable, Mapping


DEFAULT_TRAY_ORDER = ["cpu", "ram"]
SUPPORTED_TRAY_KEYS = ["cpu", "ram"]


def normalize_tray_order(raw_order: Iterable[str] | None) -> list[str]:
    if raw_order is None:
        return DEFAULT_TRAY_ORDER.copy()

    normalized: list[str] = []
    seen: set[str] = set()

    for key in raw_order:
        key_norm = str(key).strip().lower()
        if key_norm in SUPPORTED_TRAY_KEYS and key_norm not in seen:
            normalized.append(key_norm)
            seen.add(key_norm)

    for key in DEFAULT_TRAY_ORDER:
        if key not in seen:
            normalized.append(key)

    return normalized


def parse_tray_order_text(raw_text: str) -> list[str]:
    parts = [p.strip().lower() for p in raw_text.replace(";", ",").split(",") if p.strip()]
    return normalize_tray_order(parts)


def ordered_tray_parts(parts_by_key: Mapping[str, str], tray_order: Iterable[str]) -> list[str]:
    parts: list[str] = []
    for key in normalize_tray_order(tray_order):
        value = parts_by_key.get(key)
        if value:
            parts.append(value)
    return parts

