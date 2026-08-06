# detect_objects_yolo_world.py
"""
Object detection script using YOLO-World (Ultralytics) for SandStories sessions.

The script scans a given session folder for RGB frames (or video) and runs
YOLO-World inference, writing detection results to `objects.jsonl` in the
session directory. The JSONL format matches the expectations of the
`evaluate_session.py` metric script (one JSON object per line, each object
contains `frame_index`, `detections` list with `class`, `confidence`, and
`bbox` coordinates).

Usage:
    python3 detect_objects_yolo_world.py --session <path_to_session_folder>
    python3 detect_objects_yolo_world.py --batch <path_to_root_folder>

Dependencies:
    ultralytics>=8.2.0 (provides YOLO-World models)
    opencv-python (for frame reading)

The script creates the model once per process and re‑uses it for batch
processing. Errors are logged but do not abort the whole run – a best‑effort
approach is preferred because the downstream evaluation can handle missing
or empty `objects.jsonl`.
"""

import argparse
import itertools
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

# Attempt to import required libraries; if missing, provide a clear error.
try:
    import cv2
except ImportError as e:
    sys.stderr.write("[detect_objects_yolo_world] Error: opencv-python is required. Install with 'pip install opencv-python'.\n")
    raise

try:
    from ultralytics import YOLO
except ImportError as e:
    sys.stderr.write("[detect_objects_yolo_world] Error: ultralytics is required. Install with 'pip install ultralytics'.\n")
    raise

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def get_frame_paths(session_dir: Path) -> List[Path]:
    """Return a sorted list of image frame paths inside a session.
    The SandStories capture pipeline stores RGB frames as
    `rgb_*.jpg` (or `.png`). We look for common extensions.
    """
    img_exts = [".jpg", ".jpeg", ".png", ".bmp"]
    frames = []
    for ext in img_exts:
        frames.extend(sorted(session_dir.glob(f"rgb_*{ext}")))
        frames.extend(sorted((session_dir / "rgb").glob(f"r_*{ext}")))
    return sorted(set(frames))


def get_v2_video_path(session_dir: Path) -> Path | None:
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    streams = manifest.get("v2Streams") or {}
    video_path = session_dir / streams.get("rgbVideoPath", "streams/rgb.mp4")
    return video_path if video_path.is_file() else None


def iter_session_frames(session_dir: Path, sample_fps: float) -> Iterator[Tuple[int, float | None, object]]:
    """Yield legacy RGB images or sampled frames from a v2 RGB video."""
    frame_paths = get_frame_paths(session_dir)
    if frame_paths:
        for frame_index, frame_path in enumerate(frame_paths):
            image = cv2.imread(str(frame_path))
            if image is None:
                raise ValueError(f"Failed to read image {frame_path}")
            yield frame_index, None, image
        return

    video_path = get_v2_video_path(session_dir)
    if video_path is None:
        return
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Failed to open RGB video {video_path}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    if source_fps <= 0:
        source_fps = 30.0
    stride = max(1, int(round(source_fps / max(sample_fps, 0.01))))
    frame_index = 0
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                break
            if frame_index % stride == 0:
                yield frame_index, frame_index / source_fps, image
            frame_index += 1
    finally:
        capture.release()


def load_model(classes: List[str] | None = None) -> YOLO:
    """Load the YOLO-World model.
    YOLO-World provides a ``yolo-world`` checkpoint name. If the model is not
    cached locally, Ultralytics will download it automatically.
    """
    # Using the small model for speed; can be changed to 'yolo-world-s' or
    # a custom checkpoint path if desired.
    model = YOLO("yolov8s-worldv2.pt")
    if classes:
        model.set_classes(classes)
    return model


def run_inference(model: YOLO, image) -> List[Dict]:
    """Run inference on a single image and return a list of detection dicts.
    Each detection dict contains:
        - class (str)
        - confidence (float)
        - bbox (list) [x_min, y_min, x_max, y_max]
    """
    results = model(image, verbose=False)
    detections = []
    for r in results:
        for box in r.boxes:
            cls_id = int(box.cls[0]) if box.cls is not None else -1
            class_name = model.names.get(cls_id, "unknown") if hasattr(model, "names") else str(cls_id)
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            # bbox format: [x1, y1, x2, y2]
            bbox = [float(v) for v in box.xyxy[0].tolist()]
            detections.append({
                "class": class_name,
                "confidence": conf,
                "bbox": bbox,
            })
    return detections


