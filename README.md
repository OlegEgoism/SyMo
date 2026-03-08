# SyMo

<img src="logo.png" width="96" alt="SyMo logo" />

SyMo is a GTK-based Linux system tray utility that shows real-time system metrics, supports quick power actions, and can send periodic notifications to Telegram/Discord.

## Features

- Real-time monitoring:
  - CPU usage + temperature;
  - RAM and SWAP;
  - disk usage;
  - network speed (download/upload);
  - uptime;
  - keyboard and mouse click counters.
- Tray context menu with flexible visibility settings.
- Graph windows on metric click (CPU, RAM, SWAP, Disk, Network, Keyboard, Mouse).
- Power actions:
  - power off;
  - reboot;
  - lock screen;
  - delayed execution with timer.
- Notifications:
  - Telegram bot;
  - Discord webhook.
- Interface localization.

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

- Linux desktop environment with GTK3/AppIndicator (or Ayatana AppIndicator).
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

## Configuration Files and Log

The app uses files in the user home directory:

- `~/.symo_settings.json` — display/behavior settings;
- `~/.symo_telegram.json` — Telegram settings;
- `~/.symo_discord.json` — Discord settings;
- `~/.symo_log.txt` — metrics log.

## Build

The `build.sh` script performs:

1. `standalone` build via Nuitka;
2. attempted `onefile` build;
3. launcher script generation;
4. artifact bundling into `SyMo-bundle/`;
5. desktop entry + autostart entry creation.

Run:

```bash
chmod +x build.sh
./build.sh
```

Check output:

```bash
ls -la SyMo-bundle
```

Expected artifacts (depending on onefile build success):

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
