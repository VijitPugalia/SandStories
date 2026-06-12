#!/usr/bin/env python3
"""Fixed-camera RGB/LiDAR sand-change experiment.

This is intentionally separate from the production importer. It tests the
pipeline where LiDAR provides low-frequency geometry/occlusion and high-res RGB
provides persistent fine sand-change evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage.filters import frangi, sato


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_v2_frames(session_dir: Path) -> list[dict[str, Any]]:
    frames_path = session_dir / "v2_frames.jsonl"
    frames: list[dict[str, Any]] = []
    for line in frames_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            frames.append(json.loads(line))
    return frames


def _read_depth(stream_path: Path, frame: dict[str, Any], key: str = "depthByteOffset") -> np.ndarray:
    return np.memmap(
        stream_path,
        dtype="<f4",
        mode="r",
        offset=int(frame[key]),
        shape=(int(frame["height"]), int(frame["width"])),
    ).copy()


def _read_confidence(stream_path: Path, frame: dict[str, Any]) -> np.ndarray:
    return np.memmap(
        stream_path,
        dtype=np.uint8,
        mode="r",
        offset=int(frame.get("confidenceByteOffset", 0)),
        shape=(int(frame["height"]), int(frame["width"])),
    ).copy()


def _frame_indices(total: int, requested: list[int] | None, count: int) -> list[int]:
    if requested:
        return sorted({min(total, max(1, index)) for index in requested})
    return [int(i) for i in np.unique(np.linspace(1, total, count, dtype=int))]


def _extract_rgb_frames(video_path: Path, output_dir: Path, indices: list[int], fps: float, width: int) -> dict[int, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    for index in indices:
        out_path = output_dir / f"rgb_{index:06d}.png"
        if out_path.exists():
            paths[index] = out_path
            continue
        _save_rgb(out_path, _read_video_frame(video_path, index, width))
        paths[index] = out_path
    return paths


def _extract_baseline_rgb(video_path: Path, output_dir: Path, count: int, fps: float, width: int) -> np.ndarray:
    rgb_dir = output_dir / "baseline_rgb_samples"
    indices = list(range(1, count + 1))
    paths = _extract_rgb_frames(video_path, rgb_dir, indices, fps, width)
    samples = [np.asarray(Image.open(paths[index]).convert("RGB"), dtype=np.float32) / 255.0 for index in indices]
    return np.median(np.stack(samples), axis=0).astype(np.float32)


def _surface_mask_from_depth(depth_stack: np.ndarray, confidence_stack: np.ndarray | None) -> np.ndarray:
    valid = np.isfinite(depth_stack) & (depth_stack > 0.15) & (depth_stack < 2.5)
    if confidence_stack is not None:
        valid &= confidence_stack >= 1
    stable = valid.mean(axis=0) > 0.6
    kernel = np.ones((7, 7), dtype=np.uint8)
    stable_u8 = cv2.morphologyEx(stable.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(stable_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(stable_u8, contours, -1, 1, thickness=cv2.FILLED)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(stable_u8, connectivity=8)
    if count > 1:
        h, w = stable.shape
        center = labels[h // 3 : h * 2 // 3, w // 3 : w * 2 // 3]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        keep = int(ids[int(np.argmax(freq))]) if ids.size else int(np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1)
        stable_u8 = (labels == keep).astype(np.uint8)
    return stable_u8.astype(bool)


def _local_luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114


def _local_normalize(lum: np.ndarray, use_clahe: bool = False) -> np.ndarray:
    local_mean = cv2.GaussianBlur(lum.astype(np.float32), (0, 0), 10.0)
    local_sq = cv2.GaussianBlur((lum * lum).astype(np.float32), (0, 0), 10.0)
    local_std = np.sqrt(np.maximum(local_sq - local_mean * local_mean, 1e-5))
    normalized = np.clip((lum - local_mean) / (local_std + 1e-4), -3.0, 3.0) / 6.0 + 0.5
    if not use_clahe:
        return normalized.astype(np.float32)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(np.clip(normalized * 255.0, 0, 255).astype(np.uint8)).astype(np.float32) / 255.0


def _lab_channels(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab[:, :, 0] / 255.0, (lab[:, :, 1] - 128.0) / 127.0, (lab[:, :, 2] - 128.0) / 127.0


def _remove_small_binary(mask: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return mask.astype(bool)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


def _keep_structured_components(mask: np.ndarray, min_area: int, min_aspect: float = 2.2) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return mask.astype(bool)
    keep = np.zeros(count, dtype=bool)
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        component = (labels == label).astype(np.uint8)
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        aspect = 1.0
        if contours:
            (_, _), (w, h), _ = cv2.minAreaRect(max(contours, key=cv2.contourArea))
            short = max(1e-3, min(w, h))
            aspect = max(w, h) / short
        # Keep long groove-like components, plus large broad disturbed regions.
        keep[label] = aspect >= min_aspect or area >= min_area * 8
    return keep[labels]


def _keep_groove_scale_evidence(evidence: np.ndarray, threshold: float, min_area: int, min_aspect: float) -> np.ndarray:
    mask = evidence > threshold
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8))
    mask = _keep_structured_components(mask.astype(bool), min_area=min_area, min_aspect=min_aspect)
    out = evidence.copy()
    out[~mask] = 0.0
    return out


def _inpaint_foreground_from_baseline(rgb: np.ndarray, baseline_rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    if not np.any(mask):
        return out
    expanded = cv2.dilate(mask.astype(np.uint8), np.ones((13, 13), dtype=np.uint8), iterations=1).astype(bool)
    out[expanded] = baseline_rgb[expanded]
    return out


def _normalize_percentile(image: np.ndarray, mask: np.ndarray | None = None, lo: float = 2.0, hi: float = 98.0) -> np.ndarray:
    values = image[mask] if mask is not None and np.any(mask) else image.reshape(-1)
    p_lo = float(np.percentile(values, lo))
    p_hi = float(np.percentile(values, hi))
    if p_hi <= p_lo:
        return np.zeros_like(image, dtype=np.float32)
    return np.clip((image - p_lo) / (p_hi - p_lo), 0.0, 1.0).astype(np.float32)


def _gradient_mag(image: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return np.hypot(gx, gy)


def _rgb_foreground_mask(rgb: np.ndarray) -> np.ndarray:
    rgb8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(rgb8, cv2.COLOR_RGB2HSV)
    ycrcb = cv2.cvtColor(rgb8, cv2.COLOR_RGB2YCrCb)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]

    # Sand is beige and can pass loose YCrCb skin thresholds. Keep this mask
    # intentionally strict: real hands are warmer and more saturated than the
    # tray/sand background in this fixed-camera setup.
    skin_hue = ((h <= 18) | (h >= 170))
    skin = skin_hue & (s > 42) & (v > 72) & (cr > 138) & (cr < 176) & (cb > 82) & (cb < 126)
    blue_marker_or_tool = (h > 88) & (h < 126) & (s > 70) & (v > 55)
    mask = skin | blue_marker_or_tool
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), dtype=np.uint8)).astype(bool)
    mask = _remove_small_binary(mask, min_area=max(120, int(rgb.shape[1] * rgb.shape[1] * 0.00012)))
    mask = cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), dtype=np.uint8), iterations=1).astype(bool)
    return mask


def _rgb_tool_mask(rgb: np.ndarray) -> np.ndarray:
    rgb8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(rgb8, cv2.COLOR_RGB2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    blue = (h > 88) & (h < 126) & (s > 70) & (v > 55)
    mask = blue
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), dtype=np.uint8)).astype(bool)
    mask = _remove_small_binary(mask, min_area=max(45, int(rgb.shape[1] * rgb.shape[1] * 0.00004)))
    return mask


def _rgb_skin_candidate(rgb: np.ndarray, baseline_rgb: np.ndarray) -> np.ndarray:
    rgb8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(rgb8, cv2.COLOR_RGB2HSV)
    ycrcb = cv2.cvtColor(rgb8, cv2.COLOR_RGB2YCrCb)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    _, lab_a, lab_b = _lab_channels(rgb)
    _, base_a, base_b = _lab_channels(baseline_rgb)
    chroma_delta = np.hypot(lab_a - base_a, lab_b - base_b)

    # Sand shares loose skin colors. Require both warmer/pinker color and a
    # chromatic departure from the baseline sand at the same pixel.
    skin_hue = ((h <= 16) | (h >= 174))
    skin = skin_hue & (s > 48) & (v > 82) & (cr > 146) & (cr < 178) & (cb > 78) & (cb < 120)
    skin &= (lab_a > base_a + 0.018) & (chroma_delta > 0.030)
    skin = cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), dtype=np.uint8)).astype(bool)
    skin = _remove_small_binary(skin, min_area=max(80, int(rgb.shape[1] * rgb.shape[1] * 0.00007)))
    return skin


def _largest_component(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return mask.astype(bool)
    keep = int(np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1)
    return labels == keep


def _sand_roi_from_baseline(baseline_rgb: np.ndarray, surface_mask_hi: np.ndarray) -> np.ndarray:
    lum = _local_luminance(baseline_rgb)
    _, lab_a, lab_b = _lab_channels(baseline_rgb)
    chroma = np.hypot(lab_a, lab_b)

    # Keep the broad beige sand surface, but reject tray edges, dark borders,
    # colored markers/tools, and blown-out side walls before any temporal logic.
    sand_like = (lum > 0.20) & (lum < 0.88) & (chroma < 0.28)
    sand_like &= surface_mask_hi
    sand_like = cv2.morphologyEx(sand_like.astype(np.uint8), cv2.MORPH_OPEN, np.ones((9, 9), dtype=np.uint8))
    sand_like = cv2.morphologyEx(sand_like, cv2.MORPH_CLOSE, np.ones((21, 21), dtype=np.uint8))
    sand_like = _largest_component(sand_like.astype(bool))
    sand_like = cv2.erode(sand_like.astype(np.uint8), np.ones((9, 9), dtype=np.uint8), iterations=1).astype(bool)
    return sand_like


def _rgb_relief_evidence(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    lab_l, _, _ = _lab_channels(rgb)
    denoised = cv2.bilateralFilter(lab_l.astype(np.float32), d=9, sigmaColor=0.055, sigmaSpace=7.0)
    norm = _local_normalize(denoised)
    norm8 = np.clip(norm * 255.0, 0, 255).astype(np.uint8)

    # Dark groove shadows are much more reliable than generic high-frequency texture.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19))
    dark_grooves = cv2.morphologyEx(norm8, cv2.MORPH_BLACKHAT, kernel).astype(np.float32) / 255.0
    edges = cv2.Canny(norm8, 38, 96).astype(np.float32) / 255.0

    small_size = (max(64, norm.shape[1] // 2), max(64, norm.shape[0] // 2))
    small = cv2.resize(norm.astype(np.float32), small_size, interpolation=cv2.INTER_AREA)
    vessel_dark = frangi(small, sigmas=(2, 3, 4), black_ridges=True)
    vessel = cv2.resize(vessel_dark.astype(np.float32), (norm.shape[1], norm.shape[0]), interpolation=cv2.INTER_LINEAR)

    evidence = dark_grooves * 0.62 + edges * dark_grooves * 0.18 + vessel * 0.20
    evidence = cv2.GaussianBlur(evidence.astype(np.float32), (0, 0), 1.1)
    evidence = _normalize_percentile(evidence, mask, 78.0, 99.75)
    evidence[~mask] = 0.0
    keep = _keep_structured_components(
        evidence > 0.28,
        min_area=max(70, int(rgb.shape[1] * rgb.shape[1] * 0.00009)),
        min_aspect=2.0,
    )
    evidence[~keep] = 0.0
    evidence = cv2.GaussianBlur(evidence.astype(np.float32), (0, 0), 0.95)
    evidence[~mask] = 0.0
    evidence = np.clip(evidence * 0.58, 0.0, 1.0)
    return evidence


def _rgb_signed_visual_height(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Estimate a signed visual height field from RGB shading cues.

    It is not measured geometry. It is a fixed-camera visualization prior:
    broad darker sand grooves go below neutral, bright rims/ridges go above it.
    """
    lab_l, _, _ = _lab_channels(rgb)
    denoised = cv2.bilateralFilter(lab_l.astype(np.float32), d=9, sigmaColor=0.055, sigmaSpace=7.0)
    local = _local_normalize(denoised)
    smooth = cv2.GaussianBlur(local.astype(np.float32), (0, 0), 1.2)
    signed = (smooth - 0.5) * 2.0

    # Suppress camera/lighting gradients while keeping broad hand-made grooves.
    low_freq = cv2.GaussianBlur(signed.astype(np.float32), (0, 0), 18.0)
    signed = signed - low_freq * 0.65

    grad = _gradient_mag(local)
    dark_support = denoised < cv2.GaussianBlur(denoised.astype(np.float32), (0, 0), 9.0) - 0.010
    bright_support = denoised > cv2.GaussianBlur(denoised.astype(np.float32), (0, 0), 9.0) + 0.008
    support = (grad > np.percentile(grad[mask], 45.0) if np.any(mask) else grad > 0.0) | dark_support | bright_support
    support = cv2.dilate(support.astype(np.uint8), np.ones((5, 5), dtype=np.uint8), iterations=1).astype(bool)

    signed[~support] *= 0.25
    signed = cv2.GaussianBlur(signed.astype(np.float32), (0, 0), 0.85)
    signed[~mask] = 0.0
    return np.clip(signed, -1.0, 1.0).astype(np.float32)


