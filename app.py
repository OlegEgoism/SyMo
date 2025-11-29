from __future__ import annotations
import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppInd
except (ValueError, ImportError):
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppInd
