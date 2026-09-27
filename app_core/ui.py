"""Общие GTK-помощники."""
from __future__ import annotations

from typing import Optional

from gi.repository import Gtk


def mapped_or_none(widget: Optional[Gtk.Widget]) -> Optional[Gtk.Widget]:
    return widget if (widget is not None and widget.get_mapped()) else None


def show_message(title: str, message: str, parent: Optional[Gtk.Widget] = None,
                 message_type: Gtk.MessageType = Gtk.MessageType.INFO) -> Gtk.MessageDialog:
    """Показать информационное окно без вложенного цикла событий (без dialog.run())."""
    dialog = Gtk.MessageDialog(
        transient_for=mapped_or_none(parent),
        flags=0,
        message_type=message_type,
        buttons=Gtk.ButtonsType.OK,
        text=message,
    )
    dialog.set_title(title)
    dialog.connect("response", lambda d, _r: d.destroy())
    dialog.show()
    return dialog
