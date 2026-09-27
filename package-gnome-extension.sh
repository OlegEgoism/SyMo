#!/usr/bin/env bash
# Собирает архивы расширения SyMo Launcher для extensions.gnome.org.
# Для одного UUID загружаются две версии:
#   gnome-42-44 — старый формат imports.* (Ubuntu 22.04);
#   gnome-45    — ES-модули (Ubuntu 24.04 и новее).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$ROOT_DIR/gnome_extension"
DIST_DIR="${1:-$ROOT_DIR/dist}"
VARIANTS=(gnome-42-44 gnome-45)

mkdir -p "$DIST_DIR"

read_metadata() {
  python3 - "$1" "$2" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]
print(" ".join(value) if isinstance(value, list) else value)
PY
}

for variant in "${VARIANTS[@]}"; do
  dir="$SRC_DIR/$variant"
  for required in metadata.json extension.js; do
    if [[ ! -f "$dir/$required" ]]; then
      echo "Error: $dir/$required not found." >&2
      exit 1
    fi
  done

  uuid="$(read_metadata "$dir/metadata.json" uuid)"
  shells="$(read_metadata "$dir/metadata.json" shell-version)"
  out="$DIST_DIR/${uuid%%@*}-launcher-${variant}.shell-extension.zip"
  rm -f "$out"

  if command -v gnome-extensions >/dev/null 2>&1; then
    tmp="$(mktemp -d)"
    gnome-extensions pack "$dir" --force --out-dir="$tmp" >/dev/null
    mv "$tmp/$uuid.shell-extension.zip" "$out"
    rmdir "$tmp"
  else
    (cd "$dir" && zip -qr -X "$out" metadata.json extension.js)
  fi

  echo "✔ $variant (GNOME $shells): $out"
done
