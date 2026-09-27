# SyMo ([RU](README_RU.md))

<img src="logo.png" width="96" alt="SyMo logo" />

SyMo is a lightweight GTK Linux tray app for monitoring system metrics, controlling power actions, and sending notifications to Telegram/Discord.

## Minimal Project Description

- Tray monitor for Linux desktop (CPU/RAM/Swap/Disk/Network/Uptime).
- Quick power actions: shutdown, reboot, lock, timer.
- Notifications from Discord, Telegram.

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
│  ├─ app.py                 # runtime: tray, menu, update loop, shutdown
│  ├─ graphs.py              # declarative graph specs + single GraphWindow
│  ├─ graph_math.py          # zoom/pan/decimation logic (no GTK)
│  ├─ history.py             # thread-safe metrics history for graphs
│  ├─ settings.py            # settings defaults, sanitizing, atomic JSON writes
│  ├─ dialogs.py             # settings dialog
│  ├─ power_control.py       # power commands and scheduler
│  ├─ system_usage.py        # system metrics collection + MetricsSnapshot
│  ├─ click_tracker.py       # keyboard/mouse counters
│  ├─ localization.py        # i18n helpers
│  ├─ language.py            # translation dictionaries
│  ├─ constants.py           # constants and config/log paths
│  ├─ ui.py                  # shared GTK helpers
│  └─ logging_utils.py       # logging setup and metrics log writer
├─ notifications/
│  ├─ base.py                # retries, status formatting, background dispatcher
│  ├─ telegram.py            # Telegram notifier + command polling
│  └─ discord.py             # Discord webhook notifier
├─ gnome_extension/          # SyMo Launcher for GNOME Shell
│  ├─ gnome-42-44/           # legacy format (Ubuntu 22.04)
│  └─ gnome-45/              # ES modules (Ubuntu 24.04 and newer)
├─ build.sh                  # release build: app archive + extension zips
├─ install.sh                # per-user installer shipped in the release archive
├─ uninstall-symo.sh         # removes SyMo (--purge also removes settings)
├─ package-gnome-extension.sh
├─ requirements.txt          # runtime dependencies
├─ requirements-build.txt    # build dependencies (Nuitka)
├─ LICENSE                   # GPL-2.0
├─ logo.png
├─ img.png
└─ README.md
```

## Supported systems

| Ubuntu | GNOME Shell | Python |
|---|---|---|
| 22.04 LTS | 42 | 3.10 |
| 24.04 LTS | 46 | 3.12 |
| 24.10 / 25.04 / 25.10 / 26.04 | 47 / 48 / 49 / 50 | 3.12+ |

The tray icon needs AppIndicator support. Ubuntu ships it by default
(the "Ubuntu AppIndicators" extension); on vanilla GNOME install
`gnome-shell-extension-appindicator`.

## Install (release archive)

Download `SyMo-<version>-linux-x86_64.tar.gz` from GitHub Releases, then:

```bash
sudo apt install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
tar xzf SyMo-*-linux-x86_64.tar.gz
./SyMo-*-linux-x86_64/install.sh
```

The app is installed to `~/.local/opt/SyMo`, gets a menu entry, the `symo`
command and autostart on login (`--no-autostart` to disable).

Optional tools for the Telegram `/screenshot` command:

```bash
sudo apt install gnome-screenshot scrot grim imagemagick
```

### GNOME Shell extension

[![GNOME Extensions](https://img.shields.io/badge/GNOME_Extensions-SyMo_Launcher-4A86CF?style=for-the-badge&logo=gnome&logoColor=white)](https://extensions.gnome.org/extension/9526/symo-launcher/)

[SyMo Launcher](https://extensions.gnome.org/extension/9526/symo-launcher/) adds a
panel button with **Open SyMo** and **Project page**. Install the SyMo app first
(see above): extensions.gnome.org does not allow extensions to ship programs.

The button is shown only while SyMo is not running. Once SyMo starts, only its own
tray icon stays on the panel; when SyMo quits, the button comes back.

| GNOME Shell | Ubuntu | Extension archive |
|---|---|---|
| 42–44 | 22.04 | `symo-launcher-gnome-42-44.shell-extension.zip` |
| 45–50 | 24.04, 24.10, 25.04, 25.10, 26.04 | `symo-launcher-gnome-45.shell-extension.zip` |

Check your version with `gnome-shell --version`.

**Extension Manager app** (easiest):

```bash
sudo apt install gnome-shell-extension-manager
```

Open *Extension Manager* → *Browse* → search for **SyMo Launcher** → *Install*.

**Web browser:** install the browser connector (`chrome-gnome-shell` on Ubuntu 22.04,
`gnome-browser-connector` on 24.04 and newer) and the *GNOME Shell integration*
add-on for Firefox or Chrome, then open the
[extension page](https://extensions.gnome.org/extension/9526/symo-launcher/) and
switch it on.

**Manual install:** if the site shows *INCOMPATIBLE* for your GNOME version,
download the matching archive from GitHub Releases and run:

```bash
gnome-extensions install --force symo-launcher-gnome-*.shell-extension.zip
```

Log out and back in (required on Wayland), then enable it:

```bash
gnome-extensions enable symo@olegegoism.github.io
```

## Uninstall

```bash
~/.local/opt/SyMo/uninstall-symo.sh           # keep settings and tokens
~/.local/opt/SyMo/uninstall-symo.sh --purge   # remove everything
```

## Run from source

```bash
sudo apt install python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  gir1.2-ayatanaappindicator3-0.1
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

`--system-site-packages` reuses PyGObject and pycairo from apt, so nothing has to
be compiled and the same steps work on every supported Ubuntu version.

## Build a release

Build on Ubuntu 22.04: the binary depends on glibc and runs on that version and
all newer ones.

```bash
sudo apt install build-essential patchelf
.venv/bin/pip install -r requirements-build.txt
./build.sh
```

Output in `dist/`:

- `SyMo-<version>-linux-<arch>.tar.gz` and `.sha256` — attach to a GitHub release;
- `symo-launcher-gnome-42-44.shell-extension.zip` and
  `symo-launcher-gnome-45.shell-extension.zip` — upload both to extensions.gnome.org
  as separate versions of the same extension, and attach them to the GitHub release
  for manual installation.

The version is set in `app_core/constants.py` (`APP_VERSION`); the extension
version is `version-name` in `gnome_extension/*/metadata.json`.

## License

Copyright © 2025–2026 OlegEgoism.

SyMo and the SyMo Launcher extension are free software, licensed under the
GNU General Public License v2.0 or later (GPL-2.0-or-later). See [LICENSE](LICENSE).

## Contact

- Author: [OlegEgoism](https://github.com/OlegEgoism)
- Repository: <https://github.com/OlegEgoism/SyMo>
- Telegram: [@OlegEgoism](https://t.me/OlegEgoism)
- Email: olegpustovalov220@gmail.com

<img src="img.png" width="960" alt="SyMo preview" />

## Video on YouTube:

[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/shorts/X1tlQ4XuLSM?feature=share)
[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtu.be/zvdoo9JA88k)
