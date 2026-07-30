#!/usr/bin/env python3
"""Render RGB overlays for fitted hand-only MANO arrays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from fit_mano_hand_only_2d import _draw_overlay


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        default="hamer_inference_manifest.json",
    )
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--frames",
        default="all",
        help="all or comma-separated zero-based frame indices",
    )
    parser.add_argument(
        "--image-pattern",
        default="clean_rgb_{frame:06d}.png",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    args.fit_dir = args.fit_dir.resolve()
    args.rgb_dir = args.rgb_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    manifest_path = args.fit_dir / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {
        int(record["frameIndex"]): record for record in manifest["frames"]
    }
    if args.frames == "all":
        frames = sorted(records)
    else:
        frames = sorted(
            {
                int(item.strip())
                for item in args.frames.split(",")
                if item.strip()
            }
        )
    missing = [frame for frame in frames if frame not in records]
    if missing:
        raise KeyError(f"Frames absent from fit manifest: {missing}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for frame in frames:
        arrays = np.load(args.fit_dir / records[frame]["arrays"])
        image_path = args.rgb_dir / args.image_pattern.format(frame=frame)
        image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise FileNotFoundError(image_path)
        overlay = _draw_overlay(
            image_bgr,
            arrays["vertex_uv"],
            arrays["joint_uv"],
            arrays["crop_landmarks_xy"],
            arrays["faces"].astype(np.int32),
        )
        output_path = args.output_dir / f"mano_hand_only_{frame:06d}.png"
        if not cv2.imwrite(str(output_path), overlay):
            raise RuntimeError(f"Failed to write {output_path}")
        print(output_path.name, flush=True)


if __name__ == "__main__":
    main()
