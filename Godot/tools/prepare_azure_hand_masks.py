#!/usr/bin/env python3
"""Generate hand/arm binary masks for ProPainter from a processed Azure Kinect
Godot session.

Primary mask source: the per-frame depth-based `occlusionMask` PNGs produced by
prepare_production_session.py (pixels closer to the camera than the fixed sand
baseline, i.e. the hand/arm above the surface). This is far more reliable for a
fixed top-down camera than open-vocabulary YOLO-World detection.

Optionally, YOLO-World `hand. arm.` boxes can be OR'd in as an additional
signal. Output is one grayscale PNG per frame (white = region ProPainter should
inpaint), numbered like the reference pipeline (00001.png ...).

"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def _load_manifest(session_dir: Path) -> dict:
    return json.loads((session_dir / "processed_manifest.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--occlusion-key", default="occlusionMask")
    parser.add_argument("--mask-dilate", type=int, default=6,
                        help="Dilation applied to the combined mask before writing.")
    parser.add_argument("--min-pixels", type=int, default=120,
                        help="Drop masks with fewer than this many white pixels.")
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--yolo-model", default="")
    parser.add_argument("--yolo-classes", nargs="+", default=["hand", "arm"])
    parser.add_argument("--yolo-confidence", type=float, default=0.10)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    manifest = _load_manifest(session_dir)
    frames = manifest["frames"]
    if args.start_frame > 0:
        frames = frames[args.start_frame:]
    if args.max_frames is not None:
        frames = frames[: args.max_frames]

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    yolo = None
    if args.yolo_model:
        from ultralytics import YOLO
        import torch

        yolo = YOLO(args.yolo_model)
        if hasattr(yolo, "set_classes"):
            yolo.set_classes(args.yolo_classes)
        device = args.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = ""

    total = 0
    active = 0
    report = []
    for idx, frame in enumerate(frames, start=1):
        mask_path = session_dir / frame[args.occlusion_key]
        mask = np.asarray(Image.open(mask_path).convert("L")) > 0
        if yolo is not None:
            rgb_path = session_dir / frame["cleanRgb"]
            rgb = np.asarray(Image.open(rgb_path).convert("RGB"), dtype=np.uint8)
            results = yolo.predict(rgb, conf=args.yolo_confidence, verbose=False, device=device)
            h, w = mask.shape
            yolo_mask = np.zeros((h, w), dtype=bool)
            for result in results:
                names = getattr(result, "names", None) or {}
                for box in result.boxes:
                    label = str(names.get(int(box.cls[0]), "")).lower()
                    if not any(tok in label for tok in args.yolo_classes):
                        continue
                    x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].tolist()]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    yolo_mask[y1:y2, x1:x2] = True
            mask = mask | yolo_mask
        if args.mask_dilate > 0 and mask.any():
            from scipy import ndimage

            mask = ndimage.binary_dilation(mask, iterations=args.mask_dilate)
        pixels = int(mask.sum())
        if pixels < args.min_pixels:
            mask = np.zeros_like(mask)
            pixels = 0
        name = f"{idx:05d}.png"
        Image.fromarray(mask.astype(np.uint8) * 255, "L").save(out_dir / name)
        total += 1
        if pixels > 0:
            active += 1
        report.append({
            "index": idx,
            "file": name,
            "frameIndex": int(frame.get("frameIndex", idx)),
            "maskPixels": pixels,
        })

    (out_dir / "mask_report.json").write_text(json.dumps({
        "totalFrames": total,
        "activeFrames": active,
        "emptyFrames": total - active,
        "maskSource": f"depth occlusion ({args.occlusion_key})"
        + (f" + yolo {args.yolo_classes}" if yolo else ""),
        "maskDilatePixels": args.mask_dilate,
        "minPixels": args.min_pixels,
        "device": device or "depth-only",
        "sourceSession": str(session_dir),
        "sourceFrameCount": len(manifest["frames"]),
        "frames": report,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": total, "active": active, "report": str(out_dir / "mask_report.json")}))


if __name__ == "__main__":
    main()
