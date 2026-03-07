#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

remove_path() {
  local target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    if [ -w "$target" ] || [ -w "$(dirname "$target")" ]; then
      rm -rf "$target"
    else
      sudo rm -rf "$target"
    fi
    echo "Removed $target"
  fi
}

echo "Removing SyMo binaries (if present)..."
BINARIES=(
  "/usr/local/bin/SyMo-onefile"
  "/usr/local/bin/SyMo-launch"
  "/usr/local/bin/SyMo-run"
  "/usr/local/bin/symo"
  "$HOME/.local/bin/SyMo-onefile"
  "$HOME/.local/bin/SyMo-launch"
  "$HOME/.local/bin/SyMo-run"
  "$HOME/.local/bin/symo"
)
for bin_path in "${BINARIES[@]}"; do
  remove_path "$bin_path"
done

echo "Removing desktop entries (if present)..."
DESKTOP_FILES=(
  "$HOME/.local/share/applications/SyMo.desktop"
  "$HOME/.local/share/applications/symo.desktop"
  "$HOME/.config/autostart/SyMo.desktop"
  "$HOME/.config/autostart/symo.desktop"
  "/usr/share/applications/SyMo.desktop"
  "/usr/share/applications/symo.desktop"
)
for desktop_file in "${DESKTOP_FILES[@]}"; do
  remove_path "$desktop_file"
done

echo "Removing installed SyMo folders (if present)..."
INSTALL_DIRS=(
  "/opt/SyMo"
  "/opt/SyMo-bundle"
  "$HOME/.local/opt/SyMo"
  "$HOME/.local/opt/SyMo-bundle"
)
for dir_path in "${INSTALL_DIRS[@]}"; do
  remove_path "$dir_path"
done

echo "Removing local build artifacts near uninstall script (if present)..."
LOCAL_ARTIFACTS=(
  "$SCRIPT_DIR/app.build"
  "$SCRIPT_DIR/app.dist"
  "$SCRIPT_DIR/app.onefile-build"
  "$SCRIPT_DIR/build_standalone"
  "$SCRIPT_DIR/SyMo-standalone"
  "$SCRIPT_DIR/SyMo-onefile"
  "$SCRIPT_DIR/SyMo-launch"
  "$SCRIPT_DIR/SyMo-run"
  "$SCRIPT_DIR/SyMo-bundle"
)
for local_path in "${LOCAL_ARTIFACTS[@]}"; do
  remove_path "$local_path"
done

echo "Cleanup complete."
