#!/usr/bin/env bash
# Merge AppSupport/SandStories-App-Info.plist into xtool/SandStories.app/Info.plist
# (xtool-generated bundles omit privacy keys unless merged after build.)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_PLIST="${ROOT}/xtool/SandStories.app/Info.plist"
EXTRA_PLIST="${ROOT}/AppSupport/SandStories-App-Info.plist"
if [[ ! -f "$APP_PLIST" ]]; then
  echo "error: missing $APP_PLIST — run xtool dev build first" >&2
  exit 1
fi
if [[ ! -f "$EXTRA_PLIST" ]]; then
  echo "error: missing $EXTRA_PLIST" >&2
  exit 1
fi
python3 - "$ROOT" <<'PY'
import plistlib
import os
import sys
from pathlib import Path
root = Path(sys.argv[1])
app_plist = root / "xtool" / "SandStories.app" / "Info.plist"
extra_plist = root / "AppSupport" / "SandStories-App-Info.plist"
base = plistlib.loads(app_plist.read_bytes())
extra = plistlib.loads(extra_plist.read_bytes())
for k, v in extra.items():
    base[k] = v
run_number = os.environ.get("GITHUB_RUN_NUMBER")
run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
commit = os.environ.get("GITHUB_SHA", "local")
if run_number and run_number.isdigit():
    base["CFBundleVersion"] = f"{run_number}.{run_attempt}"
base["SandStoriesBuildRun"] = run_number or "local"
base["SandStoriesBuildCommit"] = commit
app_plist.write_bytes(plistlib.dumps(base))
print("Merged privacy keys and build fingerprint into", app_plist)
PY
