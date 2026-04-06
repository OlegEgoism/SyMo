# SyMo ([RU](README_RU.md))

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
  - Interactive controls in graph windows:
    - mouse wheel: horizontal zoom;
    - left mouse button drag: horizontal pan;
    - mouse hover: tooltip near cursor with timestamp and metric values for the nearest point.
- Power controls:
    - shutdown;
    - reboot;
    - lock screen;
    - delayed execution with scheduler/timer.
- Notifications:
    - Telegram bot integration;
    - Discord webhook integration.
  - Telegram bot commands:
    - `/status` — current system status;
    - `/screenshot` — take a desktop screenshot and send it to Telegram.
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

### Optional screenshot dependencies (for Telegram `/screenshot`)

SyMo tries multiple screenshot backends. Install at least one of them:

```bash
sudo apt install -y gnome-screenshot scrot grim imagemagick
```

> Notes:
> - On GNOME/X11, `gnome-screenshot` is usually enough.
> - On Wayland compositors (e.g., Sway), `grim` is commonly used.
> - `imagemagick` provides the `import` command fallback.

### Python dependencies

```bash
pip install -r requirements.txt
```

## Run in Development Mode

```bash
python3 app.py
```

## Telegram `/screenshot` Setup

1. Open **Settings → Notifications → Telegram**.
2. Fill in:
   - Bot token
   - Chat ID
3. Enable Telegram notifications.
4. Set **Screenshot quality**:
   - **Low** — smallest size, fastest upload;
   - **Medium** — balanced (recommended);
   - **Maximum** — best quality, larger file.
5. Click **Apply**.
6. In Telegram chat with your bot, send:

```text
/screenshot
```

The bot will capture the desktop and send the image to your configured chat.


## GNOME Extensions upload package

The repository now includes `gnome_extension/` with a minimal GNOME Shell extension (`metadata.json` and `extension.js`) that adds a panel launcher for SyMo.

Build the zip archive for <https://extensions.gnome.org/upload/>:

```bash
chmod +x package-gnome-extension.sh
./package-gnome-extension.sh
```

By default, the package is created at `dist/symo@olegegoism.github.io.zip`.

Before uploading, verify:
- UUID in `gnome_extension/metadata.json`;
- supported `shell-version` values;
- local install works (`gnome-extensions install --force dist/symo@olegegoism.github.io.zip`).

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

## Uninstall

```bash
chmod +x uninstall-symo.sh
./uninstall-symo.sh
```

## Tests

```bash
pytest -q
```

## Contact

- Author: [OlegEgoism](https://github.com/OlegEgoism)
- Repository: <https://github.com/OlegEgoism/SyMo>
- Telegram: [@OlegEgoism](https://t.me/OlegEgoism)
- Email: olegpustovalov220@gmail.com

<img src="img.png" width="960" alt="SyMo preview" />

## Video on YouTube:

[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/shorts/X1tlQ4XuLSM?feature=share)
