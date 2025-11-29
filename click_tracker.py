from __future__ import annotations

import threading
from typing import Tuple

_clicks_lock = threading.Lock()
keyboard_clicks = 0
mouse_clicks = 0


def increment_keyboard() -> None:
    global keyboard_clicks
    with _clicks_lock:
        keyboard_clicks += 1


def increment_mouse() -> None:
    global mouse_clicks
    with _clicks_lock:
        mouse_clicks += 1


def get_counts() -> Tuple[int, int]:
    with _clicks_lock:
        return keyboard_clicks, mouse_clicks


def reset_counts() -> None:
    global keyboard_clicks, mouse_clicks
    with _clicks_lock:
        keyboard_clicks = 0
        mouse_clicks = 0
