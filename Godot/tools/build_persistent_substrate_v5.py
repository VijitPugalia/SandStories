#!/usr/bin/env python3
"""Build a coherent hand-free RGB-D session from latent substrate states.

The older bidirectional filter selected a different past/future donor for
every pixel.  A moving hand therefore left donor-time contours in the height
field even when every selected pixel was technically hand-free.  This builder
instead estimates coherent pre/post substrate atlases from unoccluded samples
and a single robust progress value per frame.  Masked geometry can only lie on
that low-rank substrate trajectory; a harmonic bias field and wide transition
make it meet the measured, unmasked Azure surface without an actor outline.

DiffuEraser output is accepted as an RGB-only proposal inside the same mask.
Geometry remains metrically anchored to the Azure-derived source session.
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


def read_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(path)
    return image


def read_bgr(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def decode_rg16_metric(path: Path, metric_low: float, metric_high: float) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        raise FileNotFoundError(path)
    packed = (
        (image[..., 2].astype(np.uint16) << 8)
        | image[..., 1].astype(np.uint16)
    )
    normalized_height = packed.astype(np.float32) / 65535.0
    return metric_high - normalized_height * (metric_high - metric_low)


def encode_rg16_metric(
    metric: np.ndarray,
    surface: np.ndarray,
    metric_low: float,
    metric_high: float,
) -> np.ndarray:
    normalized = np.clip(
        (metric_high - metric) / (metric_high - metric_low), 0.0, 1.0
    )
    packed = np.rint(normalized * 65535.0).astype(np.uint32)
    packed[~surface] = 65535
    bgr = np.zeros((*packed.shape, 3), np.uint8)
    bgr[..., 2] = (packed >> 8) & 0xFF
    bgr[..., 1] = packed & 0xFF
    return bgr


def object_normals(
    normalized_height: np.ndarray,
    world_height_per_unit: float,
    plane_width: float,
    plane_depth: float,
) -> np.ndarray:
    derivative_x = cv2.Scharr(normalized_height, cv2.CV_32F, 1, 0) / 32.0
    derivative_z = cv2.Scharr(normalized_height, cv2.CV_32F, 0, 1) / 32.0
    pixel_world_x = plane_width / max(normalized_height.shape[1] - 1, 1)
    pixel_world_z = plane_depth / max(normalized_height.shape[0] - 1, 1)
    slope_x = derivative_x * world_height_per_unit / pixel_world_x
    slope_z = derivative_z * world_height_per_unit / pixel_world_z
    normal = np.dstack((-slope_x, np.ones_like(normalized_height), -slope_z))
    normal /= np.maximum(np.linalg.norm(normal, axis=2, keepdims=True), 1e-8)
    return normal.astype(np.float32)


def encode_normal(normal: np.ndarray, surface: np.ndarray) -> np.ndarray:
    encoded = np.uint8(np.clip((normal * 0.5 + 0.5) * 255.0 + 0.5, 0, 255))
    bgr = encoded[..., [2, 1, 0]].copy()
    bgr[~surface] = np.array([128, 255, 128], np.uint8)
    return bgr


def smoothstep(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def robust_state_progress(
    frames: np.ndarray,
    masks: np.ndarray,
    before: np.ndarray,
    after: np.ndarray,
    surface: np.ndarray,
    exclusion_radius: int,
    change_threshold_m: float,
    temporal_sigma: float,
) -> np.ndarray:
    delta = after - before
    change = (np.abs(delta) >= change_threshold_m) & surface
    kernel_size = exclusion_radius * 2 + 1
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    progress: list[float] = []
    for index in range(frames.shape[0]):
        excluded = cv2.dilate(np.uint8(masks[index]) * 255, kernel) > 0
        trusted = change & ~excluded & np.isfinite(frames[index])
        ratio = (frames[index][trusted] - before[trusted]) / delta[trusted]
        ratio = ratio[np.isfinite(ratio) & (np.abs(ratio) < 3.0)]
        progress.append(float(np.median(ratio)) if ratio.size else 0.0)
    values = np.clip(np.asarray(progress, np.float32), 0.0, 1.0)
    values = cv2.GaussianBlur(values.reshape(1, -1), (0, 0), temporal_sigma).ravel()
    # This clip records a carving action. Enforcing a non-decreasing latent
    # state prevents a briefly re-occluded trench from snapping backwards.
    values = np.maximum.accumulate(values)
    if values[-1] > values[0] + 1e-5:
        values = (values - values[0]) / (values[-1] - values[0])
    return np.clip(values, 0.0, 1.0)


def spatial_activation_times(
    frames: np.ndarray,
    masks: np.ndarray,
    before: np.ndarray,
    after: np.ndarray,
    surface: np.ndarray,
    change_threshold_m: float,
    exclusion_radius: int,
    vote_window: int,
    vote_minimum: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate when each persistent changed pixel was first drawn.

    Evidence is accepted only from unoccluded observations and must persist in
    multiple future samples.  Missing event times are spatially propagated
    from those trusted observations, so the activation front follows the
    stroke rather than the moving hand boundary.
    """
    delta = after - before
    changed = (np.abs(delta) >= change_threshold_m) & surface
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (exclusion_radius * 2 + 1, exclusion_radius * 2 + 1)
    )
    trusted_hits: list[np.ndarray] = []
    for index in range(frames.shape[0]):
        excluded = cv2.dilate(np.uint8(masks[index]) * 255, kernel) > 0
        trusted = changed & ~excluded
        ratio = np.zeros_like(before, np.float32)
        ratio[changed] = (frames[index][changed] - before[changed]) / delta[changed]
        trusted_hits.append(trusted & np.isfinite(ratio) & (ratio >= 0.42))

    tau = np.full(before.shape, np.nan, np.float32)
    for index in range(frames.shape[0]):
        stop = min(frames.shape[0], index + vote_window)
        votes = np.sum(np.stack(trusted_hits[index:stop]), axis=0)
        newly_active = changed & ~np.isfinite(tau) & (votes >= vote_minimum)
        tau[newly_active] = float(index)

    known = changed & np.isfinite(tau)
    if known.any():
        seed = np.zeros_like(tau, np.float32)
        seed[known] = tau[known]
        unknown = np.uint8(~known) * 255
        filled = cv2.inpaint(seed, unknown, 21.0, cv2.INPAINT_NS)
        tau[~known] = filled[~known]
    else:
        tau[changed] = frames.shape[0] * 0.5
    smooth = cv2.bilateralFilter(tau, 15, 10.0, 13.0)
    tau[changed] = smooth[changed]
    tau[~changed] = float(frames.shape[0] + 1)
    return tau, changed


