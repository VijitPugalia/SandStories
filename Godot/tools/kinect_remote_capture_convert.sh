#!/usr/bin/env bash
set -euo pipefail

ROOT="${SANDSTORIES_REMOTE_ROOT:-$HOME/SandStoriesRemote}"
LIBFREENECT_BUILD="${LIBFREENECT_BUILD:-$HOME/libfreenect/build}"
DURATION="${1:-4}"
SESSION_ID="${2:-kinect_$(date +%Y%m%d_%H%M%S)}"
STRIDE="${STRIDE:-9}"
REGISTERED_FRAMES="${REGISTERED_FRAMES:-48}"
BUILD_REGISTERED_SMOOTH="${BUILD_REGISTERED_SMOOTH:-1}"

RECORD_DIR="$ROOT/recordings/$SESSION_ID"
PROJECT_DIR="$ROOT/Godot"

mkdir -p "$ROOT/recordings" "$PROJECT_DIR/assets/processed_sessions" "$ROOT/diagnostics"

echo "Recording Kinect to $RECORD_DIR for ${DURATION}s"
rm -rf "$RECORD_DIR"
timeout "${DURATION}s" "$LIBFREENECT_BUILD/bin/fakenect-record" "$RECORD_DIR" || true

DEPTH_COUNT=$(find "$RECORD_DIR" -maxdepth 1 -name 'd-*.pgm' | wc -l)
RGB_COUNT=$(find "$RECORD_DIR" -maxdepth 1 -name 'r-*.ppm' | wc -l)
echo "Captured depth=$DEPTH_COUNT rgb=$RGB_COUNT"
if [ "$DEPTH_COUNT" -eq 0 ] || [ "$RGB_COUNT" -eq 0 ]; then
  echo "No usable Kinect frames captured." >&2
  exit 1
fi

python3 "$PROJECT_DIR/tools/convert_kinect_record_session.py" "$RECORD_DIR" \
  --project "$PROJECT_DIR" \
  --session-id "$SESSION_ID" \
  --stride "$STRIDE"

OUT_DIR="$PROJECT_DIR/assets/processed_sessions/session_$SESSION_ID"
cp "$OUT_DIR/frame_contact_sheet.png" "$ROOT/diagnostics/${SESSION_ID}_contact_sheet.png"
cp "$OUT_DIR/processed_manifest.json" "$ROOT/diagnostics/${SESSION_ID}_processed_manifest.json"

REGISTERED_SESSION_JSON=""
if [ "$BUILD_REGISTERED_SMOOTH" = "1" ] \
  && [ -x "$PROJECT_DIR/tools/fakenect_registered_dump" ] \
  && [ -x "$LIBFREENECT_BUILD/fakenect/fakenect.sh" ]; then
  FRAMES_TO_DUMP="$REGISTERED_FRAMES"
  if [ "$DEPTH_COUNT" -lt "$FRAMES_TO_DUMP" ]; then
    FRAMES_TO_DUMP="$DEPTH_COUNT"
  fi
  REGISTERED_SKIP=$(( DEPTH_COUNT / FRAMES_TO_DUMP ))
  if [ "$REGISTERED_SKIP" -lt 1 ]; then
    REGISTERED_SKIP=1
  fi

  REGISTERED_DIR="$ROOT/diagnostics/${SESSION_ID}_official_registered"
  TEMPORAL_DIR="$ROOT/diagnostics/${SESSION_ID}_temporal_smooth_metric"
  REGISTERED_SESSION_ID="${SESSION_ID}_temporal_smooth_godot"

  echo "Building official registered temporal smooth session: frames=$FRAMES_TO_DUMP skip=$REGISTERED_SKIP"
  rm -rf "$REGISTERED_DIR" "$TEMPORAL_DIR"
  mkdir -p "$REGISTERED_DIR"
  (
    cd "$REGISTERED_DIR"
    "$LIBFREENECT_BUILD/fakenect/fakenect.sh" "$RECORD_DIR" \
      "$PROJECT_DIR/tools/fakenect_registered_dump" "$FRAMES_TO_DUMP" "$REGISTERED_SKIP" official
  )

  python3 "$PROJECT_DIR/tools/repair_registered_rgb_from_recording.py" \
    --record-dir "$RECORD_DIR" \
    --registered-dir "$REGISTERED_DIR" \
    --prefix official \
    --frames "$FRAMES_TO_DUMP" \
    --skip "$REGISTERED_SKIP"

  python3 "$PROJECT_DIR/tools/official_registered_surface_mesh.py" "$REGISTERED_DIR" \
    --output-dir "$TEMPORAL_DIR" \
    --temporal-fusion \
    --detail-gain 0.0 \
    --max-detail-mm 0 \
    --rgb-visual-mm 0 \
    --stride 2

  REGISTERED_SESSION_JSON=$(python3 "$PROJECT_DIR/tools/prepare_kinect_temporal_godot_session.py" "$TEMPORAL_DIR" \
    --project "$PROJECT_DIR" \
    --session-id "$REGISTERED_SESSION_ID" \
    --height-scale 3.2 \
    --material-strength 0.72)
elif [ "$BUILD_REGISTERED_SMOOTH" = "1" ]; then
  echo "Skipping official registered temporal session; fakenect_registered_dump or fakenect.sh is missing." >&2
fi

cat <<EOF

Done.
Recording: $RECORD_DIR
Processed session: $OUT_DIR/session.json
Contact sheet: $ROOT/diagnostics/${SESSION_ID}_contact_sheet.png
Official registered smooth session: ${REGISTERED_SESSION_JSON:-not generated}

For immediate local debugging, serve the remote workspace with:
  cd "$ROOT" && python3 -m http.server 8780 --bind 0.0.0.0

Then open the contact sheet:
  http://127.0.0.1:8780/diagnostics/${SESSION_ID}_contact_sheet.png

Note: Godot Web index.pck is a static export. A newly captured session will not
be inside that pck unless the Web export is rebuilt or recopied after generation.
The bundled Web export can still open sessions that were packed before export.

To serve the bundled Godot Web export:
  cd "$ROOT/Godot/build/web" && python3 -m http.server 8777 --bind 0.0.0.0

EOF
