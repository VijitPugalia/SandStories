#!/usr/bin/env python3
"""Add temporally stable, mask-aware object-space normals to a Godot session.

The source depth remains unchanged.  Normals are estimated from a separate
regularized height stack so millimetre-scale inpainting seams do not become
large lighting creases.  Existing session assets are hard-linked when
possible, making the derived session non-destructive and inexpensive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import cv2
import numpy as np


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def decode_rg16(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if bgr is None or bgr.ndim != 3 or bgr.shape[2] < 3:
        raise FileNotFoundError(path)
    high = bgr[..., 2].astype(np.uint16)
    low = bgr[..., 1].astype(np.uint16)
    return ((high << 8) | low).astype(np.float32) / 65535.0


def object_normals(
    height: np.ndarray,
    world_height_per_unit: float,
    plane_width: float,
    plane_depth: float,
) -> np.ndarray:
    # Scharr's unnormalised first derivative has a scale of 32.
    derivative_x = cv2.Scharr(height, cv2.CV_32F, 1, 0) / 32.0
    derivative_z = cv2.Scharr(height, cv2.CV_32F, 0, 1) / 32.0
    pixel_world_x = plane_width / max(height.shape[1] - 1, 1)
    pixel_world_z = plane_depth / max(height.shape[0] - 1, 1)
    slope_x = derivative_x * world_height_per_unit / pixel_world_x
    slope_z = derivative_z * world_height_per_unit / pixel_world_z
    normal = np.dstack((-slope_x, np.ones_like(height), -slope_z))
    normal /= np.maximum(np.linalg.norm(normal, axis=2, keepdims=True), 1e-8)
    return normal.astype(np.float32)


def encode_object_normal(normal: np.ndarray, surface: np.ndarray) -> np.ndarray:
    encoded = np.uint8(np.clip((normal * 0.5 + 0.5) * 255.0 + 0.5, 0, 255))
    # OpenCV writes BGR; the texture must decode as RGB=(nx, ny, nz).
    bgr = encoded[..., [2, 1, 0]].copy()
    bgr[~surface] = np.array([128, 255, 128], np.uint8)
    return bgr


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_session", type=Path)
    parser.add_argument("output_session", type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--temporal-radius", type=int, default=2)
    parser.add_argument("--fine-diameter", type=int, default=7)
    parser.add_argument("--fine-sigma-mm", type=float, default=1.5)
    parser.add_argument("--coarse-diameter", type=int, default=15)
    parser.add_argument("--coarse-sigma-mm", type=float, default=4.0)
    parser.add_argument("--coarse-spatial-sigma", type=float, default=5.0)
    parser.add_argument("--masked-normal-confidence", type=float, default=0.68)
    parser.add_argument("--plane-width", type=float, default=5.5)
    parser.add_argument("--plane-depth", type=float, default=5.5)
    parser.add_argument("--shader-arg-1", type=float, default=11.625)
    parser.add_argument("--displacement", type=float, default=-5.0)
    parser.add_argument("--metric-range-mm", type=float, default=230.0)
    parser.add_argument("--review-frames", default="1,100,112,131,160,181,201")
    args = parser.parse_args()

    if args.output_session.exists():
        raise FileExistsError(args.output_session)
    depth_files = sorted((args.source_session / "clean_depth").glob("*.png"))
    feather_files = sorted((args.source_session / "feather_mask").glob("*.png"))
    if not depth_files or len(depth_files) != len(feather_files):
        raise ValueError("clean_depth and feather_mask must have matching frames")
    surface = cv2.imread(str(args.source_session / "surface_mask.png"), cv2.IMREAD_GRAYSCALE)
    if surface is None:
        raise FileNotFoundError(args.source_session / "surface_mask.png")
    surface = surface > 0

    print(f"loading {len(depth_files)} RG16 height frames", flush=True)
    height_stack = np.stack([decode_rg16(path) for path in depth_files])
    feather_stack = np.stack([
        cv2.imread(str(path), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
        for path in feather_files
    ])

    # Preserve all source assets using hard links, then replace only metadata.
    for source in args.source_session.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(args.source_session)
        if relative.name in {"session.json", "processed_manifest.json", "build_receipt.json"}:
            continue
        link_or_copy(source, args.output_session / relative)
    normal_dir = args.output_session / "normal_map"
    confidence_dir = args.output_session / "normal_confidence"
    normal_dir.mkdir(parents=True, exist_ok=True)
    confidence_dir.mkdir(parents=True, exist_ok=True)

    # RG16 encodes 230 mm across 0..1. Convert bilateral sigma from millimetres.
    fine_sigma = args.fine_sigma_mm / args.metric_range_mm
    coarse_sigma = args.coarse_sigma_mm / args.metric_range_mm
    world_height_per_unit = abs(args.displacement) / args.shader_arg_1
    previous_raw_normal = None
    previous_robust_normal = None
    raw_temporal_angles: list[np.ndarray] = []
    robust_temporal_angles: list[np.ndarray] = []
    core_angle_changes: list[np.ndarray] = []
    review_indices = {int(value) for value in args.review_frames.split(",") if value.strip()}
    review_rows: list[np.ndarray] = []

    print("building temporal-median + bilateral local-plane normals", flush=True)
    for index, depth_path in enumerate(depth_files):
        start = max(0, index - args.temporal_radius)
        stop = min(len(depth_files), index + args.temporal_radius + 1)
        temporal_median = np.median(height_stack[start:stop], axis=0).astype(np.float32)
        alpha = feather_stack[index]
        temporal_weight = 0.70 * alpha
        temporal_height = height_stack[index] * (1.0 - temporal_weight) + temporal_median * temporal_weight
        fine = cv2.bilateralFilter(
            temporal_height,
            args.fine_diameter,
            fine_sigma,
            2.5,
        )
        coarse = cv2.bilateralFilter(
            temporal_height,
            args.coarse_diameter,
            coarse_sigma,
            args.coarse_spatial_sigma,
        )
        normal_height = fine * (1.0 - alpha) + coarse * alpha
        robust_normal = object_normals(
            normal_height,
            world_height_per_unit,
            args.plane_width,
            args.plane_depth,
        )
        raw_normal = object_normals(
            height_stack[index],
            world_height_per_unit,
            args.plane_width,
            args.plane_depth,
        )
        confidence = 1.0 - alpha * (1.0 - args.masked_normal_confidence)
        confidence[~surface] = 0.0

        stem = f"{index + 1:06d}"
        cv2.imwrite(str(normal_dir / f"normal_{stem}.png"), encode_object_normal(robust_normal, surface))
        cv2.imwrite(
            str(confidence_dir / f"normal_confidence_{stem}.png"),
            np.uint8(np.clip(confidence * 255.0 + 0.5, 0, 255)),
        )

        core = (alpha >= 0.99) & surface
        if core.any():
            dot = np.sum(raw_normal * robust_normal, axis=2)
            core_angle_changes.append(np.degrees(np.arccos(np.clip(dot[core], -1.0, 1.0))))
        if previous_raw_normal is not None:
            shared = (alpha >= 0.25) & (feather_stack[index - 1] >= 0.25) & surface
            if shared.any():
                raw_dot = np.sum(previous_raw_normal * raw_normal, axis=2)
                robust_dot = np.sum(previous_robust_normal * robust_normal, axis=2)
                raw_temporal_angles.append(np.degrees(np.arccos(np.clip(raw_dot[shared], -1.0, 1.0))))
                robust_temporal_angles.append(np.degrees(np.arccos(np.clip(robust_dot[shared], -1.0, 1.0))))
        previous_raw_normal = raw_normal
        previous_robust_normal = robust_normal

        if index + 1 in review_indices:
            normal_rgb = cv2.cvtColor(encode_object_normal(robust_normal, surface), cv2.COLOR_BGR2RGB)
            raw_slope = np.degrees(np.arccos(np.clip(raw_normal[..., 1], -1.0, 1.0)))
            robust_slope = np.degrees(np.arccos(np.clip(robust_normal[..., 1], -1.0, 1.0)))
            raw_heat = cv2.applyColorMap(np.uint8(np.clip(raw_slope / 45.0 * 255.0, 0, 255)), cv2.COLORMAP_TURBO)
            robust_heat = cv2.applyColorMap(np.uint8(np.clip(robust_slope / 45.0 * 255.0, 0, 255)), cv2.COLORMAP_TURBO)
            raw_heat[~surface] = 0
            robust_heat[~surface] = 0
            mask_vis = cv2.applyColorMap(np.uint8(alpha * 255.0), cv2.COLORMAP_MAGMA)
            row = np.hstack([
                cv2.resize(normal_rgb, (320, 288), interpolation=cv2.INTER_AREA),
                cv2.resize(raw_heat, (320, 288), interpolation=cv2.INTER_AREA),
                cv2.resize(robust_heat, (320, 288), interpolation=cv2.INTER_AREA),
                cv2.resize(mask_vis, (320, 288), interpolation=cv2.INTER_AREA),
            ])
            cv2.putText(row, f"frame {index + 1}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            review_rows.append(row)
        if (index + 1) % 20 == 0 or index + 1 == len(depth_files):
            print(f"  normal {index + 1}/{len(depth_files)}", flush=True)

    source_manifest = json.loads((args.source_session / "processed_manifest.json").read_text(encoding="utf-8"))
    frames = source_manifest.get("frames", [])
    for index, frame in enumerate(frames):
        stem = f"{index + 1:06d}"
        frame["normalMap"] = f"normal_map/normal_{stem}.png"
        frame["normalConfidence"] = f"normal_confidence/normal_confidence_{stem}.png"
    source_manifest["sessionId"] = args.session_id
    source_manifest["robustNormalSidecar"] = {
        "version": 1,
        "space": "object",
        "encoding": "rgb8_signed_unit_vector",
        "temporalMedianRadiusFrames": args.temporal_radius,
        "fineBilateralSigmaMm": args.fine_sigma_mm,
        "coarseBilateralSigmaMm": args.coarse_sigma_mm,
        "maskedNormalConfidence": args.masked_normal_confidence,
        "planeSize": [args.plane_width, args.plane_depth],
        "displacement": args.displacement,
        "shaderArg1": args.shader_arg_1,
    }
    (args.output_session / "processed_manifest.json").write_text(
        json.dumps(source_manifest, indent=2), encoding="utf-8"
    )

    source_session = json.loads((args.source_session / "session.json").read_text(encoding="utf-8"))
    source_session["id"] = args.session_id
    source_session["title"] = args.title
    relative = f"res://assets/processed_sessions/{args.session_id}"
    data_sources = source_session.setdefault("data_sources", {})
    data_sources["depth_map"] = f"{relative}/clean_depth/clean_depth_000001.png"
    data_sources["detail_depth_map"] = data_sources["depth_map"]
    data_sources["texture_map"] = f"{relative}/clean_rgb/clean_rgb_000001.png"
    data_sources["surface_mask"] = f"{relative}/surface_mask.png"
    data_sources["processed_manifest"] = f"{relative}/processed_manifest.json"
    data_sources["normal_map"] = f"{relative}/normal_map/normal_000001.png"
    data_sources["normal_confidence"] = f"{relative}/normal_confidence/normal_confidence_000001.png"
    data_sources["use_reconstructed_normal_map"] = True
    data_sources["preserve_masked_depth_detail"] = True
    source_session.setdefault("production_session", {})["robustNormalSidecar"] = source_manifest["robustNormalSidecar"]
    (args.output_session / "session.json").write_text(
        json.dumps(source_session, indent=2), encoding="utf-8"
    )

    raw_angles = np.concatenate(raw_temporal_angles) if raw_temporal_angles else np.array([], np.float32)
    robust_angles = np.concatenate(robust_temporal_angles) if robust_temporal_angles else np.array([], np.float32)
    changed_angles = np.concatenate(core_angle_changes) if core_angle_changes else np.array([], np.float32)
    stats = {
        "processedFrames": len(depth_files),
        "coreNormalChangeMedianDegrees": float(np.median(changed_angles)) if changed_angles.size else 0.0,
        "coreNormalChangeP95Degrees": float(np.percentile(changed_angles, 95)) if changed_angles.size else 0.0,
        "maskedRawTemporalJumpMedianDegrees": float(np.median(raw_angles)) if raw_angles.size else 0.0,
        "maskedRobustTemporalJumpMedianDegrees": float(np.median(robust_angles)) if robust_angles.size else 0.0,
        "maskedRawTemporalJumpP95Degrees": float(np.percentile(raw_angles, 95)) if raw_angles.size else 0.0,
        "maskedRobustTemporalJumpP95Degrees": float(np.percentile(robust_angles, 95)) if robust_angles.size else 0.0,
    }
    (args.output_session / "robust_normal_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    if review_rows:
        cv2.imwrite(str(args.output_session / "robust_normal_review.png"), np.vstack(review_rows))
    receipt = {
        "sessionJsonSha256": sha256(args.output_session / "session.json"),
        "processedManifestSha256": sha256(args.output_session / "processed_manifest.json"),
        "stats": stats,
    }
    (args.output_session / "normal_build_receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2), flush=True)
    print(f"done: {args.output_session}", flush=True)


if __name__ == "__main__":
    main()
