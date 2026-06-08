#!/usr/bin/env bash
# Install xtool on GitHub Actions macOS runners (Xcode / iOS SDK is preinstalled).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/.github/xtool-version.env"

: "${XTOOL_VERSION:?}"

XTOOL_APP="/Applications/xtool.app"
XTOOL_BIN="${XTOOL_APP}/Contents/Resources/bin/xtool"

add_xtool_to_path() {
  local bin_dir
  bin_dir="$(dirname "$XTOOL_BIN")"
  export PATH="${bin_dir}:${PATH}"
  if [[ -n "${GITHUB_PATH:-}" ]]; then
    echo "$bin_dir" >>"$GITHUB_PATH"
  fi
}

if [[ -x "$XTOOL_BIN" ]]; then
  add_xtool_to_path
  xtool --version
  exit 0
fi

if command -v xtool >/dev/null; then
  xtool --version
  exit 0
fi

echo "==> Install xtool ${XTOOL_VERSION} from release zip"
TMP_ZIP="$(mktemp -t xtool.XXXXXX.zip)"
trap 'rm -f "$TMP_ZIP"' EXIT
curl -fL \
  "https://github.com/xtool-org/xtool/releases/download/${XTOOL_VERSION}/xtool.app.zip" \
  -o "$TMP_ZIP"
unzip -q "$TMP_ZIP" -d /Applications

if [[ ! -x "$XTOOL_BIN" ]]; then
  echo "error: xtool binary missing at $XTOOL_BIN" >&2
  exit 1
fi

add_xtool_to_path
xtool --version
