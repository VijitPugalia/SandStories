#!/usr/bin/env python3
"""Fuse ShadowSAM probabilities with photometric and depth evidence.

ShadowSAM supplies learned shadow semantics.  A multi-scale morphological
illumination envelope verifies local radiance loss, while reconstructed depth
gradients protect real sand relief.  The three signals must agree before a
smooth multiplicative illumination correction is applied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import (
    gaussian_filter,
    gaussian_gradient_magnitude,
    grey_closing,
)


LUMA_WEIGHTS = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def srgb_to_linear(value: np.ndarray) -> np.ndarray:
    value = value.astype(np.float32) / 255.0
    return np.where(
        value <= 0.04045,
        value / 12.92,
        ((value + 0.055) / 1.055) ** 2.4,
    )


def linear_to_srgb(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    encoded = np.where(
        value <= 0.0031308,
        value * 12.92,
        1.055 * np.power(value, 1.0 / 2.4) - 0.055,
    )
    return np.clip(np.round(encoded * 255.0), 0, 255).astype(np.uint8)


def smoothstep(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    scaled = np.clip((value - edge0) / max(edge1 - edge0, 1.0e-6), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def find_frame_file(directory: Path, prefix: str, frame_number: int) -> Path:
    exact = directory / f"{prefix}{frame_number:06d}.png"
    if exact.exists():
        return exact
    raise FileNotFoundError(exact)


def photometric_deficit(
    input_path: Path,
    *,
    spatial_sigma: float,
    closing_size: int,
    maximum_gain: float,
) -> np.ndarray:
    source_u8 = np.asarray(Image.open(input_path).convert("RGB"))
    linear = srgb_to_linear(source_u8)
    luma = np.maximum(np.sum(linear * LUMA_WEIGHTS, axis=2), 1.0e-5)
    low_luma = gaussian_filter(luma, sigma=spatial_sigma, mode="nearest")
    envelope = grey_closing(
        low_luma,
        size=(closing_size, closing_size),
        mode="nearest",
    )
    envelope = gaussian_filter(
        envelope,
        sigma=spatial_sigma,
        mode="nearest",
    )
    deficit = np.log(
        np.maximum(envelope, 1.0e-5) / np.maximum(low_luma, 1.0e-5)
    )
    return np.clip(deficit, 0.0, np.log(maximum_gain))


def photometric_chromatic_log_gain(
    input_path: Path,
    *,
    spatial_sigma: float,
    closing_size: int,
    maximum_gain: float,
) -> np.ndarray:
    """Estimate the colour of the missing low-frequency illumination.

    The scalar deficit determines *how much* light is missing.  This auxiliary
    field only estimates the relative RGB balance of that light, so applying it
    does not replace or blur the observed high-frequency sand texture.
    """
    source_u8 = np.asarray(Image.open(input_path).convert("RGB"))
    linear = srgb_to_linear(source_u8)
    low_rgb = gaussian_filter(
        linear,
        sigma=(spatial_sigma, spatial_sigma, 0.0),
        mode="nearest",
    )
    envelope_rgb = np.empty_like(low_rgb)
    for channel in range(3):
        envelope_rgb[..., channel] = grey_closing(
            low_rgb[..., channel],
            size=(closing_size, closing_size),
            mode="nearest",
        )
    envelope_rgb = gaussian_filter(
        envelope_rgb,
        sigma=(spatial_sigma, spatial_sigma, 0.0),
        mode="nearest",
    )
    channel_deficit = np.log(
        np.maximum(envelope_rgb, 1.0e-5)
        / np.maximum(low_rgb, 1.0e-5)
    )
    return np.clip(channel_deficit, 0.0, np.log(maximum_gain))


def derive_control_intervals(
    actor_mask_dir: Path,
    surface: np.ndarray,
) -> tuple[list[int], list[int], list[int]]:
    mask_paths = sorted(actor_mask_dir.glob("*.png"))
    if not mask_paths:
        raise FileNotFoundError(actor_mask_dir)
    empty = []
    for frame_index, mask_path in enumerate(mask_paths):
        actor = np.asarray(Image.open(mask_path).convert("L")) > 0
        empty.append(int(np.count_nonzero(actor & surface)) == 0)

    prefix: list[int] = []
    for frame_index, is_empty in enumerate(empty):
        if not is_empty:
            break
        prefix.append(frame_index)
    suffix: list[int] = []
    for frame_index in range(len(empty) - 1, -1, -1):
        if not empty[frame_index]:
            break
        suffix.append(frame_index)
    suffix.reverse()
    if len(prefix) < 3 or len(suffix) < 3:
        raise RuntimeError(
            f"insufficient automatic controls: prefix={len(prefix)} "
            f"suffix={len(suffix)}"
        )
    return prefix, suffix, [index for index, is_empty in enumerate(empty) if is_empty]


def contact_sheet(
    records: list[dict[str, object]],
    destination: Path,
) -> None:
    cell_size = (320, 240)
    cell_width, cell_height = cell_size
    canvas = Image.new(
        "RGB",
        (4 * cell_width, len(records) * (cell_height + 24)),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for row, record in enumerate(records):
        images = [
            Image.open(Path(str(record[key]))).convert("RGB").resize(
                cell_size,
                Image.Resampling.LANCZOS,
            )
            for key in ("input", "modelProbability", "fusedMatte", "output")
        ]
        labels = ("v20d input", "ShadowSAM probability", "fused matte", "corrected")
        y = row * (cell_height + 24)
        for column, (image, label) in enumerate(zip(images, labels)):
            canvas.paste(image, (column * cell_width, y))
            draw.text(
                (column * cell_width + 4, y + cell_height + 4),
                f"f{record['frameIndex']:03d} {label}",
                fill="black",
                font=font,
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--probability-dir", type=Path, required=True)
    parser.add_argument("--actor-mask-dir", type=Path, required=True)
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spatial-sigma", type=float, default=6.0)
    parser.add_argument("--closing-size", type=int, default=129)
    parser.add_argument("--deficit-threshold", type=float, default=0.045)
    parser.add_argument("--deficit-softness", type=float, default=0.13)
    parser.add_argument("--model-threshold", type=float, default=0.32)
    parser.add_argument("--model-softness", type=float, default=0.42)
    parser.add_argument("--maximum-gain", type=float, default=1.70)
    parser.add_argument("--strength", type=float, default=1.0)
    parser.add_argument("--depth-protection", type=float, default=0.82)
    parser.add_argument(
        "--chromatic-gain",
        action="store_true",
        help=(
            "estimate a smooth three-channel illumination colour while "
            "retaining the scalar fused matte and original RGB texture"
        ),
    )
    parser.add_argument(
        "--chroma-strength",
        type=float,
        default=0.65,
        help="blend from scalar gain (0) to estimated RGB illumination (1)",
    )
    parser.add_argument(
        "--frame-numbers",
        help="optional comma-separated one-based frame numbers to process",
    )
    parser.add_argument("--contact-sheet", type=Path)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    matte_dir = args.output_dir / "mattes"
    matte_dir.mkdir()

    probability_paths = sorted(
        args.probability_dir.glob("shadow_probability_*.png")
    )
    if not probability_paths:
        raise FileNotFoundError(args.probability_dir)
    if args.frame_numbers:
        wanted_frame_numbers = {
            int(item.strip())
            for item in args.frame_numbers.split(",")
            if item.strip()
        }
        probability_paths = [
            path
            for path in probability_paths
            if int(path.stem.rsplit("_", 1)[1]) in wanted_frame_numbers
        ]
        if not probability_paths:
            raise FileNotFoundError(
                "none of --frame-numbers exists in probability directory"
            )
    surface = np.asarray(Image.open(args.surface_mask).convert("L")) > 127
    rgb_paths = sorted(
        path
        for path in args.rgb_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    initial_controls, final_controls, all_empty_controls = (
        derive_control_intervals(args.actor_mask_dir, surface)
    )
    initial_deficit = np.median(
        np.stack(
            [
                photometric_deficit(
                    rgb_paths[index],
                    spatial_sigma=args.spatial_sigma,
                    closing_size=args.closing_size,
                    maximum_gain=args.maximum_gain,
                )
                for index in initial_controls
            ]
        ),
        axis=0,
    )
    final_deficit = np.median(
        np.stack(
            [
                photometric_deficit(
                    rgb_paths[index],
                    spatial_sigma=args.spatial_sigma,
                    closing_size=args.closing_size,
                    maximum_gain=args.maximum_gain,
                )
                for index in final_controls
            ]
        ),
        axis=0,
    )
    print(
        f"automatic controls prefix={initial_controls[0]}-"
        f"{initial_controls[-1]} suffix={final_controls[0]}-"
        f"{final_controls[-1]}",
        flush=True,
    )
    records: list[dict[str, object]] = []

    for probability_path in probability_paths:
        frame_number = int(probability_path.stem.rsplit("_", 1)[1])
        frame_index = frame_number - 1
        input_path = args.rgb_dir / f"{frame_index:04d}.png"
        if not input_path.exists():
            input_path = find_frame_file(
                args.rgb_dir,
                "clean_rgb_",
                frame_number,
            )
        depth_path = find_frame_file(
            args.depth_dir,
            "clean_depth_",
            frame_number,
        )
        source_u8 = np.asarray(Image.open(input_path).convert("RGB"))
        linear = srgb_to_linear(source_u8)
        deficit = photometric_deficit(
            input_path,
            spatial_sigma=args.spatial_sigma,
            closing_size=args.closing_size,
            maximum_gain=args.maximum_gain,
        )
        sequence_alpha = frame_index / max(len(rgb_paths) - 1, 1)
        control_baseline = (
            (1.0 - sequence_alpha) * initial_deficit
            + sequence_alpha * final_deficit
        )
        transient_deficit = np.clip(
            deficit - control_baseline,
            0.0,
            np.log(args.maximum_gain),
        )
        photometric = smoothstep(
            args.deficit_threshold,
            args.deficit_threshold + args.deficit_softness,
            transient_deficit,
        )

        probability = (
            np.asarray(Image.open(probability_path).convert("L"), dtype=np.float32)
            / 255.0
        )
        semantic = smoothstep(
            args.model_threshold,
            args.model_threshold + args.model_softness,
            probability,
        )

        depth = np.asarray(
            Image.open(depth_path).convert("L"),
            dtype=np.float32,
        )
        depth_gradient = gaussian_gradient_magnitude(
            depth,
            sigma=2.0,
            mode="nearest",
        )
        gradient_scale = float(np.percentile(depth_gradient[surface], 90))
        geometry_edge = smoothstep(
            0.15 * gradient_scale,
            gradient_scale,
            depth_gradient,
        )
        geometry_guard = 1.0 - args.depth_protection * geometry_edge
        matte = semantic * photometric * geometry_guard * surface.astype(np.float32)
        matte = gaussian_filter(matte, sigma=1.2, mode="nearest")
        matte *= surface.astype(np.float32)
        matte = np.clip(matte, 0.0, 1.0)

        if args.chromatic_gain:
            channel_deficit = photometric_chromatic_log_gain(
                input_path,
                spatial_sigma=args.spatial_sigma,
                closing_size=args.closing_size,
                maximum_gain=args.maximum_gain,
            )
            channel_luma = np.sum(
                channel_deficit * LUMA_WEIGHTS[None, None, :],
                axis=2,
            )
            chroma_delta = channel_deficit - channel_luma[..., None]
            chromatic_log_gain = (
                transient_deficit[..., None]
                + args.chroma_strength * chroma_delta
            )
            chromatic_log_gain = np.clip(
                chromatic_log_gain,
                0.0,
                np.log(args.maximum_gain),
            )
            applied_log_gain = (
                chromatic_log_gain * matte[..., None] * args.strength
            )
        else:
            applied_log_gain = (
                transient_deficit * matte * args.strength
            )[..., None]
        output_u8 = linear_to_srgb(
            linear * np.exp(applied_log_gain)
        )
        output_u8[~surface] = source_u8[~surface]
        changed = np.any(output_u8 != source_u8, axis=2)
        outside_changes = int(np.count_nonzero(changed & ~surface))

        output_path = args.output_dir / f"clean_rgb_{frame_number:06d}.png"
        Image.fromarray(output_u8, mode="RGB").save(output_path)
        matte_path = matte_dir / f"fused_shadow_matte_{frame_number:06d}.png"
        Image.fromarray(
            np.clip(np.round(matte * 255.0), 0, 255).astype(np.uint8),
            mode="L",
        ).save(matte_path)
        records.append(
            {
                "frameIndex": frame_index,
                "input": str(input_path),
                "modelProbability": str(probability_path),
                "fusedMatte": str(matte_path),
                "output": str(output_path),
                "matteCoverageAt005": float(np.mean(matte[surface] > 0.05)),
                "matteCoverageAt05": float(np.mean(matte[surface] > 0.50)),
                "meanGainInMatte": float(
                    np.mean(
                        np.exp(
                            transient_deficit[matte > 0.05] * args.strength
                        )
                    )
                    if np.any(matte > 0.05)
                    else 1.0
                ),
                "changedPixels": int(np.count_nonzero(changed)),
                "outsideSurfaceChangedPixels": outside_changes,
            }
        )
        print(json.dumps(records[-1]), flush=True)

    report = {
        "method": (
            "ShadowSAM learned probability AND multi-scale photometric "
            "radiance loss AND reconstructed-depth relief guard"
        ),
        "parameters": {
            "spatialSigma": args.spatial_sigma,
            "closingSize": args.closing_size,
            "deficitThreshold": args.deficit_threshold,
            "deficitSoftness": args.deficit_softness,
            "modelThreshold": args.model_threshold,
            "modelSoftness": args.model_softness,
            "maximumGain": args.maximum_gain,
            "strength": args.strength,
            "depthProtection": args.depth_protection,
            "chromaticGain": args.chromatic_gain,
            "chromaStrength": args.chroma_strength,
        },
        "provenance": {
            "surfaceMask": str(args.surface_mask.resolve()),
            "surfaceMaskSha256": file_sha256(args.surface_mask),
            "actorMaskDir": str(args.actor_mask_dir.resolve()),
            "automaticInitialControls": initial_controls,
            "automaticFinalControls": final_controls,
            "allActorFreeSurfaceFrames": all_empty_controls,
            "probabilityDir": str(args.probability_dir.resolve()),
            "maskAuthoring": "none",
            "fixedImageRegion": "none",
            "skinOrActorRule": "none",
        },
        "frames": records,
    }
    (args.output_dir / "fusion_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    if args.contact_sheet:
        contact_sheet(records, args.contact_sheet)


if __name__ == "__main__":
    main()
