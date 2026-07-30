#!/usr/bin/env python3
"""Posterior temporal repair for hand/tool occlusions in fixed-camera sessions.

This pass uses after-the-fact evidence from future frames to fill pixels that were
covered by hands/tools. It intentionally does not rerun detection; it consumes the
object/depth masks from an already object-removed session and writes a new session.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_rgb(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _read_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(path)
    return image


def _write_rgb(path: Path, image: np.ndarray) -> None:
    bgr = cv2.cvtColor(np.clip(image, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr, [cv2.IMWRITE_PNG_COMPRESSION, 0])


def _write_gray(path: Path, image: np.ndarray) -> None:
    cv2.imwrite(str(path), np.clip(image, 0, 255).astype(np.uint8), [cv2.IMWRITE_PNG_COMPRESSION, 0])


def _session_path(path: Path) -> Path:
    return path / "session.json" if path.is_dir() else path


def _manifest_path(session_path: Path, session: dict[str, Any]) -> Path:
    manifest = str(session.get("data_sources", {}).get("processed_manifest", ""))
    if not manifest:
        raise ValueError(f"Session has no data_sources.processed_manifest: {session_path}")
    if manifest.startswith("res://assets/processed_sessions/"):
        return session_path.parent / Path(manifest).name
    if manifest.startswith("res://"):
        raise ValueError(f"Cannot resolve manifest outside session directory: {manifest}")
    return session_path.parent / manifest


def _resolve_frame_path(session_dir: Path, frame: dict[str, Any], key: str) -> Path:
    value = str(frame.get(key, ""))
    if not value:
        raise KeyError(f"Frame missing {key}")
    return session_dir / value


def _dilate(mask: np.ndarray, pixels: int) -> np.ndarray:
    if pixels <= 0 or not np.any(mask):
        return mask.astype(bool)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pixels * 2 + 1, pixels * 2 + 1))
    return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool)


def _local_density_mask(mask: np.ndarray, radius: int, threshold: float) -> np.ndarray:
    if radius <= 0 or threshold <= 0.0:
        return mask
    kernel = radius * 2 + 1
    density = cv2.blur(mask.astype(np.float32), (kernel, kernel))
    return mask & (density >= threshold)


def _filter_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    if min_area <= 1 or not np.any(mask):
        return mask
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


def _feather_blend(base: np.ndarray, filled: np.ndarray, mask: np.ndarray, feather: int, inner_alpha: float = 0.92) -> np.ndarray:
    if feather <= 0 or not np.any(mask):
        result = base.copy()
        result[mask] = filled[mask]
        return result
    kernel = feather * 2 + 1
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (kernel, kernel), 0)
    alpha = np.clip(alpha, 0.0, 1.0)
    alpha = np.minimum(alpha, inner_alpha)
    alpha[mask] = np.maximum(alpha[mask], inner_alpha)
    if base.ndim == 3:
        alpha = alpha[:, :, None]
    return np.clip(base.astype(np.float32) * (1.0 - alpha) + filled.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


def _skin_like_mask(rgb: np.ndarray) -> np.ndarray:
    ycrcb = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2YCrCb)
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    return (cr >= 133) & (cr <= 180) & (cb >= 75) & (cb <= 135)


def _group_fill_from_sources(
    base: np.ndarray,
    selected_indices: np.ndarray,
    target_mask: np.ndarray,
    source_frames: list[dict[str, Any]],
    source_dir: Path,
    key: str,
    cache: dict[tuple[str, int], np.ndarray],
) -> np.ndarray:
    filled = base.copy()
    valid = target_mask & (selected_indices >= 0)
    if not np.any(valid):
        return filled
    for source_index in np.unique(selected_indices[valid]):
        source_index_int = int(source_index)
        source_mask = valid & (selected_indices == source_index_int)
        cache_key = (key, source_index_int)
        if cache_key not in cache:
            path = _resolve_frame_path(source_dir, source_frames[source_index_int], key)
            cache[cache_key] = _read_rgb(path) if base.ndim == 3 else _read_gray(path)
        source = cache[cache_key]
        filled[source_mask] = source[source_mask]
    return filled


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copy2(src, dst)


def _load_frame_stacks(session_dir: Path, frames: list[dict[str, Any]], label: str) -> dict[str, np.ndarray]:
    stacks: dict[str, np.ndarray] = {}
    for key in ["cleanRgb", "cleanDepth", "detailDepth", "shadedDepth"]:
        images = []
        for index, frame in enumerate(frames):
            path = _resolve_frame_path(session_dir, frame, key)
            images.append(_read_rgb(path) if key == "cleanRgb" else _read_gray(path))
            if (index + 1) % 100 == 0 or index == len(frames) - 1:
                print(f"loaded {label} {key} {index + 1}/{len(frames)}", flush=True)
        stacks[key] = np.stack(images, axis=0)
    return stacks


def _hand_sidecar_path(masked_session_path: Path, masked_session: dict[str, Any]) -> Path | None:
    value = str(masked_session.get("data_sources", {}).get("hand_tracks", ""))
    if not value:
        return None
    if value.startswith("res://"):
        value = Path(value).name
    return masked_session_path.parent / value


def _build_hand_contact_stack(
    sidecar_path: Path | None,
    frames: list[dict[str, Any]],
    height: int,
    width: int,
    *,
    radius: int,
    future_window: int,
    intents: set[str],
    contact_index: int,
    directional_half: bool,
) -> np.ndarray:
    stack = np.zeros((len(frames), height, width), dtype=np.uint8)
    if sidecar_path is None or not sidecar_path.exists() or radius <= 0:
        return stack.astype(bool)
    payload = _load_json(sidecar_path)
    frame_to_local = {int(frame.get("frameIndex", index)): index for index, frame in enumerate(frames)}
    contact_indices = payload.get("contactIndices") or [contact_index]
    if contact_index not in contact_indices:
        contact_indices = [contact_index]
    contact_points: list[list[tuple[int, int]]] = [[] for _ in frames]
    for track in payload.get("hand_tracks", []):
        for sample in track.get("samples", []):
            intent = str(sample.get("intent", ""))
            if intents and intent not in intents:
                continue
            frame_index = int(sample.get("frameIndex", -1))
            local_index = frame_to_local.get(frame_index)
            if local_index is None:
                continue
            pixels = sample.get("pixelLandmarks") or []
            for landmark_index in contact_indices:
                if landmark_index >= len(pixels):
                    continue
                point = pixels[landmark_index]
                if not isinstance(point, list) or len(point) < 2:
                    continue
                x = int(round(float(point[0])))
                y = int(round(float(point[1])))
                if 0 <= x < width and 0 <= y < height:
                    contact_points[local_index].append((x, y))
    for local_index, points in enumerate(contact_points):
        for x, y in points:
            cv2.circle(stack[local_index], (x, y), radius, 1, thickness=-1)
        if not directional_half or not points:
            continue
        end_index = min(len(contact_points), local_index + max(0, future_window) + 1)
        future_points = [point for frame_points in contact_points[local_index + 1:end_index] for point in frame_points]
        if not future_points:
            continue
        origin = np.array(points[0], dtype=np.float32)
        future = np.median(np.array(future_points, dtype=np.float32), axis=0)
        direction = future - origin
        norm = float(np.linalg.norm(direction))
        if norm < 3.0:
            continue
        direction /= norm
        reach = int(max(radius * 2, min(radius * 4, norm + radius * 2)))
        x0 = max(0, int(origin[0]) - reach)
        x1 = min(width, int(origin[0]) + reach + 1)
        y0 = max(0, int(origin[1]) - reach)
        y1 = min(height, int(origin[1]) + reach + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dx = xx.astype(np.float32) - origin[0]
        dy = yy.astype(np.float32) - origin[1]
        along = dx * direction[0] + dy * direction[1]
        cross = np.abs(dx * direction[1] - dy * direction[0])
        capsule = (along >= -float(radius) * 0.4) & (along <= float(reach)) & (cross <= float(radius) * 1.2)
        stack[local_index, y0:y1, x0:x1][capsule] = 1
    return stack.astype(bool)


def _build_change_and_stability(
    stacks: dict[str, np.ndarray],
    visible_stack: np.ndarray,
    *,
    rgb_change_threshold: float,
    depth_change_threshold: int,
    change_dilate: int,
) -> tuple[np.ndarray, np.ndarray]:
    frame_count = visible_stack.shape[0]
    change_stack = np.zeros_like(visible_stack, dtype=bool)
    rgb_stack = stacks["cleanRgb"].astype(np.int16)
    detail_stack = stacks["detailDepth"].astype(np.int16)

    for index in range(1, frame_count):
        both_visible = visible_stack[index] & visible_stack[index - 1]
        if not np.any(both_visible):
            continue
        rgb_delta = np.mean(np.abs(rgb_stack[index] - rgb_stack[index - 1]), axis=2)
        depth_delta = np.abs(detail_stack[index] - detail_stack[index - 1])
        changed = both_visible & ((rgb_delta >= rgb_change_threshold) | (depth_delta >= depth_change_threshold))
        change_stack[index] = _dilate(changed, change_dilate) if change_dilate > 0 else changed

    stable_stack = np.zeros_like(visible_stack, dtype=np.uint8)
    stable_stack[-1][visible_stack[-1]] = 1
    for index in range(frame_count - 2, -1, -1):
        visible = visible_stack[index]
        stable_stack[index][visible] = 1
        same_next = visible & visible_stack[index + 1] & ~change_stack[index + 1]
        stable_stack[index][same_next] = np.clip(stable_stack[index + 1][same_next].astype(np.uint16) + 1, 0, 255).astype(np.uint8)
        if (index + 1) % 100 == 0:
            print(f"built stability from frame {index + 1}/{frame_count}", flush=True)
    return change_stack, stable_stack


def repair_session(
    source_session_path: Path,
    masked_session_path: Path,
    output_dir: Path,
    *,
    start_frame: int,
    max_frames: int | None,
    future_window: int,
    past_window: int,
    mask_dilate: int,
    donor_mask_dilate: int,
    feather: int,
    prefer_future: bool,
    debug_maps: bool,
    accept_score: float,
    min_support: int,
    rgb_change_threshold: float,
    depth_change_threshold: int,
    change_dilate: int,
    spatial_radius: int,
    spatial_density: float,
    min_component_area: int,
    require_future_change: bool,
    allow_past_fill: bool,
    use_source_donor: bool,
    rgb_repair_alpha: float,
    hand_guided_rgb: bool,
    hand_rgb_radius: int,
    hand_rgb_future_window: int,
    hand_rgb_intents: set[str],
    hand_rgb_directional_half: bool,
    current_rgb_update_threshold: float,
    rgb_donor_clean_threshold: float,
    source_rgb_when_no_repair: bool,
) -> Path:
    source_session = _load_json(source_session_path)
    masked_session = _load_json(masked_session_path)
    source_manifest = _load_json(_manifest_path(source_session_path, source_session))
    masked_manifest = _load_json(_manifest_path(masked_session_path, masked_session))
    source_frames: list[dict[str, Any]] = list(source_manifest.get("frames", []))
    masked_frames: list[dict[str, Any]] = list(masked_manifest.get("frames", []))
    if start_frame > 0:
        source_frames = source_frames[start_frame:]
        masked_frames = masked_frames[start_frame:]
    if max_frames is not None:
        source_frames = source_frames[:max_frames]
        masked_frames = masked_frames[:max_frames]
    frame_count = min(len(source_frames), len(masked_frames))
    if frame_count <= 0:
        raise ValueError("No frames to repair")
    source_frames = source_frames[:frame_count]
    masked_frames = masked_frames[:frame_count]

    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("*.png"):
        old.unlink()
    for old in output_dir.glob("*.json"):
        old.unlink()

    surface_mask = _read_gray(masked_session_path.parent / "surface_mask.png") > 0
    height, width = surface_mask.shape
    _write_gray(output_dir / "surface_mask.png", surface_mask.astype(np.uint8) * 255)

    repair_stack = np.zeros((frame_count, height, width), dtype=bool)
    repair_target_stack = np.zeros((frame_count, height, width), dtype=bool)
    visible_stack = np.zeros((frame_count, height, width), dtype=bool)

    total_repair_pixels = 0
    for index, frame in enumerate(masked_frames):
        object_path = masked_session_path.parent / str(frame.get("objectMask", ""))
        depth_object_path = masked_session_path.parent / str(frame.get("depthObjectMask", ""))
        object_mask = _read_gray(object_path) > 0 if object_path.exists() else np.zeros((height, width), dtype=bool)
        depth_object_mask = _read_gray(depth_object_path) > 0 if depth_object_path.exists() else np.zeros((height, width), dtype=bool)
        repair_target = (object_mask | depth_object_mask) & surface_mask
        repair_mask = _dilate(repair_target, mask_dilate) & surface_mask
        donor_block_mask = _dilate(repair_mask, donor_mask_dilate) & surface_mask
        valid_path = _resolve_frame_path(masked_session_path.parent, frame, "occlusionMask")
        valid = (_read_gray(valid_path) > 0) & surface_mask
        visible = valid & ~donor_block_mask
        repair_stack[index] = repair_mask
        repair_target_stack[index] = repair_target
        visible_stack[index] = visible
        total_repair_pixels += int(repair_mask.sum())
        if (index + 1) % 50 == 0 or index == frame_count - 1:
            print(f"prepared masks {index + 1}/{frame_count}", flush=True)

    masked_stacks = _load_frame_stacks(masked_session_path.parent, masked_frames, "masked")
    source_stacks = _load_frame_stacks(source_session_path.parent, source_frames, "source") if use_source_donor else masked_stacks
    change_stack, stable_stack = _build_change_and_stability(
        masked_stacks,
        visible_stack,
        rgb_change_threshold=rgb_change_threshold,
        depth_change_threshold=depth_change_threshold,
        change_dilate=change_dilate,
    )
    hand_contact_stack = _build_hand_contact_stack(
        _hand_sidecar_path(masked_session_path, masked_session),
        masked_frames,
        height,
        width,
        radius=hand_rgb_radius,
        future_window=hand_rgb_future_window,
        intents=hand_rgb_intents,
        contact_index=8,
        directional_half=hand_rgb_directional_half,
    ) if hand_guided_rgb else np.zeros_like(visible_stack, dtype=bool)

    output_frames: list[dict[str, Any]] = []
    posterior_pixels_total = 0
    future_pixels_total = 0
    past_pixels_total = 0

    for index, frame in enumerate(masked_frames):
        frame_started = time.monotonic()
        stem = f"{index + 1:06d}"
        repair_mask = repair_stack[index]
        repair_target = repair_target_stack[index]
        selected = np.full((height, width), -1, dtype=np.int16)

        base_images: dict[str, np.ndarray] = {
            "cleanRgb": masked_stacks["cleanRgb"][index],
            "cleanDepth": masked_stacks["cleanDepth"][index],
            "detailDepth": masked_stacks["detailDepth"][index],
            "shadedDepth": masked_stacks["shadedDepth"][index],
        }
        if use_source_donor and source_rgb_when_no_repair and not np.any(repair_mask):
            base_images["cleanRgb"] = source_stacks["cleanRgb"][index].copy()
        if use_source_donor and current_rgb_update_threshold > 0.0:
            source_rgb_now = source_stacks["cleanRgb"][index]
            rgb_delta_now = np.mean(
                np.abs(source_rgb_now.astype(np.int16) - base_images["cleanRgb"].astype(np.int16)),
                axis=2,
            )
            safe_current_rgb = (
                visible_stack[index]
                & (rgb_delta_now <= current_rgb_update_threshold)
                & ~_dilate(_skin_like_mask(source_rgb_now), max(4, donor_mask_dilate // 2))
            )
            if np.any(safe_current_rgb):
                base = base_images["cleanRgb"].copy()
                base[safe_current_rgb] = source_rgb_now[safe_current_rgb]
                base_images["cleanRgb"] = base
        filled_images = {key: value.copy() for key, value in base_images.items()}
        remaining = repair_target.copy()
        baseline_index = np.full((height, width), -1, dtype=np.int16)
        baseline_rgb = np.zeros((height, width, 3), dtype=np.uint8)
        baseline_detail = np.zeros((height, width), dtype=np.uint8)
        baseline_remaining = repair_target.copy()
        for offset in range(1, past_window + 1):
            source_index = index - offset
            if source_index < 0 or not np.any(baseline_remaining):
                break
            baseline_mask = baseline_remaining & visible_stack[source_index]
            if not np.any(baseline_mask):
                continue
            baseline_rgb[baseline_mask] = source_stacks["cleanRgb"][source_index][baseline_mask]
            baseline_detail[baseline_mask] = source_stacks["detailDepth"][source_index][baseline_mask]
            baseline_index[baseline_mask] = source_index
            baseline_remaining[baseline_mask] = False
        future_pixels = 0
        past_pixels = 0

        repair_pixel_count = max(1, int(repair_target.sum()))

        def apply_temporal_cache(offsets: range, is_future: bool, require_stable: bool) -> None:
            nonlocal future_pixels, past_pixels, remaining
            for offset in offsets:
                if not np.any(remaining):
                    break
                if 1.0 - (float(remaining.sum()) / float(repair_pixel_count)) >= accept_score:
                    break
                source_index = index + offset
                if source_index < 0 or source_index >= frame_count:
                    continue
                clear_answer = remaining & visible_stack[source_index]
                if require_stable:
                    clear_answer &= stable_stack[source_index] >= min_support
                if require_stable and require_future_change:
                    has_baseline = baseline_index >= 0
                    rgb_delta = np.mean(
                        np.abs(source_stacks["cleanRgb"][source_index].astype(np.int16) - baseline_rgb.astype(np.int16)),
                        axis=2,
                    )
                    depth_delta = np.abs(source_stacks["detailDepth"][source_index].astype(np.int16) - baseline_detail.astype(np.int16))
                    changed_since_baseline = has_baseline & (
                        (rgb_delta >= rgb_change_threshold) | (depth_delta >= depth_change_threshold)
                    )
                    clear_answer &= changed_since_baseline
                clear_answer = _local_density_mask(clear_answer, spatial_radius, spatial_density)
                if not np.any(clear_answer):
                    continue
                for key in ["cleanRgb", "cleanDepth", "detailDepth", "shadedDepth"]:
                    source = source_stacks[key][source_index]
                    filled_images[key][clear_answer] = source[clear_answer]
                selected[clear_answer] = source_index
                count = int(clear_answer.sum())
                if is_future:
                    future_pixels += count
                else:
                    past_pixels += count
                remaining[clear_answer] = False

        if prefer_future:
            apply_temporal_cache(range(1, future_window + 1), True, True)
            if allow_past_fill and np.any(remaining):
                apply_temporal_cache(range(-1, -past_window - 1, -1), False, False)
        else:
            if allow_past_fill:
                apply_temporal_cache(range(-1, -past_window - 1, -1), False, False)
            if np.any(remaining):
                apply_temporal_cache(range(1, future_window + 1), True, True)

        target_mask = repair_target & (selected >= 0)
        target_mask = _filter_small_components(target_mask, min_component_area)
        selected[~target_mask] = -1
        if hand_guided_rgb:
            rgb_guide = np.zeros((height, width), dtype=bool)
            end_index = min(frame_count, index + max(0, hand_rgb_future_window) + 1)
            if end_index > index:
                rgb_guide = np.any(hand_contact_stack[index:end_index], axis=0)
            rgb_target_mask = target_mask & rgb_guide
        else:
            rgb_target_mask = target_mask
        if use_source_donor and rgb_donor_clean_threshold > 0.0 and np.any(rgb_target_mask):
            clean_donor_rgb = np.zeros((height, width), dtype=bool)
            for source_index in np.unique(selected[rgb_target_mask]):
                source_index_int = int(source_index)
                if source_index_int < 0:
                    continue
                source_mask = rgb_target_mask & (selected == source_index_int)
                if not np.any(source_mask):
                    continue
                source_rgb = source_stacks["cleanRgb"][source_index_int]
                masked_rgb = masked_stacks["cleanRgb"][source_index_int]
                donor_delta = np.mean(
                    np.abs(source_rgb.astype(np.int16) - masked_rgb.astype(np.int16)),
                    axis=2,
                )
                clean_donor_rgb[source_mask & (donor_delta <= rgb_donor_clean_threshold) & ~_dilate(_skin_like_mask(source_rgb), max(4, donor_mask_dilate // 2))] = True
            rgb_target_mask &= clean_donor_rgb
        posterior_pixels = int(target_mask.sum())
        posterior_pixels_total += posterior_pixels
        future_pixels_total += future_pixels
        past_pixels_total += past_pixels

        repaired_rgb = _feather_blend(base_images["cleanRgb"], filled_images["cleanRgb"], rgb_target_mask, feather, rgb_repair_alpha)

        outputs: dict[str, str] = {}
        for key, out_name in [
            ("cleanDepth", f"clean_depth_{stem}.png"),
            ("detailDepth", f"detail_depth_{stem}.png"),
            ("shadedDepth", f"shaded_depth_{stem}.png"),
        ]:
            repaired_gray = _feather_blend(base_images[key], filled_images[key], target_mask, max(1, feather // 2), 0.92)
            _write_gray(output_dir / out_name, repaired_gray)
            outputs[key] = out_name

        clean_rgb_name = f"clean_rgb_{stem}.png"
        valid_name = f"valid_mask_{stem}.png"
        _write_rgb(output_dir / clean_rgb_name, repaired_rgb)
        _copy_if_exists(_resolve_frame_path(masked_session_path.parent, frame, "occlusionMask"), output_dir / valid_name)

        next_frame = dict(frame)
        next_frame.update({
            "cleanRgb": clean_rgb_name,
            "cleanDepth": outputs["cleanDepth"],
            "detailDepth": outputs["detailDepth"],
            "shadedDepth": outputs["shadedDepth"],
            "occlusionMask": valid_name,
            "maskOverlay": outputs["shadedDepth"],
            "posteriorRepairPixels": posterior_pixels,
            "posteriorRgbRepairPixels": int(rgb_target_mask.sum()),
            "posteriorFuturePixels": future_pixels,
            "posteriorPastPixels": past_pixels,
        })
        if debug_maps:
            repair_mask_name = f"posterior_repair_mask_{stem}.png"
            selected_name = f"posterior_source_index_{stem}.png"
            _write_gray(output_dir / repair_mask_name, repair_mask.astype(np.uint8) * 255)
            selected_vis = np.where(selected >= 0, np.clip(selected.astype(np.int32) * 255 // max(1, frame_count - 1), 0, 255), 0).astype(np.uint8)
            _write_gray(output_dir / selected_name, selected_vis)
            next_frame["posteriorRepairMask"] = repair_mask_name
            next_frame["posteriorSourceIndex"] = selected_name
        output_frames.append(next_frame)
        if frame_count <= 25 or (index + 1) % 25 == 0 or index == frame_count - 1:
            print(
                f"repaired {index + 1}/{frame_count} posterior={posterior_pixels} future={future_pixels} past={past_pixels} seconds={time.monotonic() - frame_started:.2f}",
                flush=True,
            )

    next_manifest = dict(masked_manifest)
    next_manifest["sourceSession"] = str(source_session_path.parent)
    next_manifest["processedFrameCount"] = frame_count
    next_manifest["frames"] = output_frames
    next_manifest["posteriorRepair"] = {
        "method": "stable_visible_pixel_cache_future_then_past_fixed_camera_backfill",
        "sourceSession": str(source_session_path.parent),
        "maskedSession": str(masked_session_path.parent),
        "futureWindow": future_window,
        "pastWindow": past_window,
        "maskDilatePixels": mask_dilate,
        "donorMaskDilatePixels": donor_mask_dilate,
        "featherPixels": feather,
        "preferFuture": prefer_future,
        "acceptScore": accept_score,
        "minSupportFrames": min_support,
        "rgbChangeThreshold": rgb_change_threshold,
        "depthChangeThreshold": depth_change_threshold,
        "changeDilatePixels": change_dilate,
        "spatialRadius": spatial_radius,
        "spatialDensity": spatial_density,
        "minComponentArea": min_component_area,
        "requireFutureChange": require_future_change,
        "allowPastFill": allow_past_fill,
        "useSourceDonor": use_source_donor,
        "rgbRepairAlpha": rgb_repair_alpha,
        "handGuidedRgb": hand_guided_rgb,
        "handRgbRadius": hand_rgb_radius,
        "handRgbFutureWindow": hand_rgb_future_window,
        "handRgbDirectionalHalf": hand_rgb_directional_half,
        "currentRgbUpdateThreshold": current_rgb_update_threshold,
        "rgbDonorCleanThreshold": rgb_donor_clean_threshold,
        "sourceRgbWhenNoRepair": source_rgb_when_no_repair,
        "handRgbIntents": sorted(hand_rgb_intents),
        "totalRepairMaskPixels": total_repair_pixels,
        "totalPosteriorFilledPixels": posterior_pixels_total,
        "totalFutureFilledPixels": future_pixels_total,
        "totalPastFilledPixels": past_pixels_total,
        "note": "Posterior repair caches nearest later/earlier stable visible fixed-camera evidence per pixel to fill hand/tool occlusions; it is not real-time sensor observation.",
    }
    _save_json(output_dir / "processed_manifest.json", next_manifest)

    final = output_frames[-1]
    rel_output = f"res://assets/processed_sessions/{output_dir.name}"
    next_session = dict(masked_session)
    next_session["id"] = f"{masked_session.get('id', output_dir.name)}_posterior_repair"
    next_session["title"] = f"{masked_session.get('title', output_dir.name)} - posterior repaired"
    next_session["duration"] = float(final.get("time", next_session.get("duration", 0.0)))
    data_sources = dict(next_session.get("data_sources", {}))
    data_sources.update({
        "depth_map": f"{rel_output}/{final['cleanDepth']}",
        "detail_depth_map": f"{rel_output}/{final['detailDepth']}",
        "texture_map": f"{rel_output}/{final['cleanRgb']}",
        "surface_mask": f"{rel_output}/surface_mask.png",
        "occlusion_mask": f"{rel_output}/{final['occlusionMask']}",
        "processed_manifest": f"{rel_output}/processed_manifest.json",
    })
    next_session["data_sources"] = data_sources
    production = dict(next_session.get("production_session", {}))
    production["posteriorRepair"] = next_manifest["posteriorRepair"]
    next_session["production_session"] = production
    _save_json(output_dir / "session.json", next_session)

    hand_sidecar = masked_session_path.parent / str(data_sources.get("hand_tracks", "hand_tracks_mediapipe.json"))
    if hand_sidecar.exists():
        shutil.copy2(hand_sidecar, output_dir / hand_sidecar.name)

    return output_dir / "session.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", required=True, type=Path, help="Raw/uncleaned processed session or session.json")
    parser.add_argument("--masked-session", required=True, type=Path, help="Existing object-removed session or session.json")
    parser.add_argument("--output-session", required=True, type=Path, help="Output session directory")
    parser.add_argument("--future-window", type=int, default=120)
    parser.add_argument("--past-window", type=int, default=45)
    parser.add_argument("--start-frame", type=int, default=0, help="Zero-based frame offset for testing/subset repair")
    parser.add_argument("--max-frames", type=int, default=None, help="Limit number of frames for testing/subset repair")
    parser.add_argument("--mask-dilate", type=int, default=2)
    parser.add_argument("--donor-mask-dilate", type=int, default=12, help="Extra source-frame exclusion around object masks to avoid copying hand/tool boundaries")
    parser.add_argument("--feather", type=int, default=10)
    parser.add_argument("--prefer-past", action="store_true", help="Prefer past visible evidence instead of future evidence")
    parser.add_argument("--debug-maps", action="store_true", help="Write posterior mask/source-index diagnostic maps")
    parser.add_argument("--accept-score", type=float, default=0.7, help="Stop scanning once a nearby donor covers this fraction of the remaining repair mask")
    parser.add_argument("--min-support", type=int, default=2, help="Required consecutive stable visible frames before a future pixel is trusted")
    parser.add_argument("--rgb-change-threshold", type=float, default=8.0, help="Mean RGB delta treated as a real per-pixel surface change")
    parser.add_argument("--depth-change-threshold", type=int, default=7, help="Detail-depth delta treated as a real per-pixel surface change")
    parser.add_argument("--change-dilate", type=int, default=1, help="Dilate temporal change mask to avoid unstable edges")
    parser.add_argument("--spatial-radius", type=int, default=5, help="Local support radius for accepting stable future pixels")
    parser.add_argument("--spatial-density", type=float, default=0.35, help="Minimum local accepted-pixel density inside spatial-radius")
    parser.add_argument("--min-component-area", type=int, default=180, help="Drop posterior repair islands smaller than this pixel area")
    parser.add_argument("--no-require-future-change", action="store_true", help="Allow future fill even if it does not differ from the nearest past visible baseline")
    parser.add_argument("--allow-past-fill", action="store_true", help="Fill unresolved repair pixels from past frames instead of preserving the current cleaned frame")
    parser.add_argument("--use-source-donor", action="store_true", help="Copy donor RGB-D from source session at pixels proven visible by the masked session")
    parser.add_argument("--rgb-repair-alpha", type=float, default=0.35, help="Blend strength for posterior RGB; depth/detail maps are still strongly repaired")
    parser.add_argument("--current-rgb-update-threshold", type=float, default=0.0, help="Safely refresh currently visible RGB from the source frame when source and cleaned RGB differ by at most this mean RGB delta; 0 disables")
    parser.add_argument("--rgb-donor-clean-threshold", type=float, default=0.0, help="Allow source RGB donors only where the source and cleaned donor frame agree within this mean RGB delta; 0 disables")
    parser.add_argument("--source-rgb-when-no-repair", action="store_true", help="For frames with no repair mask, write the current source RGB instead of carrying the cleaned/reference RGB")
    parser.add_argument("--hand-guided-rgb", action="store_true", help="Restrict posterior RGB blending to MediaPipe contact/fingertip trail regions")
    parser.add_argument("--hand-rgb-radius", type=int, default=28, help="Pixel radius around MediaPipe contact landmarks allowed to receive posterior RGB")
    parser.add_argument("--hand-rgb-future-window", type=int, default=18, help="Future frame window for contact-trail guided RGB repair")
    parser.add_argument("--hand-rgb-directional-half", action="store_true", help="Expand RGB guide to the contact-side half-plane inferred from fingertip motion")
    parser.add_argument("--hand-rgb-intents", default="drawing,erasing", help="Comma-separated intents whose fingertip/contact trail guides RGB repair")
    args = parser.parse_args()

    output = repair_session(
        _session_path(args.source_session),
        _session_path(args.masked_session),
        args.output_session,
        start_frame=max(0, args.start_frame),
        max_frames=args.max_frames if args.max_frames is None else max(1, args.max_frames),
        future_window=max(0, args.future_window),
        past_window=max(0, args.past_window),
        mask_dilate=max(0, args.mask_dilate),
        donor_mask_dilate=max(0, args.donor_mask_dilate),
        feather=max(0, args.feather),
        prefer_future=not args.prefer_past,
        debug_maps=args.debug_maps,
        accept_score=max(0.0, min(1.0, args.accept_score)),
        min_support=max(1, args.min_support),
        rgb_change_threshold=max(0.0, args.rgb_change_threshold),
        depth_change_threshold=max(0, args.depth_change_threshold),
        change_dilate=max(0, args.change_dilate),
        spatial_radius=max(0, args.spatial_radius),
        spatial_density=max(0.0, min(1.0, args.spatial_density)),
        min_component_area=max(0, args.min_component_area),
        require_future_change=not args.no_require_future_change,
        allow_past_fill=args.allow_past_fill,
        use_source_donor=args.use_source_donor,
        rgb_repair_alpha=max(0.0, min(1.0, args.rgb_repair_alpha)),
        hand_guided_rgb=args.hand_guided_rgb,
        hand_rgb_radius=max(0, args.hand_rgb_radius),
        hand_rgb_future_window=max(0, args.hand_rgb_future_window),
        hand_rgb_intents={item.strip() for item in str(args.hand_rgb_intents).split(",") if item.strip()},
        hand_rgb_directional_half=args.hand_rgb_directional_half,
        current_rgb_update_threshold=max(0.0, args.current_rgb_update_threshold),
        rgb_donor_clean_threshold=max(0.0, args.rgb_donor_clean_threshold),
        source_rgb_when_no_repair=args.source_rgb_when_no_repair,
    )
    print(output)


if __name__ == "__main__":
    main()
