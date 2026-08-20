#!/usr/bin/env python3
"""Prepare Azure Kinect sparse metric inputs for Any2Full (adapted from the
Kinect v22 path; depth is native mm instead of encoded-height + tan model).

Per frame:
  quality = surface & valid & ~object_dilated
            & (depth in band) & (9x9 local residual <= res_mm) & (sobel <= grad_mm)
  metric  = depth / 1000  (metres)
  anchors = quality at grid4 / grid6 lattice positions -> sparse npy (0 elsewhere)
  reference.npz = {metric, surface, quality, valid, object_dilated, grid4, grid6}
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import cv2
import numpy as np


def link_or_copy(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgb-dir", type=Path, required=True, help="aligned RGB frames (jpg/png), frame_%06d")
    parser.add_argument("--depth-dir", type=Path, required=True, help="depth PNGs 16-bit mm, depth_%06d")
    parser.add_argument("--object-mask-dir", type=Path, required=True, help="SAM2 binary masks, frame_%06d.png")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--band-mm", type=float, nargs=2, default=[450.0, 950.0], help="sand surface band")
    parser.add_argument("--object-dilate", type=int, default=8)
    parser.add_argument("--local-residual-mm", type=float, default=8.0)
    parser.add_argument("--gradient-mm", type=float, default=30.0)
    parser.add_argument("--frames", type=int, default=0, help="frame count (0 = all found)")
    args = parser.parse_args()

    if args.output_root.exists():
        raise FileExistsError(f"refusing to overwrite {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    rgb_dir = args.output_root / "rgb"
    reference_dir = args.output_root / "reference"
    mask_dir = args.output_root / "masks"
    depth_dirs = {4: args.output_root / "depth_grid4", 6: args.output_root / "depth_grid6"}
    for directory in [rgb_dir, reference_dir, mask_dir, *depth_dirs.values()]:
        directory.mkdir(parents=True, exist_ok=True)

    rgb_files = sorted(args.rgb_dir.glob("frame_*.jp*")) or sorted(args.rgb_dir.glob("frame_*.png"))
    depth_files = sorted(args.depth_dir.glob("depth_*.png"))
    mask_files = sorted(args.object_mask_dir.glob("*.png"))
    n = len(depth_files)
    if args.frames:
        n = min(n, args.frames)
    n = min(n, len(rgb_files), len(mask_files))
    print(f"pairs: {n} (rgb={len(rgb_files)} depth={len(depth_files)} masks={len(mask_files)})")

    lo, hi = args.band_mm
    yy, xx = np.indices((576, 640))
    kernel_size = args.object_dilate * 2 + 1
    object_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))

    # static surface band from the first frame (hand-free start expected)
    first = cv2.imread(str(depth_files[0]), cv2.IMREAD_UNCHANGED).astype(np.float32)
    surface = (first > lo) & (first < hi)
    print(f"surface band [{lo:.0f},{hi:.0f}] mm covers {surface.mean()*100:.1f}% of frame")
    cv2.imwrite(str(args.output_root / "surface_mask.png"), (surface.astype(np.uint8)) * 255)

    frame_reports = []
    for index in range(1, n + 1):
        stem = f"frame_{index:06d}"
        rgb_src = next((p for p in args.rgb_dir.glob(f"frame_{index:06d}.*")), None)
        if rgb_src is None:
            raise FileNotFoundError(f"rgb frame {index}")
        depth = cv2.imread(str(depth_files[index - 1]), cv2.IMREAD_UNCHANGED).astype(np.float32)
        valid = depth > 0
        object_mask = cv2.imread(str(mask_files[index - 1]), cv2.IMREAD_GRAYSCALE) > 0
        object_dilated = cv2.dilate(object_mask.astype(np.uint8), object_kernel) > 0
        depth_u8 = np.clip(depth / 4.0, 0, 255).astype(np.uint8)
        local_median = cv2.medianBlur(depth_u8, 9).astype(np.float32) * 4.0
        local_residual = np.abs(depth - local_median)
        gx = cv2.Sobel(depth, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(depth, cv2.CV_32F, 0, 1, ksize=3)
        gradient = np.sqrt(gx * gx + gy * gy)
        quality = (
            surface & valid & ~object_dilated
            & (depth >= lo) & (depth <= hi)
            & (local_residual <= args.local_residual_mm)
            & (gradient <= args.gradient_mm)
        )
        metric = (depth / 1000.0).astype(np.float32)

        link_or_copy(rgb_src, rgb_dir / f"{stem}.jpg")
        cv2.imwrite(str(mask_dir / f"{stem}_quality.png"), quality.astype(np.uint8) * 255)
        cv2.imwrite(str(mask_dir / f"{stem}_object_dilated.png"), object_dilated.astype(np.uint8) * 255)

        reference_payload = {
            "metric": metric, "surface": surface, "quality": quality,
            "valid": valid, "object_dilated": object_dilated,
        }
        report = {"frame": index, "qualityRatio": float(quality[surface].mean()),
                  "qualityCount": int(np.count_nonzero(quality))}
        for spacing, directory in depth_dirs.items():
            offset = spacing // 2
            anchor_mask = quality & (xx % spacing == offset) & (yy % spacing == offset)
            sparse = np.zeros_like(metric, dtype=np.float32)
            sparse[anchor_mask] = metric[anchor_mask]
            np.save(directory / f"{stem}.npy", sparse)
            cv2.imwrite(str(mask_dir / f"{stem}_grid{spacing}.png"), anchor_mask.astype(np.uint8) * 255)
            reference_payload[f"grid{spacing}"] = anchor_mask
            report[f"grid{spacing}Ratio"] = float(anchor_mask[surface].mean())
            report[f"grid{spacing}Count"] = int(np.count_nonzero(anchor_mask))
        np.savez_compressed(reference_dir / f"{stem}.npz", **reference_payload)
        frame_reports.append(report)
        if index % 300 == 0:
            print(json.dumps(report), flush=True)

    (args.output_root / "input_report.json").write_text(json.dumps(
        {"method": "Azure Kinect mm depth, quality-filtered grid anchors",
         "bandMm": [lo, hi], "objectDilatePx": args.object_dilate,
         "localResidualMm": args.local_residual_mm, "gradientMm": args.gradient_mm,
         "frames": frame_reports}, indent=2))
    print(f"done: {n} frames -> {args.output_root}")


if __name__ == "__main__":
    main()
