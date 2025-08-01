#!/bin/bash

# Настройки пакета
PACKAGE_NAME="SyMo"
VERSION="1.0.1"
MAINTAINER="Your Name <olegpustovalov220@gmail.com>"
DESCRIPTION="SyMo application with tray icon"
DEPENDS="python3, python3-gi, python3-psutil, gir1.2-appindicator3-0.1, python3-pynput, python3-requests"

# Создаем временную директорию сборки
BUILD_DIR="deb_build"
rm -rf ${BUILD_DIR}  # Очищаем предыдущую сборку
mkdir -p ${BUILD_DIR}/DEBIAN
mkdir -p ${BUILD_DIR}/usr/share/${PACKAGE_NAME}
mkdir -p ${BUILD_DIR}/usr/share/applications
mkdir -p ${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps
mkdir -p ${BUILD_DIR}/usr/bin

# Копируем файлы проекта
cp app.py language.py logo.png ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/

# Создаем исполняемый файл в /usr/bin
cat > ${BUILD_DIR}/usr/bin/${PACKAGE_NAME} <<EOF
#!/bin/bash
cd /usr/share/${PACKAGE_NAME}
exec python3 app.py "\$@"
EOF
chmod +x ${BUILD_DIR}/usr/bin/${PACKAGE_NAME}

# Копируем иконку
cp logo.png ${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps/${PACKAGE_NAME}.png

# Создаем desktop-файл
cat > ${BUILD_DIR}/usr/share/applications/${PACKAGE_NAME}.desktop <<EOF
[Desktop Entry]
Name=SyMo
Comment=${DESCRIPTION}
Exec=${PACKAGE_NAME}
Icon=${PACKAGE_NAME}
Terminal=false
Type=Application
Categories=Utility;System;
StartupNotify=true
Keywords=monitor;system;tray;
X-GNOME-UsesNotifications=true
EOF

# Создаем файл control
cat > ${BUILD_DIR}/DEBIAN/control <<EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: ${DEPENDS}
Maintainer: ${MAINTAINER}
Description: ${DESCRIPTION}
 A comprehensive SyMo application that shows:
  - CPU usage and temperature
  - RAM and swap usage
  - Disk space
  - Network speed
  - Uptime
  - Keyboard/mouse activity
 Includes power management features and Telegram notifications.
EOF

# Создаем postinst скрипт
cat > ${BUILD_DIR}/DEBIAN/postinst <<EOF
#!/bin/bash
# Обновление иконок
gtk-update-icon-cache -f -t /usr/share/icons/hicolor/
update-desktop-database /usr/share/applications/

# Установка прав
chmod 755 /usr/bin/${PACKAGE_NAME}
EOF
chmod +x ${BUILD_DIR}/DEBIAN/postinst

# Создаем prerm скрипт
cat > ${BUILD_DIR}/DEBIAN/prerm <<EOF
#!/bin/bash
# Остановка приложения перед удалением
pkill -f "/usr/share/${PACKAGE_NAME}/app.py" || true
EOF
chmod +x ${BUILD_DIR}/DEBIAN/prerm

# Собираем пакет
fakeroot dpkg-deb --build ${BUILD_DIR} ${PACKAGE_NAME}_${VERSION}_all.deb

# Проверяем пакет
lintian ${PACKAGE_NAME}_${VERSION}_all.deb

echo "Пакет собран: ${PACKAGE_NAME}_${VERSION}_all.deb"
