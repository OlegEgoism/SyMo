from __future__ import annotations

import logging
import math
import subprocess
import threading
import time
from enum import Enum
from typing import Callable, Optional

from gi.repository import Gio, GLib, Gtk

from .localization import tr
from .ui import mapped_or_none, show_message

logger = logging.getLogger(__name__)


class Action(Enum):
    POWER_OFF = "power_off"
    REBOOT = "reboot"
    LOCK = "lock"


def action_label(act: Action) -> str:
    return {
        Action.POWER_OFF: tr('power_off'),
        Action.REBOOT: tr('reboot'),
        Action.LOCK: tr('lock'),
    }.get(act, act.value)


# Сообщить об итоге тому, кто запросил действие удалённо (например, в Telegram).
# Вызывается в главном потоке и не должен ждать сеть.
RemoteNotifier = Callable[[str], None]

_COMMAND_TIMEOUT_SEC = 60
_DBUS_TIMEOUT_MS = 10_000
WARNING_BEFORE_SEC = 60
# Срок, пропущенный больше чем на столько, значит, что компьютер спал: действие
# не выполняется сразу после пробуждения, а откладывается с предупреждением.
_OVERDUE_THRESHOLD_SEC = 5
_OVERDUE_GRACE_SEC = 60
# Ответ кнопки «Отменить действие»: Escape и крестик дают DELETE_EVENT и только закрывают окно.
_RESPONSE_CANCEL_ACTION = 1
# Если после запроса выключения через менеджер сессии компьютер всё ещё работает,
# удалённому пользователю сообщается: возможно, приложение ждёт ответа на экране.
_SHUTDOWN_WATCHDOG_SEC = 180

# Выключение через менеджер сессии: приложения успевают сохранить данные или спросить
# пользователя. (имя на шине, путь, интерфейс, метод, (сигнатура, аргументы) или None)
_SESSION_MANAGER_CALLS = {
    Action.POWER_OFF: (
        ("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager",
         "RequestShutdown", None),
        ("org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown", "logoutAndShutdown", None),
        ("org.kde.ksmserver", "/KSMServer", "org.kde.KSMServerInterface", "logout", ("(iii)", (0, 2, 2))),
        ("org.xfce.SessionManager", "/org/xfce/SessionManager", "org.xfce.Session.Manager",
         "Shutdown", ("(b)", (True,))),
    ),
    Action.REBOOT: (
        ("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager",
         "RequestReboot", None),
        ("org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown", "logoutAndReboot", None),
        ("org.kde.ksmserver", "/KSMServer", "org.kde.KSMServerInterface", "logout", ("(iii)", (0, 1, 2))),
        ("org.xfce.SessionManager", "/org/xfce/SessionManager", "org.xfce.Session.Manager",
         "Restart", ("(b)", (True,))),
    ),
}


