#!/usr/bin/env bash
# Собирает пакет symo_<версия>_<arch>.deb из готовой сборки build.sh.
# Пакет ставит приложение в /opt/symo, команду symo, ярлык в меню и автозапуск
# для всех пользователей; зависимости apt устанавливает сам.
#   ./build-deb.sh <каталог сборки> <версия>
set -euo pipefail

STAGE="${1:?каталог сборки, например dist/SyMo-1.2.0-linux-x86_64}"
VERSION="${2:?версия, например 1.2.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"
PYTHON="${PYTHON:-python3}"
ARCH="$(dpkg --print-architecture)"
DEB="$DIST_DIR/symo_${VERSION}_${ARCH}.deb"

if [[ ! -x "$STAGE/app/SyMo" ]]; then
    echo "❌ Не найден $STAGE/app/SyMo. Сначала выполните ./build.sh" >&2
    exit 1
fi

PKG="$(mktemp -d)"
trap 'rm -rf "$PKG"' EXIT

mkdir -p "$PKG/opt/symo" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/etc/xdg/autostart" \
    "$PKG/usr/share/icons/hicolor/256x256/apps" "$PKG/usr/share/doc/symo" "$PKG/DEBIAN"

cp -a "$STAGE/app" "$STAGE/symo" "$PKG/opt/symo/"
ln -s /opt/symo/symo "$PKG/usr/bin/symo"
cp "$ROOT_DIR/LICENSE" "$PKG/usr/share/doc/symo/copyright"

"$PYTHON" - "$ROOT_DIR/logo.png" "$PKG/usr/share/icons/hicolor/256x256/apps/symo.png" <<'PY'
import sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
pixbuf = GdkPixbuf.Pixbuf.new_from_file(sys.argv[1])
pixbuf.scale_simple(256, 256, GdkPixbuf.InterpType.HYPER).savev(sys.argv[2], "png", [], [])
PY

desktop_entry() {
    cat <<EOF
[Desktop Entry]
Type=Application
Name=SyMo
Comment=System monitor in the tray
Exec=/usr/bin/symo
Icon=symo
Terminal=false
Categories=System;Monitor;
StartupNotify=false
EOF
}
desktop_entry > "$PKG/usr/share/applications/SyMo.desktop"
{ desktop_entry; echo "X-GNOME-Autostart-enabled=true"; } > "$PKG/etc/xdg/autostart/SyMo.desktop"

cat > "$PKG/DEBIAN/control" <<EOF
Package: symo
Version: $VERSION
Architecture: $ARCH
Maintainer: OlegEgoism <olegpustovalov220@gmail.com>
Installed-Size: $(du -sk "$PKG" | cut -f1)
Depends: libc6 (>= 2.35), gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1
Recommends: gnome-shell-extension-appindicator
Suggests: gnome-screenshot
Section: utils
Priority: optional
Homepage: https://github.com/OlegEgoism/SyMo
Description: Lightweight system monitor for the tray
 SyMo shows CPU, RAM, swap, disk and network usage in the tray, with graphs,
 power actions, a shutdown timer and Telegram/Discord notifications.
EOF

# При удалении пакета останавливаем запущенные экземпляры: их файлы исчезают.
cat > "$PKG/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ]; then
    pkill -x SyMo || true
fi
EOF
chmod 755 "$PKG/DEBIAN/prerm"

# Стандартные права пакета: каталоги и программы 755, остальные файлы 644.
chmod 755 "$PKG"
find "$PKG" -type d -exec chmod 755 {} +
find "$PKG" -type f -perm /111 -exec chmod 755 {} +
find "$PKG" -type f ! -perm /111 -exec chmod 644 {} +

mkdir -p "$DIST_DIR"
rm -f "$DEB"
dpkg-deb --root-owner-group --build "$PKG" "$DEB" >/dev/null
echo "✔ Пакет: $DEB"
