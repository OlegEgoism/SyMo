#!/bin/bash

# Nuitka Compilation Build Script for SyMo (Fixed Resources + Autostart + Icons)
# - Standalone и Onefile сборки
# - Автозапуск и ярлыки с иконкой logo.png (если есть)

set -e

PACKAGE_NAME="SyMo"
VERSION="1.0.1"

echo "🔥 Building ${PACKAGE_NAME} with Nuitka (resources, autostart, icons)..."

# ---------- Зависимости ----------
echo "🔧 Checking system dependencies..."
if ! command -v patchelf &> /dev/null; then
    echo "Installing patchelf (required for Nuitka standalone builds)..."
    sudo apt update && sudo apt install -y patchelf
fi
if ! command -v gcc &> /dev/null; then
    echo "Installing build-essential..."
    sudo apt install -y build-essential
fi
if ! command -v nuitka3 &> /dev/null && ! command -v nuitka &> /dev/null; then
    echo "Installing Nuitka..."
    pip3 install nuitka
fi

# ---------- Определяем Nuitka ----------
NUITKA_CMD="nuitka"
if command -v nuitka3 &> /dev/null; then
    NUITKA_CMD="nuitka3"
elif command -v nuitka &> /dev/null; then
    NUITKA_CMD="nuitka"
else
    echo "❌ Could not install Nuitka. Install manually: pip3 install nuitka"
    exit 1
fi
echo "Using Nuitka command: $NUITKA_CMD"

# ---------- Очистка ----------
rm -rf "${PACKAGE_NAME}.dist" "${PACKAGE_NAME}.build" "${PACKAGE_NAME}.onefile-build" \
       "build_standalone" "${PACKAGE_NAME}-standalone"
rm -f  "${PACKAGE_NAME}" "${PACKAGE_NAME}.bin" "${PACKAGE_NAME}-compiled" \
       "${PACKAGE_NAME}-onefile" "${PACKAGE_NAME}-run"

APP_MENU_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$APP_MENU_DIR" "$AUTOSTART_DIR"

# ---------- Утилиты ----------
write_desktop_file() {
    local path="$1"       # полный путь к .desktop
    local name="$2"       # Name=
    local exec_cmd="$3"   # Exec=
    local icon_path="$4"  # Icon= (может быть пустым)
    local autostart="$5"  # "yes" -> добавить X-GNOME-Autostart-enabled=true

    {
        echo "[Desktop Entry]"
        echo "Type=Application"
        echo "Name=${name}"
        echo "Comment=System Monitor with tray icon"
        echo "Exec=${exec_cmd}"
        if [[ -n "$icon_path" && -f "$icon_path" ]]; then
            echo "Icon=${icon_path}"
        fi
        echo "Terminal=false"
        echo "Categories=Utility;"
        if [[ "$autostart" == "yes" ]]; then
            echo "X-GNOME-Autostart-enabled=true"
        fi
    } > "$path"
    chmod +x "$path"
    echo "📝 Wrote desktop file: $path"
}

# ---------- Сборка Standalone ----------
echo "🚀 Compiling (standalone)..."
"$NUITKA_CMD" --standalone \
    --enable-plugin=gi \
    --include-data-files=logo.png=logo.png \
    --include-data-files=language.py=language.py \
    --assume-yes-for-downloads \
    --output-dir=build_standalone \
    --follow-imports \
    --python-flag=no_site \
    --python-flag=-O \
    app.py

if [[ -d "build_standalone/app.dist" ]]; then
    echo "✅ Standalone build successful"
    cp -r "build_standalone/app.dist" "${PACKAGE_NAME}-standalone"

    # Раннер для удобного запуска standalone
    cat > "${PACKAGE_NAME}-run" <<EOF
