#!/usr/bin/env python3
"""Offline bidirectional hand removal for a static Azure Kinect sand scene.

The hand/arm mask is the union of the depth-transience classifier and the
ProPainter/SAM mask.  A short temporal propagation closes one-frame mask
holes.  Occluded pixels are reconstructed from their nearest trusted past and
future observations, so genuine terrain edits can emerge while the hand is
still covering them.  ProPainter is treated as a low-weight RGB proposal and
is accepted only where it agrees with the bidirectional reconstruction and is
at least as sharp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def read_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(path)
    return image


def read_depth(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 2:
        raise FileNotFoundError(path)
    return image


def read_rgb(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def find_frame(directory: Path, index: int) -> Path:
    matches = list(directory.glob(f"*{index:06d}.*"))
    if not matches:
        raise FileNotFoundError(f"frame {index} in {directory}")
    return matches[0]


def clean_components(mask: np.ndarray, min_area: int, dilation: int) -> np.ndarray:
    source = np.uint8(mask) * 255
    source = cv2.morphologyEx(
        source,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    source = cv2.morphologyEx(
        source,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(source, 8)
    output = np.zeros_like(source)
    for component in range(1, count):
        if stats[component, cv2.CC_STAT_AREA] >= min_area:
            output[labels == component] = 255
    if dilation > 1:
        output = cv2.dilate(
            output,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation, dilation)),
        )
    return output > 0


def temporal_support(
    raw: np.ndarray,
    position: int,
    horizon: int,
    tolerance_mm: int,
    row_block: int = 64,
) -> np.ndarray:
    stop = min(raw.shape[0], position + horizon)
    window = raw[position:stop]
    current = raw[position]
    result = np.zeros(current.shape, np.float32)
    for y0 in range(0, current.shape[0], row_block):
        y1 = min(current.shape[0], y0 + row_block)
        block = window[:, y0:y1]
        centre = current[y0:y1].astype(np.int32)
        valid = block > 0
        similar = (
            valid
            & (block >= np.maximum(centre - tolerance_mm, 0)[None])
            & (block <= (centre + tolerance_mm)[None])
        )
        result[y0:y1] = similar.sum(axis=0) / np.maximum(valid.sum(axis=0), 1)
    return result


def signed_distance_alpha(
    confidence: np.ndarray,
    surface: np.ndarray,
    inner_radius: float,
    outer_radius: float,
) -> np.ndarray:
    """Edge-smooth a soft temporal mask with a signed-distance transition."""
    core = confidence >= 0.999
    if not core.any():
        return np.zeros(core.shape, np.float32)
    inside = cv2.distanceTransform(np.uint8(core), cv2.DIST_L2, 5)
    outside = cv2.distanceTransform(np.uint8(~core), cv2.DIST_L2, 5)
    signed = inside - outside
    x = np.clip((signed + outer_radius) / (inner_radius + outer_radius), 0.0, 1.0)
    smooth = x * x * (3.0 - 2.0 * x)
    # Propagated-only pixels remain soft rather than becoming a hard union.
    smooth = np.maximum(smooth, confidence * 0.85)
    smooth[~surface] = 0.0
    return smooth.astype(np.float32)


def encode_rg16_depth(
    metric: np.ndarray, surface: np.ndarray, metric_low: float, metric_high: float
) -> np.ndarray:
    normalized = np.clip((metric_high - metric) / (metric_high - metric_low), 0.0, 1.0)
    packed = np.rint(normalized * 65535.0).astype(np.uint32)
    packed[~surface] = 65535
    bgr = np.zeros((*packed.shape, 3), dtype=np.uint8)
    bgr[..., 2] = (packed >> 8) & 0xFF
    bgr[..., 1] = packed & 0xFF
    return bgr


def smoothstep(weight: np.ndarray) -> np.ndarray:
    weight = np.clip(weight, 0.0, 1.0)
    return weight * weight * (3.0 - 2.0 * weight)


def gradient_magnitude(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(np.uint8(np.clip(image, 0, 255)), cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.GaussianBlur(cv2.magnitude(gx, gy), (0, 0), 1.2)


def heat(values: np.ndarray, low: float, high: float, mask: np.ndarray) -> np.ndarray:
    scaled = np.clip((values - low) / max(high - low, 1e-6), 0.0, 1.0)
    image = cv2.applyColorMap(np.uint8(scaled * 255), cv2.COLORMAP_TURBO)
    image[~mask] = 0
    return image


def label(image: np.ndarray, text: str) -> np.ndarray:
    output = image.copy()
    cv2.rectangle(output, (0, 0), (output.shape[1], 28), (18, 18, 18), -1)
    cv2.putText(output, text, (7, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    return output


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--post-end", type=int, default=1000)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--sample-stride", type=int, default=10)
    parser.add_argument("--margin-mm", type=float, default=15.0)
    parser.add_argument("--large-margin-mm", type=float, default=30.0)
    parser.add_argument("--short-horizon", type=int, default=45)
    parser.add_argument("--long-horizon", type=int, default=120)
    parser.add_argument("--support-threshold", type=float, default=0.55)
    parser.add_argument("--tolerance-mm", type=int, default=3)
    parser.add_argument("--min-component-area", type=int, default=120)
    parser.add_argument("--dilation", type=int, default=11)
    parser.add_argument("--temporal-radius", type=int, default=3)
    parser.add_argument("--inner-feather", type=float, default=4.0)
    parser.add_argument("--outer-feather", type=float, default=12.0)
    parser.add_argument("--propainter-max-weight", type=float, default=0.25)
    parser.add_argument("--metric-low", type=float, default=0.4)
    parser.add_argument("--metric-high", type=float, default=0.63)
    parser.add_argument("--review-frames", default="520,560,580,600,620,633,650,680,700,720")
    args = parser.parse_args()

    if args.output_session.exists():
        raise FileExistsError(f"refusing to overwrite {args.output_session}")
    depth_files = sorted((args.session / "depth").glob("depth_*.png"))
    frame_count = len(depth_files)
    post_end = min(args.post_end, frame_count)
    if not (1 <= args.start <= args.end < post_end <= frame_count):
        raise ValueError(f"invalid range {args.start}..{args.end}..{post_end}/{frame_count}")
    surface = read_gray(args.session / "surface_mask.png") > 0
    prediction_dir = args.session / "predictions_handfree" / "grid4"
    raw_rgb_dir = args.session / "rgb"
    propainter_rgb_dir = args.session / "display_rgb_full"
    propainter_mask_dir = args.session / "propainter_masks"

    print("estimating q75 sand reference", flush=True)
    sampled = []
    for path in depth_files[:: args.sample_stride]:
        frame = read_depth(path).astype(np.float32)
        frame[(frame <= 0) | ~surface] = np.nan
        sampled.append(frame)
    reference = np.nanpercentile(np.stack(sampled), 75, axis=0).astype(np.float32)
    reference_valid = np.isfinite(reference) & surface
    del sampled

    load_stop = min(frame_count, args.end + args.long_horizon - 1)
    print(f"loading raw depth 1..{load_stop}", flush=True)
    raw = np.stack([read_depth(args.session / "depth" / f"depth_{i:06d}.png") for i in range(1, load_stop + 1)])

    masks: list[np.ndarray] = []
    print("building depth-transience + ProPainter union masks", flush=True)
    for source_index in range(1, args.end + 1):
        position = source_index - 1
        current_u16 = raw[position]
        current = current_u16.astype(np.float32)
        valid = (current_u16 > 0) & reference_valid
        delta = reference - current
        short_support = temporal_support(raw, position, args.short_horizon, args.tolerance_mm)
        long_support = temporal_support(raw, position, args.long_horizon, args.tolerance_mm)
        support = np.where(delta >= args.large_margin_mm, long_support, short_support)
        actor = clean_components(
            valid & (delta >= args.margin_mm) & (support < args.support_threshold),
            args.min_component_area,
            args.dilation,
        ) & surface
        pp_path = propainter_mask_dir / f"{source_index:06d}.png"
        pp = read_gray(pp_path) > 0 if pp_path.exists() else np.zeros(surface.shape, bool)
        masks.append((actor | pp) & surface)
        if source_index == 1 or source_index % 40 == 0 or source_index == args.end:
            print(f"  mask {source_index}: actor={int(actor.sum())} pp={int(pp.sum())} union={int(masks[-1].sum())}", flush=True)

    # Post-roll masks are used only to reject future donors.  Existing depth
    # actor masks are conservative here, which is preferable to selecting a
    # hand pixel as a future sand observation.
    for source_index in range(args.end + 1, post_end + 1):
        actor_path = args.session / "depth_actor_masks" / f"{source_index:06d}.png"
        pp_path = propainter_mask_dir / f"{source_index:06d}.png"
        actor = read_gray(actor_path) > 0 if actor_path.exists() else np.zeros(surface.shape, bool)
        pp = read_gray(pp_path) > 0 if pp_path.exists() else np.zeros(surface.shape, bool)
        masks.append((actor | pp) & surface)

    print(f"propagating masks across +/-{args.temporal_radius} frames", flush=True)
    temporal_confidence: list[np.ndarray] = []
    for i in range(len(masks)):
        confidence = masks[i].astype(np.float32)
        for distance in range(1, args.temporal_radius + 1):
            propagated_weight = 1.0 - distance / (args.temporal_radius + 1.0)
            if i - distance >= 0:
                confidence = np.maximum(confidence, masks[i - distance] * propagated_weight)
            if i + distance < len(masks):
                confidence = np.maximum(confidence, masks[i + distance] * propagated_weight)
        temporal_confidence.append(np.uint8(np.rint(confidence * 255.0)))
    del masks

    # Store only the next donor maps needed for output frames.  The backward
    # pass can see well beyond the clip end and therefore recover newly carved
    # terrain as soon as it becomes visible.
    print(f"backward donor pass {post_end}..{args.start}", flush=True)
    next_depth = np.zeros(surface.shape, np.float32)
    next_rgb = np.zeros((*surface.shape, 3), np.uint8)
    next_index = np.zeros(surface.shape, np.uint16)
    next_records: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for source_index in range(post_end, args.start - 1, -1):
        prediction = np.load(prediction_dir / f"frame_{source_index:06d}.npy").astype(np.float32)
        rgb = read_rgb(find_frame(raw_rgb_dir, source_index))
        trusted = surface & (temporal_confidence[source_index - 1] == 0) & np.isfinite(prediction)
        next_depth[trusted] = prediction[trusted]
        next_rgb[trusted] = rgb[trusted]
        next_index[trusted] = source_index
        if source_index <= args.end:
            next_records[source_index] = (next_depth.copy(), next_rgb.copy(), next_index.copy())
        if source_index % 40 == 0 or source_index == args.start:
            print(f"  backward {source_index}", flush=True)

    output = args.output_session
    for subdir in ("clean_rgb", "clean_depth", "valid_mask", "persistence_mask", "feather_mask", "propainter_confidence"):
        (output / subdir).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output / "surface_mask.png"), np.uint8(surface) * 255)

    print(f"forward donor + render pass 1..{args.end}", flush=True)
    previous_depth = np.zeros(surface.shape, np.float32)
    previous_rgb = np.zeros((*surface.shape, 3), np.uint8)
    previous_index = np.zeros(surface.shape, np.uint16)
    frames_json: list[dict] = []
    review_frames = {int(v) for v in args.review_frames.split(",") if v.strip()}
    review_rows: list[np.ndarray] = []
    output_core_counts: list[int] = []
    donor_gap_values: list[np.ndarray] = []
    propainter_weights: list[np.ndarray] = []
    first_prediction = np.load(prediction_dir / f"frame_{args.start:06d}.npy").astype(np.float32)

    for source_index in range(1, args.end + 1):
        prediction = np.load(prediction_dir / f"frame_{source_index:06d}.npy").astype(np.float32)
        raw_rgb = read_rgb(find_frame(raw_rgb_dir, source_index))
        confidence = temporal_confidence[source_index - 1].astype(np.float32) / 255.0
        trusted = surface & (temporal_confidence[source_index - 1] == 0) & np.isfinite(prediction)
        previous_depth[trusted] = prediction[trusted]
        previous_rgb[trusted] = raw_rgb[trusted]
        previous_index[trusted] = source_index
        if source_index < args.start:
            continue

        next_d, next_c, next_i = next_records.pop(source_index)
        has_previous = previous_index > 0
        has_next = next_i > 0
        d_previous = np.maximum(source_index - previous_index.astype(np.int32), 0).astype(np.float32)
        d_next = np.maximum(next_i.astype(np.int32) - source_index, 0).astype(np.float32)
        denominator = np.maximum(d_previous + d_next, 1.0)
        future_weight = smoothstep(d_previous / denominator)
        future_weight[has_next & ~has_previous] = 1.0
        future_weight[has_previous & ~has_next] = 0.0
        future_weight[~has_previous & ~has_next] = 0.0

        temporal_depth = previous_depth * (1.0 - future_weight) + next_d * future_weight
        temporal_rgb = previous_rgb.astype(np.float32) * (1.0 - future_weight[..., None]) + next_c.astype(np.float32) * future_weight[..., None]
        no_donor = ~has_previous & ~has_next
        temporal_depth[no_donor] = prediction[no_donor]
        temporal_rgb[no_donor] = raw_rgb[no_donor]

        pp_rgb = read_rgb(find_frame(propainter_rgb_dir, source_index)).astype(np.float32)
        color_error = np.mean(np.abs(pp_rgb - temporal_rgb), axis=2)
        temporal_sharpness = gradient_magnitude(temporal_rgb)
        pp_sharpness = gradient_magnitude(pp_rgb)
        color_confidence = np.exp(-color_error / 24.0)
        sharpness_confidence = np.clip((pp_sharpness + 2.0) / (temporal_sharpness + 2.0), 0.0, 1.0)
        pp_weight = args.propainter_max_weight * color_confidence * sharpness_confidence
        pp_weight *= confidence
        reconstructed_rgb = temporal_rgb * (1.0 - pp_weight[..., None]) + pp_rgb * pp_weight[..., None]

        alpha = signed_distance_alpha(confidence, surface, args.inner_feather, args.outer_feather)
        filtered_depth = prediction * (1.0 - alpha) + temporal_depth * alpha
        filtered_rgb = raw_rgb.astype(np.float32) * (1.0 - alpha[..., None]) + reconstructed_rgb * alpha[..., None]
        filtered_rgb = np.uint8(np.clip(filtered_rgb, 0, 255))

        offset = source_index - args.start + 1
        stem = f"{offset:06d}"
        core = confidence >= 0.999
        output_core_counts.append(int(core.sum()))
        gaps = (d_previous + d_next)[core & has_previous & has_next]
        if gaps.size:
            donor_gap_values.append(gaps)
        if core.any():
            propainter_weights.append(pp_weight[core])

        cv2.imwrite(str(output / "clean_rgb" / f"clean_rgb_{stem}.png"), filtered_rgb)
        cv2.imwrite(str(output / "clean_depth" / f"clean_depth_{stem}.png"), encode_rg16_depth(filtered_depth, surface, args.metric_low, args.metric_high))
        raw_valid = (raw[source_index - 1] > 0) & surface
        cv2.imwrite(str(output / "valid_mask" / f"valid_mask_{stem}.png"), np.uint8(raw_valid) * 255)
        cv2.imwrite(str(output / "persistence_mask" / f"persistence_mask_{stem}.png"), np.uint8(core) * 255)
        cv2.imwrite(str(output / "feather_mask" / f"feather_mask_{stem}.png"), np.uint8(np.clip(alpha * 255.0, 0, 255)))
        cv2.imwrite(str(output / "propainter_confidence" / f"propainter_confidence_{stem}.png"), np.uint8(np.clip(pp_weight / max(args.propainter_max_weight, 1e-6) * 255.0, 0, 255)))

        frames_json.append({
            "frameIndex": source_index - 1,
            "sourceFrameIndex": source_index,
            "time": round((offset - 1) / args.fps, 6),
            "sourceTime": round((source_index - 1) / args.fps, 6),
            "cleanRgb": f"clean_rgb/clean_rgb_{stem}.png",
            "cleanDepth": f"clean_depth/clean_depth_{stem}.png",
            "occlusionMask": f"valid_mask/valid_mask_{stem}.png",
            "persistenceMask": f"persistence_mask/persistence_mask_{stem}.png",
            "occlusionPixels": int(core.sum()),
            "baselineHeightCorrection": 0.0,
        })

        if source_index in review_frames or source_index in (args.start, args.end):
            overlay = filtered_rgb.copy()
            overlay[core] = (0.25 * overlay[core] + 0.75 * np.array([0, 0, 255])).astype(np.uint8)
            source_delta = (prediction - first_prediction) * 1000.0
            filtered_delta = (filtered_depth - first_prediction) * 1000.0
            reconstruction = (filtered_depth - prediction) * 1000.0
            pp_conf_heat = cv2.applyColorMap(np.uint8(np.clip(pp_weight / max(args.propainter_max_weight, 1e-6) * 255, 0, 255)), cv2.COLORMAP_VIRIDIS)
            pp_conf_heat[~surface] = 0
            cells = [
                label(filtered_rgb, f"v3 RGB {source_index}"),
                label(overlay, f"temporal core {int(core.sum())} px"),
                label(heat(source_delta, -40, 40, surface), "Any2Full delta -40..40 mm"),
                label(heat(filtered_delta, -40, 40, surface), "bidirectional delta -40..40 mm"),
                label(heat(reconstruction, -25, 25, alpha > 0.01), "reconstruction -25..25 mm"),
                label(pp_conf_heat, f"accepted ProPainter <= {args.propainter_max_weight:.2f}"),
            ]
            review_rows.append(np.hstack([cv2.resize(cell, (320, 288), interpolation=cv2.INTER_AREA) for cell in cells]))

        if source_index % 20 == 0 or source_index == args.end:
            print(f"  render {source_index}", flush=True)

    gap_values = np.concatenate(donor_gap_values) if donor_gap_values else np.array([], np.float32)
    pp_values = np.concatenate(propainter_weights) if propainter_weights else np.array([], np.float32)
    stats = {
        "sourceFrameRange": [args.start, args.end],
        "postRollEnd": post_end,
        "processedFrames": len(frames_json),
        "maskPixelsMedian": float(np.median(output_core_counts)),
        "maskPixelsMax": int(max(output_core_counts, default=0)),
        "bidirectionalDonorSamples": int(gap_values.size),
        "donorGapMedianFrames": float(np.median(gap_values)) if gap_values.size else 0.0,
        "donorGapP95Frames": float(np.percentile(gap_values, 95)) if gap_values.size else 0.0,
        "acceptedProPainterWeightMean": float(pp_values.mean()) if pp_values.size else 0.0,
        "acceptedProPainterWeightP95": float(np.percentile(pp_values, 95)) if pp_values.size else 0.0,
    }
    filter_meta = {
        "version": 3,
        "mask": "depth transience union ProPainter/SAM, temporally propagated",
        "temporalPropagationRadiusFrames": args.temporal_radius,
        "fillPolicy": "nearest trusted past/future donor with per-pixel smoothstep",
        "innerFeatherPixels": args.inner_feather,
        "outerFeatherPixels": args.outer_feather,
        "propainterPolicy": "confidence-gated RGB proposal only",
        "propainterMaximumWeight": args.propainter_max_weight,
        "postRollEndFrame": post_end,
    }
    manifest = {
        "sessionId": args.session_id,
        "captureFormat": "azure_kinect_mkv_nfov_unbinned",
        "frameSize": {"width": int(surface.shape[1]), "height": int(surface.shape[0])},
        "sourceFrameCount": frame_count,
        "processedFrameCount": len(frames_json),
        "stride": 1,
        "depthEncoding": {"source": "Azure Kinect DEPTH16 mm", "invalidValue": 0},
        "surfaceMask": "surface_mask.png",
        "metricDepthRange": [args.metric_low, args.metric_high],
        "sourceFrameRange": [args.start, args.end],
        "bidirectionalFilter": filter_meta,
        "frames": frames_json,
    }
    (output / "processed_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    relative = f"res://assets/processed_sessions/{args.session_id}"
    session_json = {
        "id": args.session_id,
        "title": args.title,
        "duration": len(frames_json) / args.fps,
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{relative}/clean_depth/clean_depth_000001.png",
            "detail_depth_map": f"{relative}/clean_depth/clean_depth_000001.png",
            "texture_map": f"{relative}/clean_rgb/clean_rgb_000001.png",
            "surface_mask": f"{relative}/surface_mask.png",
            "occlusion_mask": f"{relative}/valid_mask/valid_mask_000001.png",
            "processed_manifest": f"{relative}/processed_manifest.json",
            "audio": "",
            "calibration": {
                "depth_uv_offset": [0.0, 0.0], "texture_uv_offset": [0.0, 0.0],
                "depth_uv_scale": [1.0, 1.0], "texture_uv_scale": [1.0, 1.0],
                "height_scale": -5.0, "material_strength": 0.65,
            },
            "depth_value_encoding": "rg16_unorm",
        },
        "production_session": {
            "schemaVersion": 1,
            "deviceModel": "Azure Kinect DK",
            "processedFrameCount": len(frames_json),
            "experiment": "azure_kinect_bidirectional_handfree_depth",
            "sourceFrameRange": [args.start, args.end],
            "bidirectionalFilter": filter_meta,
        },
        "gesture_events": [], "study_tasks": [],
    }
    (output / "session.json").write_text(json.dumps(session_json, indent=2), encoding="utf-8")
    (output / "bidirectional_filter_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    if review_rows:
        cv2.imwrite(str(output / "bidirectional_review.png"), np.vstack(review_rows))
    receipt = {
        "sessionJsonSha256": sha256(output / "session.json"),
        "processedManifestSha256": sha256(output / "processed_manifest.json"),
        "stats": stats,
    }
    (output / "build_receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2), flush=True)
    print(f"done: {output}", flush=True)


if __name__ == "__main__":
    main()
