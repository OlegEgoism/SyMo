#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="${1:-gnome_extension}"
DIST_DIR="${2:-dist}"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Error: source directory '$SRC_DIR' not found." >&2
  exit 1
fi

if [[ ! -f "$SRC_DIR/metadata.json" ]]; then
  echo "Error: '$SRC_DIR/metadata.json' is required for GNOME extension packaging." >&2
  exit 1
fi

if [[ ! -f "$SRC_DIR/extension.js" ]]; then
  echo "Error: '$SRC_DIR/extension.js' is required for GNOME extension packaging." >&2
  exit 1
fi

UUID=$(python3 - <<'PY' "$SRC_DIR/metadata.json"
import json,sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    print(json.load(f)['uuid'])
PY
)

if [[ -z "$UUID" ]]; then
  echo "Error: uuid in metadata.json is empty." >&2
  exit 1
fi

mkdir -p "$DIST_DIR"
OUT_FILE="$DIST_DIR/${UUID}.zip"

(
  cd "$SRC_DIR"
  rm -f "$OUT_FILE"
  zip -qr "../${OUT_FILE}" .
)

echo "GNOME extension package created: $OUT_FILE"
