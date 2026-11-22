"""Счётчики нажатий клавиш и кликов мыши через глобальные хуки pynput."""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from .click_tracker import get_counts, increment_keyboard, increment_mouse
from .localization import tr

logger = logging.getLogger(__name__)

KINDS = ('keyboard', 'mouse')


def is_wayland_session() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


class InputCounters:
    def __init__(self) -> None:
        # Wayland не отдаёт приложениям чужие нажатия: глобальный хук увидел бы только
        # окна XWayland, и счётчики показывали бы заниженные числа как настоящие.
        self.available = not is_wayland_session()
        if not self.available:
            logger.info("Сессия Wayland: счётчики клавиш и кликов отключены")
        self.keyboard_listener = None
        self.mouse_listener = None

    def sync(self, settings: dict) -> None:
        """Глобальный хук клавиатуры или мыши работает, только пока его счётчик показан в меню."""
        for kind in KINDS:
            attr = f'{kind}_listener'
            wanted = self.available and settings.get(f'{kind}_clicks', True)
            listener = getattr(self, attr)
            if wanted and listener is None:
                setattr(self, attr, self._start(kind))
            elif not wanted and listener is not None:
                self._stop_listener(listener)
                setattr(self, attr, None)
        if not self.available:
            self.stop()

    def _start(self, kind: str):
        # pynput падает уже при импорте, если нет X-дисплея: тогда отключаются
        # только счётчики, а не всё приложение.
        try:
            from pynput import keyboard, mouse
            if kind == 'keyboard':
                listener = keyboard.Listener(on_press=lambda _key: increment_keyboard(), daemon=True)
            else:
                listener = mouse.Listener(
                    on_click=lambda _x, _y, _button, pressed: increment_mouse() if pressed else None, daemon=True)
            listener.start()
            return listener
        except Exception as e:
            logger.warning("Счётчики клавиш и кликов недоступны: %s", e)
            self.available = False
            return None

    @staticmethod
    def _stop_listener(listener) -> None:
        # stop() ждёт готовности хука и зависает навсегда, если поток pynput упал
        # при запуске, поэтому главный поток GTK его не ждёт.
        threading.Thread(target=listener.stop, name="pynput-stop", daemon=True).start()

    def stop(self) -> None:
        for kind in KINDS:
            attr = f'{kind}_listener'
            listener = getattr(self, attr)
            if listener is not None:
                self._stop_listener(listener)
                setattr(self, attr, None)

    def counts(self) -> tuple[Optional[int], Optional[int]]:
        """Значения счётчиков; None — счётчик недоступен или скрыт (хук не работает)."""
        kbd, ms = get_counts()
        return (kbd if self.keyboard_listener is not None else None,
                ms if self.mouse_listener is not None else None)

    @staticmethod
    def unavailable_text(title_key: str) -> str:
        reason = " (Wayland)" if is_wayland_session() else ""
        return f"{tr(title_key)}: N/A{reason}"
