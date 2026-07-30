#!/usr/bin/env python3
"""Temporally stabilize Any2Full depth with independent VDA frame deltas.

Any2Full supplies the metric spatial shape. VDA supplies only frame-to-frame
motion, so broad Kinect quantization steps are not copied straight into the
displayed sand surface. The source session is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def read_gray(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=np.uint8)


def link_or_copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def stabilize_block(
    spatial: np.ndarray,
    temporal: np.ndarray,
    strength: float,
    threshold: float,
) -> np.ndarray:
    """Bidirectional adaptive smoother over a [time, y, x] block."""
    forward = np.empty_like(spatial, dtype=np.float32)
    backward = np.empty_like(spatial, dtype=np.float32)
    forward[0] = spatial[0]
    for index in range(1, len(spatial)):
        delta = temporal[index] - temporal[index - 1]
        candidate = forward[index - 1] + delta
        difference = np.abs(spatial[index] - candidate)
        weight = strength * np.exp(
            -np.square(difference / max(threshold, 1e-6))
        )
        forward[index] = spatial[index] * (1.0 - weight) + candidate * weight

    backward[-1] = spatial[-1]
    for index in range(len(spatial) - 2, -1, -1):
        delta = temporal[index + 1] - temporal[index]
        candidate = backward[index + 1] - delta
        difference = np.abs(spatial[index] - candidate)
        weight = strength * np.exp(
            -np.square(difference / max(threshold, 1e-6))
        )
        backward[index] = spatial[index] * (1.0 - weight) + candidate * weight
    return (forward + backward) * 0.5


def load_sampled_sequences(
    source_session: Path,
    vda_session: Path,
    frame_count: int,
    corrections: np.ndarray,
    stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    surface = read_gray(source_session / "surface_mask.png") > 0
    sampled_surface = surface[::stride, ::stride]
    shape = sampled_surface.shape
    spatial = np.empty((frame_count, *shape), dtype=np.float32)
    temporal = np.empty_like(spatial)
    for index in range(frame_count):
        stem = f"{index + 1:06d}"
        spatial[index] = (
            read_gray(source_session / f"clean_depth_{stem}.png")[
                ::stride, ::stride
            ].astype(np.float32)
            + corrections[index]
        )
        # The existing VDA branch has the opposite encoded direction.
        temporal[index] = 269.0 - read_gray(
            vda_session / f"clean_depth_{stem}.png"
        )[::stride, ::stride].astype(np.float32)
    return spatial, temporal, sampled_surface


def temporal_metrics(
    output: np.ndarray,
    source: np.ndarray,
    temporal: np.ndarray,
    surface: np.ndarray,
    reference_metric: np.ndarray | None = None,
    holdout: np.ndarray | None = None,
    metric_range: tuple[float, float] | None = None,
) -> dict[str, Any]:
    valid = np.broadcast_to(surface, output[1:].shape)
    output_delta = np.diff(output, axis=0)
    source_delta = np.diff(source, axis=0)
    temporal_delta = np.diff(temporal, axis=0)
    output_abs = np.abs(output_delta)[valid]
    source_abs = np.abs(source_delta)[valid]
    temporal_residual = np.abs(output_delta - temporal_delta)[valid]
    deviation = np.abs(output - source)[
        np.broadcast_to(surface, output.shape)
    ]
    transition_rows = []
    for frame in (148, 223):
        if frame > len(output):
            continue
        delta = output[frame - 1] - output[frame - 2]
        values = delta[surface]
        transition_rows.append(
            {
                "frame": frame,
                "medianDelta": float(np.median(values)),
                "medianAbsoluteDelta": float(np.median(np.abs(values))),
                "p95AbsoluteDelta": float(
                    np.percentile(np.abs(values), 95)
                ),
            }
        )
    per_frame_median = np.array(
        [
            np.median(output_delta[index][surface])
            for index in range(len(output_delta))
        ]
    )
    per_frame_median_abs = np.array(
        [
            np.median(np.abs(output_delta[index][surface]))
            for index in range(len(output_delta))
        ]
    )
    broad_jump_count = int(
        np.count_nonzero(
            (np.abs(per_frame_median) >= 0.75)
            & (per_frame_median_abs >= 1.5)
        )
    )
    report = {
        "meanAdjacentDifference": float(np.mean(output_abs)),
        "p95AdjacentDifference": float(np.percentile(output_abs, 95)),
        "meanAdjacentDifferenceBefore": float(np.mean(source_abs)),
        "vdaDeltaResidualMean": float(np.mean(temporal_residual)),
        "vdaDeltaResidualP95": float(
            np.percentile(temporal_residual, 95)
        ),
        "meanAbsoluteDeviationFromAny2Full": float(np.mean(deviation)),
        "p95AbsoluteDeviationFromAny2Full": float(
            np.percentile(deviation, 95)
        ),
        "maximumAbsoluteFrameMedianDelta": float(
            np.max(np.abs(per_frame_median))
        ),
        "broadJumpCount": broad_jump_count,
        "transitions": transition_rows,
    }
    if (
        reference_metric is not None
        and holdout is not None
        and metric_range is not None
    ):
        metric_low, metric_high = metric_range
        normalized = np.clip(
            (output / 255.0 - 0.14) / 0.78, 0.0, 1.0
        )
        output_metric = (
            metric_high - normalized * (metric_high - metric_low)
        )
        error = output_metric[holdout] - reference_metric[holdout]
        report["sampledHoldoutCount"] = int(np.count_nonzero(holdout))
        report["sampledHoldoutMaeMillimetres"] = float(
            np.mean(np.abs(error)) * 1000.0
        )
        report["sampledHoldoutRmseMillimetres"] = float(
            np.sqrt(np.mean(np.square(error))) * 1000.0
        )
        report["sampledHoldoutP95Millimetres"] = float(
            np.percentile(np.abs(error), 95) * 1000.0
        )
    return report


def load_sampled_reference(
    reference_dir: Path,
    frame_count: int,
    stride: int,
) -> tuple[np.ndarray, np.ndarray]:
    first = np.load(reference_dir / "frame_000001.npz")
    sampled_shape = first["metric"][::stride, ::stride].shape
    metric = np.empty((frame_count, *sampled_shape), dtype=np.float32)
    holdout = np.empty((frame_count, *sampled_shape), dtype=bool)
    for index in range(frame_count):
        path = reference_dir / f"frame_{index + 1:06d}.npz"
        with np.load(path) as payload:
            metric[index] = payload["metric"][::stride, ::stride]
            quality = payload["quality"][::stride, ::stride].astype(bool)
            anchors = payload["grid4"][::stride, ::stride].astype(bool)
            holdout[index] = quality & ~anchors
    return metric, holdout


def tune(
    source_session: Path,
    vda_session: Path,
    frame_count: int,
    corrections: np.ndarray,
    stride: int,
    reference_dir: Path | None,
    metric_range: tuple[float, float],
) -> dict[str, Any]:
    spatial, temporal, surface = load_sampled_sequences(
        source_session, vda_session, frame_count, corrections, stride
    )
    if reference_dir is not None:
        reference_metric, holdout = load_sampled_reference(
            reference_dir, frame_count, stride
        )
    else:
        reference_metric = None
        holdout = None
    baseline = temporal_metrics(
        spatial,
        spatial,
        temporal,
        surface,
        reference_metric,
        holdout,
        metric_range,
    )
    candidates = []
    for strength in (0.4, 0.6, 0.75, 0.85, 0.92):
        for threshold in (6.0, 10.0, 18.0):
            output = stabilize_block(
                spatial, temporal, strength, threshold
            )
            report = temporal_metrics(
                output,
                spatial,
                temporal,
                surface,
                reference_metric,
                holdout,
                metric_range,
            )
            report["strength"] = strength
            report["threshold"] = threshold
            candidates.append(report)
    candidates.sort(
        key=lambda item: (
            item["broadJumpCount"],
            max(
                transition["medianAbsoluteDelta"]
                for transition in item["transitions"]
            ),
            item["meanAbsoluteDeviationFromAny2Full"],
        )
    )
    return {
        "method": "bidirectional_vda_delta_guided_adaptive_smoothing",
        "sampleStride": stride,
        "frameCount": frame_count,
        "baseline": baseline,
        "candidates": candidates,
    }


def build(
    source_session: Path,
    vda_session: Path,
    output_session: Path,
    source_manifest: dict[str, Any],
    source_session_json: dict[str, Any],
    corrections: np.ndarray,
    strength: float,
    threshold: float,
    chunk_rows: int,
) -> dict[str, Any]:
    if output_session.exists() and any(output_session.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output session: {output_session}"
        )
    output_session.mkdir(parents=True, exist_ok=True)
    frame_count = len(source_manifest["frames"])
    surface = read_gray(source_session / "surface_mask.png") > 0
    height, width = surface.shape
    source_memmap_path = output_session / ".source_depth_u8.dat"
    vda_memmap_path = output_session / ".vda_depth_u8.dat"
    output_memmap_path = output_session / ".stabilized_depth_u8.dat"
    source_memmap = np.memmap(
        source_memmap_path,
        mode="w+",
        dtype=np.uint8,
        shape=(frame_count, height, width),
    )
    vda_memmap = np.memmap(
        vda_memmap_path,
        mode="w+",
        dtype=np.uint8,
        shape=(frame_count, height, width),
    )
    output_memmap = np.memmap(
        output_memmap_path,
        mode="w+",
        dtype=np.uint8,
        shape=(frame_count, height, width),
    )
    for index in range(frame_count):
        stem = f"{index + 1:06d}"
        source_memmap[index] = read_gray(
            source_session / f"clean_depth_{stem}.png"
        )
        vda_memmap[index] = read_gray(
            vda_session / f"clean_depth_{stem}.png"
        )
    source_memmap.flush()
    vda_memmap.flush()

    residual_sum = np.zeros(frame_count, dtype=np.float64)
    residual_count = np.zeros(frame_count, dtype=np.int64)
    for y0 in range(0, height, chunk_rows):
        y1 = min(height, y0 + chunk_rows)
        spatial = source_memmap[:, y0:y1].astype(np.float32)
        spatial += corrections[:, None, None]
        temporal = 269.0 - vda_memmap[:, y0:y1].astype(np.float32)
        stabilized = stabilize_block(
            spatial, temporal, strength, threshold
        )
        stabilized = np.clip(stabilized, 35.0, 234.0)
        chunk_surface = surface[y0:y1]
        rounded = np.rint(stabilized).astype(np.uint8)
        rounded[:, ~chunk_surface] = 255
        output_memmap[:, y0:y1] = rounded
        if np.any(chunk_surface):
            residual = (
                stabilized[:, chunk_surface]
                - rounded[:, chunk_surface].astype(np.float32)
            )
            residual_sum += np.sum(residual, axis=1)
            residual_count += residual.shape[1]
    output_memmap.flush()
    output_corrections = residual_sum / np.maximum(residual_count, 1)

    for index in range(frame_count):
        stem = f"{index + 1:06d}"
        Image.fromarray(np.asarray(output_memmap[index])).save(
            output_session / f"clean_depth_{stem}.png",
            optimize=True,
        )
        for prefix in ("clean_rgb", "valid_mask"):
            link_or_copy(
                source_session / f"{prefix}_{stem}.png",
                output_session / f"{prefix}_{stem}.png",
            )
    link_or_copy(
        source_session / "surface_mask.png",
        output_session / "surface_mask.png",
    )
    for name in (
        "any2full_report.json",
        "conditioning_report.json",
        "model_comparison.json",
        "vitl_evaluation.json",
    ):
        candidate = source_session / name
        if candidate.is_file():
            link_or_copy(candidate, output_session / name)

    sample_stride = 4
    sampled_source = (
        source_memmap[:, ::sample_stride, ::sample_stride].astype(np.float32)
        + corrections[:, None, None]
    )
    sampled_temporal = (
        269.0
        - vda_memmap[:, ::sample_stride, ::sample_stride].astype(np.float32)
    )
    sampled_output = (
        output_memmap[:, ::sample_stride, ::sample_stride].astype(np.float32)
        + output_corrections[:, None, None]
    )
    report = temporal_metrics(
        sampled_output,
        sampled_source,
        sampled_temporal,
        surface[::sample_stride, ::sample_stride],
    )
    report.update(
        {
            "method": "bidirectional_vda_delta_guided_adaptive_smoothing",
            "spatialSource": "Any2Full Large vitl_object_masked_rgb grid4",
            "temporalSource": str(vda_session),
            "strength": strength,
            "differenceThreshold": threshold,
            "vdaDirectionTransform": "269 - encoded_vda_depth",
            "outputQuantizationCorrection": (
                "per-frame mean float residual retained as "
                "baselineHeightCorrection"
            ),
            "sourceSessionPreserved": True,
        }
    )

    output_name = output_session.name
    manifest = dict(source_manifest)
    manifest["frames"] = [
        dict(frame) for frame in source_manifest["frames"]
    ]
    manifest["temporalStabilization"] = report
    for index, frame in enumerate(manifest["frames"], start=1):
        stem = f"{index:06d}"
        frame["cleanDepth"] = f"clean_depth_{stem}.png"
        frame["cleanRgb"] = f"clean_rgb_{stem}.png"
        frame["occlusionMask"] = f"valid_mask_{stem}.png"
        frame["baselineHeightCorrection"] = float(
            output_corrections[index - 1]
        )
    (output_session / "processed_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    session_json = dict(source_session_json)
    session_json["id"] = str(session_json.get("id", "sandstories")) + "_vda_temporal"
    session_json["title"] = (
        str(session_json.get("title", "SandStories"))
        + " - VDA temporal stabilization"
    )
    sources = dict(session_json["data_sources"])
    sources["depth_map"] = (
        f"res://assets/processed_sessions/{output_name}/clean_depth_000001.png"
    )
    sources["detail_depth_map"] = sources["depth_map"]
    sources["texture_map"] = (
        f"res://assets/processed_sessions/{output_name}/clean_rgb_000001.png"
    )
    sources["surface_mask"] = (
        f"res://assets/processed_sessions/{output_name}/surface_mask.png"
    )
    sources["occlusion_mask"] = (
        f"res://assets/processed_sessions/{output_name}/valid_mask_000001.png"
    )
    sources["processed_manifest"] = (
        f"res://assets/processed_sessions/{output_name}/processed_manifest.json"
    )
    session_json["data_sources"] = sources
    production = dict(session_json.get("production_session", {}))
    production["temporalStabilization"] = report
    session_json["production_session"] = production
    (output_session / "session.json").write_text(
        json.dumps(session_json, indent=2), encoding="utf-8"
    )
    (output_session / "temporal_stabilization_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    del sampled_source
    del sampled_temporal
    del sampled_output
    del source_memmap
    del vda_memmap
    del output_memmap
    source_memmap_path.unlink()
    vda_memmap_path.unlink()
    output_memmap_path.unlink()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--vda-session", type=Path, required=True)
    parser.add_argument("--output-session", type=Path)
    parser.add_argument("--tuning-report", type=Path)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--sample-stride", type=int, default=4)
    parser.add_argument("--strength", type=float, default=0.85)
    parser.add_argument("--threshold", type=float, default=10.0)
    parser.add_argument("--chunk-rows", type=int, default=16)
    args = parser.parse_args()

    source_manifest = json.loads(
        (args.source_session / "processed_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    source_session_json = json.loads(
        (args.source_session / "session.json").read_text(encoding="utf-8")
    )
    frames = source_manifest["frames"]
    frame_count = len(frames)
    corrections = np.asarray(
        [
            float(frame.get("baselineHeightCorrection", 0.0))
            for frame in frames
        ],
        dtype=np.float32,
    )
    reconstruction_info = source_manifest.get(
        "any2FullDepthCompletion", {}
    )
    metric_low, metric_high = reconstruction_info.get(
        "metricDepthRange",
        [0.8128636457361647, 0.9216704175465102],
    )
    metric_range = (float(metric_low), float(metric_high))

    if args.tune:
        tuning_report = tune(
            args.source_session,
            args.vda_session,
            frame_count,
            corrections,
            args.sample_stride,
            args.reference_dir,
            metric_range,
        )
        if args.tuning_report is not None:
            args.tuning_report.parent.mkdir(parents=True, exist_ok=True)
            args.tuning_report.write_text(
                json.dumps(tuning_report, indent=2), encoding="utf-8"
            )
        print(json.dumps(tuning_report, indent=2))
        return

    if args.output_session is None:
        parser.error("--output-session is required unless --tune is used")
    report = build(
        args.source_session,
        args.vda_session,
        args.output_session,
        source_manifest,
        source_session_json,
        corrections,
        args.strength,
        args.threshold,
        args.chunk_rows,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
