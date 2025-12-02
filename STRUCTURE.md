# Project Structure

This document outlines the main modules and responsibilities of the SyMo system tray application.

## Top-Level Entry Point
- **`app.py`** – Runs the GTK-based `SystemTrayApp` that creates the tray indicator, composes the menu, coordinates power controls, and wires notifications. It loads persisted visibility settings, manages keyboard/mouse listeners, and handles periodic UI updates and ping actions.

## Configuration and Localization
- **`constants.py`** – Centralizes application identifiers, supported languages, update intervals, and filesystem paths for log/settings/notification configuration files.
- **`localization.py`** – Provides translation helpers (`tr`, `set_language`, `detect_system_language`) and tracks the active language code.
- **`language.py`** – Defines localized string dictionaries keyed by language; referenced throughout UI construction and notifications.

## UI Components
- **`dialogs.py`** – Implements the GTK-based `SettingsDialog`, which exposes visibility toggles, logging options, language selection, and notification settings, plus helpers to export logs and reset click counters.
- **`power_control.py`** – Supplies `PowerControl` for shutdown, reboot, and lock actions, confirmation dialogs, and a scheduler dialog for delayed actions.

## Monitoring and Metrics
- **`system_usage.py`** – Wraps `psutil` helpers to report CPU temperature/usage, RAM/SWAP/Disk consumption, network throughput, and system uptime.
- **`click_tracker.py`** – Thread-safe counters with increment/reset helpers for keyboard and mouse events; used by the tray and notifications.

## Notifications
- **`notifications/telegram.py`** – Manages Telegram bot configuration, polling, command handling, and periodic status messages with system metrics and click counters.
- **`notifications/discord.py`** – Sends periodic Discord webhook updates and test messages based on saved configuration; shares settings persistence with the UI dialog.
- **`notifications/__init__.py`** – Convenience exports for notifier classes.

## Tests
- **`tests/`** – Pytest suite covering click tracking, localization key consistency, and Discord notifier behavior.

## Supporting Scripts and Assets
- **`build.sh` / `uninstall-symo.sh`** – Packaging and cleanup scripts for deployment.
- **`requirements.txt`** – Python dependencies (GTK/AppIndicator, psutil, requests, pynput, etc.).
- **`logo.png` / `img.png`** – Branding and README visuals.

## Run Pipeline
- Launch the application via `python3 app.py` after installing system dependencies and Python requirements. Build and uninstall helper scripts are available for packaged distributions.