def build_atlas(
    samples: np.ndarray,
    masks: np.ndarray,
    fallback: np.ndarray,
    start: int,
    stop: int,
) -> np.ndarray:
    window = np.where(masks[start:stop], np.nan, samples[start:stop])
    with np.errstate(all="ignore"):
        atlas = np.nanmedian(window, axis=0)
    atlas = np.where(np.isfinite(atlas), atlas, fallback).astype(np.float32)
    return cv2.bilateralFilter(atlas, 9, 0.0025, 4.0)


def transition_alpha(mask: np.ndarray, radius: float, surface: np.ndarray) -> np.ndarray:
    distance = cv2.distanceTransform(np.uint8(~mask), cv2.DIST_L2, 5)
    alpha = smoothstep(1.0 - distance / max(radius, 1.0))
    alpha[mask] = 1.0
    alpha[~surface] = 0.0
    return alpha.astype(np.float32)


def harmonic_boundary_match(
    current: np.ndarray,
    state: np.ndarray,
    mask: np.ndarray,
    expansion_radius: int,
    inpaint_radius: float,
    blur_sigma: float,
) -> np.ndarray:
    kernel_size = expansion_radius * 2 + 1
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    expanded = cv2.dilate(np.uint8(mask) * 255, kernel)
    difference = (current - state).astype(np.float32)
    bias = cv2.inpaint(difference, expanded, inpaint_radius, cv2.INPAINT_NS)
    bias = cv2.GaussianBlur(bias, (0, 0), blur_sigma)
    return state + bias


