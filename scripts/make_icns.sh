#!/usr/bin/env bash
#
# make_icns.sh — (re)generate packaging/Divoom.icns from the source app image.
#
# The macOS .app needs a real .icns (divoom.spec references it via icon=). The
# committed packaging/Divoom.icns is produced by this script so it's auditable
# and reproducible rather than an opaque binary. Run it whenever the source
# artwork changes:
#
#     scripts/make_icns.sh
#
# Requires macOS `sips` + `iconutil` (both ship with the OS).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/divoom_gui/web_ui/assets/app_icon.png"
OUT="$ROOT/packaging/Divoom.icns"

if [ ! -f "$SRC" ]; then
    echo "make_icns: source image not found: $SRC" >&2
    exit 1
fi

mkdir -p "$ROOT/packaging"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ICONSET="$WORK/Divoom.iconset"
mkdir -p "$ICONSET"

# The source is a 1024px image (historically a JPEG mis-named .png). Normalize
# to a true PNG, then emit every size Retina asset iconutil expects.
sips -s format png "$SRC" --out "$WORK/base.png" >/dev/null
for sz in 16 32 128 256 512; do
    dbl=$((sz * 2))
    sips -z "$sz" "$sz" "$WORK/base.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
    sips -z "$dbl" "$dbl" "$WORK/base.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET" -o "$OUT"
echo "make_icns: wrote $OUT"
