#!/usr/bin/env python3
"""Repair deep cast-shadow cores from real neighbouring RGB-D observations.

This is a fixed-camera video-inpainting stage for areas where multiplicative
relighting cannot recover texture because the camera signal is nearly black.
For every target frame it:

* derives the repair core from an upstream continuous, automatic shadow matte;
* ranks neighbouring frames using reconstructed-depth agreement, actor-mask
  exclusion, candidate-shadow exclusion, brightness recovery, and distance;
* colour-matches the best real frame on a ring around the repair core; and
* feathers only that real RGB plate into an optional relit base image.

There are no hand-authored spatial masks, selected reference frames, skin
thresholds, or generated pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_erosion, gaussian_filter


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


def parse_frame_numbers(value: str) -> list[int]:
    result = sorted(
        {int(item.strip()) for item in value.split(",") if item.strip()}
    )
    if not result or result[0] < 1:
        raise argparse.ArgumentTypeError("frame numbers must be positive")
    return result


def frame_path(
    directory: Path,
    frame_index: int,
    *,
    prefix: str,
    one_based: bool,
) -> Path:
    number = frame_index + 1 if one_based else frame_index
    path = directory / f"{prefix}{number:06d}.png"
    if path.exists():
        return path
    path = directory / f"{number:04d}.png"
    if path.exists():
        return path
    raise FileNotFoundError(path)


def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def load_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--matte-dir", type=Path, required=True)
    parser.add_argument("--actor-mask-dir", type=Path, required=True)
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frame-numbers", type=parse_frame_numbers, required=True)
    parser.add_argument("--base-dir", type=Path)
    parser.add_argument("--temporal-radius", type=int, default=30)
    parser.add_argument("--core-threshold", type=float, default=0.58)
    parser.add_argument("--candidate-matte-threshold", type=float, default=0.12)
    parser.add_argument("--maximum-actor-overlap", type=float, default=0.02)
    parser.add_argument("--depth-tolerance", type=float, default=2.0)
    parser.add_argument("--minimum-depth-agreement", type=float, default=0.82)
    parser.add_argument("--time-penalty", type=float, default=0.004)
    parser.add_argument("--ring-width", type=int, default=18)
    parser.add_argument("--feather-sigma", type=float, default=7.0)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    surface_path = args.surface_mask
    surface = load_gray(surface_path) > 127
    rgb_paths = sorted(
        path
        for path in args.rgb_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    frame_count = len(rgb_paths)
    records: list[dict[str, object]] = []

    for frame_number in args.frame_numbers:
        target_index = frame_number - 1
        if not 0 <= target_index < frame_count:
            raise IndexError(target_index)
        target_rgb_path = frame_path(
            args.rgb_dir,
            target_index,
            prefix="clean_rgb_",
            one_based=False,
        )
        target_depth_path = frame_path(
            args.depth_dir,
            target_index,
            prefix="clean_depth_",
            one_based=True,
        )
        target_matte_path = frame_path(
            args.matte_dir,
            target_index,
            prefix="fused_shadow_matte_",
            one_based=True,
        )
        target_rgb_u8 = load_rgb(target_rgb_path)
        target_linear = srgb_to_linear(target_rgb_u8)
        target_luma = np.sum(target_linear * LUMA_WEIGHTS, axis=2)
        target_depth = load_gray(target_depth_path).astype(np.float32)
        target_matte = load_gray(target_matte_path).astype(np.float32) / 255.0
        core = (target_matte >= args.core_threshold) & surface
        if not np.any(core):
            raise RuntimeError(f"frame {target_index} has no repair core")

        score_region = binary_dilation(core, iterations=args.ring_width) & surface
        core_count = max(int(np.count_nonzero(core)), 1)
        candidate_records: list[dict[str, float | int | str]] = []
        start = max(0, target_index - args.temporal_radius)
        stop = min(frame_count, target_index + args.temporal_radius + 1)
        for candidate_index in range(start, stop):
            if candidate_index == target_index:
                continue
            try:
                candidate_matte_path = frame_path(
                    args.matte_dir,
                    candidate_index,
                    prefix="fused_shadow_matte_",
                    one_based=True,
                )
            except FileNotFoundError:
                continue
            actor_path = sorted(args.actor_mask_dir.glob("*.png"))[candidate_index]
            candidate_actor = load_gray(actor_path) > 0
            actor_overlap = float(np.count_nonzero(candidate_actor & core) / core_count)
            if actor_overlap > args.maximum_actor_overlap:
                continue
            candidate_matte = (
                load_gray(candidate_matte_path).astype(np.float32) / 255.0
            )
            shadow_overlap = float(
                np.mean(candidate_matte[core] >= args.candidate_matte_threshold)
            )
            if shadow_overlap > 0.10:
                continue
            candidate_depth_path = frame_path(
                args.depth_dir,
                candidate_index,
                prefix="clean_depth_",
                one_based=True,
            )
            candidate_depth = load_gray(candidate_depth_path).astype(np.float32)
            depth_error = np.abs(candidate_depth - target_depth)
            depth_agreement = float(
                np.mean(depth_error[score_region] <= args.depth_tolerance)
            )
            if depth_agreement < args.minimum_depth_agreement:
                continue
            candidate_rgb_path = frame_path(
                args.rgb_dir,
                candidate_index,
                prefix="clean_rgb_",
                one_based=False,
            )
            candidate_linear = srgb_to_linear(load_rgb(candidate_rgb_path))
            candidate_luma = np.sum(candidate_linear * LUMA_WEIGHTS, axis=2)
            target_core_luma = float(np.median(target_luma[core]))
            candidate_core_luma = float(np.median(candidate_luma[core]))
            brightness_log_ratio = float(
                np.log(
                    max(candidate_core_luma, 1.0e-5)
                    / max(target_core_luma, 1.0e-5)
                )
            )
            depth_mae = float(np.mean(depth_error[score_region]))
            temporal_distance = abs(candidate_index - target_index)
            score = (
                brightness_log_ratio
                + 0.60 * depth_agreement
                - 0.20 * depth_mae / max(args.depth_tolerance, 1.0e-5)
                - args.time_penalty * temporal_distance
                - 0.50 * shadow_overlap
            )
            candidate_records.append(
                {
                    "frameIndex": candidate_index,
                    "path": str(candidate_rgb_path),
                    "score": score,
                    "brightnessLogRatio": brightness_log_ratio,
                    "depthAgreement": depth_agreement,
                    "depthMae": depth_mae,
                    "actorOverlap": actor_overlap,
                    "shadowOverlap": shadow_overlap,
                    "temporalDistance": temporal_distance,
                }
            )

        if not candidate_records:
            raise RuntimeError(f"frame {target_index}: no valid temporal plate")
        candidate_records.sort(key=lambda item: float(item["score"]), reverse=True)
        best = candidate_records[0]
        reference_path = Path(str(best["path"]))
        reference_linear = srgb_to_linear(load_rgb(reference_path))

        outer = binary_dilation(core, iterations=args.ring_width)
        inner = binary_dilation(core, iterations=max(args.ring_width // 3, 1))
        ring = (outer & ~inner & surface)
        ring &= target_matte < min(args.core_threshold * 0.35, 0.20)
        if np.count_nonzero(ring) < 128:
            ring = binary_dilation(core, iterations=args.ring_width) & ~core & surface
        colour_ratio = np.median(
            target_linear[ring] / np.maximum(reference_linear[ring], 1.0e-5),
            axis=0,
        )
        colour_ratio = np.clip(colour_ratio, 0.70, 1.40)
        reference_matched = np.clip(
            reference_linear * colour_ratio[None, None, :],
            0.0,
            1.0,
        )

        if args.base_dir:
            base_path = frame_path(
                args.base_dir,
                target_index,
                prefix="clean_rgb_",
                one_based=True,
            )
            base_u8 = load_rgb(base_path)
            base_linear = srgb_to_linear(base_u8)
        else:
            base_path = target_rgb_path
            base_u8 = target_rgb_u8
            base_linear = target_linear

        alpha = gaussian_filter(
            core.astype(np.float32),
            sigma=args.feather_sigma,
            mode="nearest",
        )
        alpha *= surface.astype(np.float32)
        alpha = np.clip(alpha, 0.0, 1.0)
        output_linear = (
            base_linear * (1.0 - alpha[..., None])
            + reference_matched * alpha[..., None]
        )
        output_u8 = linear_to_srgb(output_linear)
        output_u8[~surface] = target_rgb_u8[~surface]
        output_path = args.output_dir / f"clean_rgb_{frame_number:06d}.png"
        Image.fromarray(output_u8, mode="RGB").save(output_path)
        alpha_path = args.output_dir / f"temporal_plate_alpha_{frame_number:06d}.png"
        Image.fromarray(
            np.clip(np.round(alpha * 255.0), 0, 255).astype(np.uint8),
            mode="L",
        ).save(alpha_path)
        record = {
            "frameIndex": target_index,
            "target": str(target_rgb_path),
            "base": str(base_path),
            "output": str(output_path),
            "alpha": str(alpha_path),
            "selectedReferenceFrameIndex": int(best["frameIndex"]),
            "selectedReference": str(reference_path),
            "selectedReferenceMetrics": best,
            "topCandidates": candidate_records[:10],
            "colourRatioLinearRgb": [float(value) for value in colour_ratio],
            "corePixels": int(np.count_nonzero(core)),
            "changedOutsideSurfacePixels": int(
                np.count_nonzero(
                    np.any(output_u8 != target_rgb_u8, axis=2) & ~surface
                )
            ),
            "targetSha256": file_sha256(target_rgb_path),
            "referenceSha256": file_sha256(reference_path),
            "outputSha256": file_sha256(output_path),
        }
        records.append(record)
        print(json.dumps(record, indent=2), flush=True)

    report = {
        "method": (
            "automatic RGB-D matched real temporal background plate for deep "
            "shadow cores"
        ),
        "parameters": {
            "temporalRadius": args.temporal_radius,
            "coreThreshold": args.core_threshold,
            "candidateMatteThreshold": args.candidate_matte_threshold,
            "maximumActorOverlap": args.maximum_actor_overlap,
            "depthToleranceEncodedUnits": args.depth_tolerance,
            "minimumDepthAgreement": args.minimum_depth_agreement,
            "timePenalty": args.time_penalty,
            "ringWidth": args.ring_width,
            "featherSigma": args.feather_sigma,
        },
        "provenance": {
            "rgbDir": str(args.rgb_dir.resolve()),
            "depthDir": str(args.depth_dir.resolve()),
            "matteDir": str(args.matte_dir.resolve()),
            "actorMaskDir": str(args.actor_mask_dir.resolve()),
            "surfaceMask": str(surface_path.resolve()),
            "surfaceMaskSha256": file_sha256(surface_path),
            "manualMask": "none",
            "manualReferenceFrame": "none",
            "generatedPixels": "none",
        },
        "frames": records,
    }
    (args.output_dir / "temporal_plate_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
