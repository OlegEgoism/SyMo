# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SyMo (System Monitor) is a Python-based GTK system monitoring application with a system tray interface. It provides real-time system metrics monitoring (CPU, RAM, disk, network) and power management features with multi-language support and external notifications via Telegram and Discord.

## Architecture

### Core Components
- `app.py`: Main application (~1154 lines) containing the GTK interface and system tray implementation
- `language.py`: Multi-language support with translations for Russian, English, Chinese, and German

### Key Classes
- `SystemTrayApp`: Main application class handling the GTK system tray interface
- `SystemUsage`: Static methods for gathering system metrics (CPU, RAM, disk, network, uptime)
- `TelegramNotifier`: Handles Telegram bot notifications
- `DiscordNotifier`: Handles Discord webhook notifications

### Dependencies (from requirements.txt)
- `psutil==5.9.8`: System and process monitoring
- `pycairo==1.26.0`: 2D graphics library binding
- `PyGObject==3.48.2`: GTK/GObject introspection bindings
- `pynput==1.8.1`: Input device monitoring (keyboard/mouse)
- `requests==2.31.0`: HTTP requests for external notifications

## Development Setup

### System Dependencies (Debian/Ubuntu)
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
sudo apt install -y build-essential libgirepository1.0-dev gir1.2-glib-2.0 python3-gi python3-gi-cairo gobject-introspection
```

### Additional dependencies if issues occur:
```bash
sudo apt install python3.10-dev pkg-config libcairo2-dev build-essential gnome-shell-extension-appindicator
pip install pygobject
```

### Python Dependencies
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python3 app.py
```

## Package Building

### Traditional Debian Package
```bash
chmod +x build_deb.sh
./build_deb.sh
sudo dpkg -i SyMo_1.0.1_all.deb
```

## Modern Build Methods (Recommended)

### 1. Nuitka Compilation (Best Performance)
Compiles Python to native machine code with 3x performance improvement:
```bash
chmod +x build_nuitka.sh
./build_nuitka.sh
./SyMo-compiled  # Run compiled executable
```
**Benefits**: Native performance, faster startup, single executable, no Python interpreter needed.

### 2. PyInstaller Single Executable (Best Portability)
Creates a single-file executable with all dependencies bundled:
```bash
chmod +x build_pyinstaller.sh
./build_pyinstaller.sh
./SyMo-portable  # Run portable executable
```
**Benefits**: Single file, runs anywhere, no installation needed, no Python required.

### 3. AppImage (Best Linux Compatibility)
Creates a portable application that runs on any Linux distribution:
```bash
chmod +x build_appimage.sh
./build_appimage.sh
./SyMo-1.0.1-x86_64.AppImage  # Run AppImage
```
**Benefits**: Universal Linux compatibility, no installation, automatic desktop integration.

### 4. Flatpak (Best Desktop Integration)
Modern Linux packaging with sandboxing and automatic updates:
```bash
chmod +x build_flatpak.sh
./build_flatpak.sh
flatpak install --user com.symo.SystemMonitor.flatpak
flatpak run com.symo.SystemMonitor
```
**Benefits**: Modern packaging, excellent desktop integration, automatic updates, security sandboxing.

## Build Comparison

| Method | Size | Startup | Performance | Distribution | Installation |
|--------|------|---------|-------------|--------------|--------------|
| Debian | 50MB+ | Fast | Standard | APT repos | `dpkg -i` |
| Nuitka | 200MB | Fastest | 3x faster | Single file | Copy & run |
| PyInstaller | 400MB | Slow | Standard | Single file | Download & run |
| AppImage | 300MB | Fast | Standard | Universal | Download & run |
| Flatpak | 150MB* | Fast | Standard | Modern repos | `flatpak install` |

*With shared runtimes

## Configuration Files

The application creates several configuration files in the user's home directory:
- `~/.system_monitor_settings.json`: Application settings
- `~/.system_monitor_telegram.json`: Telegram bot configuration
- `~/.system_monitor_discord.json`: Discord webhook configuration
- `~/system_monitor_log.txt`: System monitoring logs

## Key Features

### System Monitoring
- Real-time CPU usage with temperature monitoring
- RAM and SWAP memory usage
- Disk space monitoring
- Network speed (upload/download)
- System uptime tracking
- Keyboard and mouse activity counting

### Power Management
- Immediate and scheduled power actions (shutdown, reboot, lock screen)
- Timer-based execution with notifications

### External Notifications
- Telegram bot integration for periodic system reports
- Discord webhook notifications
- Configurable notification intervals

### Multi-language Support
Supported languages: Russian (ru), English (en), Chinese (cn), German (de)

## Testing

No formal test suite is present in this codebase. Testing should be done manually by running the application and verifying system tray functionality, metric accuracy, and notification systems.

## Build Optimization Notes

### Package Size Reduction
- Original build depends on system packages: ~50MB+ total installation
- Optimized build bundles only pure Python dependencies: ~10-15MB package size
- Removed files: tests, documentation, cache files, development headers
- Uses system GTK/Cairo packages to avoid conflicts and reduce size

### Dependency Strategy
- **Bundled**: psutil, pynput, requests (pure Python, version-sensitive)
- **System packages**: python3-gi, GTK3, AppIndicator3 (complex native extensions)
- **Minimal system requirements**: Reduces installation conflicts

### Installation Benefits
- Self-contained: Works across different Ubuntu/Debian versions
- Easy updates: Single .deb file with all dependencies
- Clean removal: Proper cleanup of configuration files on purge
- Better compatibility: Less likely to break with system updates

## Notes

- The application requires a desktop environment with system tray support
- Uses GTK 3.0 and AppIndicator3 for the system tray interface
- Configuration is managed through JSON files in the user's home directory
- Both standard and optimized build scripts create proper desktop integration