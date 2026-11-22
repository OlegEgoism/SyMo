"""Запуск настоящего приложения: старт, повторный запуск, выход по сигналу.

Нужны дисплей (в CI — Xvfb) и dbus-run-session: тест поднимает собственную сессионную
шину и не мешает SyMo, который может работать у разработчика.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) or not shutil.which("dbus-run-session"),
    reason="нужны дисплей и dbus-run-session")


def test_app_starts_reopens_settings_and_quits(tmp_path):
    home, runtime = tmp_path / "home", tmp_path / "run"
    home.mkdir()
    runtime.mkdir(mode=0o700)
    primary_log, second_log = tmp_path / "primary.log", tmp_path / "second.log"
    script = f"""
"{sys.executable}" app.py > "{primary_log}" 2>&1 &
pid=$!
sleep 8
"{sys.executable}" app.py > "{second_log}" 2>&1
echo "second=$?"
sleep 2
kill -INT $pid
wait $pid
echo "primary=$?"
"""
    env = dict(os.environ, HOME=str(home), XDG_RUNTIME_DIR=str(runtime))
    result = subprocess.run(["dbus-run-session", "--", "sh", "-c", script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=90)
    primary, second = primary_log.read_text(), second_log.read_text()
    assert "Traceback" not in primary and "Traceback" not in second, primary + second
    assert "second=0" in result.stdout and "primary=0" in result.stdout, result.stdout
    assert "Повторный запуск SyMo" in primary
    assert (home / ".symo_settings.json").exists()
