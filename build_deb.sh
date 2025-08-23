#!/bin/bash

# Настройки пакета
PACKAGE_NAME="SyMo"
VERSION="1.0.1"
MAINTAINER="Your Name <olegpustovalov220@gmail.com>"
DESCRIPTION="SyMo application with tray icon"
DEPENDS="python3, python3-gi, python3-psutil, gir1.2-appindicator3-0.1, python3-pynput, python3-requests, xdg-utils"

# Автозапуск
AUTOSTART="${AUTOSTART:-system}"

# Создаем временную директорию сборки
BUILD_DIR="deb_build"
rm -rf "${BUILD_DIR}"  # Очищаем предыдущую сборку
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/share/${PACKAGE_NAME}"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/etc/xdg/autostart"   # на всякий случай — для system-автозапуска

# Копируем файлы проекта
cp app.py language.py logo.png "${BUILD_DIR}/usr/share/${PACKAGE_NAME}/"

# Создаем исполняемый файл в /usr/bin
cat > "${BUILD_DIR}/usr/bin/${PACKAGE_NAME}" <<EOF
#!/bin/bash
cd /usr/share/${PACKAGE_NAME}
exec python3 app.py "\$@"
EOF
chmod +x "${BUILD_DIR}/usr/bin/${PACKAGE_NAME}"

# Утилита управления автозапуском (enable/disable) для уже установленного пакета
cat > "${BUILD_DIR}/usr/bin/${PACKAGE_NAME}-autostart" <<'EOF'
#!/bin/bash
set -e
APP="SyMo"
DESKTOP_NAME="SyMo.desktop"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
SYSTEM_AUTOSTART="/etc/xdg/autostart/${DESKTOP_NAME}"
USER_AUTOSTART="${AUTOSTART_DIR}/${DESKTOP_NAME}"

usage() {
  echo "Usage: ${APP,,}-autostart [enable|disable|status] [--system|--user]"
  exit 1
}

scope="--user"
action="status"

for arg in "$@"; do
  case "$arg" in
    enable|disable|status) action="$arg" ;;
    --system|--user) scope="$arg" ;;
    *) usage ;;
  esac
done

ensure_user_dir() {
  mkdir -p "${AUTOSTART_DIR}"
}

case "$action:$scope" in
  status:--user)
    if [ -f "${USER_AUTOSTART}" ]; then
      echo "User autostart: enabled (${USER_AUTOSTART})"
    else
      echo "User autostart: disabled"
    fi
    ;;
  status:--system)
    if [ -f "${SYSTEM_AUTOSTART}" ]; then
      echo "System autostart: enabled (${SYSTEM_AUTOSTART})"
    else
      echo "System autostart: disabled"
    fi
    ;;
  enable:--user)
    ensure_user_dir
    cat > "${USER_AUTOSTART}" <<EOX
[Desktop Entry]
Type=Application
Name=SyMo
Comment=SyMo application with tray icon
Exec=SyMo
Icon=SyMo
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;System;
X-GNOME-UsesNotifications=true
EOX
    echo "Enabled user autostart: ${USER_AUTOSTART}"
    ;;
  disable:--user)
    rm -f "${USER_AUTOSTART}" && echo "Disabled user autostart" || echo "User autostart already disabled"
    ;;
  enable:--system)
    # Требуются root-права
    if [ "$EUID" -ne 0 ]; then
      echo "Use sudo for --system" >&2
      exit 1
    fi
    cat > "${SYSTEM_AUTOSTART}" <<EOX
[Desktop Entry]
Type=Application
Name=SyMo
Comment=SyMo application with tray icon
Exec=SyMo
Icon=SyMo
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;System;
X-GNOME-UsesNotifications=true
EOX
    echo "Enabled system autostart: ${SYSTEM_AUTOSTART}"
    ;;
  disable:--system)
    if [ "$EUID" -ne 0 ]; then
      echo "Use sudo for --system" >&2
      exit 1
    fi
    rm -f "${SYSTEM_AUTOSTART}" && echo "Disabled system autostart" || echo "System autostart already disabled"
    ;;
  *)
    usage
    ;;
