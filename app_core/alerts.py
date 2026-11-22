"""Оповещения о превышении порогов: температура процессора, занятость ОЗУ и диска."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from gi.repository import Gio, GLib

from .constants import APP_NAME
from .localization import tr
from .system_usage import MetricsSnapshot

logger = logging.getLogger(__name__)

# Повтор, пока значение остаётся выше порога, — не чаще раза в час.
REPEAT_SEC = 3600
# Снова сработать порог может только после спада на столько: значение у самой границы
# не должно слать оповещение каждые несколько секунд.
HYSTERESIS = 5.0
ALERT_SETTING_KEYS = ('alert_cpu_temp_c', 'alert_ram_percent', 'alert_disk_percent')


def _percent(used: float, total: float) -> Optional[float]:
    return used / total * 100.0 if total > 0 else None


@dataclass
class _Rule:
    setting_key: str
    value: Callable[[MetricsSnapshot], Optional[float]]
    message: Callable[[float, int, MetricsSnapshot], str]


RULES = (
    _Rule('alert_cpu_temp_c', lambda s: s.cpu_temp,
          lambda v, t, s: tr('alert_message_temp').format(round(v), t)),
    _Rule('alert_ram_percent', lambda s: _percent(s.ram_used, s.ram_total),
          lambda v, t, s: tr('alert_message_ram').format(round(v), t)),
    _Rule('alert_disk_percent', lambda s: _percent(s.disk_used, s.disk_total),
          lambda v, t, s: tr('alert_message_disk').format(s.disk_path, round(v), t)),
)


@dataclass
class AlertMonitor:
    _active: Dict[str, bool] = field(default_factory=dict)
    _last_sent: Dict[str, float] = field(default_factory=dict)

    def check(self, snapshot: MetricsSnapshot, settings: dict, now: float) -> list[str]:
        """Сообщения для отправки сейчас. Порог 0 — оповещение выключено."""
        messages = []
        for rule in RULES:
            threshold = int(settings.get(rule.setting_key) or 0)
            value = rule.value(snapshot)
            if threshold <= 0 or value is None:
                self._active[rule.setting_key] = False
                continue
            if value < threshold - HYSTERESIS:
                self._active[rule.setting_key] = False
                continue
            if value < threshold:
                continue
            last = self._last_sent.get(rule.setting_key, float("-inf"))
            if self._active.get(rule.setting_key) and now - last < REPEAT_SEC:
                continue
            self._active[rule.setting_key] = True
            self._last_sent[rule.setting_key] = now
            messages.append(rule.message(value, threshold, snapshot))
        return messages


def show_desktop_notification(text: str) -> None:
    """Уведомление рабочего стола через org.freedesktop.Notifications, без лишних пакетов."""
    def on_bus(_source, result):
        try:
            bus = Gio.bus_get_finish(result)
        except GLib.Error as e:
            logger.warning("Нет сессионной шины для уведомления: %s", e.message)
            return
        params = GLib.Variant("(susssasa{sv}i)", (APP_NAME, 0, "dialog-warning", tr('alert_title'), text,
                                                   [], {}, -1))
        bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                 "org.freedesktop.Notifications", "Notify", params, None, Gio.DBusCallFlags.NONE,
                 5000, None, None)

    Gio.bus_get(Gio.BusType.SESSION, None, on_bus)
