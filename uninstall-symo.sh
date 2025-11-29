#!/usr/bin/env bash
set -euo pipefail

BINARIES=(
  "/usr/local/bin/SyMo-onefile"
  "/usr/local/bin/symo"
  "$HOME/.local/bin/SyMo-onefile"
  "$HOME/.local/bin/symo"
)

echo "Removing SyMo binaries (if present)..."
for bin_path in "${BINARIES[@]}"; do
  if [ -e "$bin_path" ]; then
    if [ -w "$bin_path" ]; then
      rm -f "$bin_path"
    else
      sudo rm -f "$bin_path"
    fi
    echo "Removed $bin_path"
  fi
done

DESKTOP_FILES=(
  "$HOME/.local/share/applications/symo.desktop"
  "/usr/share/applications/symo.desktop"
)

echo "Removing desktop entries (if present)..."
for desktop_file in "${DESKTOP_FILES[@]}"; do
  if [ -e "$desktop_file" ]; then
    if [ -w "$desktop_file" ]; then
      rm -f "$desktop_file"
    else
      sudo rm -f "$desktop_file"
    fi
    echo "Removed $desktop_file"
  fi
done

echo "Cleanup complete."