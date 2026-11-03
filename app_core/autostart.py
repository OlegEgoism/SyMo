"""Автозапуск при входе в систему через XDG autostart (~/.config/autostart).

Пакет .deb ставит системный ярлык в /etc/xdg/autostart; пользователь отключает
его своим ярлыком с тем же именем и Hidden=true — так требует спецификация XDG.
"""
from __future__ import annotations

import configparser
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from .constants import APP_NAME

logger = logging.getLogger(__name__)

DESKTOP_FILE_NAME = f"{APP_NAME}.desktop"
_SECTION = "Desktop Entry"


def _user_autostart_file() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "autostart" / DESKTOP_FILE_NAME


def _system_autostart_file() -> Optional[Path]:
    config_dirs = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    for config_dir in config_dirs.split(":"):
        path = Path(config_dir) / "autostart" / DESKTOP_FILE_NAME
        if config_dir and path.is_file():
            return path
    return None


def _entry_active(path: Path) -> bool:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as e:
        logger.warning("Не удалось прочитать %s: %s", path, e)
        return False
    if not parser.has_section(_SECTION):
        return False
    entry = parser[_SECTION]
    return (entry.get("Hidden", "false").strip().lower() != "true"
            and entry.get("X-GNOME-Autostart-enabled", "true").strip().lower() != "false")


def is_enabled() -> bool:
    user_file = _user_autostart_file()
    if user_file.is_file():
        return _entry_active(user_file)
    system_file = _system_autostart_file()
    return system_file is not None and _entry_active(system_file)


def _quote(arg: str) -> str:
    if not any(ch in arg for ch in ' \t"\'\\$`'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def _app_root() -> Path:
    # Исходники: корень репозитория; сборка Nuitka: каталог app/ рядом с бинарником.
    return Path(__file__).resolve().parent.parent


def _launch_command() -> str:
    if "__compiled__" in globals():
        binary = Path(sys.argv[0]).resolve()
        launcher = binary.parent.parent / "symo"
        return _quote(str(launcher if launcher.is_file() else binary))
    return f"{_quote(sys.executable)} {_quote(str(_app_root() / 'app.py'))}"


def _desktop_entry() -> str:
    lines = [
        f"[{_SECTION}]",
        "Type=Application",
        f"Name={APP_NAME}",
        "Comment=System monitor in the tray",
        f"Exec={_launch_command()}",
    ]
    icon = _app_root() / "logo.png"
    if icon.is_file():
        lines.append(f"Icon={icon}")
    lines += [
        "Terminal=false",
        "StartupNotify=false",
        "X-GNOME-Autostart-enabled=true",
    ]
    return "\n".join(lines) + "\n"


def _hidden_entry() -> str:
    return f"[{_SECTION}]\nType=Application\nName={APP_NAME}\nHidden=true\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def set_enabled(enabled: bool) -> bool:
    """Включить или выключить автозапуск; False, если записать ярлык не удалось."""
    user_file = _user_autostart_file()
    system_file = _system_autostart_file()
    try:
        if system_file is not None and _entry_active(system_file):
            # Системный ярлык уже запускает SyMo: свой файл нужен только чтобы его скрыть.
            if enabled:
                user_file.unlink(missing_ok=True)
            else:
                _write_atomic(user_file, _hidden_entry())
        elif enabled:
            _write_atomic(user_file, _desktop_entry())
        else:
            user_file.unlink(missing_ok=True)
    except OSError as e:
        logger.error("Не удалось изменить автозапуск (%s): %s", user_file, e)
        return False
    return True
