#!/usr/bin/env python3
"""Audit reconstructed SandStories depth against Kinect and across time.

The audit deliberately separates two questions:

1. Spatial fidelity: does reconstructed metric depth agree with Kinect pixels
   that pass conservative validity, range, local-residual, and gradient checks?
2. Temporal baseline stability: do pixels that are nearly static in Kinect
   exhibit a frame-wide displacement in the reconstruction?

The source Kinect height PNG and the Any2Full Godot PNG use different metric
encodings, so both are converted back to metres before spatial comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from scipy import ndimage


DEFAULT_METRIC_LOW = 0.8128636457361647
DEFAULT_METRIC_HIGH = 0.9216704175465102


def read_gray(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=np.uint8)


def raw_to_meters(raw: np.ndarray) -> np.ndarray:
    return 0.1236 * np.tan(raw / 2842.5 + 1.1863)


def kinect_height_to_meters(
    height: np.ndarray, raw_low: float, raw_high: float
) -> np.ndarray:
    normalized = np.clip(
        (height.astype(np.float32) / 255.0 - 0.14) / 0.78, 0.0, 1.0
    )
    raw = raw_low + (1.0 - normalized) * (raw_high - raw_low)
    return raw_to_meters(raw).astype(np.float32)


def godot_height_to_meters(
    height: np.ndarray, metric_low: float, metric_high: float
) -> np.ndarray:
    normalized = np.clip(
        (height.astype(np.float32) / 255.0 - 0.14) / 0.78, 0.0, 1.0
    )
    return (
        metric_high - normalized * (metric_high - metric_low)
    ).astype(np.float32)


def quality_mask(
    height: np.ndarray,
    valid: np.ndarray,
    surface: np.ndarray,
    local_residual_limit: float,
    gradient_limit: float,
) -> np.ndarray:
    local_median = ndimage.median_filter(height, size=9, mode="nearest")
    local_residual = np.abs(height.astype(np.float32) - local_median)
    gradient_x = ndimage.sobel(height.astype(np.float32), axis=1, mode="nearest")
    gradient_y = ndimage.sobel(height.astype(np.float32), axis=0, mode="nearest")
    gradient = np.hypot(gradient_x, gradient_y)
    return (
        surface
        & valid
        & (height >= 40)
        & (height <= 230)
        & (local_residual <= local_residual_limit)
        & (gradient <= gradient_limit)
    )


def finite_stat(values: np.ndarray, function, default: float = float("nan")) -> float:
    return float(function(values)) if values.size else default


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def frame_file(frame: dict[str, Any], key: str, fallback: str) -> str:
    return str(frame.get(key, fallback))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconstruction-session", type=Path, required=True)
    parser.add_argument("--reference-session", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--reference-npz-dir",
        type=Path,
        help=(
            "Optional Any2Full reference NPZ directory. When supplied, use "
            "the original object-excluded quality and grid4 holdout masks."
        ),
    )
    parser.add_argument("--local-residual-limit", type=float, default=8.0)
    parser.add_argument("--gradient-limit", type=float, default=48.0)
    parser.add_argument("--stable-min-valid-ratio", type=float, default=0.85)
    parser.add_argument("--stable-max-std-code", type=float, default=1.5)
    parser.add_argument("--top-count", type=int, default=20)
    args = parser.parse_args()

    reconstruction_manifest = load_json(
        args.reconstruction_session / "processed_manifest.json"
    )
    reference_manifest = load_json(args.reference_session / "processed_manifest.json")
    reconstruction_frames = reconstruction_manifest["frames"]
    reference_frames = reference_manifest["frames"]
    if len(reconstruction_frames) != len(reference_frames):
        raise ValueError(
            "frame count mismatch: "
            f"{len(reconstruction_frames)} reconstruction vs "
            f"{len(reference_frames)} reference"
        )
    frame_count = len(reconstruction_frames)
    if frame_count < 2:
        raise ValueError("at least two frames are required")

    normalization = reference_manifest["depthNormalization"]
    raw_low = float(normalization["p02Raw"])
    raw_high = float(normalization["p98Raw"])
    reconstruction_info = reconstruction_manifest.get(
        "any2FullDepthCompletion", {}
    )
    metric_low, metric_high = reconstruction_info.get(
        "metricDepthRange", [DEFAULT_METRIC_LOW, DEFAULT_METRIC_HIGH]
    )
    metric_low = float(metric_low)
    metric_high = float(metric_high)
    height_units_per_meter = 0.78 * 255.0 / (metric_high - metric_low)
    millimetres_per_height_unit = 1000.0 / height_units_per_meter

    surface = read_gray(args.reference_session / "surface_mask.png") > 0
    if not np.any(surface):
        raise ValueError("surface mask is empty")
    # Avoid mask-edge interpolation and tray-wall pixels when building the
    # temporally stable control region.
    interior_surface = ndimage.binary_erosion(surface, iterations=6)

    shape = surface.shape
    quality_count = np.zeros(shape, dtype=np.uint16)
    quality_sum = np.zeros(shape, dtype=np.float64)
    quality_sum_sq = np.zeros(shape, dtype=np.float64)
    rows: list[dict[str, Any]] = []
    previous_reconstruction_height: np.ndarray | None = None
    previous_reference_height: np.ndarray | None = None
    previous_quality: np.ndarray | None = None

    evaluation_items = (
        load_json(args.reconstruction_session / "vitl_evaluation.json")
        .get("results", {})
        .get("grid4", [])
    )
    evaluation_by_frame = {
        int(item["frame"]): item for item in evaluation_items
    }

    for index, (reconstruction_frame, reference_frame) in enumerate(
        zip(reconstruction_frames, reference_frames), start=1
    ):
        reconstruction_name = frame_file(
            reconstruction_frame, "cleanDepth", f"clean_depth_{index:06d}.png"
        )
        reference_name = frame_file(
            reference_frame, "cleanDepth", f"clean_depth_{index:06d}.png"
        )
        valid_name = frame_file(
            reference_frame, "occlusionMask", f"valid_mask_{index:06d}.png"
        )
        reconstruction_height_u8 = read_gray(
            args.reconstruction_session / reconstruction_name
        )
        reference_height_u8 = read_gray(args.reference_session / reference_name)
        valid = read_gray(args.reference_session / valid_name) > 0
        if (
            reconstruction_height_u8.shape != shape
            or reference_height_u8.shape != shape
            or valid.shape != shape
        ):
            raise ValueError(f"shape mismatch at frame {index}")

        exact_reference_metric: np.ndarray | None = None
        exact_holdout: np.ndarray | None = None
        if args.reference_npz_dir is not None:
            reference_npz_path = (
                args.reference_npz_dir / f"frame_{index:06d}.npz"
            )
            with np.load(reference_npz_path) as payload:
                quality = payload["quality"].astype(bool)
                anchors = payload["grid4"].astype(bool)
                exact_holdout = quality & ~anchors
                exact_reference_metric = payload["metric"].astype(np.float32)
        else:
            quality = quality_mask(
                reference_height_u8,
                valid,
                surface,
                args.local_residual_limit,
                args.gradient_limit,
            )
        quality_float = quality.astype(np.float64)
        reference_float = reference_height_u8.astype(np.float64)
        quality_count += quality.astype(np.uint16)
        quality_sum += reference_float * quality_float
        quality_sum_sq += np.square(reference_float) * quality_float

        correction_units = float(
            reconstruction_frame.get("baselineHeightCorrection", 0.0)
        )
        reconstruction_height = (
            reconstruction_height_u8.astype(np.float32) + correction_units
        )
        reference_height = reference_height_u8.astype(np.float32)
        reconstruction_metric = godot_height_to_meters(
            reconstruction_height_u8, metric_low, metric_high
        )
        # The shader adds correction_units / 255 to height. Since the Godot
        # encoding is inverse-depth, this subtracts the corresponding bias.
        reconstruction_metric -= correction_units / height_units_per_meter
        reference_metric = (
            exact_reference_metric
            if exact_reference_metric is not None
            else kinect_height_to_meters(
                reference_height_u8, raw_low, raw_high
            )
        )
        error = reconstruction_metric[quality] - reference_metric[quality]
        holdout_error = (
            reconstruction_metric[exact_holdout]
            - reference_metric[exact_holdout]
            if exact_holdout is not None
            else np.asarray([], dtype=np.float32)
        )

        evaluation = evaluation_by_frame.get(index, {})
        row: dict[str, Any] = {
            "frame": index,
            "time": float(reconstruction_frame.get("time", (index - 1) / 30.0)),
            "source_pair_delta_ms": 1000.0
            * float(reference_frame.get("sourcePairDeltaSeconds", 0.0)),
            "baseline_correction_units": correction_units,
            "surface_median_height": finite_stat(
                reconstruction_height[surface], np.median
            ),
            "reference_quality_median_height": finite_stat(
                reference_height[quality], np.median
            ),
            "quality_ratio": float(np.mean(quality[surface])),
            "quality_mae_mm_no_object_exclusion": 1000.0
            * finite_stat(np.abs(error), np.mean),
            "quality_median_bias_mm_no_object_exclusion": 1000.0
            * finite_stat(error, np.median),
            "exact_holdout_mae_mm": 1000.0
            * finite_stat(np.abs(holdout_error), np.mean),
            "exact_holdout_rmse_mm": 1000.0
            * (
                float(np.sqrt(np.mean(np.square(holdout_error))))
                if holdout_error.size
                else float("nan")
            ),
            "exact_holdout_p95_mm": 1000.0
            * finite_stat(
                np.abs(holdout_error),
                lambda values: np.percentile(values, 95),
            ),
            "reported_holdout_mae_mm": 1000.0
            * float(evaluation.get("holdoutMaeMeters", float("nan"))),
            "reported_quality_p95_mm": 1000.0
            * float(evaluation.get("qualityP95AbsErrorMeters", float("nan"))),
        }
        if previous_reconstruction_height is None:
            row.update(
                {
                    "reconstruction_delta_median_units": 0.0,
                    "reconstruction_delta_median_abs_units": 0.0,
                    "reconstruction_delta_p95_abs_units": 0.0,
                    "reconstruction_delta_sign_coherence": 0.0,
                    "reference_delta_median_units": 0.0,
                    "reference_delta_median_abs_units": 0.0,
                    "reference_delta_p95_abs_units": 0.0,
                }
            )
        else:
            reconstruction_delta = (
                reconstruction_height - previous_reconstruction_height
            )[surface]
            reference_pair_mask = quality & previous_quality
            reference_delta = (
                reference_height - previous_reference_height
            )[reference_pair_mask]
            reconstruction_delta_median = finite_stat(
                reconstruction_delta, np.median
            )
            nonzero = np.abs(reconstruction_delta) >= 0.25
            if np.any(nonzero) and reconstruction_delta_median != 0.0:
                direction = np.sign(reconstruction_delta_median)
                sign_coherence = float(
                    np.mean(np.sign(reconstruction_delta[nonzero]) == direction)
                )
            else:
                sign_coherence = 0.0
            row.update(
                {
                    "reconstruction_delta_median_units": reconstruction_delta_median,
                    "reconstruction_delta_median_abs_units": finite_stat(
                        np.abs(reconstruction_delta), np.median
                    ),
                    "reconstruction_delta_p95_abs_units": finite_stat(
                        np.abs(reconstruction_delta), lambda x: np.percentile(x, 95)
                    ),
                    "reconstruction_delta_sign_coherence": sign_coherence,
                    "reference_delta_median_units": finite_stat(
                        reference_delta, np.median
                    ),
                    "reference_delta_median_abs_units": finite_stat(
                        np.abs(reference_delta), np.median
                    ),
                    "reference_delta_p95_abs_units": finite_stat(
                        np.abs(reference_delta), lambda x: np.percentile(x, 95)
                    ),
                }
            )
        rows.append(row)
        previous_reconstruction_height = reconstruction_height
        previous_reference_height = reference_height
        previous_quality = quality

    minimum_quality_count = int(
        np.ceil(args.stable_min_valid_ratio * frame_count)
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        temporal_mean = quality_sum / quality_count
        temporal_variance = quality_sum_sq / quality_count - np.square(temporal_mean)
    temporal_std = np.sqrt(np.maximum(temporal_variance, 0.0))
    stable_mask = (
        interior_surface
        & (quality_count >= minimum_quality_count)
        & (temporal_std <= args.stable_max_std_code)
    )
    stable_count = int(np.count_nonzero(stable_mask))
    if stable_count < 1000:
        raise ValueError(
            "stable control region is too small "
            f"({stable_count} pixels); relax stable thresholds"
        )

    previous_reconstruction_stable: np.ndarray | None = None
    previous_reference_stable: np.ndarray | None = None
    for index, (reconstruction_frame, reference_frame) in enumerate(
        zip(reconstruction_frames, reference_frames), start=1
    ):
        reconstruction_name = frame_file(
            reconstruction_frame, "cleanDepth", f"clean_depth_{index:06d}.png"
        )
        reference_name = frame_file(
            reference_frame, "cleanDepth", f"clean_depth_{index:06d}.png"
        )
        reconstruction_height = read_gray(
            args.reconstruction_session / reconstruction_name
        ).astype(np.float32)
        reconstruction_height += float(
            reconstruction_frame.get("baselineHeightCorrection", 0.0)
        )
        reference_height = read_gray(
            args.reference_session / reference_name
        ).astype(np.float32)
        reconstruction_stable = reconstruction_height[stable_mask]
        reference_stable = reference_height[stable_mask]
        row = rows[index - 1]
        row["stable_reconstruction_median_height"] = float(
            np.median(reconstruction_stable)
        )
        row["stable_reference_median_height"] = float(
            np.median(reference_stable)
        )
        row["stable_reconstruction_minus_reference_median_units"] = float(
            np.median(reconstruction_stable - reference_stable)
        )
        if previous_reconstruction_stable is None:
            row["stable_reconstruction_delta_median_units"] = 0.0
            row["stable_reference_delta_median_units"] = 0.0
            row["stable_delta_error_units"] = 0.0
        else:
            reconstruction_delta = (
                reconstruction_stable - previous_reconstruction_stable
            )
            reference_delta = reference_stable - previous_reference_stable
            reconstruction_delta_median = float(np.median(reconstruction_delta))
            reference_delta_median = float(np.median(reference_delta))
            row[
                "stable_reconstruction_delta_median_units"
            ] = reconstruction_delta_median
            row["stable_reference_delta_median_units"] = reference_delta_median
            row["stable_delta_error_units"] = (
                reconstruction_delta_median - reference_delta_median
            )
        previous_reconstruction_stable = reconstruction_stable
        previous_reference_stable = reference_stable

    args.output_dir.mkdir(parents=True, exist_ok=True)
    Image.fromarray(stable_mask.astype(np.uint8) * 255).save(
        args.output_dir / "stable_control_mask.png"
    )
    csv_path = args.output_dir / "depth_stability_frames.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    valid_rows = rows[1:]
    top_data_jumps = sorted(
        valid_rows,
        key=lambda row: abs(row["stable_delta_error_units"]),
        reverse=True,
    )[: args.top_count]
    top_surface_changes = sorted(
        valid_rows,
        key=lambda row: row["reconstruction_delta_median_abs_units"],
        reverse=True,
    )[: args.top_count]
    reported_holdout = np.array(
        [row["reported_holdout_mae_mm"] for row in rows], dtype=np.float64
    )
    exact_holdout_mae = np.array(
        [row["exact_holdout_mae_mm"] for row in rows], dtype=np.float64
    )
    exact_holdout_rmse = np.array(
        [row["exact_holdout_rmse_mm"] for row in rows], dtype=np.float64
    )
    exact_holdout_p95 = np.array(
        [row["exact_holdout_p95_mm"] for row in rows], dtype=np.float64
    )
    stable_delta_errors = np.array(
        [row["stable_delta_error_units"] for row in valid_rows],
        dtype=np.float64,
    )
    reconstruction_global_deltas = np.array(
        [row["reconstruction_delta_median_units"] for row in valid_rows],
        dtype=np.float64,
    )
    reference_global_deltas = np.array(
        [row["reference_delta_median_units"] for row in valid_rows],
        dtype=np.float64,
    )
    summary = {
        "frameCount": frame_count,
        "surfacePixelCount": int(np.count_nonzero(surface)),
        "stableControlPixelCount": stable_count,
        "stableControlSurfaceRatio": float(stable_count / np.count_nonzero(surface)),
        "stableDefinition": {
            "minimumQualityFrameRatio": args.stable_min_valid_ratio,
            "maximumTemporalStdHeightUnits": args.stable_max_std_code,
            "surfaceErosionPixels": 6,
            "minimumQualityFrameCount": minimum_quality_count,
        },
        "encoding": {
            "metricRangeMeters": [metric_low, metric_high],
            "heightUnitsPerMeter": height_units_per_meter,
            "millimetresPerHeightUnit": millimetres_per_height_unit,
        },
        "reportedSpatialValidation": {
            "meanHoldoutMaeMillimetres": float(np.nanmean(reported_holdout)),
            "p95FrameHoldoutMaeMillimetres": float(
                np.nanpercentile(reported_holdout, 95)
            ),
            "maximumFrameHoldoutMaeMillimetres": float(
                np.nanmax(reported_holdout)
            ),
        },
        "exactSpatialValidation": {
            "available": bool(np.any(np.isfinite(exact_holdout_mae))),
            "meanFrameHoldoutMaeMillimetres": float(
                np.nanmean(exact_holdout_mae)
            )
            if np.any(np.isfinite(exact_holdout_mae))
            else None,
            "meanFrameHoldoutRmseMillimetres": float(
                np.nanmean(exact_holdout_rmse)
            )
            if np.any(np.isfinite(exact_holdout_rmse))
            else None,
            "meanFrameHoldoutP95Millimetres": float(
                np.nanmean(exact_holdout_p95)
            )
            if np.any(np.isfinite(exact_holdout_p95))
            else None,
            "maximumFrameHoldoutMaeMillimetres": float(
                np.nanmax(exact_holdout_mae)
            )
            if np.any(np.isfinite(exact_holdout_mae))
            else None,
        },
        "temporalValidation": {
            "meanAbsoluteStableDeltaErrorHeightUnits": float(
                np.mean(np.abs(stable_delta_errors))
            ),
            "p95AbsoluteStableDeltaErrorHeightUnits": float(
                np.percentile(np.abs(stable_delta_errors), 95)
            ),
            "maximumAbsoluteStableDeltaErrorHeightUnits": float(
                np.max(np.abs(stable_delta_errors))
            ),
            "maximumAbsoluteStableDeltaErrorMillimetres": float(
                np.max(np.abs(stable_delta_errors))
                * millimetres_per_height_unit
            ),
            "reconstructionGlobalDeltaStdHeightUnits": float(
                np.std(reconstruction_global_deltas)
            ),
            "referenceGlobalDeltaStdHeightUnits": float(
                np.std(reference_global_deltas)
            ),
        },
        "topStableBaselineJumpFrames": [
            {
                key: row[key]
                for key in (
                    "frame",
                    "time",
                    "stable_reconstruction_delta_median_units",
                    "stable_reference_delta_median_units",
                    "stable_delta_error_units",
                    "reconstruction_delta_sign_coherence",
                    "reported_holdout_mae_mm",
                    "baseline_correction_units",
                    "source_pair_delta_ms",
                )
            }
            for row in top_data_jumps
        ],
        "topWholeSurfaceChangeFrames": [
            {
                key: row[key]
                for key in (
                    "frame",
                    "time",
                    "reconstruction_delta_median_abs_units",
                    "reconstruction_delta_p95_abs_units",
                    "reconstruction_delta_median_units",
                    "reference_delta_median_abs_units",
                    "reconstruction_delta_sign_coherence",
                )
            }
            for row in top_surface_changes
        ],
        "artifacts": {
            "frameCsv": str(csv_path),
            "stableControlMask": str(
                args.output_dir / "stable_control_mask.png"
            ),
            "timelinePlot": str(args.output_dir / "depth_stability_timeline.png"),
        },
    }
    (args.output_dir / "depth_stability_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    times = np.array([row["time"] for row in rows], dtype=np.float64)
    reconstruction_stable_median = np.array(
        [row["stable_reconstruction_median_height"] for row in rows]
    )
    reference_stable_median = np.array(
        [row["stable_reference_median_height"] for row in rows]
    )
    delta_mm = np.array(
        [row["stable_delta_error_units"] for row in rows]
    ) * millimetres_per_height_unit
    figure, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    axes[0].plot(
        times,
        (reconstruction_stable_median - reconstruction_stable_median[0])
        * millimetres_per_height_unit,
        label="Any2Full stable-region median",
        linewidth=1.2,
    )
    axes[0].plot(
        times,
        (reference_stable_median - reference_stable_median[0])
        * millimetres_per_height_unit,
        label="Kinect stable-region median",
        linewidth=1.0,
        alpha=0.8,
    )
    axes[0].set_ylabel("Relative height (mm)")
    axes[0].legend(loc="upper right")
    axes[0].grid(alpha=0.25)

    axes[1].plot(times, delta_mm, linewidth=0.9, color="#b23a48")
    axes[1].axhline(0.0, color="black", linewidth=0.7)
    axes[1].set_ylabel("Frame delta error (mm)")
    axes[1].grid(alpha=0.25)
    for row in top_data_jumps[:8]:
        axes[1].annotate(
            str(row["frame"]),
            (
                row["time"],
                row["stable_delta_error_units"]
                * millimetres_per_height_unit,
            ),
            fontsize=8,
        )

    axes[2].plot(
        times,
        [row["reported_holdout_mae_mm"] for row in rows],
        linewidth=0.9,
        label="Held-out Kinect MAE",
    )
    axes[2].plot(
        times,
        [row["reported_quality_p95_mm"] for row in rows],
        linewidth=0.8,
        alpha=0.75,
        label="Quality-point P95",
    )
    axes[2].set_xlabel("Session time (s)")
    axes[2].set_ylabel("Error (mm)")
    axes[2].legend(loc="upper right")
    axes[2].grid(alpha=0.25)
    figure.suptitle("SandStories Any2Full depth audit")
    figure.tight_layout()
    figure.savefig(args.output_dir / "depth_stability_timeline.png", dpi=160)
    plt.close(figure)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
