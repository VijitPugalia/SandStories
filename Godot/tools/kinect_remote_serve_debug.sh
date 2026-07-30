#!/usr/bin/env bash
set -euo pipefail

ROOT="${SANDSTORIES_REMOTE_ROOT:-$HOME/SandStoriesRemote}"
PORT="${1:-8780}"

cd "$ROOT"
cat <<EOF
Serving remote Kinect debug workspace:
  $ROOT

Open diagnostics from this machine:
  http://127.0.0.1:$PORT/diagnostics/

Open diagnostics from another machine on the LAN:
  http://$(hostname -I | awk '{print $1}'):$PORT/diagnostics/

Press Ctrl-C to stop.

EOF
python3 -m http.server "$PORT" --bind 0.0.0.0