def guarded_geometry_mask(
    hand_mask: np.ndarray,
    current: np.ndarray,
    state: np.ndarray,
    surface: np.ndarray,
    guard_radius: int,
    residual_support_radius: int,
    residual_threshold_m: float,
) -> np.ndarray:
    """Grow a hand mask through depth corruption before any feathering.

    The RGB hand mask commonly stops on the first visible hand edge while the
    depth camera leaves several further rings of biased samples.  Feathering
    against those samples turns the edge into terraced depressions.  The guard
    therefore includes a fixed registration margin plus every strong
    state-residual connected to the hand inside a wider search support.
    """
    if guard_radius <= 0:
        return hand_mask.copy()
    guard_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (guard_radius * 2 + 1, guard_radius * 2 + 1)
    )
    support_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (residual_support_radius * 2 + 1, residual_support_radius * 2 + 1),
    )
    fixed_guard = cv2.dilate(np.uint8(hand_mask) * 255, guard_kernel) > 0
    support = cv2.dilate(np.uint8(hand_mask) * 255, support_kernel) > 0
    residual = (np.abs(current - state) >= residual_threshold_m) & support & surface
    residual = cv2.morphologyEx(
        np.uint8(residual) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
    )
    residual = cv2.dilate(
        residual, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    ) > 0
    output = (fixed_guard | residual) & surface
    return output


def gradient_magnitude(depth: np.ndarray) -> np.ndarray:
    gx = cv2.Scharr(depth, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(depth, cv2.CV_32F, 0, 1)
    return cv2.magnitude(gx, gy)


def boundary_ratio(depth: np.ndarray, mask: np.ndarray, surface: np.ndarray) -> float:
    boundary = cv2.morphologyEx(
        np.uint8(mask) * 255,
        cv2.MORPH_GRADIENT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
    ) > 0
    band = cv2.dilate(
        np.uint8(boundary) * 255,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)),
    ) > 0
    far = ~(
        cv2.dilate(
            np.uint8(mask) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)),
        ) > 0
    ) & surface
    if not band.any() or not far.any():
        return 0.0
    gradient = gradient_magnitude(depth)
    return float(gradient[band].mean() / max(float(gradient[far].mean()), 1e-8))


def hillshade(depth: np.ndarray) -> np.ndarray:
    gx = cv2.Scharr(depth, cv2.CV_32F, 1, 0) / 32.0 / 0.0086
    gz = cv2.Scharr(depth, cv2.CV_32F, 0, 1) / 32.0 / 0.0095
    normal = np.dstack((-gx, np.ones_like(depth), -gz))
    normal /= np.maximum(np.linalg.norm(normal, axis=2, keepdims=True), 1e-8)
    light = np.asarray([-0.45, 0.72, -0.52], np.float32)
    light /= np.linalg.norm(light)
    shade = np.clip(0.35 + 0.85 * (normal @ light), 0.0, 1.0)
    return cv2.cvtColor(np.uint8(shade * 255.0), cv2.COLOR_GRAY2BGR)


