from __future__ import annotations

import logging
import math
import subprocess
import time
from enum import Enum
from typing import Callable, Optional

from gi.repository import GLib, Gtk

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


def run_command(cmd: list[str]) -> bool:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as e:
        logger.warning("Ошибка выполнения команды %s: %s", " ".join(cmd), e)
        return False
    if proc.returncode == 0:
        return True
    err = (proc.stderr or proc.stdout or "").strip()
    logger.warning("Команда %s завершилась с кодом %s%s", " ".join(cmd), proc.returncode, f": {err}" if err else "")
    return False


class PowerControl:
    def __init__(self):
        self.scheduled_action: Optional[Action] = None
        self._deadline: Optional[float] = None
        self._notify_timer_id: Optional[int] = None
        self._action_timer_id: Optional[int] = None
        self.current_dialog: Optional[Gtk.Dialog] = None
        self.parent_window: Optional[Gtk.Widget] = None

    def set_parent_window(self, parent: Optional[Gtk.Widget]) -> None:
        self.parent_window = mapped_or_none(parent)

    @staticmethod
    def power_off() -> None:
        if not run_command(["loginctl", "poweroff"]):
            run_command(["systemctl", "poweroff"])

    @staticmethod
    def reboot() -> None:
        if not run_command(["loginctl", "reboot"]):
            run_command(["systemctl", "reboot"])

    @staticmethod
    def lock_screen() -> None:
        for cmd in (["loginctl", "lock-session"],
                    ["gnome-screensaver-command", "-l"],
                    ["xdg-screensaver", "lock"],
                    ["dm-tool", "lock"]):
            if run_command(cmd):
                return

    def run_action(self, act: Action) -> None:
        {
            Action.POWER_OFF: self.power_off,
            Action.REBOOT: self.reboot,
            Action.LOCK: self.lock_screen,
        }[act]()

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
        dialog = Gtk.Dialog(title=tr('settings'), transient_for=self.parent_window, flags=0)
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
                show_message(tr('scheduled'), tr('action_in_time').format(action_label(act), minutes), self.parent_window)
            elif response_id == Gtk.ResponseType.REJECT:
                self.cancel_schedule()
                show_message(tr('cancelled'), tr('cancelled_text'), self.parent_window)

        dialog.connect("response", on_response)
        dialog.show_all()

    def schedule(self, act: Action, minutes: int) -> None:
        """Запланировать действие. Предыдущее расписание полностью снимается."""
        self.cancel_schedule()
        seconds = int(minutes) * 60
        self.scheduled_action = act
        self._deadline = time.monotonic() + seconds
        if minutes > 1:
            self._notify_timer_id = GLib.timeout_add_seconds(seconds - 60, self._notify_before_action, act)
        self._action_timer_id = GLib.timeout_add_seconds(seconds, self._delayed_action, act)

    def cancel_schedule(self) -> None:
        for attr in ("_notify_timer_id", "_action_timer_id"):
            source_id = getattr(self, attr)
            if source_id:
                GLib.source_remove(source_id)
                setattr(self, attr, None)
        self.scheduled_action = None
        self._deadline = None

    def remaining_seconds(self) -> int:
        if self._deadline is None:
            return 0
        return max(0, math.ceil(self._deadline - time.monotonic()))

    def countdown_text(self) -> str:
        """Текст обратного отсчёта для трея; пустая строка, если ничего не запланировано."""
        if self.scheduled_action is None:
            return ""
        remaining = self.remaining_seconds()
        h, rem = divmod(remaining, 3600)
        m, s = divmod(rem, 60)
        return f"{action_label(self.scheduled_action)} — {h:02d}:{m:02d}:{s:02d}"

    def _notify_before_action(self, act: Action) -> bool:
        self._notify_timer_id = None
        show_message(tr('notification'), tr('action_in_1_min').format(action_label(act)), self.parent_window)
        return False

    def _delayed_action(self, act: Action) -> bool:
        self._action_timer_id = None
        self.cancel_schedule()
        self.run_action(act)
        return False

    def dispose(self) -> None:
        self.cancel_schedule()
        self._replace_current_dialog(None)
