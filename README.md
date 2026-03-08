# SyMo

<img src="logo.png" width="96" alt="SyMo logo" />

SyMo is a GTK-based Linux system tray monitor that displays live system metrics, provides quick power controls, and can send periodic status notifications to Telegram and Discord.

## Features

- Live system monitoring:
  - CPU load and temperature;
  - RAM and swap usage;
  - disk usage;
  - network speed (download/upload);
  - uptime;
  - keyboard and mouse activity counters.
- Configurable tray menu:
  - show/hide menu items;
  - reorder menu items by drag-and-drop in Settings.
- Per-metric graph windows (CPU, RAM, Swap, Disk, Network, Keyboard, Mouse).
- Power controls:
  - shutdown;
  - reboot;
  - lock screen;
  - delayed execution with scheduler/timer.
- Notifications:
  - Telegram bot integration;
  - Discord webhook integration.
- Multi-language interface.

## Supported UI Languages

- 🇷🇺 Russian (`ru`)
- 🇬🇧 English (`en`)
- 🇨🇳 Chinese (`cn`)
- 🇩🇪 German (`de`)
- 🇮🇹 Italian (`it`)
- 🇪🇸 Spanish (`es`)
- 🇹🇷 Turkish (`tr`)
- 🇫🇷 French (`fr`)

## Repository Structure

```text
SyMo/
├─ app.py                    # thin launcher
├─ app_core/                 # core application logic
│  ├─ app.py                 # runtime, tray, menu, graphs, updates
│  ├─ dialogs.py             # settings dialog
│  ├─ power_control.py       # power commands and timers
│  ├─ system_usage.py        # system metrics collection
│  ├─ click_tracker.py       # keyboard/mouse counters
│  ├─ localization.py        # i18n helpers
│  ├─ language.py            # translation dictionaries
│  ├─ constants.py           # constants and config/log paths
│  └─ logging_utils.py       # log rotation helpers
├─ notifications/
│  ├─ telegram.py            # Telegram notifier + command polling
│  └─ discord.py             # Discord webhook notifier
├─ tests/                    # pytest suites
├─ build.sh                  # Nuitka build (standalone + onefile)
├─ uninstall-symo.sh         # removes artifacts/desktop files/binaries
├─ requirements.txt
├─ logo.png
├─ img.png
└─ README.md
```

## Requirements

- Linux desktop environment with GTK3 + AppIndicator (or Ayatana AppIndicator).
- Python 3.10+ (recommended).

### Base system packages (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
  gnome-shell-extension-appindicator \
  build-essential libgirepository1.0-dev gir1.2-glib-2.0 \
  gobject-introspection pkg-config libcairo2-dev
```

### Python dependencies

```bash
pip install -r requirements.txt
```

## Run in Development Mode

```bash
python3 app.py
```

## Build

`build.sh` performs:

1. Nuitka `standalone` build;
2. attempted Nuitka `onefile` build;
3. launcher script generation;
4. artifact bundling into `SyMo-bundle/`;
5. desktop and autostart entry creation.

Run:

```bash
chmod +x build.sh
./build.sh
```

Check output:

```bash
ls -la SyMo-bundle
```

Typical artifacts (depending on onefile build success):

- `app.build`
- `app.dist`
- `app.onefile-build`
- `build_standalone`
- `SyMo-standalone`
- `SyMo-onefile`
- `SyMo-launch`
- `SyMo-run`

## Uninstall

```bash
chmod +x uninstall-symo.sh
./uninstall-symo.sh
```

The script removes:

- local build artifacts near the repository;
- desktop/autostart entries (`SyMo.desktop` and `symo.desktop`);
- possible installed SyMo binaries/directories.

## Tests

```bash
pytest -q
```

## Contact

- Author: [OlegEgoism](https://github.com/OlegEgoism)
- Repository: <https://github.com/OlegEgoism/SyMo>

<img src="img.png" width="560" alt="SyMo preview" />
