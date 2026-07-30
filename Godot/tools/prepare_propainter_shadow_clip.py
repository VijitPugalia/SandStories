#!/usr/bin/env python3
"""Prepare a traceable dynamic-shadow clip for ProPainter evaluation.

The spatial masks come entirely from an upstream learned/photometric/depth
matte.  This tool only converts the continuous matte to ProPainter's required
binary missing-region convention and preserves frame ordering.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
from PIL import Image


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def link_or_copy(source: Path, destination: Path) -> str:
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--matte-dir", type=Path, required=True)
    parser.add_argument(
        "--matte-prefix",
        default="fused_shadow_matte_",
        help="Filename prefix before the one-based six-digit frame number.",
    )
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--first-frame", type=int, required=True)
    parser.add_argument("--last-frame", type=int, required=True)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="Continuous matte threshold in [0, 1].",
    )
    args = parser.parse_args()

    if not 0.0 < args.threshold < 1.0:
        raise ValueError(args.threshold)
    if args.first_frame < 0 or args.last_frame < args.first_frame:
        raise ValueError((args.first_frame, args.last_frame))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(args.output_dir)

    frames_dir = args.output_dir / "frames"
    masks_dir = args.output_dir / "masks"
    frames_dir.mkdir(parents=True)
    masks_dir.mkdir()
    surface = np.asarray(Image.open(args.surface_mask).convert("L")) > 127
    records: list[dict[str, object]] = []

    for clip_index, frame_index in enumerate(
        range(args.first_frame, args.last_frame + 1)
    ):
        frame_number = frame_index + 1
        source = args.rgb_dir / f"{frame_index:04d}.png"
        if not source.exists():
            source = args.rgb_dir / f"clean_rgb_{frame_number:06d}.png"
        matte_path = (
            args.matte_dir / f"{args.matte_prefix}{frame_number:06d}.png"
        )
        if not source.exists():
            raise FileNotFoundError(source)
        if not matte_path.exists():
            raise FileNotFoundError(matte_path)

        matte = (
            np.asarray(Image.open(matte_path).convert("L"), dtype=np.float32)
            / 255.0
        )
        missing = (matte >= args.threshold) & surface
        frame_destination = frames_dir / f"{clip_index:06d}.png"
        mask_destination = masks_dir / f"{clip_index:06d}.png"
        transfer = link_or_copy(source, frame_destination)
        Image.fromarray((missing.astype(np.uint8) * 255)).save(mask_destination)
        records.append(
            {
                "clipIndex": clip_index,
                "sourceFrameIndex": frame_index,
                "source": str(source.resolve()),
                "sourceSha256": file_sha256(source),
                "matte": str(matte_path.resolve()),
                "matteSha256": file_sha256(matte_path),
                "mask": str(mask_destination.resolve()),
                "maskedPixels": int(np.count_nonzero(missing)),
                "maskedSurfaceFraction": float(np.mean(missing[surface])),
                "frameTransfer": transfer,
            }
        )

    report = {
        "method": (
            "binary ProPainter masks from learned ShadowSAM semantics AND "
            "photometric deficit AND reconstructed-depth relief guard"
        ),
        "threshold": args.threshold,
        "mattePrefix": args.matte_prefix,
        "firstFrame": args.first_frame,
        "lastFrame": args.last_frame,
        "surfaceMask": str(args.surface_mask.resolve()),
        "surfaceMaskSha256": file_sha256(args.surface_mask),
        "frames": records,
    }
    (args.output_dir / "preparation_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output_dir.resolve()),
                "frames": len(records),
                "maskedPixelsMin": min(
                    int(record["maskedPixels"]) for record in records
                ),
                "maskedPixelsMax": max(
                    int(record["maskedPixels"]) for record in records
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
