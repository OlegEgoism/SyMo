# Project Structure (Schema Overview)

The SyMo system tray application is organized as a set of cooperating modules. The diagram below highlights the main
packages and their roles in the runtime flow.

```
SyMo/
├─ notifications/
│  ├─ __init__.py          # convenience exports for notifiers
│  ├─ telegram.py          # bot config, polling, commands, periodic status with metrics + click counts
│  └─ discord.py           # webhook config, periodic/test messages, shared persistence with UI dialog
│
├─ dialogs.py              # GTK settings dialog; export logs, reset counters, manage visibility/language/notifications
├─ power_control.py        # PowerControl actions and confirmation/scheduling dialogs
├─ system_usage.py         # psutil-based system metrics (temperature, CPU, RAM, SWAP, Disk, network, uptime)
├─ click_tracker.py        # thread-safe counters with increment/reset helpers for input events
├─ constants.py            # app names, supported languages, polling intervals, filesystem paths
├─ localization.py         # language selection utilities and translation wrapper
├─ language.py             # localized string dictionaries referenced by UI + notifications
│
├─ tests/                  # pytest suites (click tracking, localization consistency, Discord notifier)
│
├─ build.sh                # package/build helper
├─ uninstall-symo.sh       # cleanup helper
├─ requirements.txt        # Python dependencies (GTK/AppIndicator, psutil, requests, pynput, etc.)
├─ logo.png, img.png       # branding and README visuals
└─ README.md               # quickstart and usage overview
```
 