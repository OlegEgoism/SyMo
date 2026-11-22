from __future__ import annotations

from pathlib import Path

from .language import LANGUAGES

# Языки и их флаги описаны в одном месте — language.py.
SUPPORTED_LANGS = list(LANGUAGES)
APP_ID = "SystemMonitor"
APP_NAME = "SyMo"
APP_VERSION = "1.2.0"
# Имя на сессионной шине D-Bus: по нему расширение SyMo Launcher понимает,
# что приложение уже запущено, и скрывает свою кнопку.
DBUS_NAME = "io.github.olegegoism.SyMo"
ICON_FALLBACK = "system-run-symbolic"
TIME_UPDATE_SEC = 1
GRAPH_HISTORY_MINUTES_DEFAULT = 5
GRAPH_HISTORY_MINUTES_MIN = 1
GRAPH_HISTORY_MINUTES_MAX = 480

_HOME = Path.home()
LOG_FILE = _HOME / ".symo_log.txt"
SETTINGS_FILE = _HOME / ".symo_settings.json"
TELEGRAM_CONFIG_FILE = _HOME / ".symo_telegram.json"
DISCORD_CONFIG_FILE = _HOME / ".symo_discord.json"

MENU_ORDER_DEFAULT = [
    'cpu',
    'ram',
    'swap',
    'disk',
    'net',
    'keyboard_clicks',
    'mouse_clicks',
    'uptime',
    'battery',
    'gpu',
    'show_power_off',
    'show_reboot',
    'show_lock',
    'show_timer',
    'ping_network',
    'show_system_info',
]

POLL_INTERVAL_DEFAULT_SEC = 1
POLL_INTERVAL_MIN_SEC = 1
POLL_INTERVAL_MAX_SEC = 60
POLL_INTERVAL_SETTING_KEYS = (
    'tray_cpu_interval_sec',
    'tray_ram_interval_sec',
    'cpu_interval_sec',
    'ram_interval_sec',
    'net_interval_sec',
    'disk_interval_sec',
    'swap_interval_sec',
)

GRAPH_LINE_COLOR_FALLBACK = '#36c7ed'
GRAPH_COLOR_DEFAULTS = {
    'graph_line_color_cpu': '#19ccff',
    'graph_line_color_temp': '#ff6633',
    'graph_line_color_ram': '#59ff59',
    'graph_line_color_swap': '#f28cff',
    'graph_line_color_disk': '#59b8ff',
    'graph_line_color_net_recv': '#40e65a',
    'graph_line_color_net_sent': '#ffbf33',
    'graph_line_color_keyboard': '#ffd93f',
    'graph_line_color_mouse': '#66e6ff',
}

APP_LOG_FILE = _HOME / ".symo_app.log"
PING_HOST_DEFAULT = "8.8.8.8"
LOG_INTERVAL_DEFAULT_SEC = 60
LOG_INTERVAL_MIN_SEC = 1
LOG_INTERVAL_MAX_SEC = 3600
# Пороги оповещений по умолчанию; 0 — выключено.
ALERT_DEFAULTS = {'alert_cpu_temp_c': 90, 'alert_ram_percent': 95, 'alert_disk_percent': 95}

LOG_MAX_MB_MIN = 1
LOG_MAX_MB_MAX = 1024
