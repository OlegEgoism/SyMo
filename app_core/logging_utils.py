from __future__ import annotations

import logging
from pathlib import Path
from typing import IO, Optional

from .constants import LOG_FILE

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Настроить диагностический лог (stderr). Повторный вызов ничего не меняет."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(level=level, format=_LOG_FORMAT)


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