def _resize_float(image: np.ndarray, size: tuple[int, int], resample: int = Image.Resampling.BILINEAR) -> np.ndarray:
    interpolation = cv2.INTER_LINEAR if resample == Image.Resampling.BILINEAR else cv2.INTER_CUBIC
    return cv2.resize(image.astype(np.float32), size, interpolation=interpolation)


def _resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0


def _read_video_frame(video_path: Path, frame_index_one_based: int, width: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open RGB video: {video_path}")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index_one_based - 1))
        ok, bgr = cap.read()
        if not ok:
            raise RuntimeError(f"Could not read RGB video frame {frame_index_one_based}")
        height = int(round(bgr.shape[0] * (width / bgr.shape[1])))
        if height % 2 == 1:
            height += 1
        bgr = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    finally:
        cap.release()


def _read_video_frames(video_path: Path, indices: list[int], width: int) -> dict[int, np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open RGB video: {video_path}")
    frames: dict[int, np.ndarray] = {}
    try:
        for index in sorted(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, index - 1))
            ok, bgr = cap.read()
            if not ok:
                raise RuntimeError(f"Could not read RGB video frame {index}")
            height = int(round(bgr.shape[0] * (width / bgr.shape[1])))
            if height % 2 == 1:
                height += 1
            bgr = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
            frames[index] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    finally:
        cap.release()
    return frames


def _align_rgb_ecc(rgb: np.ndarray, baseline_norm: np.ndarray) -> tuple[np.ndarray, float]:
    current_norm = _local_normalize(_local_luminance(rgb))
    h, w = baseline_norm.shape
    scale = min(1.0, 480.0 / max(w, h))
    if scale < 1.0:
        small_size = (max(8, int(w * scale)), max(8, int(h * scale)))
        base_small = cv2.resize(baseline_norm.astype(np.float32), small_size, interpolation=cv2.INTER_AREA)
        cur_small = cv2.resize(current_norm.astype(np.float32), small_size, interpolation=cv2.INTER_AREA)
    else:
        base_small = baseline_norm.astype(np.float32)
        cur_small = current_norm.astype(np.float32)

    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
    try:
        score, warp_small = cv2.findTransformECC(base_small, cur_small, warp, cv2.MOTION_AFFINE, criteria, None, 3)
    except cv2.error:
        return rgb, 0.0
    warp_full = warp_small.copy()
    if scale < 1.0:
        warp_full[:, 2] /= scale
    aligned = cv2.warpAffine(
        rgb.astype(np.float32),
        warp_full,
        (w, h),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT,
    )
    return aligned, float(score)


def _parse_frame_range(spec: str) -> list[int] | None:
    if not spec:
        return None
    parts = [part.strip() for part in spec.split(":")]
    if len(parts) not in {2, 3}:
        raise ValueError("--frame-range must be start:end or start:end:stride")
    start = int(parts[0])
    end = int(parts[1])
    stride = int(parts[2]) if len(parts) == 3 else 1
    if stride <= 0:
        raise ValueError("frame range stride must be positive")
    return list(range(start, end + 1, stride))


def _save_gray(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8)).save(path)