esac
EOF
chmod +x "${BUILD_DIR}/usr/bin/${PACKAGE_NAME}-autostart"

# Копируем иконку
cp logo.png "${BUILD_DIR}/usr/share/icons/hicolor/48x48/apps/${PACKAGE_NAME}.png"

# Создаем desktop-файл (запуск вручную через меню/поиск)
cat > "${BUILD_DIR}/usr/share/applications/${PACKAGE_NAME}.desktop" <<EOF
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

# Если выбран автозапуск system — подготовим файл заранее (будет скопирован при установке)
if [ "${AUTOSTART}" = "system" ]; then
  cat > "${BUILD_DIR}/etc/xdg/autostart/${PACKAGE_NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=SyMo
Comment=${DESCRIPTION}
Exec=${PACKAGE_NAME}
Icon=${PACKAGE_NAME}
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;System;
X-GNOME-UsesNotifications=true
EOF
fi

# Создаем файл control
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
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

# postinst: обновление кэшей и настройка автозапуска
cat > "${BUILD_DIR}/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e

gtk-update-icon-cache -f -t /usr/share/icons/hicolor/ || true
update-desktop-database /usr/share/applications/ || true
chmod 755 /usr/bin/SyMo
chmod 755 /usr/bin/SyMo-autostart

# Настройка автозапуска в зависимости от режима сборки/установки
# Детектируем, был ли положен системный файл автозапуска
SYSTEM_AUTOSTART="/etc/xdg/autostart/SyMo.desktop"

if [ -f "${SYSTEM_AUTOSTART}" ]; then
  echo "SyMo: system-wide autostart is enabled."
else
  # Попытка включить автозапуск для текущего пользователя установки
  # Если пакет ставится через sudo, используем SUDO_USER, иначе — текущий пользователь
  TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo '')}"
  if [ -n "${TARGET_USER}" ] && id "${TARGET_USER}" >/dev/null 2>&1; then
    USER_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
    AUTOSTART_DIR="${USER_HOME}/.config/autostart"
    install -d -o "${TARGET_USER}" -g "${TARGET_USER}" "${AUTOSTART_DIR}"
    cat > "${AUTOSTART_DIR}/SyMo.desktop" <<EOX
[Desktop Entry]
Type=Application
Name=SyMo
Comment=SyMo application with tray icon
Exec=SyMo
Icon=SyMo
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;System;
X-GNOME-UsesNotifications=true
EOX
    chown "${TARGET_USER}:${TARGET_USER}" "${AUTOSTART_DIR}/SyMo.desktop"
    echo "SyMo: user autostart enabled for ${TARGET_USER}."
  else
    echo "SyMo: could not determine target user for user-level autostart. You can enable it later with: SyMo-autostart enable --user"
  fi
fi

exit 0
EOF
chmod +x "${BUILD_DIR}/DEBIAN/postinst"

# prerm: остановка приложения перед удалением
cat > "${BUILD_DIR}/DEBIAN/prerm" <<'EOF'
#!/bin/bash
set -e
pkill -f "/usr/share/SyMo/app.py" || true
exit 0
EOF
chmod +x "${BUILD_DIR}/DEBIAN/prerm"

# postrm: очистка автозапуска при удалении пакета
cat > "${BUILD_DIR}/DEBIAN/postrm" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  rm -f /etc/xdg/autostart/SyMo.desktop || true
  # Не трогаем user-автозапуск, чтобы не ломать настройки пользователя (он может сам удалить)
fi
exit 0
EOF
chmod +x "${BUILD_DIR}/DEBIAN/postrm"

# Собираем пакет
fakeroot dpkg-deb --build "${BUILD_DIR}" "${PACKAGE_NAME}_${VERSION}_all.deb"

# Проверяем пакет
lintian "${PACKAGE_NAME}_${VERSION}_all.deb" || true

echo "Пакет собран: ${PACKAGE_NAME}_${VERSION}_all.deb"
echo "Режим автозапуска: ${AUTOSTART} (можно переопределить переменной окружения AUTOSTART=system|user|none)"
