from __future__ import annotations

import os
from constants import LOG_FILE


def rotate_log_if_needed(max_size_bytes: int) -> None:
    """Простейшая ротация: если лог > max_size_bytes — переименовать в .1 (перезаписать .1 при наличии)."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > max_size_bytes:
            bak = LOG_FILE.with_suffix(LOG_FILE.suffix + ".1")
            try:
                if bak.exists():
                    bak.unlink()
            except Exception:
                pass
            LOG_FILE.rename(bak)
    except Exception as e:
        print("Ошибка ротации лога:", e)
