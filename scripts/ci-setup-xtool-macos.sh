#!/usr/bin/env bash
# Install xtool on GitHub Actions macOS runners (Xcode / iOS SDK is preinstalled).
set -euo pipefail

if command -v xtool >/dev/null; then
  xtool --version
  exit 0
fi

if command -v brew >/dev/null; then
  brew install xtool-org/tap/xtool
  xtool --version
  exit 0
fi

echo "error: Homebrew not found on macOS runner" >&2
exit 1
