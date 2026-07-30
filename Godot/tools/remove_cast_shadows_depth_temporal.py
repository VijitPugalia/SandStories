#!/usr/bin/env python3
"""Remove transient cast shadows with fixed-camera RGB-D temporal evidence.

The method is deliberately mask-free at authoring time:

* a robust temporal upper envelope estimates unshadowed low-frequency radiance;
* candidate observations are accepted per pixel only when reconstructed depth
  agrees with the target frame;
* a soft matte is derived from unexplained radiance loss;
* only a smooth multiplicative illumination field is changed, preserving the
  input image's high-frequency sand texture;
* pixels outside the registered surface mask remain byte-identical.

No hand-authored mask, fixed image region, semantic frame range, skin threshold,
or object-specific cleanup rule is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, gaussian_filter1d


LUMA_WEIGHTS = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)


def parse_indices(value: str) -> list[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError(f"invalid range: {item}")
            result.update(range(start, end + 1))
        else:
            result.add(int(item))
    if not result or min(result) < 0:
        raise argparse.ArgumentTypeError("indices must be non-negative")
    return sorted(result)


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


def resize_float(
    array: np.ndarray,
    size: tuple[int, int],
    *,
    resample: Image.Resampling = Image.Resampling.BILINEAR,
) -> np.ndarray:
    if array.ndim == 2:
        image = Image.fromarray(array.astype(np.float32), mode="F")
        return np.asarray(image.resize(size, resample), dtype=np.float32)
    channels = [
        np.asarray(
            Image.fromarray(array[..., channel].astype(np.float32), mode="F").resize(
                size,
                resample,
            ),
            dtype=np.float32,
        )
        for channel in range(array.shape[2])
    ]
    return np.stack(channels, axis=2)


def smoothstep(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    scaled = np.clip((value - edge0) / max(edge1 - edge0, 1.0e-6), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def masked_quantile(
    values: np.ndarray,
    valid: np.ndarray,
    quantile: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a per-pixel quantile without NumPy's slow all-NaN fallback."""
    count = np.sum(valid, axis=0, dtype=np.int16)
    packed = np.where(valid, values, -np.inf)
    packed.sort(axis=0)
    valid_index = np.ceil(
        quantile * np.maximum(count - 1, 0)
    ).astype(np.int16)
    packed_index = np.clip(
        values.shape[0] - count + valid_index,
        0,
        values.shape[0] - 1,
    ).astype(np.int64)
    result = np.take_along_axis(
        packed,
        packed_index[None],
        axis=0,
    )[0]
    result[count == 0] = np.nan
    return result, count


def list_images(directory: Path, prefix: str = "") -> list[Path]:
    candidates = sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
        and (not prefix or path.name.startswith(prefix))
    )
    if not candidates:
        raise FileNotFoundError(f"no images in {directory}")
    return candidates


