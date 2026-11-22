"""Запуск процесса SyMo: один экземпляр на сеанс, повторный запуск открывает настройки."""
from __future__ import annotations

import fcntl
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import IO, Any, Dict, Optional

from gi.repository import Gio, Gtk

from .app import APP_INDICATOR_PACKAGE, AppInd, SystemTrayApp
from .constants import APP_NAME, APP_VERSION, DBUS_NAME, SETTINGS_FILE
from .localization import detect_system_language, set_language, tr
from .logging_utils import setup_logging
from .settings import load_settings

logger = logging.getLogger(__name__)


def _acquire_single_instance_lock() -> Optional[IO[str]]:
    """Не дать запустить второй экземпляр (второй значок в трее и второй Telegram-бот)."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        lock_path = Path(runtime_dir) / f"{APP_NAME.lower()}.lock"
    else:
        # Общий /tmp: файл с uid, чтобы не столкнуться с блокировкой другого пользователя.
        lock_path = Path(tempfile.gettempdir()) / f"{APP_NAME.lower()}-{os.getuid()}.lock"
    try:
        lock_file = open(lock_path, "w")
    except OSError as e:
        logger.warning("Не удалось открыть файл блокировки %s: %s", lock_path, e)
        # Работаем без защиты от второго экземпляра, но запускаемся.
        return open(os.devnull, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def _report_missing_app_indicator() -> None:
    set_language(load_settings(SETTINGS_FILE).get('language') or detect_system_language())
    command = f"sudo apt install {APP_INDICATOR_PACKAGE}"
    logger.error("Не найдена библиотека AppIndicator. Установите: %s", command)
    dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                               text=tr('appindicator_missing').format(command))
    dialog.set_title(APP_NAME)
    dialog.run()
    dialog.destroy()


def main() -> None:
    if "--version" in sys.argv[1:]:
        print(f"{APP_NAME} {APP_VERSION}")
        return
    setup_logging()
    logger.info("%s %s", APP_NAME, APP_VERSION)

    # Gtk.Application владеет именем DBUS_NAME на сессионной шине: по нему расширение
    # SyMo Launcher видит, что SyMo запущен. Повторный запуск (из меню, командой symo)
    # не стартует второй экземпляр, а передаёт «activate» уже работающему — тот
    # открывает настройки.
    application = Gtk.Application(
        application_id=DBUS_NAME,
        flags=getattr(Gio.ApplicationFlags, "DEFAULT_FLAGS", Gio.ApplicationFlags.FLAGS_NONE))
    state: Dict[str, Any] = {}

    def on_startup(app: Gtk.Application) -> None:
        # Файл блокировки — на случай второго графического сеанса того же пользователя:
        # у него своя шина D-Bus, но второй Telegram-бот не нужен.
        lock = _acquire_single_instance_lock()
        if lock is None:
            logger.info("%s уже запущен в другом сеансе", APP_NAME)
            return
        if AppInd is None:
            _report_missing_app_indicator()
            state['exit_code'] = 1
            return
        tray = SystemTrayApp(app)
        state.update(lock=lock, tray=tray)
        app.hold()
        tray.start()

    def on_activate(_app: Gtk.Application) -> None:
        tray = state.get('tray')
        if tray is None:
            return
        if not state.get('started'):
            state['started'] = True  # первая активация — это сам запуск
            return
        logger.info("Повторный запуск %s: открываю настройки", APP_NAME)
        tray.show_settings()

    application.connect("startup", on_startup)
    application.connect("activate", on_activate)
    status = application.run([sys.argv[0]])
    if state.get('lock'):
        state['lock'].close()
    if state.get('exit_code') or status:
        raise SystemExit(state.get('exit_code') or status)
