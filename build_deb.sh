#!/bin/bash

APP_NAME="SyMo"
VERSION="1.0"
BUILD_DIR="deb_build"
INSTALL_DIR="${BUILD_DIR}/${APP_NAME}/usr/local/bin/${APP_NAME}"

# Очистка
rm -rf "$BUILD_DIR"
mkdir -p "$INSTALL_DIR"

# Копируем файлы
cp app.py logo.png requirements.txt "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/app.py"

# DEBIAN/control
mkdir -p "${BUILD_DIR}/${APP_NAME}/DEBIAN"
cat > "${BUILD_DIR}/${APP_NAME}/DEBIAN/control" <<EOF
Package: ${APP_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-3.0, gir1.2-appindicator3-0.1, python3-psutil
Maintainer: You <you@example.com>
Description: System tray monitor.
EOF

# .desktop файл
mkdir -p "${BUILD_DIR}/${APP_NAME}/usr/share/applications"
cat > "${BUILD_DIR}/${APP_NAME}/usr/share/applications/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Name=SyMo
Exec=python3 /usr/local/bin/${APP_NAME}/app.py
Icon=/usr/local/bin/${APP_NAME}/logo.png
Type=Application
Categories=Utility;
EOF

# Создание .deb
dpkg-deb --build "${BUILD_DIR}/${APP_NAME}"
