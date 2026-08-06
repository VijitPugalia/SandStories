#!/usr/bin/env python3
"""Prepare an iPad/AR production session folder for the Godot prototype.

The production folder is treated as read-only. All generated files are written
to assets/processed_sessions/<session_id>/ so future production schema changes
can be handled by this adapter instead of changing capture output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

DETAIL_DEPTH_SCALE_METERS = 0.004


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_float_rgb(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(image.convert("RGB").resize(size, Image.Resampling.LANCZOS), dtype=np.float32) / 255.0


def _depth_u16(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path), dtype=np.uint16)


def _largest_component(mask: np.ndarray, prefer_center: bool = True) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    if prefer_center:
        h, w = mask.shape
        center = labels[h // 3 : (h * 2) // 3, w // 3 : (w * 2) // 3]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        if ids.size:
            return labels == ids[int(np.argmax(freq))]
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    return labels == int(np.argmax(sizes) + 1)


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    keep = np.zeros(count + 1, dtype=bool)
    keep[1:] = sizes >= min_area
    return keep[labels]


def _sand_surface_mask(rgb0: np.ndarray) -> np.ndarray:
    """Segment the stable sand/tray interior from the first RGB frame.

    This intentionally uses broad visual cues instead of hard-coded crop
    coordinates because the production app may move between devices and setups.
    """
    mx = rgb0.max(axis=2)
    mn = rgb0.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    lum = rgb0 @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    blue_bias = rgb0[:, :, 2] - np.maximum(rgb0[:, :, 0], rgb0[:, :, 1])
    red_floor_bias = rgb0[:, :, 0] - rgb0[:, :, 2]

    sand_like = (sat < 0.34) & (lum > 0.18) & (lum < 0.92)
    sand_like &= blue_bias < 0.16
    sand_like &= red_floor_bias < 0.32

    sand_like = ndimage.binary_opening(sand_like, structure=np.ones((3, 3)))
    sand_like = ndimage.binary_closing(sand_like, structure=np.ones((9, 9)))
    sand_like = ndimage.binary_fill_holes(sand_like)
    sand_like = _largest_component(sand_like, prefer_center=True)
    sand_like = ndimage.binary_erosion(sand_like, structure=np.ones((3, 3)), iterations=1)
    sand_like = ndimage.binary_dilation(sand_like, structure=np.ones((5, 5)), iterations=1)
    return sand_like.astype(bool)


def _skin_or_cloth_mask(rgb: np.ndarray) -> np.ndarray:
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)

    skin = (sat > 0.16) & (r > 0.45) & (g > 0.25) & (b > 0.16)
    skin &= ((r - b) > 0.13) & ((r - g) > 0.005) & ((g - b) > 0.025)
    green_sleeve = (g > r * 0.95) & (g > b * 0.92) & (mx > 0.36) & (sat > 0.16)
    return skin | green_sleeve


def _occlusion_mask(
    rgb: np.ndarray,
    rgb0: np.ndarray,
    depth: np.ndarray,
    baseline_depth: np.ndarray,
    sand_mask: np.ndarray,
) -> np.ndarray:
    color_delta = np.linalg.norm(rgb - rgb0, axis=2)
    depth_delta = baseline_depth.astype(np.int32) - depth.astype(np.int32)
    foreground = (depth_delta > 1650) & (color_delta > 0.14)
    moving_foreground = (depth_delta > 900) & (color_delta > 0.30)
    semantic_foreground = _skin_or_cloth_mask(rgb) & (color_delta > 0.14)

    mask = sand_mask & (foreground | moving_foreground | semantic_foreground)
    mask = _remove_small_components(mask, min_area=18)
    mask = ndimage.binary_closing(mask, structure=np.ones((5, 5)))
    mask = ndimage.binary_dilation(mask, structure=np.ones((7, 7)), iterations=2)
    mask &= sand_mask
    return mask.astype(bool)


def _mask_overlay(rgb: np.ndarray, surface_mask: np.ndarray, occlusion_mask: np.ndarray) -> np.ndarray:
    base = _rgb_to_png(rgb).astype(np.float32)
    outside = ~surface_mask
    base[outside] *= 0.35
    red = np.array([255, 32, 24], dtype=np.float32)
    base[occlusion_mask] = base[occlusion_mask] * 0.35 + red * 0.65
    return np.clip(base, 0, 255).astype(np.uint8)


def _fill_occlusion(current: np.ndarray, previous_clean: np.ndarray, baseline: np.ndarray, occlusion: np.ndarray) -> np.ndarray:
    clean = current.copy()
    fill = previous_clean if previous_clean is not None else baseline
    clean[occlusion] = fill[occlusion]
    return clean


def _session_depth_range(depth_frames: list[np.ndarray], sand_mask: np.ndarray) -> tuple[float, float]:
    if not depth_frames:
        return 0.0, 65535.0
    valid = depth_frames[0][sand_mask]
    if valid.size == 0:
        return 0.0, 65535.0
    lo = float(np.percentile(valid, 2))
    hi = float(np.percentile(valid, 98))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _depth_stats(depth: np.ndarray, sand_mask: np.ndarray) -> dict[str, float]:
    valid = depth[sand_mask]
    if valid.size == 0:
        return {"min": 0.0, "mean": 0.0, "max": 0.0, "p02": 0.0, "p98": 0.0}
    return {
        "min": float(valid.min()),
        "mean": float(valid.mean()),
        "max": float(valid.max()),
        "p02": float(np.percentile(valid, 2)),
        "p98": float(np.percentile(valid, 98)),
    }


def _depth_to_height_png(depth: np.ndarray, sand_mask: np.ndarray, depth_range: tuple[float, float]) -> np.ndarray:
    valid = depth[sand_mask]
    if valid.size == 0:
        return np.full(depth.shape, 255, dtype=np.uint8)
    lo, hi = depth_range
    if hi <= lo:
        hi = lo + 1.0
    normalized_distance = np.clip((depth.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)
    height = 1.0 - normalized_distance
    height = 0.14 + height * 0.78
    out = np.full(depth.shape, 255, dtype=np.uint8)
    out[sand_mask] = np.clip(height[sand_mask] * 255.0, 0, 255).astype(np.uint8)
    return out


def _depth_delta_to_detail_png(delta: np.ndarray, sand_mask: np.ndarray, occlusion: np.ndarray, scale_u16: float = 96.0) -> np.ndarray:
    valid = sand_mask & ~occlusion
    detail = np.full(delta.shape, 128, dtype=np.uint8)
    if not np.any(valid):
        return detail
    clipped = np.clip(delta.astype(np.float32), -scale_u16, scale_u16)
    # Encode fixed-camera sub-centimeter changes around neutral gray so shallow
    # sand marks are visible without being dominated by absolute tray slope.
    encoded = 128.0 + (-clipped / scale_u16) * 96.0
    detail[sand_mask] = np.clip(encoded[sand_mask], 0, 255).astype(np.uint8)
    detail[occlusion & sand_mask] = 128
    return detail


def _meters_to_u16(depth_m: np.ndarray, max_depth_m: float = 8.0) -> np.ndarray:
    valid = np.isfinite(depth_m) & (depth_m > 0)
    out = np.zeros(depth_m.shape, dtype=np.uint16)
    out[valid] = np.clip(depth_m[valid] / max_depth_m * 65535.0, 0, 65535).astype(np.uint16)
    return out


def _load_v2_frames(session_dir: Path) -> list[dict[str, Any]]:
    path = session_dir / "v2_frames.jsonl"
    if not path.exists():
        return []
    frames: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            frames.append(json.loads(line))
    return frames


def _read_v2_depth(stream_path: Path, frame: dict[str, Any], key: str = "depthByteOffset") -> np.ndarray:
    width = int(frame["width"])
    height = int(frame["height"])
    offset = int(frame[key])
    return np.memmap(stream_path, dtype="<f4", mode="r", offset=offset, shape=(height, width)).copy()


def _read_v2_confidence(stream_path: Path, frame: dict[str, Any]) -> np.ndarray:
    width = int(frame["width"])
    height = int(frame["height"])
    offset = int(frame.get("confidenceByteOffset", 0))
    return np.memmap(stream_path, dtype=np.uint8, mode="r", offset=offset, shape=(height, width)).copy()


def _v2_depth_mask(depths: list[np.ndarray], confidences: list[np.ndarray]) -> np.ndarray:
    stack = np.stack(depths)
    conf_stack = np.stack(confidences) if confidences else np.ones(stack.shape, dtype=np.uint8) * 2
    valid = np.isfinite(stack) & (stack > 0.15) & (stack < 2.5) & (conf_stack >= 1)
    stable = valid.mean(axis=0) > 0.55
    stable = ndimage.binary_closing(stable, structure=np.ones((7, 7)))
    stable = ndimage.binary_fill_holes(stable)
    stable = _largest_component(stable, prefer_center=True)
    return stable.astype(bool)


def _v2_rgb_sand_mask(rgb: np.ndarray, depth_mask: np.ndarray) -> np.ndarray:
    """Find the sand/tray interior in the RGB image at depth resolution."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    pixels = lab.reshape((-1, 3)).astype(np.float32)
    cv2.setRNGSeed(7)
    _, labels, _ = cv2.kmeans(
        pixels,
        6,
        None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.2),
        5,
        cv2.KMEANS_PP_CENTERS,
    )
    labels = labels.reshape(rgb.shape[:2])
    center_label = int(labels[rgb.shape[0] // 2, rgb.shape[1] // 2])
    mask = labels == center_label
    mask = ndimage.binary_closing(mask, structure=np.ones((7, 7)), iterations=2)
    mask = ndimage.binary_fill_holes(mask)
    mask = _largest_component(mask, prefer_center=True)

    points = np.column_stack(np.nonzero(mask))[:, ::-1].astype(np.int32)
    if points.shape[0] < 3:
        return depth_mask
    hull = cv2.convexHull(points)
    hull_mask = np.zeros(mask.shape, dtype=np.uint8)
    cv2.fillConvexPoly(hull_mask, hull, 1)
    hull_mask = ndimage.binary_erosion(
        hull_mask.astype(bool),
        structure=np.ones((5, 5)),
        iterations=1,
    )
    registered = hull_mask & depth_mask
    return registered if np.any(registered) else depth_mask


def _fill_current_frame_depth(depth: np.ndarray, mask: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Fill invalid samples spatially without borrowing geometry from another frame."""
    valid = mask & np.isfinite(depth) & (depth > 0.15) & (depth < 2.5)
    clean = depth.copy()
    if np.any(valid):
        _, nearest = ndimage.distance_transform_edt(~valid, return_indices=True)
        missing = mask & ~valid
        clean[missing] = depth[nearest[0][missing], nearest[1][missing]]
    else:
        clean[mask] = fallback[mask]
    return clean


def _depth_m_to_height_png(depth_m: np.ndarray, mask: np.ndarray, depth_range: tuple[float, float]) -> np.ndarray:
    lo, hi = depth_range
    if hi <= lo:
        hi = lo + 1e-4
    norm = np.clip((depth_m - lo) / (hi - lo), 0.0, 1.0)
    height = 1.0 - norm
    out = np.full(depth_m.shape, 255, dtype=np.uint8)
    out[mask] = np.clip((0.14 + height[mask] * 0.78) * 255.0, 0, 255).astype(np.uint8)
    return out


def _depth_m_delta_to_detail_png(delta_m: np.ndarray, mask: np.ndarray, occlusion: np.ndarray, scale_m: float = DETAIL_DEPTH_SCALE_METERS) -> np.ndarray:
    detail = np.full(delta_m.shape, 128, dtype=np.uint8)
    valid = mask & ~occlusion & np.isfinite(delta_m)
    if not np.any(valid):
        return detail
    clipped = np.clip(delta_m, -scale_m, scale_m)
    encoded = 128.0 + (-clipped / scale_m) * 96.0
    detail[mask] = np.clip(encoded[mask], 0, 255).astype(np.uint8)
    detail[occlusion & mask] = 128
    return detail


def _pseudo_sand_rgb(height_png: np.ndarray, detail_png: np.ndarray, mask: np.ndarray) -> np.ndarray:
    h = height_png.astype(np.float32) / 255.0
    d = (detail_png.astype(np.float32) - 128.0) / 128.0
    shade = np.clip(0.74 + h * 0.18 + d * 0.16, 0.45, 1.0)
    base = np.array([214, 198, 158], dtype=np.float32)
    rgb = np.clip(base[None, None, :] * shade[:, :, None], 0, 255).astype(np.uint8)
    rgb[~mask] = np.array([42, 45, 42], dtype=np.uint8)
    return rgb


def _write_v2_contact_sheet(output_dir: Path, frames: list[dict[str, Any]]) -> None:
    tiles: list[Image.Image] = []
    for frame in frames:
        rgb = Image.open(output_dir / frame["cleanRgb"]).convert("RGB")
        clean = Image.open(output_dir / frame["cleanDepth"]).convert("L").convert("RGB")
        detail = Image.open(output_dir / frame["detailDepth"]).convert("L").convert("RGB")
        w, h = rgb.size
        tile = Image.new("RGB", (w * 3, h + 22), (18, 18, 18))
        tile.paste(rgb, (0, 22))
        tile.paste(clean, (w, 22))
        tile.paste(detail, (w * 2, 22))
        draw = ImageDraw.Draw(tile)
        draw.text((4, 4), f"Frame {frame['frameIndex']}: RGB | clean depth | detail depth", fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (0, index * tile.height))
    sheet.save(output_dir / "frame_contact_sheet.png")


def _sample_v2_frames(frames: list[dict[str, Any]], max_frames: int | None = None) -> list[dict[str, Any]]:
    if max_frames is None:
        return frames
    if len(frames) <= max_frames:
        return frames
    indices = np.linspace(0, len(frames) - 1, max_frames, dtype=int)
    return [frames[int(i)] for i in np.unique(indices)]


def _iter_rgb_video_frames(video_path: Path, size: tuple[int, int], count: int):
    width, height = size
    frame_size = width * height * 3
    if not video_path.exists():
        for _ in range(count):
            yield None
        return

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        for _ in range(count):
            yield None
        return

    assert process.stdout is not None
    try:
        for _ in range(count):
            chunk = process.stdout.read(frame_size)
            if len(chunk) != frame_size:
                yield None
                continue
            yield np.frombuffer(chunk, dtype=np.uint8).reshape((height, width, 3)).copy()
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _prepare_v2_session(session_dir: Path, project_dir: Path, manifest: dict[str, Any]) -> Path:
    session_id = str(manifest.get("sessionId", session_dir.name.replace("session_", "")))
    output_dir = project_dir / "assets" / "processed_sessions" / f"session_{session_id}"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    v2_frames = _load_v2_frames(session_dir)
    if not v2_frames:
        raise RuntimeError(f"No v2_frames.jsonl records found in {session_dir}")

    streams = manifest.get("v2Streams", {})
    depth_stream = session_dir / streams.get("depthStreamPath", "streams/depth.f32")
    smooth_stream = session_dir / streams.get("smoothedDepthStreamPath", "streams/smoothed_depth.f32")
    confidence_stream = session_dir / streams.get("confidenceStreamPath", "streams/confidence.bin")
    rgb_video = session_dir / streams.get("rgbVideoPath", "streams/rgb.mp4")

    probe_frames = v2_frames[: min(180, len(v2_frames))]
    probe_depths = [_read_v2_depth(depth_stream, frame) for frame in probe_frames]
    probe_confidences = []
    if confidence_stream.exists():
        probe_confidences = [_read_v2_confidence(confidence_stream, frame) for frame in probe_frames]

    depth_mask = _v2_depth_mask(probe_depths, probe_confidences)
    frame_size = (int(v2_frames[0]["width"]), int(v2_frames[0]["height"]))
    first_rgb = next(_iter_rgb_video_frames(rgb_video, frame_size, 1), None)
    sand_mask = _v2_rgb_sand_mask(first_rgb, depth_mask) if first_rgb is not None else depth_mask
    Image.fromarray(_mask_to_png(sand_mask)).save(output_dir / "surface_mask.png")

    baseline_count = min(60, len(v2_frames))
    baseline_stack = np.stack([_read_v2_depth(depth_stream, frame) for frame in v2_frames[:baseline_count]]).astype(np.float32)
    fixed_camera_baseline = np.nanmedian(baseline_stack, axis=0)
    valid_baseline = fixed_camera_baseline[sand_mask & np.isfinite(fixed_camera_baseline)]
    if valid_baseline.size == 0:
        fixed_depth_range = (0.0, 1.0)
    else:
        fixed_depth_range = (float(np.percentile(valid_baseline, 2)), float(np.percentile(valid_baseline, 98)))

    selected_frames = _sample_v2_frames(v2_frames, max_frames=None)
    rgb_frames = _iter_rgb_video_frames(rgb_video, frame_size, len(selected_frames))
    processed_frames: list[dict[str, Any]] = []
    raw_delta_std_mm: list[float] = []
    smooth_delta_std_mm: list[float] = []
    rgb_video_frames_used = 0

    for ordinal, frame in enumerate(selected_frames, start=1):
        depth = _read_v2_depth(depth_stream, frame)
        depth_delta = fixed_camera_baseline - depth
        depth_occlusion = sand_mask & np.isfinite(depth) & np.isfinite(fixed_camera_baseline) & (depth_delta > 0.015)
        if np.any(depth_occlusion):
            depth_occlusion = ndimage.binary_closing(depth_occlusion, structure=np.ones((5, 5)))
            depth_occlusion = ndimage.binary_dilation(depth_occlusion, structure=np.ones((7, 7)), iterations=2) & sand_mask
        occlusion = depth_occlusion.astype(bool)

        clean_depth = depth.copy()
        clean_depth[occlusion] = fixed_camera_baseline[occlusion]
        clean_depth = _fill_current_frame_depth(clean_depth, sand_mask, fixed_camera_baseline)
        delta = clean_depth - fixed_camera_baseline

        height_png = _depth_m_to_height_png(clean_depth, sand_mask, fixed_depth_range)
        detail_png = _depth_m_delta_to_detail_png(delta, sand_mask, occlusion)
        video_rgb = next(rgb_frames, None)
        if video_rgb is None:
            rgb_png = _pseudo_sand_rgb(height_png, detail_png, sand_mask)
        else:
            rgb_png = video_rgb
            rgb_video_frames_used += 1

        stem = f"{ordinal:06d}"
        aligned_rgb_name = f"aligned_rgb_{stem}.png"
        clean_rgb_name = f"clean_rgb_{stem}.png"
        clean_depth_name = f"clean_depth_{stem}.png"
        detail_depth_name = f"detail_depth_{stem}.png"
        occlusion_name = f"occlusion_mask_{stem}.png"
        overlay_name = f"mask_overlay_{stem}.png"

        Image.fromarray(rgb_png).save(output_dir / aligned_rgb_name)
        Image.fromarray(rgb_png).save(output_dir / clean_rgb_name)
        Image.fromarray(height_png).save(output_dir / clean_depth_name)
        Image.fromarray(detail_png).save(output_dir / detail_depth_name)
        Image.fromarray(_mask_to_png(occlusion)).save(output_dir / occlusion_name)
        Image.fromarray(rgb_png).save(output_dir / overlay_name)

        valid_delta = delta[sand_mask & ~occlusion & np.isfinite(delta)] * 1000.0
        if valid_delta.size:
            raw_delta_std_mm.append(float(np.std(valid_delta)))
        if smooth_stream.exists() and frame.get("smoothedDepthByteOffset") is not None:
            smooth = _read_v2_depth(smooth_stream, frame, "smoothedDepthByteOffset")
            smooth_delta = smooth - fixed_camera_baseline
            valid_smooth_delta = smooth_delta[sand_mask & ~occlusion & np.isfinite(smooth_delta)] * 1000.0
            if valid_smooth_delta.size:
                smooth_delta_std_mm.append(float(np.std(valid_smooth_delta)))

        processed_frames.append({
            "frameIndex": int(frame.get("frameIndex", ordinal)),
            "time": float(frame.get("monotonicElapsedSeconds", 0.0)),
            "sourceDepth": "streams/depth.f32",
            "alignedRgb": aligned_rgb_name,
            "cleanRgb": clean_rgb_name,
            "cleanDepth": clean_depth_name,
            "detailDepth": detail_depth_name,
            "occlusionMask": occlusion_name,
            "maskOverlay": overlay_name,
            "occlusionPixels": int(occlusion.sum()),
            "rawDepthStatsMeters": _depth_stats(_meters_to_u16(depth), sand_mask),
            "cleanDepthStatsMeters": {
                "min": float(np.nanmin(clean_depth[sand_mask])),
                "mean": float(np.nanmean(clean_depth[sand_mask])),
                "max": float(np.nanmax(clean_depth[sand_mask])),
                "p02": float(np.nanpercentile(clean_depth[sand_mask], 2)),
                "p98": float(np.nanpercentile(clean_depth[sand_mask], 98)),
            },
        })

    final_frame = processed_frames[-1]
    _write_v2_contact_sheet(output_dir, processed_frames[: min(80, len(processed_frames))])
    processed_manifest = {
        "sourceSession": str(session_dir),
        "sourceManifest": str(session_dir / "manifest.json"),
        "sessionId": session_id,
        "captureFormat": "v2_streams",
        "sourceFrameCount": len(v2_frames),
        "processedFrameCount": len(processed_frames),
        "frameSize": {"width": int(v2_frames[0]["width"]), "height": int(v2_frames[0]["height"])},
        "depthEncoding": manifest.get("depthEncoding", {}),
        "depthNormalization": {
            "method": "baseline_first_60_frame_median_percentile_range_meters",
            "p02BaselineMeters": fixed_depth_range[0],
            "p98BaselineMeters": fixed_depth_range[1],
        },
        "fixedCameraDetail": {
            "method": "unsmoothed_sceneDepth_minus_first_60_frame_median",
            "neutralGray": 128,
            "scaleMeters": DETAIL_DEPTH_SCALE_METERS,
            "note": "detail_depth uses unsmoothed ARKit sceneDepth; smoothedSceneDepth is retained in source streams for comparison.",
        },
        "diagnostics": {
            "rawDeltaStdMmMedian": float(np.median(raw_delta_std_mm)) if raw_delta_std_mm else None,
            "smoothDeltaStdMmMedian": float(np.median(smooth_delta_std_mm)) if smooth_delta_std_mm else None,
            "surfaceMaskPixels": int(sand_mask.sum()),
            "rgbVideoFramesUsed": rgb_video_frames_used,
        },
        "masking": {
            "method": "rgb_sand_hull_intersect_stable_depth",
            "note": "RGB and raw sceneDepth remain paired per frame. Invalid samples are filled only from spatial neighbors in the same frame; no previous-frame geometry is held, so camera motion cannot create RGB/depth drift.",
            "surfaceMask": "surface_mask.png",
            "contactSheet": "frame_contact_sheet.png",
        },
        "frames": processed_frames,
    }
    _save_json(output_dir / "processed_manifest.json", processed_manifest)

    rel_output = f"res://assets/processed_sessions/session_{session_id}"
    duration = float(manifest.get("monotonicSessionEndElapsedSeconds", final_frame["time"]))
    godot_session = {
        "id": f"production_{session_id}",
        "title": f"Production v2 Session {session_id}",
        "duration": max(duration, final_frame["time"]),
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{rel_output}/{final_frame['detailDepth']}",
            "detail_depth_map": f"{rel_output}/{final_frame['detailDepth']}",
            "preferred_depth_frame": "detailDepth",
            "texture_map": f"{rel_output}/{final_frame['cleanRgb']}",
            "surface_mask": f"{rel_output}/surface_mask.png",
            "occlusion_mask": f"{rel_output}/{final_frame['occlusionMask']}",
            "processed_manifest": f"{rel_output}/processed_manifest.json",
            "audio": "",
            "calibration": {
                "depth_uv_offset": [0.0, 0.0],
                "texture_uv_offset": [0.0, 0.0],
                "depth_uv_scale": [1.0, 1.0],
                "texture_uv_scale": [1.0, 1.0],
                "height_scale": 1.35,
                "material_strength": 0.72,
                "detail_scale_m": DETAIL_DEPTH_SCALE_METERS,
                "neutral_gray": 128.0,
                "use_rgb_grooves": False,
                "rgb_groove_strength": 0.0,
            },
        },
        "production_session": {
            "schemaVersion": manifest.get("schemaVersion"),
            "appVersion": manifest.get("appVersion"),
            "deviceModel": manifest.get("deviceModel"),
            "sourceFolder": f"res://assets/sessions/session_{session_id}",
            "rgbFrameCount": rgb_video_frames_used,
            "depthFrameCount": len(v2_frames),
            "processedFrameCount": len(processed_frames),
        },
        "gesture_events": _strokes_to_events(session_dir, manifest),
        "study_tasks": [{"id": "production_surface_review", "prompt": "Review v2 Float32 LiDAR depth reconstruction."}],
    }
    session_json_path = output_dir / "session.json"
    _save_json(session_json_path, godot_session)
    return session_json_path


def _rgb_to_png(rgb: np.ndarray) -> np.ndarray:
    return np.clip(rgb * 255.0, 0, 255).astype(np.uint8)


def _mask_to_png(mask: np.ndarray) -> np.ndarray:
    return (mask.astype(np.uint8) * 255)


def _write_contact_sheet(output_dir: Path, frames: list[dict[str, Any]]) -> None:
    tiles: list[Image.Image] = []
    for frame in frames:
        rgb = Image.open(output_dir / frame["cleanRgb"]).convert("RGB")
        depth = Image.open(output_dir / frame["cleanDepth"]).convert("L").convert("RGB")
        overlay = Image.open(output_dir / frame["maskOverlay"]).convert("RGB")
        w, h = rgb.size
        tile = Image.new("RGB", (w * 3, h + 22), (18, 18, 18))
        tile.paste(rgb, (0, 22))
        tile.paste(depth, (w, 22))
        tile.paste(overlay, (w * 2, 22))
        draw = ImageDraw.Draw(tile)
        draw.text((4, 4), f"Frame {frame['frameIndex']}: clean RGB | fixed-scale depth | mask overlay", fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (0, index * tile.height))
    sheet.save(output_dir / "frame_contact_sheet.png")


def _frame_pairs(session_dir: Path, manifest: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    depth_by_index = {int(frame["frameIndex"]): frame for frame in manifest.get("depthFrames", [])}
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for rgb_frame in manifest.get("rgbFrames", []):
        idx = int(rgb_frame["frameIndex"])
        depth_frame = depth_by_index.get(idx)
        if depth_frame is None:
            continue
        if not (session_dir / rgb_frame["relativePath"]).exists():
            continue
        if not (session_dir / depth_frame["relativePath"]).exists():
            continue
        pairs.append((rgb_frame, depth_frame))
    return pairs


def _strokes_to_events(session_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    strokes_file = manifest.get("strokesFile", "strokes.json")
    path = session_dir / strokes_file
    if not path.exists():
        return []
    try:
        strokes = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(strokes, list):
        return []
    t0 = float(manifest.get("arKitTimeReference", {}).get("firstFrameTimestamp", 0.0))
    events: list[dict[str, Any]] = []
    for i, stroke in enumerate(strokes):
        if not isinstance(stroke, dict):
            continue
        points = stroke.get("points", [])
        start = float(stroke.get("startedAt", points[0].get("timestamp", t0) if points else t0)) - t0
        end = float(stroke.get("finishedAt", points[-1].get("timestamp", t0) if points else t0)) - t0
        events.append({
            "id": f"stroke_{i + 1:03d}",
            "label": f"Stroke {i + 1}",
            "kind": "drawing",
            "start": max(0.0, start),
            "end": max(0.0, end),
        })
    return events


def prepare_session(session_dir: Path, project_dir: Path) -> Path:
    manifest_path = session_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    if manifest.get("captureFormat") == "v2_streams" or manifest.get("v2Streams"):
        return _prepare_v2_session(session_dir, project_dir, manifest)

    session_id = str(manifest.get("sessionId", session_dir.name.replace("session_", "")))
    output_dir = project_dir / "assets" / "processed_sessions" / f"session_{session_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs = _frame_pairs(session_dir, manifest)
    if not pairs:
        raise RuntimeError(f"No RGB/depth frame pairs found in {session_dir}")

    first_depth = _depth_u16(session_dir / pairs[0][1]["relativePath"])
    depth_h, depth_w = first_depth.shape
    target_size = (depth_w, depth_h)
    first_rgb = _as_float_rgb(Image.open(session_dir / pairs[0][0]["relativePath"]), target_size)
    sand_mask = _sand_surface_mask(first_rgb)
    raw_depth_frames = [_depth_u16(session_dir / depth_frame["relativePath"]) for _, depth_frame in pairs]
    fixed_depth_range = _session_depth_range(raw_depth_frames, sand_mask)
    fixed_camera_baseline = np.median(np.stack(raw_depth_frames[: min(3, len(raw_depth_frames))]).astype(np.float32), axis=0)

    Image.fromarray(_mask_to_png(sand_mask)).save(output_dir / "surface_mask.png")

    previous_clean_depth: np.ndarray | None = None
    previous_clean_rgb: np.ndarray | None = None
    processed_frames: list[dict[str, Any]] = []
    baseline_depth = first_depth
    baseline_rgb = first_rgb

    for rgb_frame, depth_frame in pairs:
        index = int(rgb_frame["frameIndex"])
        rgb = _as_float_rgb(Image.open(session_dir / rgb_frame["relativePath"]), target_size)
        depth = _depth_u16(session_dir / depth_frame["relativePath"])
        occlusion = _occlusion_mask(rgb, baseline_rgb, depth, baseline_depth, sand_mask)

        clean_depth = _fill_occlusion(depth, previous_clean_depth, baseline_depth, occlusion)
        clean_rgb = _fill_occlusion(_rgb_to_png(rgb), previous_clean_rgb, _rgb_to_png(baseline_rgb), occlusion)
        height_png = _depth_to_height_png(clean_depth, sand_mask, fixed_depth_range)
        detail_png = _depth_delta_to_detail_png(depth.astype(np.float32) - fixed_camera_baseline, sand_mask, occlusion)

        stem = f"{index:06d}"
        aligned_rgb_name = f"aligned_rgb_{stem}.png"
        clean_rgb_name = f"clean_rgb_{stem}.png"
        clean_depth_name = f"clean_depth_{stem}.png"
        detail_depth_name = f"detail_depth_{stem}.png"
        occlusion_name = f"occlusion_mask_{stem}.png"
        overlay_name = f"mask_overlay_{stem}.png"

        Image.fromarray(_rgb_to_png(rgb)).save(output_dir / aligned_rgb_name)
        Image.fromarray(clean_rgb).save(output_dir / clean_rgb_name)
        Image.fromarray(height_png).save(output_dir / clean_depth_name)
        Image.fromarray(detail_png).save(output_dir / detail_depth_name)
        Image.fromarray(_mask_to_png(occlusion)).save(output_dir / occlusion_name)
        Image.fromarray(_mask_overlay(rgb, sand_mask, occlusion)).save(output_dir / overlay_name)

        previous_clean_depth = clean_depth
        previous_clean_rgb = clean_rgb
        processed_frames.append({
            "frameIndex": index,
            "time": float(rgb_frame.get("monotonicElapsedSeconds", 0.0)),
            "sourceRgb": rgb_frame["relativePath"],
            "sourceDepth": depth_frame["relativePath"],
            "alignedRgb": aligned_rgb_name,
            "cleanRgb": clean_rgb_name,
            "cleanDepth": clean_depth_name,
            "detailDepth": detail_depth_name,
            "occlusionMask": occlusion_name,
            "maskOverlay": overlay_name,
            "occlusionPixels": int(occlusion.sum()),
            "rawDepthStatsU16": _depth_stats(depth, sand_mask),
            "cleanDepthStatsU16": _depth_stats(clean_depth, sand_mask),
        })

    final_frame = processed_frames[-1]
    _write_contact_sheet(output_dir, processed_frames)
    processed_manifest = {
        "sourceSession": str(session_dir),
        "sourceManifest": str(manifest_path),
        "sessionId": session_id,
        "frameSize": {"width": depth_w, "height": depth_h},
        "depthEncoding": manifest.get("depthEncoding", {}),
        "depthNormalization": {
            "method": "fixed_baseline_frame_percentile_range",
            "p02BaselineU16": fixed_depth_range[0],
            "p98BaselineU16": fixed_depth_range[1],
            "note": "All clean_depth frames use the first frame's sand-surface percentile range; later hand/body occluders do not rescale height.",
        },
        "fixedCameraDetail": {
            "method": "median_first_three_raw_depth_delta",
            "neutralGray": 128,
            "scaleU16": 96.0,
            "millimetersApprox": 11.7,
            "note": "detail_depth frames amplify fixed-camera millimeter-scale sand changes around neutral gray; occlusions remain neutral.",
        },
        "masking": {
            "method": "sam_like_temporal_depth_color_adapter",
            "note": "Production folder is read-only; masks are generated as derived cache assets. A SAM backend can replace the mask generator without changing session schema.",
            "surfaceMask": "surface_mask.png",
            "contactSheet": "frame_contact_sheet.png",
        },
        "frames": processed_frames,
    }
    _save_json(output_dir / "processed_manifest.json", processed_manifest)

    rel_output = f"res://assets/processed_sessions/session_{session_id}"
    duration = float(manifest.get("monotonicSessionEndElapsedSeconds", final_frame["time"]))
    godot_session = {
        "id": f"production_{session_id}",
        "title": f"Production Session {session_id}",
        "duration": max(duration, final_frame["time"]),
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{rel_output}/{final_frame['cleanDepth']}",
            "detail_depth_map": f"{rel_output}/{final_frame['detailDepth']}",
            "preferred_depth_frame": "cleanDepth",
            "texture_map": f"{rel_output}/{final_frame['cleanRgb']}",
            "surface_mask": f"{rel_output}/surface_mask.png",
            "occlusion_mask": f"{rel_output}/{final_frame['occlusionMask']}",
            "processed_manifest": f"{rel_output}/processed_manifest.json",
            "audio": "",
            "calibration": {
                "depth_uv_offset": [0.0, 0.0],
                "texture_uv_offset": [0.0, 0.0],
                "depth_uv_scale": [1.0, 1.0],
                "texture_uv_scale": [1.0, 1.0],
                "height_scale": 1.35,
                "material_strength": 0.42,
            },
        },
        "production_session": {
            "schemaVersion": manifest.get("schemaVersion"),
            "appVersion": manifest.get("appVersion"),
            "deviceModel": manifest.get("deviceModel"),
            "sourceFolder": f"res://assets/sessions/session_{session_id}",
            "rgbFrameCount": len(manifest.get("rgbFrames", [])),
            "depthFrameCount": len(manifest.get("depthFrames", [])),
            "processedFrameCount": len(processed_frames),
        },
        "gesture_events": _strokes_to_events(session_dir, manifest),
        "study_tasks": [
            {
                "id": "production_surface_review",
                "prompt": "Review reconstructed sand surface with generated surface/occlusion masks; production capture folder remains unchanged.",
            }
        ],
    }
    session_json_path = output_dir / "session.json"
    _save_json(session_json_path, godot_session)
    return session_json_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    session_json = prepare_session(args.session_dir.resolve(), args.project.resolve())
    print(session_json)


if __name__ == "__main__":
    main()
