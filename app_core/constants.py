from __future__ import annotations

from pathlib import Path

SUPPORTED_LANGS = ['ru', 'en', 'cn', 'de', 'it', 'es', 'tr', 'fr']
APP_ID = "SystemMonitor"
APP_NAME = "SyMo"
ICON_FALLBACK = "system-run-symbolic"
TIME_UPDATE_SEC = 1
GRAPH_HISTORY_MINUTES_DEFAULT = 5
GRAPH_HISTORY_MINUTES_MIN = 1
GRAPH_HISTORY_MINUTES_MAX = 480

HOME = Path.home()
LOG_FILE = HOME / ".symo_log.txt"
SETTINGS_FILE = HOME / ".symo_settings.json"
TELEGRAM_CONFIG_FILE = HOME / ".symo_telegram.json"
DISCORD_CONFIG_FILE = HOME / ".symo_discord.json"

MENU_ORDER_DEFAULT = [
    'cpu',
    'ram',
    'swap',
    'disk',
    'net',
    'keyboard_clicks',
    'mouse_clicks',
    'uptime',
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

LOG_MAX_MB_MIN = 1
LOG_MAX_MB_MAX = 1024
