#!/usr/bin/env bash
# Install xtool + ensure Darwin Swift SDK for GitHub Actions / Linux CI.
# See docs/CI.md for one-time SDK bootstrap.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/.github/xtool-version.env"

: "${XTOOL_VERSION:?}"
: "${SWIFT_VERSION:?}"

export APPIMAGE_EXTRACT_AND_RUN=1

echo "==> Swift ${SWIFT_VERSION}"
if ! command -v swift >/dev/null; then
  echo "error: swift not on PATH — workflow should run swift-actions/setup-swift first" >&2
  exit 1
fi
swift --version

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) XTOOL_ARCH="x86_64" ;;
  aarch64|arm64) XTOOL_ARCH="aarch64" ;;
  *)
    echo "error: unsupported arch: $ARCH" >&2
    exit 1
    ;;
esac

XTOOL_URL="https://github.com/xtool-org/xtool/releases/download/${XTOOL_VERSION}/xtool-${XTOOL_ARCH}.AppImage"
echo "==> xtool ${XTOOL_VERSION} (${XTOOL_ARCH})"
curl -fL "$XTOOL_URL" -o /tmp/xtool.AppImage
chmod +x /tmp/xtool.AppImage
sudo mv /tmp/xtool.AppImage /usr/local/bin/xtool
xtool --version

echo "==> Darwin Swift SDK"
if xtool sdk status 2>/dev/null | grep -q "Installed at"; then
  xtool sdk status
  exit 0
fi

# Optional: pre-built SDK tarball (maintainer uploads after local xtool setup).
if [[ -n "${DARWIN_SDK_TARBALL_URL:-}" ]]; then
  echo "Installing SDK from DARWIN_SDK_TARBALL_URL"
  curl -fL "$DARWIN_SDK_TARBALL_URL" -o /tmp/darwin-sdk.tar.gz
  mkdir -p "${HOME}/.swiftpm/swift-sdks"
  tar -xzf /tmp/darwin-sdk.tar.gz -C "${HOME}/.swiftpm/swift-sdks"
  rm -f /tmp/darwin-sdk.tar.gz
  xtool sdk status
  exit 0
fi

# Optional: install from Xcode.xip on a self-hosted runner (path in secret).
if [[ -n "${XCODE_XIP_PATH:-}" && -f "${XCODE_XIP_PATH}" ]]; then
  echo "Installing SDK from XCODE_XIP_PATH"
  xtool sdk install "${XCODE_XIP_PATH}"
  xtool sdk status
  exit 0
fi

cat >&2 <<'EOF'
error: No Darwin Swift SDK available.

CI needs the iOS SDK once. Choose one bootstrap path (docs/CI.md):

  1. Add repo secret DARWIN_SDK_TARBALL_URL pointing to a tarball of
     ~/.swiftpm/swift-sdks/darwin.artifactbundle (create with scripts/ci-pack-darwin-sdk.sh).

  2. Use a self-hosted runner with Xcode_16.3.xip and set secret XCODE_XIP_PATH.

  3. After a successful run, GitHub Actions cache for ~/.swiftpm/swift-sdks may
     satisfy later runs if the cache was seeded manually.

EOF
exit 1
