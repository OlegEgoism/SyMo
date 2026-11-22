from __future__ import annotations

import logging
from pathlib import Path
from typing import IO, Optional

from logging.handlers import RotatingFileHandler

from .constants import APP_LOG_FILE, LOG_FILE

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_APP_LOG_MAX_BYTES = 1024 * 1024


def setup_logging(level: int = logging.INFO) -> None:
    """Диагностический лог в stderr и в ~/.symo_app.log: из файла его можно сохранить
    в настройках и приложить к сообщению об ошибке. Повторный вызов ничего не меняет."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(level=level, format=_LOG_FORMAT)
    try:
        handler = RotatingFileHandler(APP_LOG_FILE, maxBytes=_APP_LOG_MAX_BYTES, backupCount=1, encoding="utf-8")
    except OSError as e:
        logging.getLogger(__name__).warning("Не удалось открыть %s: %s", APP_LOG_FILE, e)
        return
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)


class MetricsLogWriter:
    """Пишет строки метрик в открытый файл; ротация по позиции записи, без stat()."""

    def __init__(self, path: Path = LOG_FILE) -> None:
        self.path = Path(path)
        self._fh: Optional[IO[str]] = None

    def _open(self) -> IO[str]:
        if self._fh is None or self._fh.closed:
            self._fh = self.path.open("a", encoding="utf-8")
        return self._fh

    def write(self, line: str, max_bytes: int) -> None:
        fh = self._open()
        fh.write(line)
        fh.flush()
        if fh.tell() > max_bytes:
            self.rotate()

    def rotate(self) -> None:
        self.close()
        backup = self.path.with_suffix(self.path.suffix + ".1")
        try:
            if backup.exists():
                backup.unlink()
            if self.path.exists():
                self.path.rename(backup)
        except OSError as e:
            logging.getLogger(__name__).warning("Ошибка ротации лога: %s", e)

    def ensure_exists(self) -> None:
        if not self.path.exists():
            self.path.touch()

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
