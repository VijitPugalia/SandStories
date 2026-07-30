#!/usr/bin/env python3
"""Repair dark/bad registered RGB dumps using source recording RGB frames.

Some fakenect replays can return near-black frames from freenect_sync_get_video
while FREENECT_DEPTH_REGISTERED is still valid. The registered depth is already
in RGB pixel coordinates, so this replaces only the bad RGB PPM files with the
matching raw RGB frames from the original fakenect-record directory.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
from PIL import Image


def _mean_luma(path: Path) -> float:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return float((rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114).mean())


def repair(record_dir: Path, registered_dir: Path, prefix: str, frames: int, skip: int, threshold: float) -> int:
    raw_rgbs = sorted(record_dir.glob("r-*.ppm"))
    registered_rgbs = sorted(registered_dir.glob(f"{prefix}_rgb_*.ppm"))
    if not raw_rgbs:
        raise RuntimeError(f"No raw RGB PPM files found in {record_dir}")
    if not registered_rgbs:
        raise RuntimeError(f"No registered RGB PPM files found in {registered_dir} with prefix {prefix!r}")

    count = min(frames, len(registered_rgbs))
    replaced = 0
    for index in range(count):
        target = registered_rgbs[index]
        source_index = index * skip
        if source_index >= len(raw_rgbs):
            break
        if _mean_luma(target) < threshold:
            shutil.copy2(raw_rgbs[source_index], target)
            replaced += 1
    return replaced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--registered-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="official")
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--skip", type=int, required=True)
    parser.add_argument("--dark-threshold", type=float, default=20.0)
    args = parser.parse_args()
    replaced = repair(
        args.record_dir.resolve(),
        args.registered_dir.resolve(),
        args.prefix,
        max(1, args.frames),
        max(1, args.skip),
        args.dark_threshold,
    )
    print(f"replaced_registered_rgb={replaced}")


if __name__ == "__main__":
    main()
