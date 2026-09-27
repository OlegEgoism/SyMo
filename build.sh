#!/usr/bin/env bash
# Сборка релиза SyMo через Nuitka: dist/SyMo-<версия>-linux-<arch>.tar.gz
# и архивы расширения GNOME Shell.
#
# Собирайте на самой старой поддерживаемой системе (Ubuntu 22.04): бинарник
# привязан к версии glibc и работает на ней и на всех более новых.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

APP_NAME="SyMo"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"

if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x .venv/bin/python ]]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
fi

missing=()
for tool in gcc patchelf; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ((${#missing[@]})); then
    echo "❌ Не найдено: ${missing[*]}. Установите: sudo apt install build-essential patchelf" >&2
    exit 1
fi

if ! "$PYTHON" -c "import gi, cairo, psutil, pynput, requests" 2>/dev/null; then
    echo "❌ $PYTHON: нет зависимостей приложения. См. раздел «Сборка» в README." >&2
    exit 1
fi

if ! "$PYTHON" -m nuitka --version >/dev/null 2>&1; then
    echo "📦 Устанавливаю зависимости сборки..."
    "$PYTHON" -m pip install -r requirements-build.txt
fi

VERSION="$("$PYTHON" -c 'from app_core.constants import APP_VERSION; print(APP_VERSION)')"
RELEASE="${APP_NAME}-${VERSION}-linux-$(uname -m)"
STAGE="$DIST_DIR/$RELEASE"

echo "⚙️  $RELEASE: $("$PYTHON" --version), Nuitka $("$PYTHON" -m nuitka --version 2>/dev/null | head -n1)"

optional_modules=()
for module in gi._gi_cairo cairo; do
    if "$PYTHON" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$module') else 1)"; then
        optional_modules+=("--include-module=$module")
    fi
done

rm -rf "$BUILD_DIR" "$STAGE" "$STAGE.tar.gz" "$STAGE.tar.gz.sha256"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

"$PYTHON" -m nuitka \
    --standalone \
    "${optional_modules[@]}" \
    --assume-yes-for-downloads \
    --include-data-files=logo.png=logo.png \
    --output-dir="$BUILD_DIR" \
    --output-filename="$APP_NAME" \
    --python-flag=no_site \
    --python-flag=-O \
    app.py

mkdir -p "$STAGE"
mv "$BUILD_DIR/app.dist" "$STAGE/app"

cat > "$STAGE/symo" <<'EOF_LAUNCHER'
#!/usr/bin/env bash
set -e
DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
if [[ -z "${GDK_BACKEND:-}" && "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    export GDK_BACKEND="wayland,x11"
fi
export GDK_GL="${GDK_GL:-disable}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export LIBGL_DRI3_DISABLE="${LIBGL_DRI3_DISABLE:-1}"
exec "$DIR/app/SyMo" "$@"
EOF_LAUNCHER
chmod +x "$STAGE/symo"

cp install.sh uninstall-symo.sh logo.png README.md README_RU.md "$STAGE/"
[[ -f LICENSE ]] && cp LICENSE "$STAGE/"
chmod +x "$STAGE/install.sh" "$STAGE/uninstall-symo.sh"

tar -C "$DIST_DIR" -czf "$STAGE.tar.gz" "$RELEASE"
(cd "$DIST_DIR" && sha256sum "$RELEASE.tar.gz" > "$RELEASE.tar.gz.sha256")

"$ROOT_DIR/package-gnome-extension.sh" "$DIST_DIR"

echo ""
echo "🎉 Готово:"
echo "   Приложение: $STAGE.tar.gz"
echo "   Проверка:   $STAGE.tar.gz.sha256"
echo "   Установка:  tar xzf $RELEASE.tar.gz && ./$RELEASE/install.sh"