def _now() -> float:
    """Часы, которые идут и во время сна: срок таймера не сдвигается на время сна."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def run_command(cmd: list[str]) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=_COMMAND_TIMEOUT_SEC)
    except Exception as e:
        logger.warning("Ошибка выполнения команды %s: %s", " ".join(cmd), e)
        return False
    if proc.returncode == 0:
        return True
    err = (proc.stderr or proc.stdout or "").strip()
    logger.warning("Команда %s завершилась с кодом %s%s", " ".join(cmd), proc.returncode, f": {err}" if err else "")
    return False


def _bus_name_has_owner(bus: Gio.DBusConnection, name: str) -> bool:
    try:
        reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "NameHasOwner", GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"),
                              Gio.DBusCallFlags.NONE, _DBUS_TIMEOUT_MS, None)
        return bool(reply.unpack()[0])
    except GLib.Error:
        return False


def request_via_session_manager(act: Action) -> bool:
    """Попросить менеджер сессии (GNOME, KDE, XFCE) выключить или перезагрузить компьютер."""
    calls = _SESSION_MANAGER_CALLS.get(act)
    if not calls:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        logger.debug("Нет сессионной шины D-Bus: %s", e.message)
        return False
    for name, path, interface, method, args in calls:
        if not _bus_name_has_owner(bus, name):
            continue
        try:
            bus.call_sync(name, path, interface, method, GLib.Variant(*args) if args else None,
                          None, Gio.DBusCallFlags.NONE, _DBUS_TIMEOUT_MS, None)
            logger.info("%s: запрошено у менеджера сессии %s.%s", act.value, interface, method)
            return True
        except GLib.Error as e:
            logger.warning("Менеджер сессии %s не выполнил %s: %s", name, method, e.message)
    return False


def power_off() -> bool:
    return (request_via_session_manager(Action.POWER_OFF)
            or run_command(["loginctl", "poweroff"])
            or run_command(["systemctl", "poweroff"]))


def reboot() -> bool:
    return (request_via_session_manager(Action.REBOOT)
            or run_command(["loginctl", "reboot"])
            or run_command(["systemctl", "reboot"]))


def lock_screen() -> bool:
    return any(run_command(cmd) for cmd in (["loginctl", "lock-session"],
                                            ["gnome-screensaver-command", "-l"],
                                            ["xdg-screensaver", "lock"],
                                            ["dm-tool", "lock"]))


_ACTION_FUNCTIONS: dict[Action, Callable[[], bool]] = {
    Action.POWER_OFF: power_off,
    Action.REBOOT: reboot,
    Action.LOCK: lock_screen,
}


class PowerControl:
    def __init__(self):
        self.scheduled_action: Optional[Action] = None
        self._deadline: Optional[float] = None
        self._tick_id: Optional[int] = None
        self._warned = False
        self._notify_remote: Optional[RemoteNotifier] = None
        self._warning_dialog: Optional[Gtk.Dialog] = None
        self.current_dialog: Optional[Gtk.Dialog] = None
        self.parent_window: Optional[Gtk.Widget] = None

    def set_parent_window(self, parent: Optional[Gtk.Widget]) -> None:
        self.parent_window = mapped_or_none(parent)

    def power_off(self) -> None:
        self.run_action(Action.POWER_OFF)

    def reboot(self) -> None:
        self.run_action(Action.REBOOT)

    def lock_screen(self) -> None:
        self.run_action(Action.LOCK)

    def run_action(self, act: Action, notify_remote: Optional[RemoteNotifier] = None) -> None:
        """Выполнить действие в фоновом потоке: команда может ждать polkit или менеджер
        сессии, а главный поток GTK зависать не должен. О сбое сообщается в главном потоке."""
        def worker() -> None:
            try:
                ok = _ACTION_FUNCTIONS[act]()
            except Exception as e:
                logger.exception("Ошибка действия %s: %s", act.value, e)
                ok = False
            if not ok:
                GLib.idle_add(self._report_failure, act, notify_remote)
            elif notify_remote is not None and act in (Action.POWER_OFF, Action.REBOOT):
                GLib.idle_add(self._start_shutdown_watchdog, act, notify_remote)

        threading.Thread(target=worker, name=f"power-{act.value}", daemon=True).start()

    @staticmethod
    def _start_shutdown_watchdog(act: Action, notify_remote: RemoteNotifier) -> bool:
        def still_running() -> bool:
            notify_remote(f"⚠️ {tr('bot_power_still_running').format(action_label(act))}")
            return False

        GLib.timeout_add_seconds(_SHUTDOWN_WATCHDOG_SEC, still_running)
        return False

    def _report_failure(self, act: Action, notify_remote: Optional[RemoteNotifier]) -> bool:
        text = tr('action_failed').format(action_label(act))
        show_message(tr('error'), text, self.parent_window)
        if notify_remote is not None:
            notify_remote(f"❌ {text}")
        return False

    def _replace_current_dialog(self, dialog: Optional[Gtk.Dialog]) -> None:
        if self.current_dialog is not None and self.current_dialog is not dialog:
            try:
                self.current_dialog.destroy()
            except Exception:
                pass
        self.current_dialog = dialog

    def _forget_dialog(self, dialog: Gtk.Dialog) -> None:
        if self.current_dialog is dialog:
            self.current_dialog = None
        dialog.destroy()

    def confirm_action(self, _w, action_callback: Callable[[], None], message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=message,
        )
        dialog.set_title(tr('confirm_title'))
        self._replace_current_dialog(dialog)

        def on_response(d, response_id):
            self._forget_dialog(d)
            if response_id == Gtk.ResponseType.OK:
                action_callback()

        dialog.connect("response", on_response)
        dialog.show()

    def open_scheduler(self, *_):
        dialog = Gtk.Dialog(title=tr('scheduler'), transient_for=self.parent_window, flags=0)
        self._replace_current_dialog(dialog)
        box = dialog.get_content_area()
        box.set_border_width(10)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_label = Gtk.Label(label=tr('minutes'))
        time_label.set_xalign(0)
        time_spin = Gtk.SpinButton()
        time_spin.set_adjustment(Gtk.Adjustment(value=1, lower=1, upper=1440, step_increment=1))
        time_spin.set_numeric(True)
        time_spin.set_value(1)
        time_spin.set_size_request(150, -1)
        time_box.pack_start(time_label, True, True, 0)
        time_box.pack_start(time_spin, False, False, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_label_w = Gtk.Label(label=tr('action'))
        action_label_w.set_xalign(0)
        action_combo = Gtk.ComboBoxText()
        for act in Action:
            action_combo.append(act.value, action_label(act))
        action_combo.set_active_id((self.scheduled_action or Action.POWER_OFF).value)
        action_combo.set_size_request(150, -1)
        action_box.pack_start(action_label_w, True, True, 0)
        action_box.pack_start(action_combo, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)
        reset_b = Gtk.Button(label=tr('reset'))
        cancel_b = Gtk.Button(label=tr('cancel'))
        apply_b = Gtk.Button(label=tr('apply'))
        reset_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.REJECT))
        cancel_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.CANCEL))
        apply_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.OK))
        for btn in (reset_b, cancel_b, apply_b):
            btn_box.pack_start(btn, False, False, 0)

        box.add(time_box)
        box.add(action_box)
        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.add(btn_box)

        def on_response(d, response_id):
            minutes = time_spin.get_value_as_int()
            action_id = action_combo.get_active_id()
            self._forget_dialog(d)
            if response_id == Gtk.ResponseType.OK:
                act = Action(action_id)
                self.schedule(act, minutes)
                # За минуту до срока и так появится предупреждение с кнопкой отмены.
                if minutes > 1:
                    show_message(tr('scheduled'), tr('action_in_time').format(action_label(act), minutes),
                                 self.parent_window)
            elif response_id == Gtk.ResponseType.REJECT:
                self.cancel_by_user()
                show_message(tr('cancelled'), tr('cancelled_text'), self.parent_window)

        dialog.connect("response", on_response)
        dialog.show_all()

    def schedule(self, act: Action, minutes: int, notify_remote: Optional[RemoteNotifier] = None) -> None:
        """Запланировать действие. Предыдущее расписание полностью снимается.

        ``notify_remote`` получает сообщения о сбое и об отмене на компьютере.
        """
        previous_remote = self._notify_remote
        replaced = self.cancel_schedule()
        if replaced is not None and previous_remote is not None and previous_remote != notify_remote:
            previous_remote(tr('bot_action_rescheduled_locally').format(action_label(act), int(minutes)))
        self.scheduled_action = act
        self._deadline = _now() + int(minutes) * 60
        self._warned = False
        self._notify_remote = notify_remote
        # Проверка раз в секунду, а не один таймер на весь срок: таймеры GLib идут по
        # монотонным часам, которые стоят во время сна.
        self._tick_id = GLib.timeout_add_seconds(1, self._tick)
        self._tick()

    def cancel_schedule(self) -> Optional[Action]:
        """Снять расписание; вернуть отменённое действие или None, если его не было."""
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = None
        cancelled = self.scheduled_action
        self.scheduled_action = None
        self._deadline = None
        self._notify_remote = None
        self._close_warning()
        return cancelled

    def cancel_by_user(self) -> None:
        """Отмена на компьютере: сообщить тому, кто запланировал действие удалённо."""
        notify_remote = self._notify_remote
        cancelled = self.cancel_schedule()
        if cancelled is not None and notify_remote is not None:
            notify_remote(tr('bot_action_cancelled_locally').format(action_label(cancelled)))

    def remote_scheduled_action(self) -> Optional[Action]:
        """Действие, запланированное удалённо (например, из Telegram), или None."""
        return self.scheduled_action if self._notify_remote is not None else None

    def remaining_seconds(self) -> int:
        if self._deadline is None:
            return 0
        return max(0, math.ceil(self._deadline - _now()))

    def countdown_text(self) -> str:
        """Текст обратного отсчёта для трея; пустая строка, если ничего не запланировано."""
        if self.scheduled_action is None:
            return ""
        remaining = self.remaining_seconds()
        h, rem = divmod(remaining, 3600)
        m, s = divmod(rem, 60)
        return f"{action_label(self.scheduled_action)} — {h:02d}:{m:02d}:{s:02d}"

    def _tick(self) -> bool:
        act = self.scheduled_action
        if act is None or self._deadline is None:
            self._tick_id = None
            return False
        remaining = self._deadline - _now()
        if remaining <= -_OVERDUE_THRESHOLD_SEC:
            logger.info("Срок действия %s прошёл во время сна: откладываю на %s с", act.value, _OVERDUE_GRACE_SEC)
            self._deadline = _now() + _OVERDUE_GRACE_SEC
            self._warned = False
            remaining = _OVERDUE_GRACE_SEC
        if remaining <= 0:
            notify_remote = self._notify_remote
            self._tick_id = None  # источник удалит сам GLib: возвращаем False
            self.cancel_schedule()
            self.run_action(act, notify_remote)
            return False
        if not self._warned and remaining <= WARNING_BEFORE_SEC:
            self._warned = True
            self._show_warning(act)
        return True

    def _show_warning(self, act: Action) -> None:
        self._close_warning()
        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text=tr('action_in_1_min').format(action_label(act)),
        )
        dialog.set_title(tr('notification'))
        dialog.add_button(tr('cancel_action_button'), _RESPONSE_CANCEL_ACTION)
        self._warning_dialog = dialog

        def on_response(d, response_id):
            if self._warning_dialog is d:
                self._warning_dialog = None
            d.destroy()
            if response_id == _RESPONSE_CANCEL_ACTION and self.scheduled_action is act:
                self.cancel_by_user()

        dialog.connect("response", on_response)
        dialog.show()

    def _close_warning(self) -> None:
        dialog, self._warning_dialog = self._warning_dialog, None
        if dialog is not None:
            try:
                dialog.destroy()
            except Exception:
                pass

    def dispose(self) -> None:
        self.cancel_schedule()
        self._replace_current_dialog(None)
