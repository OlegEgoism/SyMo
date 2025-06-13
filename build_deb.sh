#!/bin/bash

# Настройки пакета
PACKAGE_NAME="systray-monitor"
VERSION="1.0.0"
MAINTAINER="Your Name <your.email@example.com>"
DESCRIPTION="System monitoring application with tray icon"
DEPENDS="python3, python3-gi, python3-psutil, gir1.2-appindicator3-0.1, python3-pynput"

# Создаем временную директорию сборки
BUILD_DIR="deb_build"
mkdir -p ${BUILD_DIR}/DEBIAN
mkdir -p ${BUILD_DIR}/usr/share/${PACKAGE_NAME}
mkdir -p ${BUILD_DIR}/usr/share/applications
mkdir -p ${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps
mkdir -p ${BUILD_DIR}/usr/bin

# Копируем файлы проекта
cp -r app.py language.py logo.png ${BUILD_DIR}/usr/share/${PACKAGE_NAME}/

# Создаем исполняемый файл в /usr/bin
cat > ${BUILD_DIR}/usr/bin/${PACKAGE_NAME} <<EOF
#!/bin/bash
cd /usr/share/${PACKAGE_NAME}
python3 app.py
EOF
chmod +x ${BUILD_DIR}/usr/bin/${PACKAGE_NAME}

# Копируем иконку
cp logo.png ${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps/${PACKAGE_NAME}.png

# Создаем desktop-файл
cat > ${BUILD_DIR}/usr/share/applications/${PACKAGE_NAME}.desktop <<EOF
[Desktop Entry]
Name=System Monitor
Comment=${DESCRIPTION}
Exec=${PACKAGE_NAME}
Icon=/usr/share/icons/hicolor/48x48/apps/${PACKAGE_NAME}.png
Terminal=false
Type=Application
Categories=Utility;System;
StartupNotify=true
Keywords=monitor;system;tray;
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
 A system monitoring application that shows CPU, RAM, disk and network usage
 in system tray with various power management features.
EOF

# Создаем postinst скрипт
cat > ${BUILD_DIR}/DEBIAN/postinst <<EOF
#!/bin/bash
# Установка зависимостей Python
pip3 install -r /usr/share/${PACKAGE_NAME}/requirements.txt

# Обновление иконок
gtk-update-icon-cache -f /usr/share/icons/hicolor/
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
dpkg-deb --build ${BUILD_DIR} ${PACKAGE_NAME}_${VERSION}_all.deb

# Проверяем пакет
lintian ${PACKAGE_NAME}_${VERSION}_all.deb

echo "Пакет собран: ${PACKAGE_NAME}_${VERSION}_all.deb"