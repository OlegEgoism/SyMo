#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SyMo"
BUILD_SCRIPT="./build.sh"
INSTALLER_NAME="${APP_NAME}-installer.run"
STAGE_DIR=".installer_stage"

if ! command -v makeself >/dev/null 2>&1; then
  echo "❌ makeself not found. Install it first: sudo apt install -y makeself"
  exit 1
fi

if [[ ! -x "$BUILD_SCRIPT" ]]; then
  chmod +x "$BUILD_SCRIPT"
fi

echo "⚙️ Building application binaries via $BUILD_SCRIPT"
"$BUILD_SCRIPT"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/payload"

if [[ -f "${APP_NAME}-onefile" ]]; then
  cp "${APP_NAME}-onefile" "$STAGE_DIR/payload/${APP_NAME}-onefile"
  chmod +x "$STAGE_DIR/payload/${APP_NAME}-onefile"
  cat > "$STAGE_DIR/payload/install.sh" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail
APP_NAME="SyMo"
PREFIX="${HOME}/.local/bin"
mkdir -p "$PREFIX"
install -m 0755 "${APP_NAME}-onefile" "$PREFIX/${APP_NAME}-onefile"

DESKTOP_DIR="${HOME}/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/${APP_NAME}.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=SyMo System Monitor Tray App
Exec=${PREFIX}/${APP_NAME}-onefile
Terminal=false
Categories=Utility;System;
DESKTOP

echo "✅ Installed to $PREFIX/${APP_NAME}-onefile"
echo "✅ Desktop entry: $DESKTOP_DIR/${APP_NAME}.desktop"
INNER
else
  cp -r "${APP_NAME}-standalone" "$STAGE_DIR/payload/${APP_NAME}-standalone"
  cp "${APP_NAME}-run" "$STAGE_DIR/payload/${APP_NAME}-run"
  chmod +x "$STAGE_DIR/payload/${APP_NAME}-run"
  cat > "$STAGE_DIR/payload/install.sh" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail
APP_NAME="SyMo"
TARGET_DIR="${HOME}/.local/opt/${APP_NAME}"
mkdir -p "$TARGET_DIR"
cp -r "${APP_NAME}-standalone" "$TARGET_DIR/${APP_NAME}-standalone"
install -m 0755 "${APP_NAME}-run" "$TARGET_DIR/${APP_NAME}-run"

LINK_DIR="${HOME}/.local/bin"
mkdir -p "$LINK_DIR"
ln -sf "$TARGET_DIR/${APP_NAME}-run" "$LINK_DIR/symo"

DESKTOP_DIR="${HOME}/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/${APP_NAME}.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=SyMo System Monitor Tray App
Exec=${TARGET_DIR}/${APP_NAME}-run
Terminal=false
Categories=Utility;System;
DESKTOP

echo "✅ Installed standalone to $TARGET_DIR"
echo "✅ Launcher symlink: $LINK_DIR/symo"
INNER
fi

chmod +x "$STAGE_DIR/payload/install.sh"

makeself --nox11 "$STAGE_DIR/payload" "$INSTALLER_NAME" "${APP_NAME} installer" ./install.sh

echo "🎉 Installer created: $INSTALLER_NAME"
