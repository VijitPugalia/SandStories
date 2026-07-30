#!/usr/bin/env bash
set -euo pipefail

ROOT="${SANDSTORIES_REMOTE_ROOT:-$HOME/SandStoriesRemote}"
PORT="${1:-8777}"

cd "$ROOT/Godot/build/web"
cat <<EOF
Serving bundled Godot Web export:
  $ROOT/Godot/build/web

Bundled current Kinect-down sample:
  http://127.0.0.1:$PORT/index.html?session=res://assets/processed_sessions/session_kinect_eval_record_down/session.json&debug=1&kinect=down

From another LAN machine, replace 127.0.0.1 with:
  $(hostname -I | awk '{print $1}')

Note: newly generated sessions are not automatically inside index.pck. Use
kinect_remote_serve_debug.sh for new contact sheets, or rebuild/copy a new Web
export after generating a session.

Press Ctrl-C to stop.

EOF
python3 -m http.server "$PORT" --bind 0.0.0.0
