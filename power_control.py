from __future__ import annotations

import os
from enum import Enum
from typing import Optional, TYPE_CHECKING

from gi.repository import GLib, Gtk

from localization import tr

if TYPE_CHECKING:  # pragma: no cover
    from app import SystemTrayApp


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


class PowerControl:
    def __init__(self, app: "SystemTrayApp"):
        self.app = app
        self.scheduled_action: Optional[Action] = None
        self.remaining_seconds = 0
        self._update_timer_id = None
        self._notify_timer_id = None
        self._action_timer_id = None
        self.current_dialog: Optional[Gtk.MessageDialog] = None
        self.parent_window: Optional[Gtk.Widget] = None

    def set_parent_window(self, parent: Optional[Gtk.Widget]) -> None:
        self.parent_window = parent if (parent and parent.get_mapped()) else None

    def _open_dialog(self, message: str, title: str = "", info: bool = True) -> Gtk.MessageDialog:
        if self.current_dialog:
            try:
                self.current_dialog.destroy()
            except Exception:
                pass
            self.current_dialog = None
        dialog = Gtk.MessageDialog(
            transient_for=self.parent_window,
            flags=0,
            message_type=Gtk.MessageType.INFO if info else Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK if info else Gtk.ButtonsType.OK_CANCEL,
            text=message
        )
        if title:
            dialog.set_title(title)
        self.current_dialog = dialog
        return dialog

    def _confirm_action(self, _w, action_callback, message: str):
        dialog = self._open_dialog(message, tr('confirm_title'), info=False)

        def on_response(d, response_id):
            if response_id == Gtk.ResponseType.OK and action_callback:
                action_callback()
            d.destroy()
            self.current_dialog = None

        dialog.connect("response", on_response)
        dialog.show()

    def _shutdown(self) -> None:
        try:
            if os.system("loginctl poweroff") != 0:
                os.system("systemctl poweroff")
        except Exception as e:
            print(f"Ошибка выключения: {e}")

    def _reboot(self) -> None:
        try:
            if os.system("loginctl reboot") != 0:
                os.system("systemctl reboot")
        except Exception as e:
            print(f"Ошибка перезагрузки: {e}")

    @staticmethod
    def _lock_screen() -> None:
        for c in ("loginctl lock-session",
                  "gnome-screensaver-command -l",
                  "xdg-screensaver lock",
                  "dm-tool lock"):
            if os.system(c) == 0:
                return

    def _open_settings(self, *_):
        dialog = Gtk.Dialog(
            title=tr('settings'),
            transient_for=self.parent_window,
            flags=0
        )
        self.current_dialog = dialog
        box = dialog.get_content_area()
        box.set_border_width(10)

        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_label = Gtk.Label(label=tr('minutes'))
        time_label.set_xalign(0)
        adjustment = Gtk.Adjustment(value=1, lower=1, upper=1440, step_increment=1)
        time_spin = Gtk.SpinButton()
        time_spin.set_adjustment(adjustment)
        time_spin.set_numeric(True)
        time_spin.set_value(1)
        time_spin.set_size_request(150, -1)
        time_box.pack_start(time_label, True, True, 0)
        time_box.pack_start(time_spin, False, False, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_label_w = Gtk.Label(label=tr('action'))
        action_label_w.set_xalign(0)
        action_combo = Gtk.ComboBoxText()
        action_combo.append(Action.POWER_OFF.value, action_label(Action.POWER_OFF))
        action_combo.append(Action.REBOOT.value, action_label(Action.REBOOT))
        action_combo.append(Action.LOCK.value, action_label(Action.LOCK))
        action_combo.set_active(0)
        action_combo.set_size_request(150, -1)
        action_box.pack_start(action_label_w, True, True, 0)
        action_box.pack_start(action_combo, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)
        apply_b = Gtk.Button(label=tr('apply'))
        cancel_b = Gtk.Button(label=tr('cancel'))
        reset_b = Gtk.Button(label=tr('reset'))
        apply_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.OK))
        cancel_b.connect("clicked", lambda *_: dialog.response(Gtk.ResponseType.CANCEL))
        reset_b.connect("clicked", self._reset_action_button)
        btn_box.pack_start(reset_b, False, False, 0)
        btn_box.pack_start(cancel_b, False, False, 0)
        btn_box.pack_start(apply_b, False, False, 0)

        box.add(time_box)
        box.add(action_box)
        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.add(btn_box)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            minutes = time_spin.get_value_as_int()
            action_id = action_combo.get_active_id()
            if minutes <= 0:
                self._show_message(tr('error'), tr('error_minutes_positive'))
                dialog.destroy()
                self.current_dialog = None
                return
            act = Action(action_id)
            self.scheduled_action = act
            self.remaining_seconds = minutes * 60

            if minutes > 1:
                self._notify_timer_id = GLib.timeout_add_seconds(
                    (minutes - 1) * 60, self._notify_before_action, act
                )
            self._action_timer_id = GLib.timeout_add_seconds(
                self.remaining_seconds, self._delayed_action, act
            )
            if self._update_timer_id:
                GLib.source_remove(self._update_timer_id)
            self._update_timer_id = GLib.timeout_add_seconds(1, self._update_indicator_label)

            self._show_message(tr('scheduled'), tr('action_in_time').format(action_label(act), minutes))

        dialog.destroy()
        self.current_dialog = None

    def _reset_action_button(self, *_):
        for tid in ("_update_timer_id", "_notify_timer_id", "_action_timer_id"):
            _id = getattr(self, tid, None)
            if _id:
                GLib.source_remove(_id)
                setattr(self, tid, None)
        self.scheduled_action = None
        self.remaining_seconds = 0
        self.app.indicator.set_label("", "")
        self._show_message(tr('cancelled'), tr('cancelled_text'))

    def _notify_before_action(self, act: Action) -> bool:
        self._notify_timer_id = None
        self._show_message(tr('notification'), tr('action_in_1_min').format(action_label(act)))
        return False

    def _update_indicator_label(self) -> bool:
        if self.remaining_seconds <= 0:
            self.app.indicator.set_label("", "")
            return False
        h = self.remaining_seconds // 3600
        m = (self.remaining_seconds % 3600) // 60
        s = self.remaining_seconds % 60
        self.app.indicator.set_label(f"  {action_label(self.scheduled_action)} — {h:02d}:{m:02d}:{s:02d}", "")
        self.remaining_seconds -= 1
        return True

    def _delayed_action(self, act: Action) -> bool:
        self._action_timer_id = None
        self.app.indicator.set_label("", "")
        self.scheduled_action = None
        self.remaining_seconds = 0
        if self._update_timer_id:
            GLib.source_remove(self._update_timer_id)
            self._update_timer_id = None
        if act == Action.POWER_OFF:
            self._shutdown()
        elif act == Action.REBOOT:
            self._reboot()
        elif act == Action.LOCK:
            self._lock_screen()
        return False

    def _show_message(self, title: str, message: str):
        d = self._open_dialog(message, title, info=True)
        d.run()
        d.destroy()
        self.current_dialog = None
