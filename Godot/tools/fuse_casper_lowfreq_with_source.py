#!/usr/bin/env python3
"""Restore observed RGB detail while keeping Casper's low-frequency relighting."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--generated-frames", type=Path, required=True)
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-start", type=int, default=40)
    parser.add_argument("--frame-count", type=int, default=85)
    parser.add_argument("--radii", type=int, nargs="+", default=[8, 16, 24])
    parser.add_argument("--surface-feather", type=float, default=5.0)
    return parser.parse_args()


def blur_rgb(rgb: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray(rgb, mode="RGB")
    return np.asarray(
        image.filter(ImageFilter.GaussianBlur(radius=radius)),
        dtype=np.float32,
    )


def main() -> None:
    args = parse_args()
    hard_surface = Image.open(args.surface_mask).convert("L")
    hard_surface_alpha = (
        np.asarray(hard_surface, dtype=np.float32)[..., None] > 127
    ).astype(np.float32)
    surface = hard_surface
    if args.surface_feather > 0:
        surface = surface.filter(
            ImageFilter.GaussianBlur(radius=args.surface_feather)
        )
    surface_alpha = (
        np.asarray(surface, dtype=np.float32)[..., None]
        / 255.0
        * hard_surface_alpha
    )

    output_dirs = {}
    for radius in args.radii:
        output_dir = args.output_root / f"radius_{radius:02d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dirs[radius] = output_dir

    for output_index in range(1, args.frame_count + 1):
        source_index = args.source_start + output_index - 1
        source_path = args.source_dir / f"clean_rgb_{source_index:06d}.png"
        generated_path = (
            args.generated_frames / f"frame_{output_index:03d}.png"
        )
        source_u8 = np.asarray(
            Image.open(source_path).convert("RGB"),
            dtype=np.uint8,
        )
        generated_u8 = np.asarray(
            Image.open(generated_path).convert("RGB"),
            dtype=np.uint8,
        )
        source = source_u8.astype(np.float32)

        for radius, output_dir in output_dirs.items():
            source_low = blur_rgb(source_u8, radius)
            generated_low = blur_rgb(generated_u8, radius)
            # One-level Laplacian fusion: preserve the measured source detail
            # while replacing only the broad illumination/background estimate.
            corrected = source + generated_low - source_low
            fused = (
                source * (1.0 - surface_alpha)
                + corrected * surface_alpha
            )
            fused = np.clip(np.rint(fused), 0, 255).astype(np.uint8)
            Image.fromarray(fused, mode="RGB").save(
                output_dir / f"frame_{output_index:03d}.png"
            )

        if output_index % 10 == 0 or output_index == args.frame_count:
            print(f"processed {output_index}/{args.frame_count}", flush=True)


if __name__ == "__main__":
    main()
