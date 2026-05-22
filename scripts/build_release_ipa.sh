#!/usr/bin/env bash
# Build release .app with xtool, merge required privacy keys into Info.plist, then create SandStories.ipa.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> xtool dev build -c release (app only)"
xtool dev build -c release

echo "==> merge privacy Info.plist keys"
bash "$ROOT/scripts/merge_privacy_into_app.sh"

OUT_DIR="$ROOT/xtool"
APP_NAME="SandStories"
APP_BUNDLE="${OUT_DIR}/${APP_NAME}.app"
IPA_PATH="${OUT_DIR}/${APP_NAME}.ipa"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "error: missing $APP_BUNDLE" >&2
  exit 1
fi

echo "==> package IPA"
rm -f "$IPA_PATH"
TMP_PAYLOAD="$(mktemp -d)"
trap 'rm -rf "$TMP_PAYLOAD"' EXIT
mkdir -p "$TMP_PAYLOAD/Payload"
cp -R "$APP_BUNDLE" "$TMP_PAYLOAD/Payload/"
(cd "$TMP_PAYLOAD" && zip -qr "$IPA_PATH" Payload)
echo "Wrote $IPA_PATH"
