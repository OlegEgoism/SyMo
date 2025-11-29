#!/bin/bash

# ===========================
#   SyMo — Nuitka build system
#   Standalone + Onefile + Icons + Autostart
# ===========================

set -e

APP_NAME="SyMo"
VERSION="1.0.0"

echo "⚙️  Building $APP_NAME using Nuitka..."

# ---------- Проверка системных зависимостей ----------
need_pkg() {
    if ! command -v "$1" &>/dev/null; then
        echo "📦 Installing missing dependency: $1"
        sudo apt update && sudo apt install -y "$2"
    fi
}

need_pkg gcc build-essential
need_pkg patchelf patchelf

if ! command -v nuitka3 &>/dev/null && ! command -v nuitka &>/dev/null; then
    echo "📦 Installing Nuitka..."
    pip3 install nuitka
fi

# Определяем бинарь Nuitka
NUITKA=nuitka
command -v nuitka3 &>/dev/null && NUITKA=nuitka3

echo "➡️  Using Nuitka: $NUITKA"


# ---------- Пути для ярлыков ----------
DESKTOP_MAIN="$HOME/.local/share/applications/${APP_NAME}.desktop"
DESKTOP_AUTOSTART="$HOME/.config/autostart/${APP_NAME}.desktop"

mkdir -p "$(dirname "$DESKTOP_MAIN")"
mkdir -p "$(dirname "$DESKTOP_AUTOSTART")"


# ---------- Очистка предыдущих сборок ----------
rm -rf ${APP_NAME}-standalone *.build *.dist build_standalone *.onefile-build
rm -f ${APP_NAME}-run ${APP_NAME}-onefile


# ---------- Утилита генерации .desktop ----------
write_desktop() {
    local path="$1"
    local exec_path="$2"
    local icon="$3"
    local autostart="$4"

    {
        echo "[Desktop Entry]"
        echo "Type=Application"
        echo "Name=$APP_NAME"
        echo "Comment=SyMo System Monitor Tray App"
        echo "Exec=$exec_path"
        [[ -f "$icon" ]] && echo "Icon=$icon"
        echo "Terminal=false"
        echo "Categories=Utility;System;"
        if [[ "$autostart" == "yes" ]]; then
            echo "X-GNOME-Autostart-enabled=true"
        fi
    } > "$path"

    chmod +x "$path"
    echo "📝 Desktop file written: $path"
}


# ---------- Сборка STANDALONE ----------
echo "🚀 Building STANDALONE..."

$NUITKA --standalone \
    --enable-plugin=gi \
    --follow-imports \
    --assume-yes-for-downloads \
    --include-data-files=logo.png=logo.png \
    --include-data-files=language.py=language.py \
    --include-data-files=localization.py=localization.py \
    --include-data-files=system_usage.py=system_usage.py \
    --include-data-files=power_control.py=power_control.py \
    --include-data-files=dialogs.py=dialogs.py \
    --include-data-files=click_tracker.py=click_tracker.py \
    --output-dir=build_standalone \
    --python-flag=no_site \
    --python-flag=-O \
    app.py

if [[ ! -d build_standalone/app.dist ]]; then
    echo "❌ STANDALONE failed!"
    exit 1
fi

mv build_standalone/app.dist ${APP_NAME}-standalone

echo "📦 Standalone built: ${APP_NAME}-standalone/"


# ---------- Создание раннера ----------
cat > ${APP_NAME}-run <<EOF
#!/bin/bash
set -e
DIR="\$( cd "\$( dirname "\${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
cd "\$DIR/${APP_NAME}-standalone"
exec ./app "\$@"
EOF
chmod +x ${APP_NAME}-run

echo "▶️  Standalone runner created: ${APP_NAME}-run"


# ---------- Сборка ONEFILE ----------
echo "🗜️  Building ONEFILE..."

set +e
$NUITKA --onefile \
    --enable-plugin=gi \
    --follow-imports \
    --assume-yes-for-downloads \
    --include-data-files=logo.png=logo.png \
    --include-data-files=language.py=language.py \
    --include-data-files=localization.py=localization.py \
    --include-data-files=system_usage.py=system_usage.py \
    --include-data-files=power_control.py=power_control.py \
    --include-data-files=dialogs.py=dialogs.py \
    --include-data-files=click_tracker.py=click_tracker.py \
    --python-flag=no_site \
    --python-flag=-O \
    --output-filename="${APP_NAME}-onefile" \
    app.py
ONEFILE_RC=$?
set -e

if [[ $ONEFILE_RC -eq 0 && -f "${APP_NAME}-onefile" ]]; then
    chmod +x "${APP_NAME}-onefile"
    echo "🎉 Onefile built: ${APP_NAME}-onefile"
else
    echo "⚠️  Onefile FAILED — standalone only."
fi


# ---------- Выбор исполняемого файла ----------
if [[ -f "${APP_NAME}-onefile" ]]; then
    EXEC_TARGET="$(pwd)/${APP_NAME}-onefile"
else
    EXEC_TARGET="$(pwd)/${APP_NAME}-run"
fi

ICON_PATH="$(pwd)/logo.png"


# ---------- Создаём единый ярлык ----------
write_desktop "$DESKTOP_MAIN" "$EXEC_TARGET" "$ICON_PATH" "no"

# ---------- Автозапуск ----------
write_desktop "$DESKTOP_AUTOSTART" "$EXEC_TARGET" "$ICON_PATH" "yes"


# ---------- Финал ----------
echo ""
echo "🎉 BUILD COMPLETE!"
echo "--------------------------------------"
echo "Standalone dir : ${APP_NAME}-standalone/"
echo "Standalone run : ./SyMo-run"
echo "Onefile        : ./SyMo-onefile (если собрался)"
echo "Desktop icon   : $DESKTOP_MAIN"
echo "Autostart file : $DESKTOP_AUTOSTART"
echo ""
echo "✔ Готово к распространению:"
echo "   tar -czf SyMo-standalone.tar.gz SyMo-standalone/ SyMo-run"