def label(image: np.ndarray, text: str) -> np.ndarray:
    output = image.copy()
    cv2.rectangle(output, (0, 0), (output.shape[1], 28), (15, 15, 15), -1)
    cv2.putText(
        output,
        text,
        (8, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return output


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
    parser.add_argument("--diffueraser-video", type=Path)
    parser.add_argument("--reuse-rgb-session", type=Path)
    parser.add_argument("--minimum-free-gb", type=float, default=25.0)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--atlas-frames", type=int, default=35)
    parser.add_argument("--change-threshold-mm", type=float, default=2.0)
    parser.add_argument("--progress-exclusion-radius", type=int, default=12)
    parser.add_argument("--progress-temporal-sigma", type=float, default=3.0)
    parser.add_argument("--boundary-expansion-radius", type=int, default=20)
    parser.add_argument("--boundary-inpaint-radius", type=float, default=18.0)
    parser.add_argument("--boundary-bias-sigma", type=float, default=7.0)
    parser.add_argument("--transition-radius", type=float, default=28.0)
    parser.add_argument("--geometry-guard-radius", type=int, default=0)
    parser.add_argument("--geometry-residual-support-radius", type=int, default=72)
    parser.add_argument("--geometry-residual-threshold-mm", type=float, default=3.0)
    parser.add_argument("--geometry-temporal-union", action="store_true")
    parser.add_argument("--geometry-temporal-union-margin", type=int, default=0)
    parser.add_argument("--spatial-activation", action="store_true")
    parser.add_argument("--activation-exclusion-radius", type=int, default=20)
    parser.add_argument("--activation-vote-window", type=int, default=5)
    parser.add_argument("--activation-vote-minimum", type=int, default=2)
    parser.add_argument("--activation-ramp-frames", type=float, default=4.0)
    parser.add_argument("--normal-temporal-radius", type=int, default=4)
    parser.add_argument("--normal-mask-confidence", type=float, default=0.92)
    parser.add_argument("--plane-width", type=float, default=5.5)
    parser.add_argument("--plane-depth", type=float, default=5.5)
    parser.add_argument("--shader-arg-1", type=float, default=11.625)
    parser.add_argument("--displacement", type=float, default=-5.0)
    parser.add_argument("--revision-version", type=int, default=5)
    parser.add_argument("--review-frames", default="1,81,101,103,121,141,161,181,201")
    args = parser.parse_args()

    if args.output_session.exists():
        raise FileExistsError(args.output_session)
    if args.diffueraser_video is None and args.reuse_rgb_session is None:
        parser.error("one of --diffueraser-video or --reuse-rgb-session is required")
    output_parent = args.output_session.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(output_parent).free / (1024 ** 3)
    if free_gb < args.minimum_free_gb:
        raise RuntimeError(
            f"Free space gate: {free_gb:.2f} GiB < {args.minimum_free_gb:.2f} GiB"
        )
    print(f"free-space preflight {free_gb:.2f} GiB", flush=True)

    manifest = json.loads(
        (args.source_session / "processed_manifest.json").read_text(encoding="utf-8")
    )
    session = json.loads(
        (args.source_session / "session.json").read_text(encoding="utf-8")
    )
    frames_meta = manifest["frames"]
    frame_count = len(frames_meta)
    metric_low, metric_high = [float(v) for v in manifest["metricDepthRange"]]
    surface = read_gray(args.source_session / manifest["surfaceMask"]) > 0

    print(f"loading {frame_count} metric depth frames", flush=True)
    depth_stack = np.stack([
        decode_rg16_metric(
            args.source_session / frame["cleanDepth"], metric_low, metric_high
        )
        for frame in frames_meta
    ])
    mask_stack = np.stack([
        read_gray(args.source_session / frame["persistenceMask"]) > 0
        for frame in frames_meta
    ])

    fallback = np.median(depth_stack, axis=0).astype(np.float32)
    atlas_frames = min(args.atlas_frames, max(frame_count // 2, 1))
    before = build_atlas(depth_stack, mask_stack, fallback, 0, atlas_frames)
    after = build_atlas(
        depth_stack, mask_stack, fallback, frame_count - atlas_frames, frame_count
    )
    progress = robust_state_progress(
        depth_stack,
        mask_stack,
        before,
        after,
        surface,
        args.progress_exclusion_radius,
        args.change_threshold_mm / 1000.0,
        args.progress_temporal_sigma,
    )

    atlas_delta = after - before
    activation_time: np.ndarray | None = None
    activation_changed: np.ndarray | None = None
    if args.spatial_activation:
        print("estimating persistent per-pixel drawing times", flush=True)
        activation_time, activation_changed = spatial_activation_times(
            depth_stack,
            mask_stack,
            before,
            after,
            surface,
            args.change_threshold_mm / 1000.0,
            args.activation_exclusion_radius,
            args.activation_vote_window,
            args.activation_vote_minimum,
        )
        spatial_progress: list[float] = []
        for index in range(frame_count):
            values = smoothstep(
                (index - activation_time) / max(args.activation_ramp_frames, 1.0) + 0.5
            )
            spatial_progress.append(
                float(np.mean(values[activation_changed]))
                if activation_changed.any()
                else 0.0
            )
        progress = np.asarray(spatial_progress, np.float32)

    def state_for_frame(index: int) -> np.ndarray:
        if activation_time is None or activation_changed is None:
            return before + progress[index] * atlas_delta
        activation = smoothstep(
            (index - activation_time) / max(args.activation_ramp_frames, 1.0) + 0.5
        )
        state = before.copy()
        state[activation_changed] = (
            before[activation_changed]
            + activation[activation_changed] * atlas_delta[activation_changed]
        )
        return state

    temporal_geometry_mask: np.ndarray | None = None
    if args.geometry_temporal_union:
        union = np.zeros_like(surface, dtype=bool)
        print("building fixed temporal-union geometry guard", flush=True)
        for index in range(frame_count):
            raw_state = state_for_frame(index)
            union |= guarded_geometry_mask(
                mask_stack[index],
                depth_stack[index],
                raw_state,
                surface,
                args.geometry_guard_radius,
                args.geometry_residual_support_radius,
                args.geometry_residual_threshold_mm / 1000.0,
            )
        union = cv2.morphologyEx(
            np.uint8(union) * 255,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)),
        )
        if args.geometry_temporal_union_margin > 0:
            radius = args.geometry_temporal_union_margin
            union = cv2.dilate(
                union,
                cv2.getStructuringElement(
                    cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)
                ),
            )
        temporal_geometry_mask = (union > 0) & surface
        print(
            f"  temporal geometry guard {int(temporal_geometry_mask.sum())} px",
            flush=True,
        )

    diffueraser_frames: list[np.ndarray] = []
    reuse_rgb_manifest: dict | None = None
    if args.reuse_rgb_session is not None:
        reuse_rgb_manifest = json.loads(
            (args.reuse_rgb_session / "processed_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        if len(reuse_rgb_manifest["frames"]) != frame_count:
            raise ValueError("Reused RGB session frame count differs")
        print(f"reusing RGB assets from {args.reuse_rgb_session}", flush=True)
    else:
        capture = cv2.VideoCapture(str(args.diffueraser_video))
        if not capture.isOpened():
            raise FileNotFoundError(args.diffueraser_video)
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame.shape[:2] != surface.shape:
                frame = cv2.resize(
                    frame,
                    (surface.shape[1], surface.shape[0]),
                    interpolation=cv2.INTER_AREA,
                )
            diffueraser_frames.append(frame)
        capture.release()
        if len(diffueraser_frames) != frame_count:
            raise ValueError(
                f"DiffuEraser frames {len(diffueraser_frames)} != session {frame_count}"
            )

    replaced_roots = {"clean_rgb", "clean_depth", "normal_map", "normal_confidence"}
    replaced_files = {
        "session.json",
        "processed_manifest.json",
        "build_receipt.json",
        "normal_build_receipt.json",
        "robust_normal_stats.json",
        "robust_normal_review.png",
    }
    for source in args.source_session.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(args.source_session)
        if relative.parts[0] in replaced_roots or relative.name in replaced_files:
            continue
        link_or_copy(source, args.output_session / relative)
    for name in replaced_roots:
        (args.output_session / name).mkdir(parents=True, exist_ok=True)

    outputs: list[np.ndarray] = []
    alphas: list[np.ndarray] = []
    before_ratios: list[float] = []
    after_ratios: list[float] = []
    changed_core_mm: list[np.ndarray] = []
    review_indices = {
        int(value) for value in args.review_frames.split(",") if value.strip()
    }
    review_rows: list[np.ndarray] = []
    guard_growth_pixels: list[int] = []

    print("rendering coherent latent substrate trajectory", flush=True)
    for index, frame_meta in enumerate(frames_meta):
        current = depth_stack[index]
        mask = mask_stack[index]
        state = state_for_frame(index)
        geometry_mask = (
            temporal_geometry_mask
            if temporal_geometry_mask is not None
            else guarded_geometry_mask(
                mask,
                current,
                state,
                surface,
                args.geometry_guard_radius,
                args.geometry_residual_support_radius,
                args.geometry_residual_threshold_mm / 1000.0,
            )
        )
        guard_growth_pixels.append(int(geometry_mask.sum() - mask.sum()))
        state = harmonic_boundary_match(
            current,
            state,
            geometry_mask,
            args.boundary_expansion_radius,
            args.boundary_inpaint_radius,
            args.boundary_bias_sigma,
        )
        alpha = transition_alpha(geometry_mask, args.transition_radius, surface)
        output = current * (1.0 - alpha) + state * alpha
        smoothed = cv2.bilateralFilter(output, 9, 0.0020, 3.5)
        smoothing_weight = np.minimum(alpha, 0.45)
        output = output * (1.0 - smoothing_weight) + smoothed * smoothing_weight
        output[~surface] = metric_low

        stem = f"{index + 1:06d}"
        rgb_destination = args.output_session / "clean_rgb" / f"clean_rgb_{stem}.png"
        if reuse_rgb_manifest is not None:
            reuse_frame = reuse_rgb_manifest["frames"][index]
            rgb_source = args.reuse_rgb_session / reuse_frame["cleanRgb"]
            link_or_copy(rgb_source, rgb_destination)
            clean_rgb = read_bgr(rgb_source)
        else:
            original_rgb = read_bgr(args.source_session / frame_meta["cleanRgb"])
            rgb_alpha = cv2.GaussianBlur(
                np.uint8(mask) * 255, (0, 0), 7.0
            ).astype(np.float32) / 255.0
            rgb_alpha = np.maximum(rgb_alpha, alpha * 0.88)
            rgb_alpha[~surface] = 0.0
            clean_rgb = np.uint8(np.clip(
                original_rgb.astype(np.float32) * (1.0 - rgb_alpha[..., None])
                + diffueraser_frames[index].astype(np.float32) * rgb_alpha[..., None],
                0,
                255,
            ))
            cv2.imwrite(str(rgb_destination), clean_rgb)
        cv2.imwrite(
            str(args.output_session / "clean_depth" / f"clean_depth_{stem}.png"),
            encode_rg16_metric(output, surface, metric_low, metric_high),
        )
        outputs.append(output.astype(np.float32))
        alphas.append(alpha)
        before_ratios.append(boundary_ratio(current, geometry_mask, surface))
        after_ratios.append(boundary_ratio(output, geometry_mask, surface))
        if geometry_mask.any():
            changed_core_mm.append(
                np.abs(output[geometry_mask] - current[geometry_mask]) * 1000.0
            )

        frame_meta["cleanRgb"] = f"clean_rgb/clean_rgb_{stem}.png"
        frame_meta["cleanDepth"] = f"clean_depth/clean_depth_{stem}.png"
        frame_meta["normalMap"] = f"normal_map/normal_{stem}.png"
        frame_meta["normalConfidence"] = (
            f"normal_confidence/normal_confidence_{stem}.png"
        )
        frame_meta["substrateProgress"] = round(float(progress[index]), 6)

        if index + 1 in review_indices:
            overlay = clean_rgb.copy()
            overlay[geometry_mask] = np.uint8(
                overlay[geometry_mask].astype(np.float32) * 0.25
                + np.asarray([0, 0, 255], np.float32) * 0.75
            )
            change = cv2.applyColorMap(
                np.uint8(np.clip(np.abs(output - current) / 0.020 * 255.0, 0, 255)),
                cv2.COLORMAP_TURBO,
            )
            change[~surface] = 0
            cells = [
                label(clean_rgb, f"v{args.revision_version} DiffuEraser RGB {index + 1}"),
                label(
                    overlay,
                    f"geometry guard {int(geometry_mask.sum())} px (+{guard_growth_pixels[-1]})",
                ),
                label(hillshade(current), "v3 donor hillshade"),
                label(
                    hillshade(output),
                    f"v{args.revision_version} substrate progress {progress[index]:.2f}",
                ),
                label(change, "absolute geometry change 0..20 mm"),
            ]
            review_rows.append(np.hstack([
                cv2.resize(cell, (320, 288), interpolation=cv2.INTER_AREA)
                for cell in cells
            ]))
        if (index + 1) % 20 == 0 or index + 1 == frame_count:
            print(f"  substrate {index + 1}/{frame_count}", flush=True)

    output_stack = np.stack(outputs)
    alpha_stack = np.stack(alphas)
    del outputs, alphas
    world_height_per_unit = abs(args.displacement) / args.shader_arg_1
    print("building normals from the same coherent substrate", flush=True)
    previous_normal = None
    temporal_normal_jumps: list[np.ndarray] = []
    for index in range(frame_count):
        start = max(0, index - args.normal_temporal_radius)
        stop = min(frame_count, index + args.normal_temporal_radius + 1)
        temporal = np.median(output_stack[start:stop], axis=0).astype(np.float32)
        normal_metric = (
            output_stack[index] * (1.0 - 0.58 * alpha_stack[index])
            + temporal * (0.58 * alpha_stack[index])
        )
        normal_metric = cv2.bilateralFilter(normal_metric, 9, 0.0025, 3.5)
        normalized_height = np.clip(
            (metric_high - normal_metric) / (metric_high - metric_low), 0.0, 1.0
        )
        normal = object_normals(
            normalized_height,
            world_height_per_unit,
            args.plane_width,
            args.plane_depth,
        )
        confidence = 1.0 - alpha_stack[index] * (1.0 - args.normal_mask_confidence)
        confidence[~surface] = 0.0
        stem = f"{index + 1:06d}"
        cv2.imwrite(
            str(args.output_session / "normal_map" / f"normal_{stem}.png"),
            encode_normal(normal, surface),
        )
        cv2.imwrite(
            str(
                args.output_session
                / "normal_confidence"
                / f"normal_confidence_{stem}.png"
            ),
            np.uint8(np.clip(confidence * 255.0 + 0.5, 0, 255)),
        )
        if previous_normal is not None:
            shared = (alpha_stack[index] >= 0.25) & (alpha_stack[index - 1] >= 0.25) & surface
            if shared.any():
                dot = np.sum(previous_normal * normal, axis=2)
                temporal_normal_jumps.append(
                    np.degrees(np.arccos(np.clip(dot[shared], -1.0, 1.0)))
                )
        previous_normal = normal

    manifest["sessionId"] = args.session_id
    revision_key = f"latentSubstrateV{args.revision_version}"
    artifact_prefix = f"latent_substrate_v{args.revision_version}"
    manifest[revision_key] = {
        "version": args.revision_version,
        "model": "two-state robust masked substrate atlas",
        "progress": "global robust unoccluded depth fit, temporally smoothed and monotone",
        "boundary": (
            "residual-grown clean outer guard, harmonic bias field, then transition"
            if args.geometry_guard_radius > 0
            else "harmonic bias field plus wide smooth transition"
        ),
        "rgb": "DiffuEraser accepted only inside the hand-removal support",
        "metricAnchor": "Azure-derived source depth outside the support",
        "atlasFrames": atlas_frames,
        "transitionRadiusPixels": args.transition_radius,
        "geometryGuardRadiusPixels": args.geometry_guard_radius,
        "geometryResidualSupportRadiusPixels": args.geometry_residual_support_radius,
        "geometryResidualThresholdMm": args.geometry_residual_threshold_mm,
        "geometryTemporalUnion": args.geometry_temporal_union,
        "geometryTemporalUnionMarginPixels": args.geometry_temporal_union_margin,
        "spatialActivation": args.spatial_activation,
        "activationRampFrames": args.activation_ramp_frames,
    }
    (args.output_session / "processed_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    relative = f"res://assets/processed_sessions/{args.session_id}"
    session["id"] = args.session_id
    session["title"] = args.title
    data_sources = session.setdefault("data_sources", {})
    data_sources["depth_map"] = f"{relative}/clean_depth/clean_depth_000001.png"
    data_sources["detail_depth_map"] = data_sources["depth_map"]
    data_sources["texture_map"] = f"{relative}/clean_rgb/clean_rgb_000001.png"
    data_sources["surface_mask"] = f"{relative}/surface_mask.png"
    data_sources["processed_manifest"] = f"{relative}/processed_manifest.json"
    data_sources["normal_map"] = f"{relative}/normal_map/normal_000001.png"
    data_sources["normal_confidence"] = (
        f"{relative}/normal_confidence/normal_confidence_000001.png"
    )
    data_sources["use_reconstructed_normal_map"] = True
    data_sources["preserve_masked_depth_detail"] = True
    session.setdefault("production_session", {})[revision_key] = manifest[revision_key]
    (args.output_session / "session.json").write_text(
        json.dumps(session, indent=2), encoding="utf-8"
    )

    changed = np.concatenate(changed_core_mm) if changed_core_mm else np.array([], np.float32)
    normal_jumps = (
        np.concatenate(temporal_normal_jumps)
        if temporal_normal_jumps
        else np.array([], np.float32)
    )
    valid_before = np.asarray([v for v in before_ratios if v > 0], np.float32)
    valid_after = np.asarray([v for v in after_ratios if v > 0], np.float32)
    stats = {
        "processedFrames": frame_count,
        "substrateProgressStart": float(progress[0]),
        "substrateProgressEnd": float(progress[-1]),
        "maskBoundaryGradientRatioMedianBefore": float(np.median(valid_before)),
        "maskBoundaryGradientRatioMedianAfter": float(np.median(valid_after)),
        "maskBoundaryGradientRatioP95Before": float(np.percentile(valid_before, 95)),
        "maskBoundaryGradientRatioP95After": float(np.percentile(valid_after, 95)),
        "coreGeometryChangeMedianMm": float(np.median(changed)) if changed.size else 0.0,
        "coreGeometryChangeP95Mm": float(np.percentile(changed, 95)) if changed.size else 0.0,
        "maskedNormalTemporalJumpMedianDegrees": (
            float(np.median(normal_jumps)) if normal_jumps.size else 0.0
        ),
        "maskedNormalTemporalJumpP95Degrees": (
            float(np.percentile(normal_jumps, 95)) if normal_jumps.size else 0.0
        ),
        "geometryGuardGrowthMedianPixels": float(np.median(guard_growth_pixels)),
        "geometryGuardGrowthMaxPixels": int(max(guard_growth_pixels)),
    }
    (args.output_session / f"{artifact_prefix}_stats.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8"
    )
    if review_rows:
        cv2.imwrite(
            str(args.output_session / f"{artifact_prefix}_review.png"),
            np.vstack(review_rows),
        )
    receipt = {
        "sessionJsonSha256": sha256(args.output_session / "session.json"),
        "processedManifestSha256": sha256(
            args.output_session / "processed_manifest.json"
        ),
        "stats": stats,
    }
    (args.output_session / f"{artifact_prefix}_receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, indent=2), flush=True)
    print(f"done: {args.output_session}", flush=True)


if __name__ == "__main__":
    main()