def write_jsonl(output_path: Path, records: List[Dict]):
    """Append detection records to a JSONL file.
    Each record corresponds to a single frame and contains:
        {"frame_index": int, "detections": [...]}
    """
    with output_path.open("a", encoding="utf-8") as f:
        for rec in records:
            json.dump(rec, f)
            f.write("\n")


def process_session(
    session_dir: Path,
    model: YOLO,
    sample_fps: float = 2.0,
    output_path: Path | None = None,
):
    """Process all frames in a session folder and write `objects.jsonl`.
    Existing `objects.jsonl` will be overwritten to avoid stale data.
    """
    frame_iterator = iter_session_frames(session_dir, sample_fps)
    try:
        first_frame = next(frame_iterator)
    except StopIteration:
        sys.stderr.write(f"[detect_objects_yolo_world] Warning: No RGB frames or v2 video found in {session_dir}\n")
        return

    output_path = output_path or (session_dir / "objects.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure we start from a clean file.
    if output_path.exists():
        output_path.unlink()

    batch_records = []
    for frame_index, rgb_time_seconds, image in itertools.chain([first_frame], frame_iterator):
        try:
            dets = run_inference(model, image)
        except Exception as exc:
            sys.stderr.write(f"[detect_objects_yolo_world] Frame {frame_index} error: {exc}\n")
            dets = []
        record = {"frame_index": frame_index, "detections": dets}
        if rgb_time_seconds is not None:
            record["rgb_time_seconds"] = rgb_time_seconds
        batch_records.append(record)
        # Flush every 100 frames to keep memory usage modest.
        if len(batch_records) >= 100:
            write_jsonl(output_path, batch_records)
            batch_records.clear()
    # Write any remaining records.
    if batch_records:
        write_jsonl(output_path, batch_records)
    sys.stdout.write(f"[detect_objects_yolo_world] Completed {session_dir}, wrote {output_path}\n")


def main():
    parser = argparse.ArgumentParser(description="Run YOLO-World detection on SandStories session data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session", type=str, help="Path to a single session folder")
    group.add_argument("--batch", type=str, help="Path to a root directory containing multiple session folders (processed recursively)")
    parser.add_argument("--sample-fps", type=float, default=2.0, help="Sampling rate for v2 RGB video (default: 2 fps)")
    parser.add_argument("--output", type=Path, help="Output JSONL path for a single session; use a derived path to preserve package hashes")
    parser.add_argument("--classes", type=str, help="Comma-separated open-vocabulary class prompts")
    args = parser.parse_args()

    if args.batch and args.output:
        parser.error("--output can only be used with --session")
    classes = [value.strip() for value in args.classes.split(",") if value.strip()] if args.classes else None
    model = load_model(classes)

    if args.session:
        session_path = Path(args.session).resolve()
        if not session_path.is_dir():
            sys.stderr.write(f"[detect_objects_yolo_world] Error: {session_path} is not a directory\n")
            sys.exit(1)
        process_session(
            session_path,
            model,
            sample_fps=args.sample_fps,
            output_path=args.output.resolve() if args.output else None,
        )
    else:
        root_path = Path(args.batch).resolve()
        if not root_path.is_dir():
            sys.stderr.write(f"[detect_objects_yolo_world] Error: {root_path} is not a directory\n")
            sys.exit(1)
        # Find all immediate subfolders that contain an `rgb_*.` pattern.
        for session_dir in root_path.iterdir():
            if session_dir.is_dir():
                # Quick check for at least one frame to avoid unnecessary work.
                if get_frame_paths(session_dir) or get_v2_video_path(session_dir):
                    process_session(session_dir, model, sample_fps=args.sample_fps)

if __name__ == "__main__":
    main()
