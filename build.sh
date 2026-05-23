#!/bin/bash

# ===========================
#   SyMo — Nuitka build system
#   Standalone + Onefile + Icons + Autostart
# ===========================

set -e

APP_NAME="SyMo"
VERSION="1.0.0"
OUTPUT_DIR="${APP_NAME}-bundle"

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

# ---------- Обновление Nuitka в виртуальном окружении ----------
echo "📦 Updating Nuitka..."
pip install --upgrade nuitka ordered-set

# Определяем как запускать Nuitka через python -m
NUITKA_CMD="python -m nuitka"

# Проверяем, что Nuitka установлена
if ! python -c "import nuitka" 2>/dev/null; then
    echo "❌ Nuitka not found in virtual environment"
    exit 1
fi

echo "➡️  Using Nuitka: $NUITKA_CMD"
echo "➡️  Nuitka version: $(python -m nuitka --version)"

# ---------- Опциональные модули для Nuitka ----------
NUITKA_EXTRA_MODULE_ARGS=()

add_optional_module() {
    local module_name="$1"
    if python -c "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('$module_name') else 1)" 2>/dev/null; then
        NUITKA_EXTRA_MODULE_ARGS+=("--include-module=${module_name}")
        echo "➕ Include optional module: ${module_name}"
    else
        echo "ℹ️  Skip optional module (not found): ${module_name}"
    fi
}

add_optional_module gi._gi_cairo
add_optional_module cairo

# ---------- Пути для ярлыков ----------
DESKTOP_MAIN="$HOME/.local/share/applications/${APP_NAME}.desktop"
DESKTOP_AUTOSTART="$HOME/.config/autostart/${APP_NAME}.desktop"

mkdir -p "$(dirname "$DESKTOP_MAIN")"
mkdir -p "$(dirname "$DESKTOP_AUTOSTART")"

# ---------- Очистка предыдущих сборок ----------
rm -rf "${OUTPUT_DIR}" "${APP_NAME}-standalone" *.build *.dist build_standalone *.onefile-build
rm -f "${APP_NAME}-run" "${APP_NAME}-onefile" "${APP_NAME}-launch"

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

$NUITKA_CMD --standalone \
    --enable-plugin=gi \
    --follow-imports \
    "${NUITKA_EXTRA_MODULE_ARGS[@]}" \
    --assume-yes-for-downloads \
    --include-data-files=logo.png=logo.png \
    --include-data-files=app_core/language.py=app_core/language.py \
    --include-data-files=app_core/localization.py=app_core/localization.py \
    --include-data-files=app_core/system_usage.py=app_core/system_usage.py \
    --include-data-files=app_core/power_control.py=app_core/power_control.py \
    --include-data-files=app_core/dialogs.py=app_core/dialogs.py \
    --include-data-files=app_core/click_tracker.py=app_core/click_tracker.py \
    --output-dir=build_standalone \
    --python-flag=no_site \
    --python-flag=-O \
    app.py

if [[ ! -d build_standalone/app.dist ]]; then
    echo "❌ STANDALONE failed!"
    exit 1
fi

mv build_standalone/app.dist "${APP_NAME}-standalone"

echo "📦 Standalone built: ${APP_NAME}-standalone/"

