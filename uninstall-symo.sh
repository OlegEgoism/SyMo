#!/usr/bin/env bash
# Удаление SyMo. С флагом --purge удаляются также настройки, токены и лог.
set -euo pipefail

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help) echo "Использование: $0 [--purge]"; exit 0 ;;
    *) echo "Неизвестный параметр: $arg" >&2; exit 1 ;;
  esac
done

# Останавливаем только копию из архива: пакетная работает из /opt/symo и остаётся.
if pgrep -u "$(id -u)" -f "^$HOME/.local/opt/SyMo/app/SyMo" >/dev/null 2>&1; then
  echo "Останавливаю запущенный SyMo..."
  pkill -u "$(id -u)" -f "^$HOME/.local/opt/SyMo/app/SyMo" || true
fi

package_installed() {
  dpkg-query -W -f='${Status}' symo 2>/dev/null | grep -q "install ok installed"
}

remove_path() {
  local target="$1"
  # Файлы пакета symo удаляет только apt.
  if dpkg-query -S "$target" >/dev/null 2>&1; then
    return
  fi
  # Ярлык с Hidden=true — это выключенный в настройках автозапуск пакета: без него
  # SyMo снова начнёт запускаться при входе.
  if [[ -f "$target" ]] && package_installed && grep -q '^Hidden=true' "$target"; then
    return
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -w "$(dirname "$target")" ]]; then
      rm -rf "$target"
    else
      sudo rm -rf "$target"
    fi
    echo "Removed $target"
  fi
}

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

PATHS=(
  # Текущая установка (install.sh)
  "$HOME/.local/opt/SyMo"
  "$HOME/.local/bin/symo"
  "$APPS_DIR/SyMo.desktop"
  "$AUTOSTART_DIR/SyMo.desktop"
  # Старые варианты установки
  "$HOME/.local/opt/SyMo-bundle"
  "$HOME/.local/bin/SyMo-onefile"
  "$HOME/.local/bin/SyMo-launch"
  "$HOME/.local/bin/SyMo-run"
  "$APPS_DIR/symo.desktop"
  "$AUTOSTART_DIR/symo.desktop"
  "/opt/SyMo"
  "/opt/SyMo-bundle"
  "/usr/local/bin/symo"
  "/usr/local/bin/SyMo-onefile"
  "/usr/local/bin/SyMo-launch"
  "/usr/local/bin/SyMo-run"
  "/usr/share/applications/SyMo.desktop"
  "/usr/share/applications/symo.desktop"
)

if ((PURGE)); then
  PATHS+=(
    "$HOME/.symo_settings.json"
    "$HOME/.symo_telegram.json"
    "$HOME/.symo_discord.json"
    "$HOME/.symo_log.txt"
    "$HOME/.symo_log.txt.1"
    "$HOME/.symo_app.log"
    "$HOME/.symo_app.log.1"
  )
fi

for path in "${PATHS[@]}"; do
  remove_path "$path"
done

echo "SyMo удалён."
if package_installed; then
  echo "Пакет symo по-прежнему установлен. Удалить его: sudo apt remove symo"
fi
if ((PURGE == 0)); then
  # Сам скрипт мог быть удалён вместе с ~/.local/opt/SyMo, поэтому подсказываем rm.
  echo "Настройки, токены и лог сохранены. Удалить их: rm -f ~/.symo_*.json ~/.symo_log.txt ~/.symo_log.txt.1"
fi
