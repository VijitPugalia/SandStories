#!/usr/bin/env python3
"""Generate hand/arm-free RGB conditioning for Any2Full.

For each frame, take the ProPainter display_rgb_full frame and inpaint the
hand/arm mask region (dilated a bit) using surrounding sand texture, so Any2Full
never sees hand-like RGB structure. Output: frame_%06d.png.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--mask-dir", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dilate", type=int, default=8)
    parser.add_argument("--radius", type=int, default=5)
    parser.add_argument("--mode", choices=["inpaint", "first_frame", "blend"], default="inpaint")
    parser.add_argument("--frames", type=int, default=0)
    parser.add_argument("--frame-indices", type=str, default="")
    args = parser.parse_args()

    rgb_files = sorted(args.rgb_dir.glob("frame_*.png"))
    mask_files = sorted(args.mask_dir.glob("*.png"))
    first_img = cv2.imread(str(args.rgb_dir / "frame_000001.png")) if args.mode in ("first_frame", "blend") else None
    n = min(len(rgb_files), len(mask_files))
    if args.frames:
        n = min(n, args.frames)
    frame_indices = []
    if args.frame_indices:
        frame_indices = [int(x) for x in args.frame_indices.split(",") if x.strip()]
        n = len(frame_indices)
    if args.out_dir.exists():
        raise FileExistsError(f"refusing to overwrite {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.dilate * 2 + 1, args.dilate * 2 + 1))
    print(f"frames: {n} (rgb={len(rgb_files)} masks={len(mask_files)})", flush=True)

    for idx in range(n):
        i = (frame_indices[idx] - 1) if frame_indices else idx
        rgb_src = rgb_files[i]
        mask_src = mask_files[i]
        stem = f"frame_{i+1:06d}.png"
        img = cv2.imread(str(rgb_src))
        if img is None:
            raise FileNotFoundError(rgb_src)
        mask = cv2.imread(str(mask_src), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise FileNotFoundError(mask_src)
        mask = (mask > 0).astype(np.uint8) * 255
        mask = cv2.dilate(mask, kernel)
        if mask.sum() == 0:
            out = img
        elif args.mode == "first_frame":
            out = img.copy()
            out[mask > 0] = first_img[mask > 0]
        elif args.mode == "blend":
            inp = cv2.inpaint(img, mask, args.radius, cv2.INPAINT_TELEA)
            out = img.copy()
            out[mask > 0] = inp[mask > 0]
            # 50/50 with first frame inside mask
            blended = (out.astype(np.float32) * 0.5 + first_img.astype(np.float32) * 0.5).astype(np.uint8)
            out[mask > 0] = blended[mask > 0]
        else:
            out = cv2.inpaint(img, mask, args.radius, cv2.INPAINT_TELEA)
        cv2.imwrite(str(args.out_dir / stem), out)
        if (i + 1) % 300 == 0:
            print(f"  ...{i+1}/{n}", flush=True)

    print(f"done: {n} frames -> {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
