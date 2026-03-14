#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SyMo"
PKG_NAME="symo"
VERSION="${1:-1.0.0}"
ARCH="${ARCH:-$(dpkg --print-architecture)}"
WORKDIR="${PWD}/packaging/deb-work"
PKGROOT="${WORKDIR}/${PKG_NAME}_${VERSION}_${ARCH}"

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "dpkg-deb is required (install: sudo apt install dpkg-dev)"
  exit 1
fi

rm -rf "${WORKDIR}"
mkdir -p \
  "${PKGROOT}/DEBIAN" \
  "${PKGROOT}/opt/${PKG_NAME}" \
  "${PKGROOT}/usr/bin" \
  "${PKGROOT}/usr/share/applications" \
  "${PKGROOT}/usr/share/pixmaps"

cp -r app.py app_core notifications requirements.txt logo.png README.md "${PKGROOT}/opt/${PKG_NAME}/"

cat > "${PKGROOT}/usr/bin/${PKG_NAME}" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/symo
exec python3 app.py "$@"
LAUNCH
chmod +x "${PKGROOT}/usr/bin/${PKG_NAME}"

cp logo.png "${PKGROOT}/usr/share/pixmaps/${PKG_NAME}.png"

cat > "${PKGROOT}/usr/share/applications/${PKG_NAME}.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=SyMo System Monitor Tray App
Exec=${PKG_NAME}
Icon=${PKG_NAME}
Terminal=false
Categories=Utility;System;
DESKTOP

cat > "${PKGROOT}/DEBIAN/control" <<CONTROL
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3, python3-gi, python3-psutil, python3-requests
Maintainer: SyMo Maintainers <maintainers@example.com>
Description: GTK system tray monitor for Linux
 SyMo displays system metrics in tray, includes power controls,
 and can send Telegram/Discord notifications.
CONTROL

cat > "${PKGROOT}/DEBIAN/postinst" <<'POSTINST'
#!/usr/bin/env bash
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
POSTINST
chmod 0755 "${PKGROOT}/DEBIAN/postinst"

OUTPUT_DEB="${PWD}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build "${PKGROOT}" "${OUTPUT_DEB}"

echo "Built: ${OUTPUT_DEB}"
