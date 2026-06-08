#!/usr/bin/env bash
# Pack the local Darwin SDK for uploading as DARWIN_SDK_TARBALL_URL (one-time CI bootstrap).
# Run on WSL/Linux after: xtool setup  (with Xcode_16.3.xip).
set -euo pipefail

SDK_DIR="${HOME}/.swiftpm/swift-sdks/darwin.artifactbundle"
OUT="${1:-darwin-sdk.tar.gz}"

if [[ ! -d "$SDK_DIR" ]]; then
  echo "error: missing $SDK_DIR — run 'xtool setup' with Xcode.xip first" >&2
  exit 1
fi

echo "Packing $(du -sh "$SDK_DIR" | cut -f1) from $SDK_DIR"
tar -czf "$OUT" -C "${HOME}/.swiftpm/swift-sdks" darwin.artifactbundle
echo "Wrote $OUT"
echo ""
echo "Upload this file to private storage (Drive, S3, GitHub Release asset, etc.)"
echo "Add the download URL as GitHub secret: DARWIN_SDK_TARBALL_URL"
