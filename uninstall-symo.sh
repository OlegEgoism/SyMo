#!/bin/bash

# Удаление SyMo из системы
# Запуск: chmod +x uninstall-symo.sh && ./uninstall-symo.sh

set -e  # Выход при ошибке

echo "🗑️ Начинаем удаление SyMo..."

# Пути к файлам
HOME_DIR="$HOME"
APP_DIR="$HOME_DIR/SyMo-standalone"
ONEFILE="$HOME_DIR/SyMo-onefile"
RUNNER="$HOME_DIR/SyMo-run"
DESKTOP_MENU="$HOME_DIR/.local/share/applications/SyMo.desktop"
DESKTOP_AUTOSTART="$HOME_DIR/.config/autostart/SyMo.desktop"

# Функция удаления с проверкой
safe_remove() {
    local path="$1"
    local desc="$2"
    if [[ -e "$path" ]]; then
        rm -rf "$path"
        echo "✅ Удалён $desc: $path"
    else
        echo "ℹ️  Не найден $desc: $path"
    fi
}

# Проверка запущенных процессов
echo "🔍 Проверка запущенных процессов..."
if pgrep -f "SyMo\|app.dist" > /dev/null; then
    echo "⚠️  Обнаружены запущенные процессы SyMo!"
    echo "   Остановите их перед удалением:"
    echo "   killall app  # или killall SyMo-onefile"
    echo "   Или выполните: pkill -f app"
    exit 1
fi

echo "🟢 Никаких процессов SyMo не запущено. Продолжаем..."

# Удаление по одному
echo ""
echo "🗑️ Удаляем компоненты..."

safe_remove "$APP_DIR"           "папка standalone"
safe_remove "$ONEFILE"           "onefile-исполняемый файл"
safe_remove "$RUNNER"            "скрипт запуска (SyMo-run)"
safe_remove "$DESKTOP_MENU"      "ярлык в меню приложений"
safe_remove "$DESKTOP_AUTOSTART" "автозапуск в системе"

# Дополнительно: временные папки
safe_remove "$HOME_DIR/build_standalone" "временная папка сборки"

# Финал
echo ""
echo "🎉 SyMo полностью удалён из системы!"
echo "💡 Совет: чтобы переустановить — просто перезапустите build.sh"