# Project Structure (Schema Overview)

The SyMo repository is now grouped so core application logic lives under one folder (`app_core/`),
while documentation and external notification adapters remain in dedicated top-level directories.

```
SyMo/
├─ app_core/               # core application package
│  ├─ __init__.py
│  ├─ app.py               # SystemTrayApp runtime, menu wiring, periodic updates
│  ├─ dialogs.py           # GTK settings dialog; log export, reset counters, notification settings
│  ├─ power_control.py     # power actions + confirmation/scheduling dialogs
│  ├─ system_usage.py      # psutil-based system metrics (temp, CPU, RAM/SWAP, disk, network, uptime)
│  ├─ click_tracker.py     # thread-safe keyboard/mouse counters
│  ├─ constants.py         # app constants, paths, defaults, language list
│  ├─ localization.py      # translation helpers and language selection
│  ├─ language.py          # localized string dictionaries
│  └─ logging_utils.py     # log rotation utilities
│
├─ notifications/
│  ├─ __init__.py          # convenience exports
│  ├─ telegram.py          # Telegram notifier config, polling, command handling
│  └─ discord.py           # Discord webhook notifier config + send logic
│
├─ tests/                  # pytest suites
├─ app.py                  # thin launcher for app_core.app
├─ build.sh                # build helper
├─ uninstall-symo.sh       # uninstall helper
├─ requirements.txt        # Python dependencies
├─ logo.png, img.png       # branding and README visuals
└─ README.md               # quickstart and usage overview
```
