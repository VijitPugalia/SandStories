# Kinect Example Session

This project includes one cleaned Kinect example session through Git LFS:

`assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold/session.json`

The session contains 714 processed frames from the fixed-camera Kinect capture. PNG frame assets are tracked by Git LFS because the directory is about 475 MB. Other processed sessions remain ignored and should be served as external static assets unless deliberately added with LFS.

## Godot Web URL

Serve `Godot/` locally, then open:

```text
http://127.0.0.1:8809/build/web/index.html?session=http://127.0.0.1:8809/assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold/session.json&debug=1&autoplay=1&kinect=rgb_reference_bold
```

## Generation Command

The example was produced with:

```bash
python tools/remove_foreground_objects.py \
  assets/processed_sessions/session_kinect_20260623_154953 \
  --output-dir assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold \
  --confidence 0.03 \
  --yolo-model yolov8s-world.pt \
  --sam-checkpoint /tmp/opencode/sam_vit_b_01ec64.pth \
  --sam-model-type vit_b \
  --device auto \
  --mask-dilate 9 \
  --depth-mask-dilate 24 \
  --depth-temporal-radius 1 \
  --depth-reference-repair \
  --depth-reference-threshold 22 \
  --depth-reference-min-area 120 \
  --depth-reference-dilate 8 \
  --rgb-reference-repair \
  --rgb-mask-dilate 4 \
  --rgb-temporal-radius 1 \
  --rgb-include-depth-mask \
  --rgb-reference-alpha 0.12 \
  --rgb-feather 14 \
  --surface-trim-col-ratio 0.7 \
  --surface-trim-row-ratio 0.22
```

The RGB cleanup is intentionally aggressive for this example. It removes more hand/finger contamination on the sand surface, but reference patches can still show visible tone boundaries.

## MediaPipe Virtual Hands

The cleaned example can render virtual hands from a sidecar generated from the original, uncleaned RGB-D session:

`assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold/hand_tracks_mediapipe.json`

The sidecar stores Godot-space `hand_tracks` plus per-frame MediaPipe debug data. The track points are MediaPipe RGB landmarks projected onto the same 5.5 x 5.5 Godot sand plane and lifted with the matching per-frame depth/height image. This is an overlay aligned to the current heightmap shader, not a calibrated Kinect millimetre-space skeletal reconstruction.

Generate or refresh it with:

```bash
python tools/extract_mediapipe_hands.py \
  assets/processed_sessions/session_kinect_20260623_154953 \
  --output assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold/hand_tracks_mediapipe.json \
  --attach-session assets/processed_sessions/session_kinect_20260623_154953_object_removed_sam_full_gpu_rgb_reference_repair_bold
```

Use the original session as the source because the cleaned example has the hands removed from RGB. The `--attach-session` argument updates the cleaned `session.json` with `data_sources.hand_tracks`, so Godot loads the sidecar before building the existing virtual hand renderer.
