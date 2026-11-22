"""Тесты не трогают настоящие файлы пользователя: HOME подменяется до импорта
app_core (пути настроек вычисляются при импорте)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["HOME"] = tempfile.mkdtemp(prefix="symo-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")

from app_core.localization import set_language  # noqa: E402

set_language("en")