def load_analysis_arrays(
    rgb_paths: list[Path],
    depth_paths: list[Path],
    surface_path: Path,
    analysis_size: tuple[int, int],
    spatial_sigma: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    count = len(rgb_paths)
    width, height = analysis_size
    low_rgb = np.empty((count, height, width, 3), dtype=np.float32)
    depth = np.empty((count, height, width), dtype=np.float32)

    for index, (rgb_path, depth_path) in enumerate(zip(rgb_paths, depth_paths)):
        rgb_image = Image.open(rgb_path).convert("RGB").resize(
            analysis_size,
            Image.Resampling.BOX,
        )
        low_rgb[index] = srgb_to_linear(np.asarray(rgb_image))
        depth_image = Image.open(depth_path).convert("L").resize(
            analysis_size,
            Image.Resampling.BOX,
        )
        depth[index] = np.asarray(depth_image, dtype=np.float32)
        if (index + 1) % 50 == 0 or index + 1 == count:
            print(f"loaded {index + 1}/{count}", flush=True)

    low_rgb = gaussian_filter(
        low_rgb,
        sigma=(0.0, spatial_sigma, spatial_sigma, 0.0),
        mode="nearest",
    )
    surface_image = Image.open(surface_path).convert("L").resize(
        analysis_size,
        Image.Resampling.BOX,
    )
    surface = np.asarray(surface_image, dtype=np.float32) / 255.0
    surface = smoothstep(0.35, 0.80, surface)

    luma = np.maximum(np.sum(low_rgb * LUMA_WEIGHTS, axis=3), 1.0e-5)
    core = surface > 0.95
    exposure = np.asarray(
        [np.median(luma[index][core]) for index in range(count)],
        dtype=np.float32,
    )
    exposure_reference = float(np.median(exposure))
    exposure_scale = exposure_reference / np.maximum(exposure, 1.0e-5)
    normalized_rgb = low_rgb * exposure_scale[:, None, None, None]
    return normalized_rgb, depth, surface, exposure_scale


def compute_temporal_fields(
    normalized_rgb: np.ndarray,
    depth: np.ndarray,
    surface: np.ndarray,
    *,
    radius: int,
    depth_tolerance: float,
    upper_quantile: float,
    minimum_support: int,
    matte_threshold: float,
    matte_softness: float,
    maximum_gain: float,
    temporal_sigma: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    count, height, width, _ = normalized_rgb.shape
    normalized_luma = np.maximum(
        np.sum(normalized_rgb * LUMA_WEIGHTS, axis=3),
        1.0e-5,
    )
    log_gain = np.zeros((count, height, width), dtype=np.float32)
    matte = np.zeros_like(log_gain)
    support = np.zeros((count, height, width), dtype=np.uint8)

    for frame_index in range(count):
        start = max(0, frame_index - radius)
        stop = min(count, frame_index + radius + 1)
        candidate_depth = depth[start:stop]
        valid = (
            np.abs(candidate_depth - depth[frame_index][None]) <= depth_tolerance
        )
        valid &= surface[None] > 0.05
        reference_luma, support_frame = masked_quantile(
            normalized_luma[start:stop],
            valid,
            upper_quantile,
        )
        support[frame_index] = np.minimum(support_frame, 255).astype(np.uint8)
        current_luma = normalized_luma[frame_index]
        deficit = np.log(
            np.maximum(reference_luma, 1.0e-5)
            / np.maximum(current_luma, 1.0e-5)
        )
        deficit = np.nan_to_num(deficit, nan=0.0, posinf=0.0, neginf=0.0)
        deficit = np.clip(deficit, 0.0, math.log(maximum_gain))
        reliable = support_frame >= minimum_support
        current_matte = smoothstep(
            matte_threshold,
            matte_threshold + matte_softness,
            deficit,
        )
        current_matte *= reliable.astype(np.float32) * surface
        log_gain[frame_index] = deficit
        matte[frame_index] = current_matte
        if (frame_index + 1) % 25 == 0 or frame_index + 1 == count:
            coverage = float(np.mean(current_matte > 0.05))
            print(
                f"analysed {frame_index + 1}/{count} "
                f"coverage={coverage:.4f}",
                flush=True,
            )

    if temporal_sigma > 0:
        weighted_gain = gaussian_filter1d(
            log_gain * matte,
            sigma=temporal_sigma,
            axis=0,
            mode="nearest",
        )
        matte = gaussian_filter1d(
            matte,
            sigma=temporal_sigma,
            axis=0,
            mode="nearest",
        )
        log_gain = weighted_gain / np.maximum(matte, 1.0e-5)
    log_gain = np.clip(log_gain, 0.0, math.log(maximum_gain))
    matte = np.clip(matte, 0.0, 1.0)
    return log_gain, matte, support


def contact_sheet(
    records: list[dict[str, object]],
    destination: Path,
    cell_size: tuple[int, int] = (320, 240),
) -> None:
    width, height = cell_size
    columns = 4
    rows = len(records)
    canvas = Image.new("RGB", (columns * width, rows * (height + 24)), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    labels = ("v20d input", "automatic matte", "corrected", "encoded depth")
    for row, record in enumerate(records):
        images = [
            Image.open(Path(str(record[key]))).convert("RGB").resize(
                cell_size,
                Image.Resampling.LANCZOS,
            )
            for key in ("input", "matte", "output", "depth")
        ]
        y = row * (height + 24)
        for column, image in enumerate(images):
            canvas.paste(image, (column * width, y))
            draw.text(
                (column * width + 5, y + height + 5),
                f"f{record['frameIndex']:03d} {labels[column]}",
                fill="black",
                font=font,
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rgb-prefix", default="")
    parser.add_argument("--depth-prefix", default="clean_depth_")
    parser.add_argument("--target-frames", type=parse_indices)
    parser.add_argument("--analysis-width", type=int, default=80)
    parser.add_argument("--analysis-height", type=int, default=60)
    parser.add_argument("--spatial-sigma", type=float, default=2.0)
    parser.add_argument("--temporal-radius", type=int, default=30)
    parser.add_argument("--depth-tolerance", type=float, default=2.0)
    parser.add_argument("--upper-quantile", type=float, default=0.80)
    parser.add_argument("--minimum-support", type=int, default=8)
    parser.add_argument("--matte-threshold", type=float, default=0.055)
    parser.add_argument("--matte-softness", type=float, default=0.10)
    parser.add_argument("--maximum-gain", type=float, default=1.55)
    parser.add_argument("--temporal-sigma", type=float, default=1.25)
    parser.add_argument("--strength", type=float, default=0.90)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--contact-sheet", type=Path)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    matte_dir = args.output_dir / "mattes"
    matte_dir.mkdir()

    rgb_paths = list_images(args.rgb_dir, args.rgb_prefix)
    depth_paths = list_images(args.depth_dir, args.depth_prefix)
    if len(rgb_paths) != len(depth_paths):
        raise ValueError(
            f"RGB count {len(rgb_paths)} != depth count {len(depth_paths)}"
        )
    frame_count = len(rgb_paths)
    targets = args.target_frames or list(range(frame_count))
    if targets[-1] >= frame_count:
        raise IndexError(
            f"target frame {targets[-1]} outside {frame_count} frames"
        )

    analysis_size = (args.analysis_width, args.analysis_height)
    normalized_rgb, depth, surface_low, exposure_scale = load_analysis_arrays(
        rgb_paths,
        depth_paths,
        args.surface_mask,
        analysis_size,
        args.spatial_sigma,
    )
    log_gain, matte, support = compute_temporal_fields(
        normalized_rgb,
        depth,
        surface_low,
        radius=args.temporal_radius,
        depth_tolerance=args.depth_tolerance,
        upper_quantile=args.upper_quantile,
        minimum_support=args.minimum_support,
        matte_threshold=args.matte_threshold,
        matte_softness=args.matte_softness,
        maximum_gain=args.maximum_gain,
        temporal_sigma=args.temporal_sigma,
    )

    surface_full = (
        np.asarray(Image.open(args.surface_mask).convert("L"), dtype=np.float32)
        / 255.0
    )
    surface_full_bool = surface_full >= 0.5
    records: list[dict[str, object]] = []
    total_outside_changes = 0
    for target_index in targets:
        input_path = rgb_paths[target_index]
        source_u8 = np.asarray(Image.open(input_path).convert("RGB"))
        height, width = source_u8.shape[:2]
        gain_full = resize_float(
            log_gain[target_index],
            (width, height),
        )
        matte_full = resize_float(
            matte[target_index],
            (width, height),
        )
        matte_full = np.clip(matte_full * surface_full, 0.0, 1.0)
        applied_log_gain = gain_full * matte_full * args.strength
        corrected_linear = srgb_to_linear(source_u8) * np.exp(
            applied_log_gain[..., None]
        )
        corrected_u8 = linear_to_srgb(corrected_linear)
        corrected_u8[~surface_full_bool] = source_u8[~surface_full_bool]

        changed = np.any(corrected_u8 != source_u8, axis=2)
        outside_changes = int(np.count_nonzero(changed & ~surface_full_bool))
        total_outside_changes += outside_changes
        output_name = f"clean_rgb_{target_index + 1:06d}.png"
        output_path = args.output_dir / output_name
        Image.fromarray(corrected_u8, mode="RGB").save(output_path)

        matte_u8 = np.clip(np.round(matte_full * 255.0), 0, 255).astype(np.uint8)
        matte_path = matte_dir / f"shadow_matte_{target_index + 1:06d}.png"
        Image.fromarray(matte_u8, mode="L").save(matte_path)
        depth_preview = (
            Image.open(depth_paths[target_index])
            .convert("L")
            .resize((width, height), Image.Resampling.NEAREST)
        )
        depth_preview_path = matte_dir / f"depth_{target_index + 1:06d}.png"
        depth_preview.save(depth_preview_path)

        coverage = float(np.mean(matte[target_index] > 0.05))
        high_confidence = float(np.mean(matte[target_index] > 0.50))
        mean_gain = float(
            np.mean(
                np.exp(
                    log_gain[target_index][matte[target_index] > 0.05]
                    * args.strength
                )
            )
            if np.any(matte[target_index] > 0.05)
            else 1.0
        )
        records.append(
            {
                "frameIndex": target_index,
                "input": str(input_path),
                "output": str(output_path),
                "matte": str(matte_path),
                "depth": str(depth_preview_path),
                "matteCoverage": coverage,
                "highConfidenceCoverage": high_confidence,
                "meanCandidateGain": mean_gain,
                "changedPixels": int(np.count_nonzero(changed)),
                "outsideSurfaceChangedPixels": outside_changes,
                "inputSha256": file_sha256(input_path),
                "outputSha256": file_sha256(output_path),
            }
        )
        print(
            f"wrote frame {target_index}: coverage={coverage:.4f} "
            f"meanGain={mean_gain:.4f}",
            flush=True,
        )

    control_indices = [
        index
        for index in [*range(0, 23), *range(max(0, frame_count - 49), frame_count)]
        if index < frame_count
    ]
    report = {
        "method": (
            "fixed-camera depth-conditioned temporal upper-envelope intrinsic "
            "illumination correction"
        ),
        "frameCount": frame_count,
        "writtenFrameCount": len(targets),
        "parameters": {
            "analysisSize": list(analysis_size),
            "spatialSigma": args.spatial_sigma,
            "temporalRadius": args.temporal_radius,
            "depthToleranceEncodedUnits": args.depth_tolerance,
            "upperQuantile": args.upper_quantile,
            "minimumSupport": args.minimum_support,
            "matteThresholdLogRadiance": args.matte_threshold,
            "matteSoftnessLogRadiance": args.matte_softness,
            "maximumGain": args.maximum_gain,
            "temporalSigmaFrames": args.temporal_sigma,
            "strength": args.strength,
        },
        "provenance": {
            "rgbDir": str(args.rgb_dir.resolve()),
            "depthDir": str(args.depth_dir.resolve()),
            "surfaceMask": str(args.surface_mask.resolve()),
            "surfaceMaskSha256": file_sha256(args.surface_mask),
            "maskAuthoring": "none",
            "fixedFrameRanges": "none",
            "actorOrSkinRules": "none",
        },
        "sequenceDiagnostics": {
            "exposureScaleP01MedianP99": [
                float(value)
                for value in np.percentile(exposure_scale, [1, 50, 99])
            ],
            "matteCoverageP50P90P99": [
                float(value)
                for value in np.percentile(
                    np.mean(matte > 0.05, axis=(1, 2)),
                    [50, 90, 99],
                )
            ],
            "highConfidenceCoverageP50P90P99": [
                float(value)
                for value in np.percentile(
                    np.mean(matte > 0.50, axis=(1, 2)),
                    [50, 90, 99],
                )
            ],
            "controlMatteCoverageP50P90P99": [
                float(value)
                for value in np.percentile(
                    np.mean(matte[control_indices] > 0.05, axis=(1, 2)),
                    [50, 90, 99],
                )
            ],
            "minimumSupportP01MedianP99": [
                float(value)
                for value in np.percentile(support, [1, 50, 99])
            ],
            "outsideSurfaceChangedPixels": total_outside_changes,
        },
        "frames": records,
    }
    report_path = args.report or args.output_dir / "shadow_removal_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.contact_sheet:
        contact_sheet(records, args.contact_sheet)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
