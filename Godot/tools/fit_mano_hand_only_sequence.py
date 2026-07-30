#!/usr/bin/env python3
"""Fit a stable, anatomically constrained MANO sequence to 2D hand tracks.

All requested frames share one MANO shape and one fixed perspective depth.
Only low-dimensional MANO PCA pose, global orientation, and image translation
vary per frame. Consecutive frames receive temporal priors. Articulation
observations are weighted continuously by the track confidence and the amount
of existing registered RGB-D actor support, so a partially observed hand keeps
its recent pose instead of fitting noise. Tool geometry, intent-specific poses,
and hand-authored masks are not used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn.functional as functional

from fit_mano_hand_only_2d import (
    _axis_angle_to_rotation_matrix,
    _draw_overlay,
    _install_legacy_compatibility,
    _load_track,
    _rotation_matrix_to_axis_angle,
    _sha256,
    MANO,
)


_install_legacy_compatibility()

from smplx.lbs import batch_rodrigues


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--input-manifest",
        default="hamer_inference_manifest.json",
    )
    parser.add_argument("--track-json", type=Path, required=True)
    parser.add_argument("--mano-model-path", type=Path, required=True)
    parser.add_argument(
        "--shared-parameter-report",
        type=Path,
        help=(
            "Optional prior sequence report whose shared MANO betas and "
            "fixed camera depth are reused exactly"
        ),
    )
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument(
        "--observed-geometry-dir",
        type=Path,
        required=True,
        help=(
            "Registered RGB-D geometry whose confidence channel supplies the "
            "existing model-produced actor support"
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--include-intents",
        default="positioning,erasing,drawing,tool_drawing",
        help=(
            "Comma-separated sidecar intent labels. Intent labels only select "
            "frames; they never choose a pose or contact rule."
        ),
    )
    parser.add_argument("--minimum-frame", type=int, default=0)
    parser.add_argument("--maximum-frame", type=int, default=10**9)
    parser.add_argument(
        "--diagnostic-frames",
        default="356,400,526,604",
    )
    parser.add_argument(
        "--image-pattern",
        default="clean_rgb_{frame:06d}.png",
    )
    parser.add_argument("--image-width", type=int, default=640)
    parser.add_argument("--image-height", type=int, default=480)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--learning-rate", type=float, default=0.025)
    parser.add_argument("--pca-components", type=int, default=15)
    parser.add_argument("--pose-prior-weight", type=float, default=0.0025)
    parser.add_argument("--camera-prior-weight", type=float, default=0.001)
    parser.add_argument("--orientation-prior-weight", type=float, default=0.001)
    parser.add_argument(
        "--pose-reference-weight",
        type=float,
        default=0.0,
        help=(
            "Optional fidelity weight to the input sequence's MANO PCA pose. "
            "Use this for a semantics-preserving stabilization pass."
        ),
    )
    parser.add_argument(
        "--orientation-matrix-reference-weight",
        type=float,
        default=0.0,
        help=(
            "Optional representation-independent fidelity weight to the "
            "input sequence's global rotation matrices"
        ),
    )
    parser.add_argument(
        "--camera-screen-reference-weight",
        type=float,
        default=0.0,
        help=(
            "Optional fidelity weight to the input sequence's projected "
            "camera translation in pixel space"
        ),
    )
    parser.add_argument("--mask-containment-weight", type=float, default=0.08)
    parser.add_argument("--distance-field-downsample", type=int, default=4)
    parser.add_argument(
        "--support-reference-percentile",
        type=float,
        default=50.0,
        help=(
            "Observed actor-support area percentile treated as fully visible"
        ),
    )
    parser.add_argument(
        "--densified-reliability-scale",
        type=float,
        default=0.65,
        help="Reliability multiplier for interpolated 21-point observations",
    )
    parser.add_argument(
        "--minimum-landmark-weight",
        type=float,
        default=0.08,
        help="Nonzero floor for uncertain landmark observations",
    )
    parser.add_argument("--pose-acceleration-weight", type=float, default=0.004)
    parser.add_argument(
        "--pose-velocity-weight",
        type=float,
        default=0.06,
        help=(
            "First-order pose continuity applied most strongly where "
            "articulation evidence is weak"
        ),
    )
    parser.add_argument(
        "--orientation-acceleration-weight",
        type=float,
        default=0.001,
    )
    parser.add_argument("--camera-acceleration-weight", type=float, default=0.01)
    parser.add_argument(
        "--orientation-matrix-acceleration-weight",
        type=float,
        default=0.0,
        help=(
            "Representation-independent temporal weight on global rotation "
            "matrices"
        ),
    )
    parser.add_argument(
        "--camera-screen-acceleration-weight",
        type=float,
        default=0.0,
        help="Temporal weight on projected camera translation in pixel space",
    )
    parser.add_argument(
        "--repair-short-track-excursions",
        action="store_true",
        help=(
            "Replace short, automatically detected tracker-association "
            "excursions with bracketed temporal observations"
        ),
    )
    parser.add_argument(
        "--track-excursion-minimum-jump-pixels",
        type=float,
        default=64.0,
    )
    parser.add_argument(
        "--track-excursion-mad-scale",
        type=float,
        default=8.0,
    )
    parser.add_argument(
        "--track-excursion-maximum-frames",
        type=int,
        default=12,
    )
    parser.add_argument(
        "--track-excursion-reliability-scale",
        type=float,
        default=0.15,
    )
    parser.add_argument(
        "--track-surface-mask",
        type=Path,
        help=(
            "Existing registered reconstruction ROI. Detected anchors outside "
            "this support, plus dense spans sourced from them, are excluded."
        ),
    )
    parser.add_argument(
        "--minimum-track-surface-landmark-ratio",
        type=float,
        default=0.2,
    )
    return parser.parse_args()


def _csv_strings(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _csv_frames(value: str) -> set[int]:
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def _forward_mano_batch(
    mano: MANO,
    global_axis_angle: torch.Tensor,
    pose_coefficients: torch.Tensor,
    hand_components: torch.Tensor,
    hand_mean: torch.Tensor,
    betas: torch.Tensor,
) -> tuple[Any, torch.Tensor]:
    batch_size = global_axis_angle.shape[0]
    hand_axis_angle = (
        pose_coefficients @ hand_components + hand_mean
    ).reshape(batch_size, 15, 3)
    rotations = batch_rodrigues(
        torch.cat((global_axis_angle[:, None, :], hand_axis_angle), dim=1)
        .reshape(-1, 3)
    ).reshape(batch_size, 16, 3, 3)
    output = mano(
        global_orient=rotations[:, :1],
        hand_pose=rotations[:, 1:],
        betas=betas,
    )
    return output, hand_axis_angle


def _project_batch(
    points: torch.Tensor,
    camera_xy: torch.Tensor,
    camera_z: torch.Tensor,
    focal_length: torch.Tensor,
    image_size: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    batch_size = points.shape[0]
    z = camera_z.expand(batch_size, 1)
    camera = torch.cat((camera_xy, z), dim=1)
    camera_points = points + camera[:, None, :]
    uv = torch.stack(
        (
            focal_length * camera_points[:, :, 0] / camera_points[:, :, 2]
            + image_size[0] * 0.5,
            focal_length * camera_points[:, :, 1] / camera_points[:, :, 2]
            + image_size[1] * 0.5,
        ),
        dim=2,
    )
    return uv, camera


def _consecutive_triples(frames: list[int], device: torch.device) -> torch.Tensor:
    triples = [
        (index - 1, index, index + 1)
        for index in range(1, len(frames) - 1)
        if frames[index] - frames[index - 1] == 1
        and frames[index + 1] - frames[index] == 1
    ]
    if not triples:
        return torch.empty((0, 3), dtype=torch.long, device=device)
    return torch.tensor(triples, dtype=torch.long, device=device)


def _consecutive_pairs(frames: list[int], device: torch.device) -> torch.Tensor:
    pairs = [
        (index - 1, index)
        for index in range(1, len(frames))
        if frames[index] - frames[index - 1] == 1
    ]
    if not pairs:
        return torch.empty((0, 2), dtype=torch.long, device=device)
    return torch.tensor(pairs, dtype=torch.long, device=device)


def _acceleration_loss(
    values: torch.Tensor,
    triples: torch.Tensor,
) -> torch.Tensor:
    if triples.shape[0] == 0:
        return values.new_zeros(())
    acceleration = (
        values[triples[:, 2]]
        - 2.0 * values[triples[:, 1]]
        + values[triples[:, 0]]
    )
    return acceleration.square().mean()


def _rotation_matrix_acceleration_loss(
    axis_angles: torch.Tensor,
    triples: torch.Tensor,
) -> torch.Tensor:
    if triples.shape[0] == 0:
        return axis_angles.new_zeros(())
    rotations = batch_rodrigues(axis_angles)
    acceleration = (
        rotations[triples[:, 2]]
        - 2.0 * rotations[triples[:, 1]]
        + rotations[triples[:, 0]]
    )
    return acceleration.square().mean()


def _reliability_weighted_velocity_loss(
    values: torch.Tensor,
    pairs: torch.Tensor,
    reliability: torch.Tensor,
) -> torch.Tensor:
    if pairs.shape[0] == 0:
        return values.new_zeros(())
    velocity = values[pairs[:, 1]] - values[pairs[:, 0]]
    pair_reliability = torch.minimum(
        reliability[pairs[:, 0]],
        reliability[pairs[:, 1]],
    )
    weak_evidence_weight = (1.0 - pair_reliability).square()
    per_pair = velocity.square().reshape(velocity.shape[0], -1).mean(dim=1)
    return (
        (per_pair * weak_evidence_weight).sum()
        / weak_evidence_weight.sum().clamp_min(1e-6)
    )


def _detect_short_track_excursions(
    samples: dict[int, dict[str, Any]],
    frames: list[int],
    minimum_jump_pixels: float,
    mad_scale: float,
    maximum_frames: int,
) -> tuple[list[dict[str, Any]], float]:
    if len(frames) < 4:
        return [], float(minimum_jump_pixels)
    wrists = np.stack(
        [
            np.asarray(samples[frame]["pixelLandmarks"][0], dtype=np.float64)
            for frame in frames
        ],
        axis=0,
    )
    consecutive = np.asarray(
        [frames[index + 1] == frames[index] + 1 for index in range(len(frames) - 1)],
        dtype=bool,
    )
    speeds = np.linalg.norm(np.diff(wrists, axis=0), axis=1)
    robust_speeds = speeds[consecutive]
    median_speed = float(np.median(robust_speeds))
    mad = float(np.median(np.abs(robust_speeds - median_speed)))
    threshold = max(
        float(minimum_jump_pixels),
        median_speed + float(mad_scale) * 1.4826 * mad,
    )
    jump_edges = [
        index
        for index, speed in enumerate(speeds)
        if consecutive[index] and float(speed) > threshold
    ]
    excursions: list[dict[str, Any]] = []
    consumed_until = -1
    for edge_index in jump_edges:
        start_index = edge_index + 1
        if start_index <= consumed_until:
            continue
        search_stop = min(
            len(frames) - 1,
            start_index + int(maximum_frames),
        )
        right_index = None
        for candidate in range(start_index + 1, search_stop + 1):
            if frames[candidate] != frames[candidate - 1] + 1:
                break
            if not bool(samples[frames[candidate]].get("densified", False)):
                right_index = candidate
                break
        if right_index is None or right_index <= start_index:
            continue
        if not all(
            bool(samples[frames[index]].get("densified", False))
            for index in range(start_index + 1, right_index)
        ):
            continue
        left_frame = frames[edge_index]
        right_frame = frames[right_index]
        span = float(right_frame - left_frame)
        predicted_start = (
            wrists[edge_index]
            + (wrists[right_index] - wrists[edge_index])
            * ((frames[start_index] - left_frame) / span)
        )
        start_residual = float(
            np.linalg.norm(wrists[start_index] - predicted_start)
        )
        if start_residual <= threshold:
            continue
        excursions.append(
            {
                "startIndex": start_index,
                "endIndex": right_index - 1,
                "startFrame": frames[start_index],
                "endFrame": frames[right_index - 1],
                "leftBracketFrame": left_frame,
                "rightBracketFrame": right_frame,
                "entryJumpPixels": float(speeds[edge_index]),
                "entryResidualFromBracketPixels": start_residual,
            }
        )
        consumed_until = right_index - 1
    return excursions, threshold


def _surface_excluded_track_ranges(
    samples: dict[int, dict[str, Any]],
    frames: list[int],
    surface_mask_path: Path,
    minimum_landmark_ratio: float,
) -> tuple[list[dict[str, Any]], np.ndarray, list[int]]:
    surface_mask = cv2.imread(str(surface_mask_path), cv2.IMREAD_GRAYSCALE)
    if surface_mask is None:
        raise FileNotFoundError(surface_mask_path)
    height, width = surface_mask.shape
    supported = surface_mask > 0
    ratios: list[float] = []
    for frame in frames:
        points = np.asarray(
            samples[frame]["pixelLandmarks"],
            dtype=np.float64,
        )
        pixel_x = np.clip(np.rint(points[:, 0]).astype(np.int64), 0, width - 1)
        pixel_y = np.clip(np.rint(points[:, 1]).astype(np.int64), 0, height - 1)
        ratios.append(float(np.mean(supported[pixel_y, pixel_x])))
    ratio_array = np.asarray(ratios, dtype=np.float32)
    invalid_anchor_frames = {
        frame
        for index, frame in enumerate(frames)
        if not bool(samples[frame].get("densified", False))
        and ratio_array[index] < minimum_landmark_ratio
    }
    invalid_indices: list[int] = []
    for index, frame in enumerate(frames):
        sample = samples[frame]
        source_anchors = {
            int(value)
            for value in sample.get("densifiedFromFrameIndices", [])
        }
        if frame in invalid_anchor_frames or bool(
            source_anchors & invalid_anchor_frames
        ):
            invalid_indices.append(index)
    ranges: list[dict[str, Any]] = []
    range_start = None
    for position, index in enumerate(invalid_indices):
        if range_start is None:
            range_start = index
        next_is_consecutive = (
            position + 1 < len(invalid_indices)
            and invalid_indices[position + 1] == index + 1
            and frames[index + 1] == frames[index] + 1
        )
        if next_is_consecutive:
            continue
        range_end = index
        if range_start > 0 and range_end + 1 < len(frames):
            if (
                frames[range_start] == frames[range_start - 1] + 1
                and frames[range_end + 1] == frames[range_end] + 1
            ):
                ranges.append(
                    {
                        "startIndex": range_start,
                        "endIndex": range_end,
                        "startFrame": frames[range_start],
                        "endFrame": frames[range_end],
                        "leftBracketFrame": frames[range_start - 1],
                        "rightBracketFrame": frames[range_end + 1],
                        "reason": (
                            "outside registered surface ROI or densified from "
                            "an outside anchor"
                        ),
                        "minimumSurfaceLandmarkRatio": float(
                            ratio_array[range_start : range_end + 1].min()
                        ),
                    }
                )
        range_start = None
    return ranges, ratio_array, sorted(invalid_anchor_frames)


def _interpolate_ranges(
    values: np.ndarray,
    frames: list[int],
    ranges: list[dict[str, Any]],
) -> np.ndarray:
    result = values.copy()
    for record in ranges:
        start_index = int(record["startIndex"])
        end_index = int(record["endIndex"])
        left_index = start_index - 1
        right_index = end_index + 1
        frame_span = float(frames[right_index] - frames[left_index])
        for index in range(start_index, end_index + 1):
            alpha = (frames[index] - frames[left_index]) / frame_span
            result[index] = (
                (1.0 - alpha) * result[left_index]
                + alpha * result[right_index]
            )
    return result


def _interpolate_global_rotations(
    rotation_matrices: np.ndarray,
    frames: list[int],
    ranges: list[dict[str, Any]],
) -> np.ndarray:
    result = rotation_matrices.copy()
    for record in ranges:
        start_index = int(record["startIndex"])
        end_index = int(record["endIndex"])
        left_index = start_index - 1
        right_index = end_index + 1
        frame_span = float(frames[right_index] - frames[left_index])
        for index in range(start_index, end_index + 1):
            alpha = (frames[index] - frames[left_index]) / frame_span
            blended = (
                (1.0 - alpha) * result[left_index]
                + alpha * result[right_index]
            )
            left, _, right = np.linalg.svd(blended)
            projected = left @ right
            if float(np.linalg.det(projected)) < 0.0:
                left[:, -1] *= -1.0
                projected = left @ right
            result[index] = projected
    return np.stack(
        [
            _rotation_matrix_to_axis_angle(matrix).reshape(3)
            for matrix in result
        ],
        axis=0,
    ).astype(np.float32)


def _outside_distance_fields(
    directory: Path,
    frames: list[int],
    image_width: int,
    image_height: int,
    downsample: int,
) -> tuple[np.ndarray, np.ndarray]:
    if downsample < 1:
        raise ValueError("--distance-field-downsample must be positive")
    field_width = max(1, image_width // downsample)
    field_height = max(1, image_height // downsample)
    fields: list[np.ndarray] = []
    support_pixels: list[int] = []
    for frame in frames:
        geometry_path = directory / f"virtual_hand_geometry_{frame:06d}.png"
        geometry = cv2.imread(str(geometry_path), cv2.IMREAD_UNCHANGED)
        if (
            geometry is None
            or geometry.shape[:2] != (image_height, image_width)
            or geometry.ndim != 3
            or geometry.shape[2] < 3
        ):
            raise FileNotFoundError(geometry_path)
        support = geometry[:, :, 1] > 0
        support_pixels.append(int(np.count_nonzero(support)))
        outside_distance = cv2.distanceTransform(
            (~support).astype(np.uint8),
            cv2.DIST_L2,
            5,
        )
        if downsample > 1:
            outside_distance = cv2.resize(
                outside_distance,
                (field_width, field_height),
                interpolation=cv2.INTER_LINEAR,
            )
        fields.append(outside_distance.astype(np.float32))
    return (
        np.stack(fields, axis=0)[:, None, :, :],
        np.asarray(support_pixels, dtype=np.float32),
    )


def _sample_distance_fields(
    fields: torch.Tensor,
    vertex_uv: torch.Tensor,
    image_size: torch.Tensor,
) -> torch.Tensor:
    grid = torch.stack(
        (
            vertex_uv[:, :, 0] / (image_size[0] - 1.0) * 2.0 - 1.0,
            vertex_uv[:, :, 1] / (image_size[1] - 1.0) * 2.0 - 1.0,
        ),
        dim=2,
    )[:, :, None, :]
    return functional.grid_sample(
        fields,
        grid,
        mode="bilinear",
        padding_mode="border",
        align_corners=True,
    )[:, 0, :, 0]


def main() -> None:
    args = _parse_args()
    args.input_dir = args.input_dir.resolve()
    args.track_json = args.track_json.resolve()
    args.mano_model_path = args.mano_model_path.resolve()
    args.rgb_dir = args.rgb_dir.resolve()
    args.observed_geometry_dir = args.observed_geometry_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    source_manifest_path = args.input_dir / args.input_manifest
    for path in (
        args.input_dir,
        source_manifest_path,
        args.track_json,
        args.mano_model_path,
        args.rgb_dir,
        args.observed_geometry_dir,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    if not 1 <= args.pca_components <= 44:
        raise ValueError("--pca-components must be between 1 and 44")
    if args.iterations <= 0:
        raise ValueError("--iterations must be positive")
    if not 0.0 <= args.support_reference_percentile <= 100.0:
        raise ValueError(
            "--support-reference-percentile must be between 0 and 100"
        )
    if not 0.0 <= args.densified_reliability_scale <= 1.0:
        raise ValueError(
            "--densified-reliability-scale must be between 0 and 1"
        )
    if not 0.0 < args.minimum_landmark_weight <= 1.0:
        raise ValueError("--minimum-landmark-weight must be in (0, 1]")

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA device requested but unavailable: {device}")
    samples = _load_track(args.track_json)
    include_intents = _csv_strings(args.include_intents)
    diagnostic_frames = _csv_frames(args.diagnostic_frames)

    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    source_records = {
        int(record["frameIndex"]): record
        for record in source_manifest["frames"]
    }
    frames = sorted(
        frame
        for frame, sample in samples.items()
        if frame in source_records
        and args.minimum_frame <= frame <= args.maximum_frame
        and str(sample.get("intent")) in include_intents
    )
    if not frames:
        raise ValueError("No source frames matched the requested hand-only filter")

    source_arrays = [
        np.load(args.input_dir / source_records[frame]["arrays"])
        for frame in frames
    ]
    shared_parameter_report = None
    if args.shared_parameter_report is not None:
        shared_parameter_report = json.loads(
            args.shared_parameter_report.read_text(encoding="utf-8")
        )
        shared_betas = np.asarray(
            shared_parameter_report["sharedBetas"],
            dtype=np.float32,
        )
        shared_camera_z = float(
            shared_parameter_report["sharedCameraZ"]
        )
    else:
        shared_betas = np.median(
            np.stack([arrays["betas"] for arrays in source_arrays], axis=0),
            axis=0,
        ).astype(np.float32)
        shared_camera_z = float(
            np.median(
                [float(arrays["cam_full"][2]) for arrays in source_arrays]
            )
        )
    focal_lengths = np.asarray(
        [float(arrays["focal_length_px"]) for arrays in source_arrays],
        dtype=np.float32,
    )
    if float(np.ptp(focal_lengths)) > 1e-3:
        raise ValueError("Expected one fixed focal length across the sequence")
    focal_length_value = float(np.median(focal_lengths))

    mano = MANO(
        model_path=str(args.mano_model_path),
        is_rhand=True,
        use_pca=True,
        num_pca_comps=args.pca_components,
        flat_hand_mean=False,
    ).to(device)
    mano.eval()
    for parameter in mano.parameters():
        parameter.requires_grad_(False)
    faces = np.asarray(mano.faces, dtype=np.int32)
    hand_components = mano.hand_components.detach()
    hand_mean = mano.hand_mean.detach()
    betas = (
        torch.from_numpy(shared_betas)
        .to(device)
        .reshape(1, -1)
        .expand(len(frames), -1)
    )

    initial_global_matrices_np = np.stack(
        [
            np.asarray(arrays["global_orient"], dtype=np.float32).reshape(3, 3)
            for arrays in source_arrays
        ],
        axis=0,
    )
    initial_global_np = np.stack(
        [
            _rotation_matrix_to_axis_angle(matrix).reshape(3)
            for matrix in initial_global_matrices_np
        ],
        axis=0,
    ).astype(np.float32)
    initial_hand_np = np.stack(
        [
            _rotation_matrix_to_axis_angle(arrays["hand_pose"]).reshape(45)
            for arrays in source_arrays
        ],
        axis=0,
    )
    initial_camera_np = np.stack(
        [arrays["cam_full"].astype(np.float32) for arrays in source_arrays],
        axis=0,
    )
    target_np = np.stack(
        [
            np.asarray(samples[frame]["pixelLandmarks"], dtype=np.float32)
            for frame in frames
        ],
        axis=0,
    )
    if target_np.shape != (len(frames), 21, 2) or not np.isfinite(
        target_np
    ).all():
        raise ValueError("Invalid sequence landmark tensor")
    source_target_np = target_np.copy()
    track_excursions: list[dict[str, Any]] = []
    track_excursion_threshold = None
    track_surface_ratios_np = np.ones(len(frames), dtype=np.float32)
    invalid_surface_anchor_frames: list[int] = []
    if args.repair_short_track_excursions:
        speed_excursions, track_excursion_threshold = (
            _detect_short_track_excursions(
                samples,
                frames,
                args.track_excursion_minimum_jump_pixels,
                args.track_excursion_mad_scale,
                args.track_excursion_maximum_frames,
            )
        )
        track_excursions.extend(speed_excursions)
    if args.track_surface_mask is not None:
        (
            surface_excursions,
            track_surface_ratios_np,
            invalid_surface_anchor_frames,
        ) = _surface_excluded_track_ranges(
            samples,
            frames,
            args.track_surface_mask,
            args.minimum_track_surface_landmark_ratio,
        )
        track_excursions.extend(surface_excursions)
    track_excursions.sort(key=lambda item: int(item["startIndex"]))
    for previous, current in zip(track_excursions, track_excursions[1:]):
        if int(current["startIndex"]) <= int(previous["endIndex"]):
            raise ValueError(
                "Overlapping automatic track-excursion repairs are ambiguous"
            )
    temporal_association_scale_np = np.ones(len(frames), dtype=np.float32)
    if track_excursions:
        target_np = _interpolate_ranges(
            target_np,
            frames,
            track_excursions,
        )
        initial_global_np = _interpolate_global_rotations(
            initial_global_matrices_np,
            frames,
            track_excursions,
        )
        initial_hand_np = _interpolate_ranges(
            initial_hand_np,
            frames,
            track_excursions,
        )
        initial_camera_np = _interpolate_ranges(
            initial_camera_np,
            frames,
            track_excursions,
        )
        for record in track_excursions:
            temporal_association_scale_np[
                int(record["startIndex"]) : int(record["endIndex"]) + 1
            ] = args.track_excursion_reliability_scale
        print(
            "repaired track excursions: "
            + ", ".join(
                f"{record['startFrame']}-{record['endFrame']}"
                for record in track_excursions
            ),
            flush=True,
        )
    target_scale_np = np.maximum(
        np.linalg.norm(
            target_np.max(axis=1) - target_np.min(axis=1),
            axis=1,
        ),
        24.0,
    ).astype(np.float32)
    outside_distance_np, support_pixels_np = _outside_distance_fields(
        args.observed_geometry_dir,
        frames,
        args.image_width,
        args.image_height,
        args.distance_field_downsample,
    )
    support_reference_pixels = float(
        np.percentile(
            support_pixels_np,
            args.support_reference_percentile,
        )
    )
    if support_reference_pixels <= 0.0:
        raise ValueError("Observed actor support is empty")
    support_reliability_np = np.clip(
        support_pixels_np / support_reference_pixels,
        0.0,
        1.0,
    ).astype(np.float32)
    track_confidence_np = np.clip(
        np.asarray(
            [
                float(samples[frame].get("confidence", 0.0))
                for frame in frames
            ],
            dtype=np.float32,
        ),
        0.0,
        1.0,
    )
    source_track_confidence_np = track_confidence_np.copy()
    track_confidence_np *= temporal_association_scale_np
    densified_scale_np = np.asarray(
        [
            (
                args.densified_reliability_scale
                if bool(samples[frame].get("densified", False))
                else 1.0
            )
            for frame in frames
        ],
        dtype=np.float32,
    )
    articulation_reliability_np = np.clip(
        track_confidence_np
        * support_reliability_np
        * densified_scale_np,
        0.0,
        1.0,
    ).astype(np.float32)
    rigid_reliability_np = np.sqrt(
        np.clip(
            track_confidence_np * support_reliability_np,
            0.0,
            1.0,
        )
    ).astype(np.float32)

    initial_global = torch.from_numpy(initial_global_np).to(device)
    initial_hand = torch.from_numpy(initial_hand_np).to(device)
    initial_camera = torch.from_numpy(initial_camera_np).to(device)
    target = torch.from_numpy(target_np).to(device)
    target_scale = torch.from_numpy(target_scale_np).to(device)
    outside_distance_fields = torch.from_numpy(outside_distance_np).to(device)
    articulation_reliability = torch.from_numpy(
        articulation_reliability_np
    ).to(device)
    rigid_reliability = torch.from_numpy(rigid_reliability_np).to(device)
    initial_coefficients = (
        (initial_hand - hand_mean) @ hand_components.transpose(0, 1)
    )[:, : args.pca_components]
    initial_global_matrices = torch.from_numpy(
        initial_global_matrices_np
    ).to(device)
    pose_coefficients = torch.nn.Parameter(initial_coefficients.clone())
    global_axis_angle = torch.nn.Parameter(initial_global.clone())
    camera_xy = torch.nn.Parameter(initial_camera[:, :2].clone())
    camera_z = torch.tensor(
        shared_camera_z,
        dtype=torch.float32,
        device=device,
    )
    focal_length = torch.tensor(
        focal_length_value,
        dtype=torch.float32,
        device=device,
    )
    image_size = torch.tensor(
        [float(args.image_width), float(args.image_height)],
        dtype=torch.float32,
        device=device,
    )
    triples = _consecutive_triples(frames, device)
    pairs = _consecutive_pairs(frames, device)
    palm_joint_indices = torch.tensor(
        [0, 1, 5, 9, 13, 17],
        dtype=torch.long,
        device=device,
    )

    optimizer = torch.optim.Adam(
        [
            {"params": [pose_coefficients], "lr": args.learning_rate},
            {"params": [global_axis_angle], "lr": args.learning_rate * 0.35},
            {"params": [camera_xy], "lr": args.learning_rate * 0.08},
        ]
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=args.iterations,
        eta_min=args.learning_rate * 0.02,
    )

    with torch.no_grad():
        initial_output, _ = _forward_mano_batch(
            mano,
            global_axis_angle,
            pose_coefficients,
            hand_components,
            hand_mean,
            betas,
        )
        initial_joint_uv, _ = _project_batch(
            initial_output.joints,
            camera_xy,
            camera_z,
            focal_length,
            image_size,
        )
        initial_error = torch.linalg.vector_norm(
            initial_joint_uv - target, dim=2
        )

    for iteration in range(args.iterations):
        optimizer.zero_grad(set_to_none=True)
        output, _ = _forward_mano_batch(
            mano,
            global_axis_angle,
            pose_coefficients,
            hand_components,
            hand_mean,
            betas,
        )
        joint_uv, _ = _project_batch(
            output.joints,
            camera_xy,
            camera_z,
            focal_length,
            image_size,
        )
        vertex_uv, _ = _project_batch(
            output.vertices,
            camera_xy,
            camera_z,
            focal_length,
            image_size,
        )
        normalized_delta = (
            joint_uv - target
        ) / target_scale[:, None, None]
        per_coordinate_landmark_loss = functional.smooth_l1_loss(
            normalized_delta,
            torch.zeros_like(normalized_delta),
            beta=0.025,
            reduction="none",
        )
        per_joint_landmark_loss = per_coordinate_landmark_loss.mean(dim=2)
        landmark_weights = articulation_reliability[:, None].expand(
            -1, target.shape[1]
        ).clone()
        landmark_weights[:, palm_joint_indices] = rigid_reliability[:, None]
        landmark_weights = landmark_weights.clamp_min(
            args.minimum_landmark_weight
        )
        landmark_loss = (
            (per_joint_landmark_loss * landmark_weights).sum()
            / landmark_weights.sum().clamp_min(1e-6)
        )
        outside_distance = _sample_distance_fields(
            outside_distance_fields,
            vertex_uv,
            image_size,
        )
        mask_containment_loss = functional.smooth_l1_loss(
            outside_distance / target_scale[:, None],
            torch.zeros_like(outside_distance),
            beta=0.01,
        )
        pose_prior = pose_coefficients.square().mean()
        pose_reference = (
            (
                pose_coefficients - initial_coefficients
            ).square().mean(dim=1)
            * articulation_reliability
        ).sum() / articulation_reliability.sum().clamp_min(1e-6)
        orientation_prior = (
            global_axis_angle - initial_global
        ).square().mean()
        global_rotation_matrices = batch_rodrigues(global_axis_angle)
        orientation_matrix_reference = (
            (
                global_rotation_matrices - initial_global_matrices
            ).square().mean(dim=(1, 2))
            * rigid_reliability
        ).sum() / rigid_reliability.sum().clamp_min(1e-6)
        camera_prior = (
            (camera_xy - initial_camera[:, :2]) / camera_z
        ).square().mean()
        camera_screen_reference = (
            (
                focal_length
                * (camera_xy - initial_camera[:, :2])
                / camera_z
            ).square().mean(dim=1)
            * rigid_reliability
        ).sum() / rigid_reliability.sum().clamp_min(1e-6)
        pose_acceleration = _acceleration_loss(pose_coefficients, triples)
        pose_velocity = _reliability_weighted_velocity_loss(
            pose_coefficients,
            pairs,
            articulation_reliability,
        )
        orientation_acceleration = _acceleration_loss(
            global_axis_angle, triples
        )
        camera_acceleration = _acceleration_loss(camera_xy / camera_z, triples)
        orientation_matrix_acceleration = (
            _rotation_matrix_acceleration_loss(
                global_axis_angle,
                triples,
            )
        )
        camera_screen_acceleration = _acceleration_loss(
            focal_length * camera_xy / camera_z,
            triples,
        )
        loss = (
            landmark_loss
            + args.mask_containment_weight * mask_containment_loss
            + args.pose_prior_weight * pose_prior
            + args.pose_reference_weight * pose_reference
            + args.orientation_prior_weight * orientation_prior
            + args.orientation_matrix_reference_weight
            * orientation_matrix_reference
            + args.camera_prior_weight * camera_prior
            + args.camera_screen_reference_weight
            * camera_screen_reference
            + args.pose_acceleration_weight * pose_acceleration
            + args.pose_velocity_weight * pose_velocity
            + args.orientation_acceleration_weight * orientation_acceleration
            + args.camera_acceleration_weight * camera_acceleration
            + args.orientation_matrix_acceleration_weight
            * orientation_matrix_acceleration
            + args.camera_screen_acceleration_weight
            * camera_screen_acceleration
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            [pose_coefficients, global_axis_angle, camera_xy],
            max_norm=8.0,
        )
        optimizer.step()
        scheduler.step()
        if iteration % 100 == 0 or iteration + 1 == args.iterations:
            print(
                f"iteration {iteration + 1}/{args.iterations}: "
                f"loss={float(loss.detach()):.6f}, "
                f"landmarks={float(landmark_loss.detach()):.6f}, "
                f"containment={float(mask_containment_loss.detach()):.6f}",
                flush=True,
            )

    with torch.no_grad():
        output, hand_axis_angle = _forward_mano_batch(
            mano,
            global_axis_angle,
            pose_coefficients,
            hand_components,
            hand_mean,
            betas,
        )
        vertex_uv, camera = _project_batch(
            output.vertices,
            camera_xy,
            camera_z,
            focal_length,
            image_size,
        )
        joint_uv, _ = _project_batch(
            output.joints,
            camera_xy,
            camera_z,
            focal_length,
            image_size,
        )
        final_error = torch.linalg.vector_norm(joint_uv - target, dim=2)

    vertices_np = output.vertices.cpu().numpy().astype(np.float32)
    joints_np = output.joints.cpu().numpy().astype(np.float32)
    vertex_uv_np = vertex_uv.cpu().numpy().astype(np.float32)
    joint_uv_np = joint_uv.cpu().numpy().astype(np.float32)
    camera_np = camera.cpu().numpy().astype(np.float32)
    global_np = global_axis_angle.detach().cpu().numpy().astype(np.float32)
    hand_np = hand_axis_angle.cpu().numpy().astype(np.float32)
    coefficients_np = (
        pose_coefficients.detach().cpu().numpy().astype(np.float32)
    )
    initial_error_np = initial_error.cpu().numpy()
    final_error_np = final_error.cpu().numpy()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        vertices_camera = vertices_np[index] + camera_np[index]
        joints_camera = joints_np[index] + camera_np[index]
        array_path = args.output_dir / f"mano_hand_only_{frame:06d}.npz"
        np.savez_compressed(
            array_path,
            vertices_model=vertices_np[index],
            vertices_camera=vertices_camera,
            joints_model=joints_np[index],
            joints_camera=joints_camera,
            faces=faces,
            vertex_uv=vertex_uv_np[index],
            joint_uv=joint_uv_np[index],
            cam_full=camera_np[index],
            focal_length_px=np.float32(focal_length_value),
            crop_landmarks_xy=target_np[index],
            source_crop_landmarks_xy=source_target_np[index],
            global_orient=_axis_angle_to_rotation_matrix(
                global_np[index]
            ).reshape(1, 3, 3),
            hand_pose=_axis_angle_to_rotation_matrix(hand_np[index]),
            hand_pose_axis_angle=hand_np[index],
            mano_pca_coefficients=coefficients_np[index],
            betas=shared_betas,
            is_right=np.float32(1.0),
            track_excursion_repaired=np.asarray(
                temporal_association_scale_np[index] < 1.0,
                dtype=np.bool_,
            ),
        )
        overlay_name = None
        if frame in diagnostic_frames:
            image_path = args.rgb_dir / args.image_pattern.format(frame=frame)
            image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image_bgr is None:
                raise FileNotFoundError(image_path)
            overlay = _draw_overlay(
                image_bgr,
                vertex_uv_np[index],
                joint_uv_np[index],
                target_np[index],
                faces,
            )
            overlay_path = (
                args.output_dir
                / f"mano_hand_only_{frame:06d}_overlay.png"
            )
            if not cv2.imwrite(str(overlay_path), overlay):
                raise RuntimeError(f"Failed to write {overlay_path}")
            overlay_name = overlay_path.name
        records.append(
            {
                "frameIndex": frame,
                "intent": samples[frame].get("intent"),
                "trackConfidence": float(track_confidence_np[index]),
                "sourceTrackConfidence": float(
                    source_track_confidence_np[index]
                ),
                "trackDensified": bool(
                    samples[frame].get("densified", False)
                ),
                "trackExcursionRepaired": bool(
                    temporal_association_scale_np[index] < 1.0
                ),
                "trackSurfaceLandmarkRatio": float(
                    track_surface_ratios_np[index]
                ),
                "observedSupportPixels": int(support_pixels_np[index]),
                "observedSupportReliability": float(
                    support_reliability_np[index]
                ),
                "articulationReliability": float(
                    articulation_reliability_np[index]
                ),
                "rigidReliability": float(rigid_reliability_np[index]),
                "sourceArrays": str(
                    (args.input_dir / source_records[frame]["arrays"]).resolve()
                ),
                "arrays": array_path.name,
                "arraysSha256": _sha256(array_path),
                "overlay": overlay_name,
                "initialMeanLandmarkErrorPixels": float(
                    initial_error_np[index].mean()
                ),
                "finalMeanLandmarkErrorPixels": float(
                    final_error_np[index].mean()
                ),
                "finalP95LandmarkErrorPixels": float(
                    np.percentile(final_error_np[index], 95)
                ),
            }
        )

    final_mean = np.asarray(
        [record["finalMeanLandmarkErrorPixels"] for record in records],
        dtype=np.float64,
    )
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "method": (
            "hand-only low-dimensional MANO sequence inverse kinematics "
            "against model-produced 21-point image landmarks, with shared "
            "shape, fixed perspective depth, confidence/support-weighted "
            "articulation, and temporal continuity priors"
        ),
        "handAuthoredMasks": False,
        "constraintsExcluded": [
            "tool geometry",
            "tool contact",
            "intent-specific pose rules",
            "hand-authored masks",
        ],
        "sourceInferenceManifest": str(source_manifest_path),
        "sourceInferenceManifestSha256": _sha256(source_manifest_path),
        "trackJson": str(args.track_json),
        "trackJsonSha256": _sha256(args.track_json),
        "observedGeometryDir": str(args.observed_geometry_dir),
        "observedSupportPolicy": (
            "distance-to-existing registered RGB-D actor support; "
            "no mask synthesis or dilation"
        ),
        "manoModelPath": str(args.mano_model_path),
        "manoModelSha256": _sha256(args.mano_model_path),
        "rgbDir": str(args.rgb_dir),
        "includeIntents": sorted(include_intents),
        "minimumFrame": args.minimum_frame,
        "maximumFrame": args.maximum_frame,
        "frameCount": len(frames),
        "framesRequested": frames,
        "sharedBetas": shared_betas.tolist(),
        "sharedParameterReport": (
            str(args.shared_parameter_report.resolve())
            if args.shared_parameter_report is not None
            else None
        ),
        "sharedParameterReportSha256": (
            _sha256(args.shared_parameter_report)
            if args.shared_parameter_report is not None
            else None
        ),
        "cameraDepthPolicy": "shared_fixed",
        "sharedCameraZ": shared_camera_z,
        "focalLengthPixels": focal_length_value,
        "pcaComponents": args.pca_components,
        "iterations": args.iterations,
        "maskContainmentWeight": args.mask_containment_weight,
        "distanceFieldDownsample": args.distance_field_downsample,
        "supportReferencePercentile": args.support_reference_percentile,
        "supportReferencePixels": support_reference_pixels,
        "densifiedReliabilityScale": args.densified_reliability_scale,
        "minimumLandmarkWeight": args.minimum_landmark_weight,
        "articulationReliability": {
            "minimum": float(articulation_reliability_np.min()),
            "mean": float(articulation_reliability_np.mean()),
            "p10": float(
                np.percentile(articulation_reliability_np, 10)
            ),
            "p50": float(
                np.percentile(articulation_reliability_np, 50)
            ),
            "p90": float(
                np.percentile(articulation_reliability_np, 90)
            ),
            "maximum": float(articulation_reliability_np.max()),
        },
        "temporalConsecutiveTripleCount": int(triples.shape[0]),
        "temporalConsecutivePairCount": int(pairs.shape[0]),
        "poseAccelerationWeight": args.pose_acceleration_weight,
        "poseVelocityWeight": args.pose_velocity_weight,
        "poseReferenceWeight": args.pose_reference_weight,
        "orientationAccelerationWeight": (
            args.orientation_acceleration_weight
        ),
        "orientationMatrixReferenceWeight": (
            args.orientation_matrix_reference_weight
        ),
        "cameraAccelerationWeight": args.camera_acceleration_weight,
        "cameraScreenReferenceWeight": (
            args.camera_screen_reference_weight
        ),
        "orientationMatrixAccelerationWeight": (
            args.orientation_matrix_acceleration_weight
        ),
        "cameraScreenAccelerationWeight": (
            args.camera_screen_acceleration_weight
        ),
        "repairShortTrackExcursions": bool(
            args.repair_short_track_excursions
        ),
        "trackExcursionJumpThresholdPixels": (
            track_excursion_threshold
        ),
        "trackExcursionReliabilityScale": (
            args.track_excursion_reliability_scale
        ),
        "trackSurfaceMask": (
            str(args.track_surface_mask.resolve())
            if args.track_surface_mask is not None
            else None
        ),
        "trackSurfaceMaskSha256": (
            _sha256(args.track_surface_mask)
            if args.track_surface_mask is not None
            else None
        ),
        "minimumTrackSurfaceLandmarkRatio": (
            args.minimum_track_surface_landmark_ratio
        ),
        "invalidSurfaceAnchorFrames": invalid_surface_anchor_frames,
        "repairedTrackExcursions": [
            {
                key: value
                for key, value in record.items()
                if key not in {"startIndex", "endIndex"}
            }
            for record in track_excursions
        ],
        "finalLandmarkErrorPixels": {
            "mean": float(final_mean.mean()),
            "p50": float(np.percentile(final_mean, 50)),
            "p90": float(np.percentile(final_mean, 90)),
            "p95": float(np.percentile(final_mean, 95)),
            "maximum": float(final_mean.max()),
        },
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cudaRuntime": torch.version.cuda,
            "gpu": (
                torch.cuda.get_device_name(device)
                if device.type == "cuda"
                else None
            ),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
        "frames": records,
    }
    report_path = args.output_dir / "mano_hand_only_sequence_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    inference_manifest_path = args.output_dir / "hamer_inference_manifest.json"
    inference_manifest_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {len(frames)} frames to {args.output_dir}; "
        f"mean landmark error {final_mean.mean():.3f}px",
        flush=True,
    )


if __name__ == "__main__":
    main()
