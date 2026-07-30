#!/usr/bin/env python3
"""Render before/after diagnostics for suspicious depth-frame transitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def read_gray(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=np.float32)


def read_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconstruction-session", type=Path, required=True)
    parser.add_argument("--reference-session", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", required=True)
    args = parser.parse_args()

    frames = [int(value) for value in args.frames.split(",") if value.strip()]
    reconstruction_manifest = json.loads(
        (args.reconstruction_session / "processed_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    surface = read_gray(args.reference_session / "surface_mask.png") > 0
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for frame in frames:
        if frame <= 1 or frame > len(reconstruction_manifest["frames"]):
            raise ValueError(f"invalid event frame {frame}")
        previous = frame - 1
        previous_stem = f"{previous:06d}"
        current_stem = f"{frame:06d}"
        previous_meta = reconstruction_manifest["frames"][previous - 1]
        current_meta = reconstruction_manifest["frames"][frame - 1]
        previous_correction = float(
            previous_meta.get("baselineHeightCorrection", 0.0)
        )
        current_correction = float(
            current_meta.get("baselineHeightCorrection", 0.0)
        )

        rgb_previous = read_rgb(
            args.reconstruction_session / f"clean_rgb_{previous_stem}.png"
        )
        rgb_current = read_rgb(
            args.reconstruction_session / f"clean_rgb_{current_stem}.png"
        )
        reference_previous = read_gray(
            args.reference_session / f"clean_depth_{previous_stem}.png"
        )
        reference_current = read_gray(
            args.reference_session / f"clean_depth_{current_stem}.png"
        )
        reconstruction_previous = (
            read_gray(
                args.reconstruction_session / f"clean_depth_{previous_stem}.png"
            )
            + previous_correction
        )
        reconstruction_current = (
            read_gray(
                args.reconstruction_session / f"clean_depth_{current_stem}.png"
            )
            + current_correction
        )
        reference_delta = np.where(
            surface, reference_current - reference_previous, np.nan
        )
        reconstruction_delta = np.where(
            surface, reconstruction_current - reconstruction_previous, np.nan
        )

        figure, axes = plt.subplots(2, 4, figsize=(18, 9))
        axes[0, 0].imshow(rgb_previous)
        axes[0, 0].set_title(f"Displayed RGB frame {previous}")
        axes[0, 1].imshow(rgb_current)
        axes[0, 1].set_title(f"Displayed RGB frame {frame}")
        axes[0, 2].imshow(reference_previous, cmap="gray", vmin=35, vmax=235)
        axes[0, 2].set_title(f"Kinect encoded height {previous}")
        axes[0, 3].imshow(reference_current, cmap="gray", vmin=35, vmax=235)
        axes[0, 3].set_title(f"Kinect encoded height {frame}")

        axes[1, 0].imshow(
            reconstruction_previous, cmap="gray", vmin=35, vmax=235
        )
        axes[1, 0].set_title(f"Any2Full corrected height {previous}")
        axes[1, 1].imshow(
            reconstruction_current, cmap="gray", vmin=35, vmax=235
        )
        axes[1, 1].set_title(f"Any2Full corrected height {frame}")
        reference_plot = axes[1, 2].imshow(
            reference_delta, cmap="coolwarm", vmin=-8, vmax=8
        )
        axes[1, 2].set_title(
            "Kinect delta\n"
            f"median={np.nanmedian(reference_delta):.2f}, "
            f"median |d|={np.nanmedian(np.abs(reference_delta)):.2f}"
        )
        reconstruction_plot = axes[1, 3].imshow(
            reconstruction_delta, cmap="coolwarm", vmin=-8, vmax=8
        )
        axes[1, 3].set_title(
            "Any2Full delta\n"
            f"median={np.nanmedian(reconstruction_delta):.2f}, "
            f"median |d|={np.nanmedian(np.abs(reconstruction_delta)):.2f}"
        )
        for axis in axes.flat:
            axis.axis("off")
        figure.colorbar(
            reference_plot,
            ax=[axes[1, 2], axes[1, 3]],
            location="bottom",
            fraction=0.05,
            pad=0.05,
            label="Encoded height-unit change (1 unit ≈ 0.547 mm)",
        )
        figure.suptitle(
            f"SandStories depth transition {previous} → {frame}",
            fontsize=16,
        )
        figure.subplots_adjust(
            left=0.02, right=0.98, top=0.92, bottom=0.10, wspace=0.05, hspace=0.12
        )
        figure.savefig(
            args.output_dir / f"depth_transition_{previous_stem}_{current_stem}.png",
            dpi=150,
        )
        plt.close(figure)


if __name__ == "__main__":
    main()
