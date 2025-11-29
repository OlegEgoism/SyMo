from __future__ import annotations

from pathlib import Path

SUPPORTED_LANGS = ['ru', 'en', 'cn', 'de', 'it', 'es', 'tr', 'fr']
APP_ID = "SystemMonitor"
APP_NAME = "SyMo"
ICON_FALLBACK = "system-run-symbolic"
TIME_UPDATE_SEC = 1  # частота обновления UI/логики

HOME = Path.home()
LOG_FILE = HOME / ".symo_log.txt"
SETTINGS_FILE = HOME / ".symo_settings.json"
TELEGRAM_CONFIG_FILE = HOME / ".symo_telegram.json"
DISCORD_CONFIG_FILE = HOME / ".symo_discord.json"
