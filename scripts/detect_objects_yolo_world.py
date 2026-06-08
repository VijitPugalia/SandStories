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
import json
import os
import sys
from pathlib import Path
from typing import List, Dict

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
    return frames


def load_model() -> YOLO:
    """Load the YOLO-World model.
    YOLO-World provides a ``yolo-world`` checkpoint name. If the model is not
    cached locally, Ultralytics will download it automatically.
    """
    # Using the small model for speed; can be changed to 'yolo-world-s' or
    # a custom checkpoint path if desired.
    return YOLO("yolo-world-s.pt")


def run_inference(model: YOLO, image_path: Path) -> List[Dict]:
    """Run inference on a single image and return a list of detection dicts.
    Each detection dict contains:
        - class (str)
        - confidence (float)
        - bbox (list) [x_min, y_min, x_max, y_max]
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Failed to read image {image_path}")
    results = model(img)
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


def process_session(session_dir: Path, model: YOLO):
    """Process all frames in a session folder and write `objects.jsonl`.
    Existing `objects.jsonl` will be overwritten to avoid stale data.
    """
    frames = get_frame_paths(session_dir)
    if not frames:
        sys.stderr.write(f"[detect_objects_yolo_world] Warning: No RGB frames found in {session_dir}\n")
        return

    output_path = session_dir / "objects.jsonl"
    # Ensure we start from a clean file.
    if output_path.exists():
        output_path.unlink()

    batch_records = []
    for idx, frame_path in enumerate(frames):
        try:
            dets = run_inference(model, frame_path)
        except Exception as exc:
            sys.stderr.write(f"[detect_objects_yolo_world] Frame {frame_path} error: {exc}\n")
            dets = []
        batch_records.append({"frame_index": idx, "detections": dets})
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
    args = parser.parse_args()

    model = load_model()

    if args.session:
        session_path = Path(args.session).resolve()
        if not session_path.is_dir():
            sys.stderr.write(f"[detect_objects_yolo_world] Error: {session_path} is not a directory\n")
            sys.exit(1)
        process_session(session_path, model)
    else:
        root_path = Path(args.batch).resolve()
        if not root_path.is_dir():
            sys.stderr.write(f"[detect_objects_yolo_world] Error: {root_path} is not a directory\n")
            sys.exit(1)
        # Find all immediate subfolders that contain an `rgb_*.` pattern.
        for session_dir in root_path.iterdir():
            if session_dir.is_dir():
                # Quick check for at least one frame to avoid unnecessary work.
                if any(session_dir.glob("rgb_*.jpg")) or any(session_dir.glob("rgb_*.png")):
                    process_session(session_dir, model)

if __name__ == "__main__":
    main()