#!/bin/bash
set -e
DIR="\$( cd "\$( dirname "\${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "\$DIR/${PACKAGE_NAME}-standalone"
exec ./app "\$@"
EOF
    chmod +x "${PACKAGE_NAME}-run"

    STANDALONE_SIZE=$(du -sh "${PACKAGE_NAME}-standalone" | cut -f1)
    echo "📦 Standalone dir: ${PACKAGE_NAME}-standalone (size: ${STANDALONE_SIZE})"
    echo "▶️  Run: ./$(basename "${PACKAGE_NAME}-run")"

    # .desktop + автозапуск для standalone
    ABS_RUNNER_PATH="$(pwd)/${PACKAGE_NAME}-run"
    ABS_ICON_STANDALONE="$(pwd)/${PACKAGE_NAME}-standalone/logo.png"  # если есть
    DESKTOP_MAIN="${APP_MENU_DIR}/${PACKAGE_NAME}.desktop"
    DESKTOP_AUTOSTART="${AUTOSTART_DIR}/${PACKAGE_NAME}.desktop"

    write_desktop_file "$DESKTOP_MAIN" "${PACKAGE_NAME}" "$ABS_RUNNER_PATH" "$ABS_ICON_STANDALONE" "no"
    write_desktop_file "$DESKTOP_AUTOSTART" "${PACKAGE_NAME}" "$ABS_RUNNER_PATH" "$ABS_ICON_STANDALONE" "yes"

    echo "📋 Distribution tips:"
    echo "  tar -czf ${PACKAGE_NAME}-standalone.tar.gz ${PACKAGE_NAME}-standalone/ ${PACKAGE_NAME}-run"
    echo "  # end-user:"
    echo "  tar -xzf ${PACKAGE_NAME}-standalone.tar.gz && ./${PACKAGE_NAME}-run"
else
    echo "❌ Standalone compilation failed."
    echo "Try PyInstaller as alternative: ./build_pyinstaller.sh"
    exit 1
fi

# ---------- Сборка Onefile (экспериментально) ----------
echo ""
echo "🗜️ Compiling (onefile, experimental)..."
set +e
"$NUITKA_CMD" --onefile \
    --enable-plugin=gi \
    --include-data-files=logo.png=logo.png \
    --include-data-files=language.py=language.py \
    --assume-yes-for-downloads \
    --output-filename="${PACKAGE_NAME}-onefile" \
    --follow-imports \
    --python-flag=no_site \
    --python-flag=-O \
    app.py
ONEFILE_RC=$?
set -e

if [[ $ONEFILE_RC -eq 0 && -f "${PACKAGE_NAME}-onefile" ]]; then
    chmod +x "${PACKAGE_NAME}-onefile"
    ONEFILE_SIZE=$(du -h "${PACKAGE_NAME}-onefile" | cut -f1)
    echo "✅ Onefile build successful (size: ${ONEFILE_SIZE})"
    echo "▶️  Run: ./$(basename "${PACKAGE_NAME}-onefile")"
    echo "⚠️  Note: Onefile может иметь проблемы с загрузкой ресурсов; при сбоях используйте standalone."

    # .desktop + автозапуск для onefile с иконкой logo.png (если в корне проекта есть)
    ABS_ONEFILE_PATH="$(pwd)/${PACKAGE_NAME}-onefile"
    ABS_ICON_ONEFILE="$(pwd)/logo.png"
    DESKTOP_ONE_MAIN="${APP_MENU_DIR}/${PACKAGE_NAME}-onefile.desktop"
    DESKTOP_ONE_AUTOSTART="${AUTOSTART_DIR}/${PACKAGE_NAME}-onefile.desktop"

    write_desktop_file "$DESKTOP_ONE_MAIN" "${PACKAGE_NAME} (Onefile)" "$ABS_ONEFILE_PATH" "$ABS_ICON_ONEFILE" "no"
    write_desktop_file "$DESKTOP_ONE_AUTOSTART" "${PACKAGE_NAME} (Onefile)" "$ABS_ONEFILE_PATH" "$ABS_ICON_ONEFILE" "yes"
else
    echo "⚠️  Onefile build failed or skipped; standalone is ready."
fi

# ---------- Финал ----------
# Чистка временной директории standalone-сборки (оставляем итоговые артефакты)
rm -rf build_standalone

echo ""
echo "🎉 Done!"
echo "• Standalone: ${PACKAGE_NAME}-standalone/ + ${PACKAGE_NAME}-run (+ ярлыки и автозапуск)"
echo "• Onefile  : ${PACKAGE_NAME}-onefile (если собрался) (+ ярлыки и автозапуск)"
echo "• Иконка   : logo.png будет использована в .desktop, если найдена."