# ---------- Создание раннера ----------
cat > "${APP_NAME}-run" <<EOF_RUN
#!/bin/bash
set -e
DIR="\$( cd "\$( dirname "\${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
cd "\$DIR/${APP_NAME}-standalone"

if [[ -x "./app" ]]; then
    exec ./app "\$@"
fi
if [[ -x "./app.bin" ]]; then
    exec ./app.bin "\$@"
fi

echo "❌ Не найден исполняемый файл ./app или ./app.bin в ${APP_NAME}-standalone"
exit 1
EOF_RUN
chmod +x "${APP_NAME}-run"

echo "▶️  Standalone runner created: ${APP_NAME}-run"

# ---------- Универсальный лаунчер ----------
cat > "${APP_NAME}-launch" <<'EOF_LAUNCH'
#!/bin/bash
set -e

if [[ -z "${GDK_BACKEND:-}" && "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    export GDK_BACKEND="wayland,x11"
fi
export GDK_GL="${GDK_GL:-disable}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export LIBGL_DRI3_DISABLE="${LIBGL_DRI3_DISABLE:-1}"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
cd "$DIR"

if [[ "${SYMO_FORCE_ONEFILE:-0}" == "1" && -x "./SyMo-onefile" ]]; then
    exec "./SyMo-onefile" "$@"
fi

if [[ -x "./SyMo-run" ]]; then
    exec "./SyMo-run" "$@"
fi

if [[ -x "./SyMo-onefile" ]]; then
    exec "./SyMo-onefile" "$@"
fi

echo "❌ Не найден исполняемый файл SyMo-run или SyMo-onefile"
exit 1
EOF_LAUNCH
chmod +x "${APP_NAME}-launch"

echo "▶️  Launcher created: ${APP_NAME}-launch"

# ---------- Сборка ONEFILE ----------
echo "🗜️  Building ONEFILE..."

set +e
$NUITKA_CMD --onefile \
    --enable-plugin=gi \
    --follow-imports \
    "${NUITKA_EXTRA_MODULE_ARGS[@]}" \
    --assume-yes-for-downloads \
    --include-data-files=logo.png=logo.png \
    --include-data-files=app_core/language.py=app_core/language.py \
    --include-data-files=app_core/localization.py=app_core/localization.py \
    --include-data-files=app_core/system_usage.py=app_core/system_usage.py \
    --include-data-files=app_core/power_control.py=app_core/power_control.py \
    --include-data-files=app_core/dialogs.py=app_core/dialogs.py \
    --include-data-files=app_core/click_tracker.py=app_core/click_tracker.py \
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

# ---------- Сборка всех артефактов в одну папку ----------
mkdir -p "${OUTPUT_DIR}"

move_if_exists() {
    local target="$1"
    if [[ -e "$target" ]]; then
        mv "$target" "${OUTPUT_DIR}/" 2>/dev/null || true
    fi
}

move_if_exists "app.build"
move_if_exists "app.dist"
move_if_exists "app.onefile-build"
move_if_exists "build_standalone"
move_if_exists "${APP_NAME}-standalone"
move_if_exists "${APP_NAME}-onefile"
move_if_exists "${APP_NAME}-launch"
move_if_exists "${APP_NAME}-run"

# ---------- Выбор исполняемого файла ----------
EXEC_TARGET="$(pwd)/${OUTPUT_DIR}/${APP_NAME}-launch"
ICON_PATH="$(pwd)/logo.png"

# ---------- Создаём единый ярлык ----------
if [[ -f "$ICON_PATH" ]]; then
    write_desktop "$DESKTOP_MAIN" "$EXEC_TARGET" "$ICON_PATH" "no"
    write_desktop "$DESKTOP_AUTOSTART" "$EXEC_TARGET" "$ICON_PATH" "yes"
else
    echo "⚠️  Icon not found at $ICON_PATH, skipping .desktop creation"
fi

# ---------- Финал ----------
echo ""
echo "🎉 BUILD COMPLETE!"
echo "--------------------------------------"
echo "Build artifacts dir: ${OUTPUT_DIR}/"
echo "Standalone dir      : ${OUTPUT_DIR}/${APP_NAME}-standalone/"
echo "Standalone run      : ${OUTPUT_DIR}/SyMo-run"
echo "Launcher            : ${OUTPUT_DIR}/SyMo-launch"
[[ -f "${OUTPUT_DIR}/SyMo-onefile" ]] && echo "Onefile             : ${OUTPUT_DIR}/SyMo-onefile"
echo ""
echo "✔ Готово к распространению:"
echo "   tar -czf ${APP_NAME}-bundle.tar.gz ${OUTPUT_DIR}/"