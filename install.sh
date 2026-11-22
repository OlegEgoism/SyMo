#!/usr/bin/env bash
# Установка SyMo из распакованного релизного архива для текущего пользователя.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local/opt/SyMo}"
BIN_LINK="$HOME/.local/bin/symo"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
AUTOSTART=1

usage() {
    echo "Использование: $0 [--no-autostart]"
    echo "  PREFIX=<каталог>  куда установить (по умолчанию ~/.local/opt/SyMo)"
}

for arg in "$@"; do
    case "$arg" in
        --no-autostart) AUTOSTART=0 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 1 ;;
    esac
done

# Пакет ставит свои ярлыки в /usr/share и /etc/xdg; ярлыки из ~/.local их перекрыли бы,
# и меню, автозапуск и расширение запускали бы эту копию вместо пакетной.
if dpkg-query -W -f='${Status}' symo 2>/dev/null | grep -q "install ok installed"; then
    echo "❌ Установлен пакет symo. Обновляйте его через .deb или сначала удалите: sudo apt remove symo" >&2
    exit 1
fi

if [[ ! -x "$SRC_DIR/app/SyMo" ]]; then
    echo "❌ Не найден $SRC_DIR/app/SyMo. Запускайте install.sh из распакованного архива релиза." >&2
    exit 1
fi

typelib_installed() {
    compgen -G "/usr/lib/*/girepository-1.0/$1" >/dev/null ||
        compgen -G "/usr/lib/girepository-1.0/$1" >/dev/null ||
        compgen -G "/usr/lib64/girepository-1.0/$1" >/dev/null
}

missing=()
typelib_installed Gtk-3.0.typelib || missing+=(gir1.2-gtk-3.0)
typelib_installed AyatanaAppIndicator3-0.1.typelib || typelib_installed AppIndicator3-0.1.typelib ||
    missing+=(gir1.2-ayatanaappindicator3-0.1)
if ((${#missing[@]})); then
    echo "❌ Не хватает системных пакетов: ${missing[*]}" >&2
    echo "   Установите: sudo apt install ${missing[*]}" >&2
    exit 1
fi

# Значение Exec по спецификации desktop-файлов: % удваивается, аргумент с особыми
# символами берётся в кавычки, а обратная косая черта экранируется ещё раз для ключа.
desktop_exec_quote() {
    local s="${1//%/%%}"
    case "$s" in
        *[[:space:]\"\'\\\<\>~\|\&\;\$\*\?\#\(\)\`]*)
            s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//\`/\\\`}"; s="${s//\$/\\\$}"
            s="\"$s\"" ;;
    esac
    printf '%s' "${s//\\/\\\\}"
}

was_running=0
if [[ "$SRC_DIR" != "$PREFIX" ]]; then
    if [[ -e "$PREFIX" && ! -x "$PREFIX/app/SyMo" ]]; then
        echo "❌ $PREFIX существует и не похож на установку SyMo. Укажите другой PREFIX." >&2
        exit 1
    fi
    # Запущенная копия грузит модули из $PREFIX по мере надобности: удалить каталог
    # под ней — значит уронить её. Останавливаем и после обновления запускаем снова.
    if pgrep -u "$(id -u)" -f "^$PREFIX/app/SyMo" >/dev/null 2>&1; then
        echo "Останавливаю запущенный SyMo..."
        pkill -u "$(id -u)" -f "^$PREFIX/app/SyMo" || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            pgrep -u "$(id -u)" -f "^$PREFIX/app/SyMo" >/dev/null 2>&1 || break
            sleep 0.5
        done
        was_running=1
    fi
    rm -rf "$PREFIX"
    mkdir -p "$(dirname "$PREFIX")"
    cp -a "$SRC_DIR" "$PREFIX"
fi

write_desktop() {
    local path="$1" extra="$2"
    mkdir -p "$(dirname "$path")"
    cat > "$path" <<EOF
[Desktop Entry]
Type=Application
Name=SyMo
Comment=System monitor in the tray
Exec=$(desktop_exec_quote "$PREFIX/symo")
Icon=$PREFIX/app/logo.png
Terminal=false
Categories=System;Monitor;
StartupNotify=false
$extra
EOF
}

write_desktop "$APPS_DIR/SyMo.desktop" ""
if ((AUTOSTART)); then
    write_desktop "$AUTOSTART_DIR/SyMo.desktop" "X-GNOME-Autostart-enabled=true"
else
    rm -f "$AUTOSTART_DIR/SyMo.desktop"
fi

mkdir -p "$(dirname "$BIN_LINK")"
ln -sfn "$PREFIX/symo" "$BIN_LINK"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "✔ SyMo установлен в $PREFIX"
echo "  Запуск: меню приложений → SyMo, команда «symo» или расширение SyMo Launcher."
if ((AUTOSTART)); then
    echo "  Автозапуск при входе включён (отключить: $0 --no-autostart)."
fi
if ((was_running)); then
    nohup "$PREFIX/symo" >/dev/null 2>&1 &
    disown
    echo "  SyMo перезапущен."
fi
