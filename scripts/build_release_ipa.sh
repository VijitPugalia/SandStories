#!/usr/bin/env bash
# Build release .app with xtool, merge required privacy keys into Info.plist, then create SandStories.ipa.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CONFIGURATION="${1:-release}"

echo "==> xtool dev build -c ${CONFIGURATION} (app only)"
xtool dev build -c "${CONFIGURATION}"

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

WINDOWS_SHARE_DIR="/mnt/c/Users/vijit/SandStoriesIPA"
if [[ -d "$WINDOWS_SHARE_DIR" ]]; then
  cp "$IPA_PATH" "$WINDOWS_SHARE_DIR/"
  echo "Copied IPA to Windows share: $WINDOWS_SHARE_DIR/SandStories.ipa"
else
  echo "Warning: Windows share directory $WINDOWS_SHARE_DIR does not exist. Skipping copy."
fi

