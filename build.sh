#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv-build"
DIST_DIR="$PROJECT_ROOT/dist"
PACKAGE_DIR="$DIST_DIR/installer"

python3 -m venv "$VENV_PATH"
source "$VENV_PATH/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "$PROJECT_ROOT/requirements.txt" pyinstaller

pyinstaller \
  --noconfirm \
  --clean \
  --name "SyMo-onefile" \
  --onefile \
  --add-data "logo.png:." \
  --hidden-import "gi.repository.GLib" \
  --hidden-import "gi.repository.GObject" \
  --hidden-import "gi.repository.Gtk" \
  --hidden-import "gi.repository.AppIndicator3" \
  --hidden-import "gi.repository.AyatanaAppIndicator3" \
  "$PROJECT_ROOT/app.py"

mkdir -p "$PACKAGE_DIR"
cp "$DIST_DIR/SyMo-onefile" "$PACKAGE_DIR/"
cp "$PROJECT_ROOT/uninstall-symo.sh" "$PACKAGE_DIR/"
cp "$PROJECT_ROOT/README.md" "$PACKAGE_DIR/README.md"

tar -czf "$DIST_DIR/SyMo-installer.tar.gz" -C "$PACKAGE_DIR" .

echo "Build complete. Artifacts:"
echo " - Binary: $DIST_DIR/SyMo-onefile"
echo " - Installer archive: $DIST_DIR/SyMo-installer.tar.gz"