def _save_rgb(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8)).save(path)


def _depth_delta_visual(delta_m: np.ndarray, mask: np.ndarray, scale_m: float = 0.025) -> np.ndarray:
    out = np.full(delta_m.shape, 0.5, dtype=np.float32)
    valid = mask & np.isfinite(delta_m)
    encoded = 0.5 + np.clip(-delta_m / scale_m, -1.0, 1.0) * 0.45
    out[valid] = encoded[valid]
    return out


def _overlay(rgb: np.ndarray, evidence: np.ndarray, occlusion: np.ndarray, shadow: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    heat = np.zeros_like(out)
    heat[:, :, 0] = evidence
    heat[:, :, 1] = evidence * 0.75
    out = np.clip(out * (1.0 - evidence[:, :, None] * 0.55) + heat * 0.95, 0, 1)
    out[shadow] = out[shadow] * 0.45 + np.array([0.2, 0.3, 1.0], dtype=np.float32) * 0.55
    out[occlusion] = out[occlusion] * 0.35 + np.array([1.0, 0.08, 0.02], dtype=np.float32) * 0.65
    return out


def _contact_sheet(output_dir: Path, rows: list[dict[str, str]]) -> None:
    labels = ["rgb", "current_hand", "recent_touch", "post_visible", "rgb_change", "occlusion", "persistent", "fused", "overlay"]
    tiles: list[Image.Image] = []
    for row in rows:
        images = [Image.open(output_dir / row[label]).convert("RGB") for label in labels]
        w, h = images[0].size
        tile = Image.new("RGB", (w * len(labels), h + 28), (18, 18, 18))
        draw = ImageDraw.Draw(tile)
        for i, (label, image) in enumerate(zip(labels, images)):
            tile.paste(image, (i * w, 28))
            draw.text((i * w + 5, 7), label, fill=(255, 255, 255))
        draw.text((5, h + 10), f"frame {row['frameIndex']} time {float(row['time']):.2f}s", fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (0, i * tile.height))
    sheet.save(output_dir / "contact_sheet.png")


def run_experiment(
    session_dir: Path,
    output_dir: Path,
    width: int,
    sample_count: int,
    frame_indices: list[int] | None,
    align_ecc: bool,
    baseline_rgb_count: int,
    baseline_depth_count: int,
    contact_sheet_count: int,
) -> None:
    manifest = _load_json(session_dir / "manifest.json")
    frames = _load_v2_frames(session_dir)
    if not frames:
        raise RuntimeError("No v2 frames found")

    streams = manifest.get("v2Streams", {})
    depth_stream = session_dir / streams.get("depthStreamPath", "streams/depth.f32")
    confidence_stream = session_dir / streams.get("confidenceStreamPath", "streams/confidence.bin")
    rgb_video = session_dir / streams.get("rgbVideoPath", "streams/rgb.mp4")
    output_dir.mkdir(parents=True, exist_ok=True)

    fps = 60.0
    if len(frames) > 2:
        duration = max(float(frames[-1].get("rgbPresentationTimeSeconds", 0.0)), float(frames[-1].get("monotonicElapsedSeconds", 0.0)))
        if duration > 0:
            fps = max(1.0, min(120.0, len(frames) / duration))

    depth_baseline_count = min(max(1, baseline_depth_count), len(frames))
    rgb_baseline_count = min(max(1, baseline_rgb_count), len(frames))
    depth_samples = [_read_depth(depth_stream, frame) for frame in frames[:depth_baseline_count]]
    confidence_samples = None
    if confidence_stream.exists():
        confidence_samples = np.stack([_read_confidence(confidence_stream, frame) for frame in frames[:depth_baseline_count]])
    depth_stack = np.stack(depth_samples).astype(np.float32)
    baseline_depth = np.nanmedian(depth_stack, axis=0).astype(np.float32)
    surface_mask = _surface_mask_from_depth(depth_stack, confidence_samples)

    baseline_rgb = _extract_baseline_rgb(rgb_video, output_dir, rgb_baseline_count, fps, width)
    rgb_h, rgb_w = baseline_rgb.shape[:2]
    rgb_size = (rgb_w, rgb_h)
    surface_mask_hi = _resize_mask(surface_mask, rgb_size)
    surface_mask_hi = cv2.erode(surface_mask_hi.astype(np.uint8), np.ones((11, 11), dtype=np.uint8), iterations=1).astype(bool)
    surface_mask_hi = _sand_roi_from_baseline(baseline_rgb, surface_mask_hi)
    baseline_foreground = _rgb_foreground_mask(baseline_rgb)
    baseline_relief_mask = surface_mask_hi & ~baseline_foreground
    _save_rgb(output_dir / "baseline_rgb.png", baseline_rgb)
    _save_gray(output_dir / "surface_mask.png", surface_mask_hi.astype(np.float32))
    _save_gray(output_dir / "baseline_depth.png", _depth_delta_visual(baseline_depth - np.nanmedian(baseline_depth[surface_mask]), surface_mask, scale_m=0.15))
    _save_gray(output_dir / "baseline_foreground_mask.png", baseline_foreground.astype(np.float32))
    baseline_relief = _rgb_relief_evidence(baseline_rgb, baseline_relief_mask)
    baseline_signed_height = _rgb_signed_visual_height(baseline_rgb, baseline_relief_mask)
    _save_gray(output_dir / "baseline_relief.png", baseline_relief)

    baseline_lum = _local_luminance(baseline_rgb)
    baseline_norm = _local_normalize(baseline_lum)
    baseline_grad = _gradient_mag(baseline_norm)
    baseline_lab_l, baseline_lab_a, baseline_lab_b = _lab_channels(baseline_rgb)
    baseline_lab_resid = _local_normalize(baseline_lab_l)

    indices = _frame_indices(len(frames), frame_indices, sample_count)
    rgb_by_index = _read_video_frames(rgb_video, indices, width)
    persistent = np.zeros((rgb_h, rgb_w), dtype=np.float32)
    clean_sum = np.zeros((rgb_h, rgb_w, 3), dtype=np.float32)
    clean_votes = np.zeros((rgb_h, rgb_w), dtype=np.uint16)
    touched_by_hand = np.zeros((rgb_h, rgb_w), dtype=bool)
    accepted_update = np.zeros((rgb_h, rgb_w), dtype=bool)
    last_touch_ordinal = np.full((rgb_h, rgb_w), -100000, dtype=np.int32)
    clear_streak = np.zeros((rgb_h, rgb_w), dtype=np.uint16)
    last_clean_rgb = baseline_rgb.copy()
    rows: list[dict[str, str]] = []
    contact_indices = set(_frame_indices(len(indices), None, min(contact_sheet_count, len(indices))))
    diagnostics: list[dict[str, Any]] = []

    for ordinal, index in enumerate(indices, start=1):
        frame = frames[index - 1]
        rgb = rgb_by_index[index]
        alignment_score = 1.0
        if align_ecc:
            rgb, alignment_score = _align_rgb_ecc(rgb, baseline_norm)
        depth = _read_depth(depth_stream, frame)
        delta = depth - baseline_depth
        occlusion_low = surface_mask & np.isfinite(delta) & (delta < -0.075)
        lidar_change_low = surface_mask & np.isfinite(delta) & (np.abs(delta) > 0.006)
        depth_occlusion_hi = _resize_mask(occlusion_low, rgb_size)
        lidar_delta_hi = _resize_float(_depth_delta_visual(delta, surface_mask), rgb_size)
        lidar_change_hi = _resize_mask(lidar_change_low, rgb_size)
        lum = _local_luminance(rgb)
        norm = _local_normalize(lum)
        grad = _gradient_mag(norm)
        lab_l, lab_a, lab_b = _lab_channels(rgb)
        lab_resid = _local_normalize(lab_l)

        norm_change = np.abs(norm - baseline_norm)
        lab_resid_change = np.abs(lab_resid - baseline_lab_resid)
        grad_change = np.abs(grad - baseline_grad)
        chroma_change = np.hypot(lab_a - baseline_lab_a, lab_b - baseline_lab_b)
        luminance_ratio = lum / np.maximum(baseline_lum, 1e-4)

        raw_change = (
            lab_resid_change * 0.45
            + norm_change * 0.20
            + np.clip(grad_change * 1.4, 0, 1) * 0.25
            + np.clip(chroma_change * 1.8, 0, 1) * 0.10
        )
        raw_change = cv2.GaussianBlur(raw_change.astype(np.float32), (0, 0), 1.25)
        raw_change = np.clip((raw_change - 0.20) / 0.32, 0, 1)

        tool_foreground = _rgb_tool_mask(rgb) & surface_mask_hi & (raw_change > 0.10)
        skin_candidate = _rgb_skin_candidate(rgb, baseline_rgb) & surface_mask_hi & (raw_change > 0.14)
        depth_seed = depth_occlusion_hi & surface_mask_hi
        depth_seed = cv2.morphologyEx(depth_seed.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), dtype=np.uint8)).astype(bool)
        depth_seed = _remove_small_binary(depth_seed, min_area=max(80, int(width * width * 0.00007)))
        near_depth = cv2.dilate(depth_seed.astype(np.uint8), np.ones((27, 27), dtype=np.uint8), iterations=1).astype(bool)
        color_foreground = tool_foreground | (skin_candidate & near_depth)
        color_foreground = _remove_small_binary(color_foreground, min_area=max(80, int(width * width * 0.00007)))
        nearby_color_foreground = cv2.dilate(color_foreground.astype(np.uint8), np.ones((21, 21), dtype=np.uint8), iterations=1).astype(bool)
        depth_motion_occlusion = depth_seed & (nearby_color_foreground | (raw_change > 0.34))
        depth_motion_occlusion = _remove_small_binary(depth_motion_occlusion, min_area=max(90, int(width * width * 0.00008)))
        current_hand = (color_foreground | depth_motion_occlusion) & surface_mask_hi
        current_hand = cv2.morphologyEx(current_hand.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8)).astype(bool)
        current_hand = _remove_small_binary(current_hand, min_area=max(100, int(width * width * 0.00009)))
        occlusion_hi = current_hand
        hand_trace = cv2.dilate(current_hand.astype(np.uint8), np.ones((9, 9), dtype=np.uint8), iterations=1).astype(bool)
        hand_trace &= surface_mask_hi

        # The visible hand/tool silhouette is not the same as the sand contact
        # area. Keep the full silhouette for occlusion, but only allow future
        # persistent updates near small, high-evidence contact bands.
        close_core_low = surface_mask & np.isfinite(delta) & (delta < -0.16)
        close_core_hi = _resize_mask(close_core_low, rgb_size) & current_hand
        close_core_hi = cv2.morphologyEx(close_core_hi.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), dtype=np.uint8)).astype(bool)
        close_core_hi = _remove_small_binary(close_core_hi, min_area=max(50, int(width * width * 0.000045)))
        contact_seed = (tool_foreground | close_core_hi) & surface_mask_hi
        contact_seed &= (raw_change > 0.24) | lidar_change_hi
        contact_trace = cv2.dilate(contact_seed.astype(np.uint8), np.ones((9, 9), dtype=np.uint8), iterations=1).astype(bool)
        contact_trace &= hand_trace
        contact_trace = _remove_small_binary(contact_trace, min_area=max(60, int(width * width * 0.00005)))

        touched_by_hand |= contact_trace
        last_touch_ordinal[contact_trace] = ordinal
        clean_sum[hand_trace] = 0.0
        clean_votes[hand_trace] = 0
        clear_streak[occlusion_hi] = 0
        clear_streak[~occlusion_hi] = np.minimum(clear_streak[~occlusion_hi] + 1, np.iinfo(np.uint16).max)

        recently_touched = (ordinal - last_touch_ordinal) <= 36

        shadow = (luminance_ratio < 0.78) & (chroma_change < 0.075) & (lab_resid_change < 0.18) & ~lidar_change_hi
        shadow = cv2.morphologyEx(shadow.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)).astype(bool)
        shadow = cv2.dilate(shadow.astype(np.uint8), np.ones((5, 5), dtype=np.uint8), iterations=1).astype(bool)
        valid = surface_mask_hi & ~occlusion_hi & ~shadow
        post_hand_visible = valid & recently_touched & (clear_streak >= 5)

        clean_rgb = _inpaint_foreground_from_baseline(rgb, baseline_rgb, occlusion_hi)
        observe = post_hand_visible & (raw_change > 0.08)
        clean_sum[observe] += clean_rgb[observe]
        clean_votes[observe] = np.minimum(clean_votes[observe] + 1, np.iinfo(np.uint16).max)

        stable_observed = clean_votes >= 3
        observed_rgb = baseline_rgb.copy()
        observed_rgb[stable_observed] = clean_sum[stable_observed] / clean_votes[stable_observed, None].astype(np.float32)
        observed_lum = _local_luminance(observed_rgb)
        observed_norm = _local_normalize(observed_lum)
        observed_grad = _gradient_mag(observed_norm)
        observed_lab_l, observed_lab_a, observed_lab_b = _lab_channels(observed_rgb)
        observed_lab_resid = _local_normalize(observed_lab_l)
        stable_change = (
            np.abs(observed_lab_resid - baseline_lab_resid) * 0.50
            + np.abs(observed_norm - baseline_norm) * 0.18
            + np.clip(np.abs(observed_grad - baseline_grad) * 1.4, 0, 1) * 0.22
            + np.clip(np.hypot(observed_lab_a - baseline_lab_a, observed_lab_b - baseline_lab_b) * 1.8, 0, 1) * 0.10
        )
        stable_change = cv2.GaussianBlur(stable_change.astype(np.float32), (0, 0), 1.0)
        stable_change = np.clip((stable_change - 0.18) / 0.32, 0, 1)
        candidate = stable_change
        candidate[~stable_observed | ~touched_by_hand | ~surface_mask_hi] = 0.0
        candidate = _keep_groove_scale_evidence(
            candidate,
            threshold=0.27,
            min_area=max(120, int(width * width * 0.00013)),
            min_aspect=1.7,
        )
        persistent = cv2.GaussianBlur(candidate.astype(np.float32), (0, 0), 0.9)
        accepted_update = persistent > 0.08
        persistent[~accepted_update] = 0.0
        if np.mean(occlusion_hi & surface_mask_hi) < 0.08:
            last_clean_rgb = clean_rgb

        rgb_detail = (persistent - 0.35) / 0.65
        rgb_detail = np.clip(rgb_detail, 0, 1)
        clean_signed_height = baseline_signed_height.copy()
        clean_signed_height[occlusion_hi | shadow] = 0.0
        # Raw per-frame LiDAR deltas include hands/tools and low-res occlusion
        # artifacts. For the fixed-camera visualization, use LiDAR for gating
        # and occlusion only; draw visible relief from RGB-supported evidence.
        fused = np.clip(0.5 + clean_signed_height * 0.20 + rgb_detail * 0.20, 0, 1)
        fused[~surface_mask_hi | occlusion_hi | shadow] = 0.5
        overlay = _overlay(rgb, persistent, occlusion_hi, shadow)

        stem = f"frame_{index:06d}"
        files = {
            "rgb": f"{stem}_rgb.png",
            "baseline_relief": f"{stem}_baseline_relief.png",
            "touched": f"{stem}_touched_by_hand.png",
            "current_hand": f"{stem}_current_hand.png",
            "recent_touch": f"{stem}_recent_touch.png",
            "post_visible": f"{stem}_post_hand_visible.png",
            "rgb_change": f"{stem}_rgb_change.png",
            "shadow": f"{stem}_shadow.png",
            "occlusion": f"{stem}_occlusion.png",
            "lidar_delta": f"{stem}_lidar_delta.png",
            "persistent": f"{stem}_persistent.png",
            "fused": f"{stem}_fused_displacement.png",
            "overlay": f"{stem}_overlay.png",
        }
        row = {**files, "frameIndex": str(index), "time": str(frame.get("monotonicElapsedSeconds", 0.0))}
        if ordinal in contact_indices or ordinal == len(indices):
            _save_rgb(output_dir / files["rgb"], rgb)
            _save_rgb(output_dir / f"{stem}_clean_rgb.png", clean_rgb)
            _save_gray(output_dir / files["baseline_relief"], baseline_relief)
            _save_gray(output_dir / files["rgb_change"], raw_change)
            _save_gray(output_dir / files["shadow"], shadow.astype(np.float32))
            _save_gray(output_dir / files["occlusion"], occlusion_hi.astype(np.float32))
            _save_gray(output_dir / files["lidar_delta"], lidar_delta_hi)
            _save_gray(output_dir / files["persistent"], persistent)
            _save_gray(output_dir / files["fused"], fused)
            _save_rgb(output_dir / files["overlay"], overlay)
            _save_gray(output_dir / files["touched"], touched_by_hand.astype(np.float32))
            _save_gray(output_dir / files["current_hand"], current_hand.astype(np.float32))
            _save_gray(output_dir / files["recent_touch"], recently_touched.astype(np.float32))
            _save_gray(output_dir / files["post_visible"], post_hand_visible.astype(np.float32))
            row["clean_rgb"] = f"{stem}_clean_rgb.png"
            row["touched_by_hand"] = files["touched"]
            row["current_hand"] = files["current_hand"]
            row["recent_touch"] = files["recent_touch"]
            row["post_hand_visible"] = files["post_visible"]
            rows.append(row)
        diagnostics.append({
            "frameIndex": index,
            "time": float(frame.get("monotonicElapsedSeconds", 0.0)),
            "candidateMean": float(candidate[valid].mean()) if np.any(valid) else 0.0,
            "persistentP95": float(np.percentile(persistent[surface_mask_hi], 95)) if np.any(surface_mask_hi) else 0.0,
            "baselineReliefP95": float(np.percentile(baseline_relief[surface_mask_hi], 95)) if np.any(surface_mask_hi) else 0.0,
            "occlusionPixels": int(occlusion_hi.sum()),
            "currentHandPixels": int(current_hand.sum()),
            "shadowPixels": int(shadow.sum()),
            "touchedByHandPixels": int(touched_by_hand.sum()),
            "recentlyTouchedPixels": int(recently_touched.sum()),
            "postHandVisiblePixels": int(post_hand_visible.sum()),
            "acceptedUpdatePixels": int(accepted_update.sum()),
            "evidenceVotePixels": int((clean_votes >= 3).sum()),
            "alignmentScore": alignment_score,
            "lidarDeltaMmP95Abs": float(np.percentile(np.abs(delta[surface_mask & np.isfinite(delta)]) * 1000.0, 95)) if np.any(surface_mask & np.isfinite(delta)) else 0.0,
        })

    _save_rgb(output_dir / "last_clean_rgb.png", last_clean_rgb)

    _contact_sheet(output_dir, rows)
    _save_json(output_dir / "experiment_manifest.json", {
        "sourceSession": str(session_dir),
        "method": "fixed_camera_lidar_grounded_rgb_persistent_change_v1",
        "rgbWidth": width,
        "baselineRgbFrames": rgb_baseline_count,
        "baselineDepthFrames": depth_baseline_count,
        "sampledFrames": indices,
        "contactSheetFrames": [int(row["frameIndex"]) for row in rows],
        "depthFrameSize": {"width": int(frames[0]["width"]), "height": int(frames[0]["height"])},
        "rgbCameraSize": {
            "width": int(frames[0].get("cameraImageResolutionWidth", 0)),
            "height": int(frames[0].get("cameraImageResolutionHeight", 0)),
        },
        "notes": [
            "LiDAR delta is treated as low-frequency geometry and occlusion evidence.",
            "RGB local-normalized luminance/gradient/chromaticity change is treated as high-frequency sand evidence.",
            "Fused displacement is visual/evidence displacement, not measured true high-resolution depth.",
            "baseline_relief extracts pre-existing grooves from the baseline RGB so the latest session can start with visible sand detail.",
            "Full hand/tool silhouettes are used only for occlusion; persistent updates are limited to conservative contact traces near high-evidence hand/tool rims.",
        ],
        "alignEcc": align_ecc,
        "diagnostics": diagnostics,
        "rows": rows,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--sample-count", type=int, default=14)
    parser.add_argument("--frames", type=str, default="")
    parser.add_argument("--frame-range", type=str, default="", help="Continuous frame range, e.g. 1:300:1. Overrides --frames.")
    parser.add_argument("--align-ecc", action="store_true", help="Use ECC affine alignment before differencing. Off by default for fixed cameras.")
    parser.add_argument("--baseline-rgb-count", type=int, default=10, help="Number of initial RGB frames used for visual baseline.")
    parser.add_argument("--baseline-depth-count", type=int, default=60, help="Number of initial LiDAR frames used for depth baseline median.")
    parser.add_argument("--contact-sheet-count", type=int, default=14, help="Number of processed frames to include in contact_sheet.png.")
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    output_dir = args.output
    if output_dir is None:
        output_dir = session_dir.parents[1] / "experiments" / f"{session_dir.name}_fixed_camera_change"
    frame_indices = _parse_frame_range(args.frame_range)
    if frame_indices is None:
        frame_indices = [int(part.strip()) for part in args.frames.split(",") if part.strip()] or None
    run_experiment(
        session_dir,
        output_dir.resolve(),
        args.width,
        args.sample_count,
        frame_indices,
        args.align_ecc,
        args.baseline_rgb_count,
        args.baseline_depth_count,
        args.contact_sheet_count,
    )
    print(output_dir.resolve())


if __name__ == "__main__":
    main()
