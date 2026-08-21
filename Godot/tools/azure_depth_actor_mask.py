#!/usr/bin/env python3
"""Generate raw-depth actor masks (close objects, e.g., hand/arm above sand)."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--threshold-mm", type=float, default=420.0)
    parser.add_argument("--min-area", type=int, default=100)
    parser.add_argument("--frames", type=int, default=0)
    args = parser.parse_args()

    depth_files = sorted(args.depth_dir.glob("depth_*.png"))
    n = len(depth_files)
    if args.frames:
        n = min(n, args.frames)
    if args.out_dir.exists():
        raise FileExistsError(f"refusing to overwrite {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    print(f"session: {args.session.name} frames={n} threshold={args.threshold_mm}mm", flush=True)

    for i in range(n):
        stem = f"{i+1:06d}"
        depth = cv2.imread(str(args.depth_dir / f"depth_{stem}.png"), cv2.IMREAD_UNCHANGED).astype(np.float32)
        mask = ((depth > 0) & (depth < args.threshold_mm)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_k)
        # keep large components
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        out = np.zeros_like(mask)
        for lab in range(1, num):
            if stats[lab, cv2.CC_STAT_AREA] >= args.min_area:
                out[labels == lab] = 255
        cv2.imwrite(str(args.out_dir / f"{stem}.png"), out)
        if (i + 1) % 300 == 0:
            print(f"  ...{i+1}/{n}", flush=True)

    print(f"done: {n} masks -> {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
