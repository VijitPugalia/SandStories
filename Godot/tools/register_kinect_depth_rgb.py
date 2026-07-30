#!/usr/bin/env python3
"""Register Kinect raw depth to RGB and export review PLYs.

The libfreenect recording gives RGB and depth frames with the same nominal
640x480 size, but they are not the same camera. This tool estimates a 2D
depth-to-RGB warp from visual evidence in the sand surface, then writes depth
maps and colored point clouds in RGB image coordinates for MeshLab review.
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


KINECT_FX = 594.21
KINECT_FY = 594.21
KINECT_CX = 339.5
KINECT_CY = 242.7


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_token(handle) -> bytes:
    token = b""
    while True:
        char = handle.read(1)
        if not char:
            return token
        if char == b"#":
            handle.readline()
            continue
        if char.isspace():
            if token:
                return token
            continue
        token += char


def _read_ppm(path: Path) -> np.ndarray:
    with path.open("rb") as handle:
        magic = _read_token(handle)
        if magic != b"P6":
            raise ValueError(f"Expected P6 PPM: {path}")
        width = int(_read_token(handle))
        height = int(_read_token(handle))
        max_value = int(_read_token(handle))
        if max_value != 255:
            raise ValueError(f"Unsupported PPM max value {max_value}: {path}")
        data = np.frombuffer(handle.read(width * height * 3), dtype=np.uint8)
    return data.reshape((height, width, 3))


def _read_fakenect_depth(path: Path, *, byteswap: bool) -> np.ndarray:
    depth = np.asarray(Image.open(path), dtype=np.uint16)
    if byteswap:
        depth = depth.byteswap()
    return depth.astype(np.float32)


def _raw_to_meters(raw: np.ndarray) -> np.ndarray:
    return 1.0 / (raw * -0.0030711016 + 3.3309495161)


def _pair_frames(record_dir: Path) -> list[tuple[int, Path, Path]]:
    rgb_paths = sorted(record_dir.glob("r-*.ppm"))
    depth_paths = sorted(record_dir.glob("d-*.pgm"))
    return [(index, rgb_paths[index], depth_paths[index]) for index in range(min(len(rgb_paths), len(depth_paths)))]


def _normalize_percentile(image: np.ndarray, mask: np.ndarray | None = None, lo: float = 2.0, hi: float = 98.0) -> np.ndarray:
    values = image[mask] if mask is not None and np.any(mask) else image.reshape(-1)
    if values.size == 0:
        return np.zeros_like(image, dtype=np.float32)
    p0 = float(np.percentile(values, lo))
    p1 = float(np.percentile(values, hi))
    if p1 <= p0:
        return np.zeros_like(image, dtype=np.float32)
    return np.clip((image - p0) / (p1 - p0), 0.0, 1.0).astype(np.float32)


def _gradient(image: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return np.hypot(gx, gy).astype(np.float32)


def _local_luminance(rgb: np.ndarray) -> np.ndarray:
    rgb_f = rgb.astype(np.float32) / 255.0
    lum = rgb_f[:, :, 0] * 0.299 + rgb_f[:, :, 1] * 0.587 + rgb_f[:, :, 2] * 0.114
    mean = cv2.GaussianBlur(lum, (0, 0), 12.0)
    sq = cv2.GaussianBlur(lum * lum, (0, 0), 12.0)
    std = np.sqrt(np.maximum(sq - mean * mean, 1e-5))
    return (np.clip((lum - mean) / (std + 1e-4), -3.0, 3.0) / 6.0 + 0.5).astype(np.float32)


def _surface_mask(rgb: np.ndarray, raw_depth: np.ndarray) -> np.ndarray:
    rgb_f = rgb.astype(np.float32) / 255.0
    valid = (raw_depth > 0) & (raw_depth < 2047)
    mx = rgb_f.max(axis=2)
    mn = rgb_f.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    lum = rgb_f[:, :, 0] * 0.299 + rgb_f[:, :, 1] * 0.587 + rgb_f[:, :, 2] * 0.114
    blue_bias = rgb_f[:, :, 2] - np.maximum(rgb_f[:, :, 0], rgb_f[:, :, 1])
    sand = valid & (sat < 0.50) & (lum > 0.12) & (lum < 0.94) & (blue_bias < 0.24)
    sand = ndimage.binary_opening(sand, structure=np.ones((3, 3)))
    sand = ndimage.binary_closing(sand, structure=np.ones((19, 19)))
    sand = ndimage.binary_fill_holes(sand)
    labels, count = ndimage.label(sand)
    if count:
        h, w = sand.shape
        center = labels[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        if ids.size:
            sand = labels == ids[int(np.argmax(freq))]
    sand = ndimage.binary_erosion(sand, structure=np.ones((7, 7)), iterations=1)
    return sand.astype(bool)


def _rgb_sand_mask(rgb: np.ndarray) -> np.ndarray:
    rgb_f = rgb.astype(np.float32) / 255.0
    mx = rgb_f.max(axis=2)
    mn = rgb_f.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    lum = rgb_f[:, :, 0] * 0.299 + rgb_f[:, :, 1] * 0.587 + rgb_f[:, :, 2] * 0.114
    blue_bias = rgb_f[:, :, 2] - np.maximum(rgb_f[:, :, 0], rgb_f[:, :, 1])
    red_bias = rgb_f[:, :, 0] - rgb_f[:, :, 2]
    mask = (sat < 0.55) & (lum > 0.10) & (lum < 0.94) & (blue_bias < 0.20) & (red_bias < 0.55)
    mask = ndimage.binary_opening(mask, structure=np.ones((5, 5)))
    mask = ndimage.binary_closing(mask, structure=np.ones((23, 23)))
    mask = ndimage.binary_fill_holes(mask)
    labels, count = ndimage.label(mask)
    if count:
        h, w = mask.shape
        center = labels[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        keep = ids[int(np.argmax(freq))] if ids.size else int(np.argmax(ndimage.sum(mask, labels, index=np.arange(1, count + 1))) + 1)
        mask = labels == keep
    return ndimage.binary_erosion(mask, structure=np.ones((5, 5)), iterations=1).astype(bool)


def _depth_surface_mask(raw_depth: np.ndarray) -> np.ndarray:
    valid = (raw_depth > 0) & (raw_depth < 2047)
    labels, count = ndimage.label(valid)
    if count:
        h, w = valid.shape
        center = labels[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        keep = ids[int(np.argmax(freq))] if ids.size else int(np.argmax(ndimage.sum(valid, labels, index=np.arange(1, count + 1))) + 1)
        valid = labels == keep
    valid = ndimage.binary_closing(valid, structure=np.ones((15, 15)))
    valid = ndimage.binary_fill_holes(valid)
    return ndimage.binary_erosion(valid, structure=np.ones((7, 7)), iterations=1).astype(bool)


def _mask_boundary(mask: np.ndarray, thickness: int = 3) -> np.ndarray:
    mask_u8 = mask.astype(np.uint8)
    edge = cv2.morphologyEx(mask_u8, cv2.MORPH_GRADIENT, np.ones((thickness, thickness), dtype=np.uint8)) > 0
    return edge


def _mask_boundary_overlay(rgb: np.ndarray, rgb_mask: np.ndarray, depth_mask_registered: np.ndarray) -> np.ndarray:
    out = rgb.astype(np.float32) * 0.50
    rgb_edge = _mask_boundary(rgb_mask, thickness=5)
    depth_edge = _mask_boundary(depth_mask_registered, thickness=5)
    both = rgb_edge & depth_edge
    rgb_only = rgb_edge & ~depth_edge
    depth_only = depth_edge & ~rgb_edge
    out[rgb_only] = np.array([20, 105, 255], dtype=np.float32)
    out[depth_only] = np.array([255, 25, 10], dtype=np.float32)
    out[both] = np.array([20, 255, 60], dtype=np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    intersection = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    return float(intersection / union) if union else 0.0


def _depth_residual_metric(raw_depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
    valid = mask & (raw_depth > 0) & (raw_depth < 2047)
    meters = np.zeros_like(raw_depth, dtype=np.float32)
    meters[valid] = _raw_to_meters(raw_depth[valid])
    filled = meters.copy()
    if np.any(valid):
        median = float(np.median(meters[valid]))
        filled[~valid] = median
    low = cv2.GaussianBlur(filled, (0, 0), 10.0)
    residual = low - filled
    residual[~valid] = 0.0
    return residual.astype(np.float32)


def _prep_registration_images(rgb: np.ndarray, raw_depth: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb_edge = _normalize_percentile(_gradient(_local_luminance(rgb)), mask, 55.0, 99.7)
    residual = _depth_residual_metric(raw_depth, mask)
    depth_edge = _normalize_percentile(_gradient(residual), mask, 55.0, 99.7)
    weight = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 3.0)
    rgb_edge = (rgb_edge * weight).astype(np.float32)
    depth_edge = (depth_edge * weight).astype(np.float32)
    return rgb_edge, depth_edge, weight


def _translation_score(template: np.ndarray, moving: np.ndarray, mask: np.ndarray, dx: int, dy: int) -> float:
    h, w = template.shape
    x0 = max(0, dx)
    x1 = min(w, w + dx)
    y0 = max(0, dy)
    y1 = min(h, h + dy)
    if x1 <= x0 or y1 <= y0:
        return -1.0
    tx0 = x0
    tx1 = x1
    ty0 = y0
    ty1 = y1
    mx0 = x0 - dx
    mx1 = x1 - dx
    my0 = y0 - dy
    my1 = y1 - dy
    valid = mask[ty0:ty1, tx0:tx1] > 0.2
    if int(valid.sum()) < 500:
        return -1.0
    a = template[ty0:ty1, tx0:tx1][valid]
    b = moving[my0:my1, mx0:mx1][valid]
    a = a - float(a.mean())
    b = b - float(b.mean())
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 1e-6 else -1.0


def _initial_translation(template: np.ndarray, moving: np.ndarray, mask: np.ndarray, max_shift: int) -> tuple[int, int, float]:
    best = (0, 0, -1.0)
    for dy in range(-max_shift, max_shift + 1, 2):
        for dx in range(-max_shift, max_shift + 1, 2):
            score = _translation_score(template, moving, mask, dx, dy)
            if score > best[2]:
                best = (dx, dy, score)
    return best


def _estimate_warp(rgb: np.ndarray, raw_depth: np.ndarray, motion: str, max_shift: int) -> dict[str, Any]:
    mask = _surface_mask(rgb, raw_depth)
    rgb_edge, depth_edge, weight = _prep_registration_images(rgb, raw_depth, mask)
    dx, dy, score = _initial_translation(rgb_edge, depth_edge, weight, max_shift=max_shift)
    if motion == "translation":
        warp = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
        return {"warp": warp, "ecc": score, "mask": mask, "rgbEdge": rgb_edge, "depthEdge": depth_edge, "initial": [dx, dy, score]}

    motion_type = cv2.MOTION_EUCLIDEAN if motion == "euclidean" else cv2.MOTION_AFFINE
    warp = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6)
    try:
        ecc, warp = cv2.findTransformECC(
            rgb_edge,
            depth_edge,
            warp,
            motion_type,
            criteria,
            inputMask=(weight > 0.5).astype(np.uint8) * 255,
            gaussFiltSize=5,
        )
    except cv2.error:
        ecc = score
    return {"warp": warp.astype(np.float32), "ecc": float(ecc), "mask": mask, "rgbEdge": rgb_edge, "depthEdge": depth_edge, "initial": [dx, dy, score]}


def _manual_warp(dx: float, dy: float, scale: float) -> np.ndarray:
    cx = KINECT_CX
    cy = KINECT_CY
    return np.array([
        [scale, 0.0, dx + cx * (1.0 - scale)],
        [0.0, scale, dy + cy * (1.0 - scale)],
    ], dtype=np.float32)


def _score_registered_edges(rgb_edge: np.ndarray, depth_edge_registered: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    valid = mask.astype(bool)
    if int(valid.sum()) < 500:
        return {"corr": 0.0, "iou": 0.0, "matched": 0.0}
    a = rgb_edge[valid].reshape(-1)
    b = depth_edge_registered[valid].reshape(-1)
    corr = 0.0
    if a.size > 3 and float(a.std()) > 1e-6 and float(b.std()) > 1e-6:
        corr = float(np.corrcoef(a, b)[0, 1])
    rgb_bin = np.zeros_like(valid)
    dep_bin = np.zeros_like(valid)
    rgb_bin[valid] = rgb_edge[valid] >= float(np.percentile(rgb_edge[valid], 94.5))
    dep_bin[valid] = depth_edge_registered[valid] >= float(np.percentile(depth_edge_registered[valid], 94.5))
    intersection = int(np.count_nonzero(rgb_bin & dep_bin))
    union = int(np.count_nonzero(rgb_bin | dep_bin))
    rgb_count = int(np.count_nonzero(rgb_bin))
    return {"corr": corr, "iou": float(intersection / union) if union else 0.0, "matched": float(intersection / max(1, rgb_count))}


def _warp_to_rgb(image: np.ndarray, warp: np.ndarray, size: tuple[int, int], interpolation: int, border: float = 0.0) -> np.ndarray:
    return cv2.warpAffine(
        image,
        warp,
        size,
        flags=interpolation | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def _edge_overlay(rgb: np.ndarray, rgb_edge: np.ndarray, depth_edge_registered: np.ndarray, mask: np.ndarray) -> np.ndarray:
    rgb_f = rgb.astype(np.float32) / 255.0
    out = rgb_f * 0.52
    valid = mask.astype(bool)
    rgb_bin = rgb_edge >= np.percentile(rgb_edge[valid], 94.5) if np.any(valid) else rgb_edge > 0.8
    dep_bin = depth_edge_registered >= np.percentile(depth_edge_registered[valid], 94.5) if np.any(valid) else depth_edge_registered > 0.8
    both = rgb_bin & dep_bin & valid
    depth_only = dep_bin & ~rgb_bin & valid
    rgb_only = rgb_bin & ~dep_bin & valid
    out[rgb_only] = np.array([0.05, 0.35, 1.0], dtype=np.float32)
    out[depth_only] = np.array([1.0, 0.08, 0.02], dtype=np.float32)
    out[both] = np.array([0.04, 1.0, 0.16], dtype=np.float32)
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def _write_ply(path: Path, rgb: np.ndarray, metric_depth_rgb: np.ndarray, valid: np.ndarray, stride: int) -> int:
    h, w = metric_depth_rgb.shape
    vertices: list[tuple[float, float, float, int, int, int]] = []
    for v in range(0, h, stride):
        for u in range(0, w, stride):
            if not valid[v, u]:
                continue
            z = float(metric_depth_rgb[v, u])
            if not (0.25 <= z <= 1.5):
                continue
            x = (u - KINECT_CX) * z / KINECT_FX
            y = (v - KINECT_CY) * z / KINECT_FY
            r, g, b = rgb[v, u]
            vertices.append((x, y, z, int(r), int(g), int(b)))
    with path.open("w", encoding="utf-8") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(vertices)}\n")
        handle.write("property float x\nproperty float y\nproperty float z\n")
        handle.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        handle.write("end_header\n")
        for vertex in vertices:
            handle.write(f"{vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f} {vertex[3]} {vertex[4]} {vertex[5]}\n")
    return len(vertices)


def _write_contact_sheet(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    labels = ["rgb", "before", "after", "registered_depth", "overlay"]
    tiles: list[Image.Image] = []
    for row in rows:
        images = [Image.open(output_dir / row[label]).convert("RGB") for label in labels]
        w, h = images[0].size
        tile = Image.new("RGB", (w * len(images), h + 40), (18, 18, 18))
        draw = ImageDraw.Draw(tile)
        for i, (label, image) in enumerate(zip(labels, images)):
            tile.paste(image, (i * w, 24))
            draw.text((i * w + 5, 6), label, fill=(255, 255, 255))
        draw.text((5, h + 25), row["caption"], fill=(255, 255, 255))
        tiles.append(tile)
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (0, i * tile.height))
    sheet.save(output_dir / "registration_contact_sheet.png")


def register_record(
    record_dir: Path,
    output_dir: Path,
    *,
    stride: int,
    max_frames: int,
    byteswap: bool,
    motion: str,
    max_shift: int,
    ply_stride: int,
    manual_translation: tuple[float, float] | None,
    manual_scale: float,
) -> None:
    pairs = _pair_frames(record_dir)
    if not pairs:
        raise RuntimeError(f"No RGB/depth pairs found in {record_dir}")
    selected = pairs[:: max(1, stride)][:max_frames]
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("*.png"):
        old.unlink()
    for old in output_dir.glob("*.ply"):
        old.unlink()

    first_rgb = _read_ppm(selected[0][1])
    first_depth = _read_fakenect_depth(selected[0][2], byteswap=byteswap)
    estimate = _estimate_warp(first_rgb, first_depth, motion=motion, max_shift=max_shift)
    warp = _manual_warp(manual_translation[0], manual_translation[1], manual_scale) if manual_translation else estimate["warp"]
    h, w = first_depth.shape
    rows: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []

    for out_index, (source_index, rgb_path, depth_path) in enumerate(selected, start=1):
        rgb = _read_ppm(rgb_path)
        raw_depth = _read_fakenect_depth(depth_path, byteswap=byteswap)
        mask = _surface_mask(rgb, raw_depth)
        rgb_edge, depth_edge, _ = _prep_registration_images(rgb, raw_depth, mask)
        depth_edge_registered = _warp_to_rgb(depth_edge, warp, (w, h), cv2.INTER_LINEAR)
        mask_registered = _warp_to_rgb(mask.astype(np.float32), warp, (w, h), cv2.INTER_NEAREST) > 0.5
        edge_score = _score_registered_edges(rgb_edge, depth_edge_registered, mask_registered)
        valid_depth = (raw_depth > 0) & (raw_depth < 2047)
        metric = np.zeros_like(raw_depth, dtype=np.float32)
        metric[valid_depth] = _raw_to_meters(raw_depth[valid_depth])
        metric_registered = _warp_to_rgb(metric, warp, (w, h), cv2.INTER_LINEAR)
        valid_registered = (_warp_to_rgb(valid_depth.astype(np.float32), warp, (w, h), cv2.INTER_NEAREST) > 0.5) & mask_registered

        depth_vis = _normalize_percentile(metric_registered, valid_registered, 2.0, 98.0)
        depth_vis = np.where(valid_registered, 1.0 - depth_vis, 0.0)
        before_overlay = _edge_overlay(rgb, rgb_edge, depth_edge, mask)
        after_overlay = _edge_overlay(rgb, rgb_edge, depth_edge_registered, mask_registered)

        stem = f"{out_index:06d}"
        rgb_name = f"rgb_{stem}.png"
        before_name = f"edge_overlay_before_{stem}.png"
        after_name = f"edge_overlay_after_{stem}.png"
        registered_name = f"registered_depth_{stem}.png"
        overlay_name = f"registered_depth_on_rgb_{stem}.png"
        ply_name = f"registered_depth_rgb_{stem}.ply"

        Image.fromarray(rgb).save(output_dir / rgb_name)
        Image.fromarray(before_overlay).save(output_dir / before_name)
        Image.fromarray(after_overlay).save(output_dir / after_name)
        Image.fromarray(np.clip(depth_vis * 255.0, 0, 255).astype(np.uint8)).save(output_dir / registered_name)
        overlay = (rgb.astype(np.float32) * 0.58 + np.dstack([depth_vis * 255.0, depth_vis * 160.0, np.zeros_like(depth_vis)]) * 0.42)
        Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8)).save(output_dir / overlay_name)
        vertices = _write_ply(output_dir / ply_name, rgb, metric_registered, valid_registered, ply_stride)

        caption = f"frame {source_index}: vertices {vertices}, corr {edge_score['corr']:.3f}, iou {edge_score['iou']:.3f}, warp {warp.reshape(-1).round(4).tolist()}"
        rows.append({"rgb": rgb_name, "before": before_name, "after": after_name, "registered_depth": registered_name, "overlay": overlay_name, "caption": caption})
        frames.append({
            "sourceIndex": source_index,
            "sourceRgb": rgb_path.name,
            "sourceDepth": depth_path.name,
            "rgb": rgb_name,
            "edgeOverlayBefore": before_name,
            "edgeOverlayAfter": after_name,
            "registeredDepth": registered_name,
            "registeredDepthOnRgb": overlay_name,
            "pointCloud": ply_name,
            "vertices": vertices,
            "edgeScore": edge_score,
        })

    _write_contact_sheet(output_dir, rows)
    _save_json(output_dir / "registration_manifest.json", {
        "sourceSession": str(record_dir),
        "method": "depth_edges_to_rgb_edges_ecc_affine",
        "motion": motion,
        "byteswapApplied": byteswap,
        "initialTranslationDxDyScore": estimate["initial"],
        "ecc": estimate["ecc"],
        "manualTranslationDxDy": list(manual_translation) if manual_translation else None,
        "manualScale": manual_scale if manual_translation else None,
        "warpDepthToRgb": warp.tolist(),
        "warpUsage": "OpenCV warpAffine with WARP_INVERSE_MAP; maps raw depth images into RGB pixel coordinates.",
        "plyProjection": {"fx": KINECT_FX, "fy": KINECT_FY, "cx": KINECT_CX, "cy": KINECT_CY, "note": "Uses RGB pixel coordinates after registration for visual MeshLab review."},
        "frames": frames,
        "contactSheet": "registration_contact_sheet.png",
    })
    print(output_dir.resolve())


def preview_grid(
    record_dir: Path,
    output_dir: Path,
    *,
    byteswap: bool,
    dx_values: list[float],
    dy_values: list[float],
    scale_values: list[float],
    grid_mode: str,
) -> None:
    pairs = _pair_frames(record_dir)
    if not pairs:
        raise RuntimeError(f"No RGB/depth pairs found in {record_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("grid_*.png"):
        old.unlink()
    source_index, rgb_path, depth_path = pairs[0]
    rgb = _read_ppm(rgb_path)
    raw_depth = _read_fakenect_depth(depth_path, byteswap=byteswap)
    h, w = raw_depth.shape
    mask = _surface_mask(rgb, raw_depth)
    rgb_edge, depth_edge, _ = _prep_registration_images(rgb, raw_depth, mask)
    rgb_mask = _rgb_sand_mask(rgb)
    depth_mask = _depth_surface_mask(raw_depth)
    candidates: list[dict[str, Any]] = []
    thumb_w = 320
    thumb_h = 240
    for scale in scale_values:
        tiles: list[Image.Image] = []
        for dy in dy_values:
            row_tiles: list[Image.Image] = []
            for dx in dx_values:
                warp = _manual_warp(dx, dy, scale)
                if grid_mode == "mask":
                    depth_mask_registered = _warp_to_rgb(depth_mask.astype(np.float32), warp, (w, h), cv2.INTER_NEAREST) > 0.5
                    overlay = _mask_boundary_overlay(rgb, rgb_mask, depth_mask_registered)
                    score = {
                        "corr": _mask_iou(_mask_boundary(rgb_mask, thickness=7), _mask_boundary(depth_mask_registered, thickness=7)),
                        "iou": _mask_iou(rgb_mask, depth_mask_registered),
                        "matched": _mask_iou(_mask_boundary(rgb_mask, thickness=13), _mask_boundary(depth_mask_registered, thickness=13)),
                    }
                else:
                    depth_edge_registered = _warp_to_rgb(depth_edge, warp, (w, h), cv2.INTER_LINEAR)
                    mask_registered = _warp_to_rgb(mask.astype(np.float32), warp, (w, h), cv2.INTER_NEAREST) > 0.5
                    score = _score_registered_edges(rgb_edge, depth_edge_registered, mask_registered)
                    overlay = _edge_overlay(rgb, rgb_edge, depth_edge_registered, mask_registered)
                img = Image.fromarray(overlay).resize((thumb_w, thumb_h), Image.Resampling.BILINEAR)
                draw = ImageDraw.Draw(img)
                draw.rectangle((0, 0, thumb_w, 28), fill=(0, 0, 0))
                draw.text((5, 6), f"dx {dx:g} dy {dy:g} s {scale:g} c {score['corr']:.3f} i {score['iou']:.3f}", fill=(255, 255, 255))
                row_tiles.append(img)
                candidates.append({"dx": dx, "dy": dy, "scale": scale, **score})
            row = Image.new("RGB", (thumb_w * len(row_tiles), thumb_h), (0, 0, 0))
            for i, img in enumerate(row_tiles):
                row.paste(img, (i * thumb_w, 0))
            tiles.append(row)
        sheet = Image.new("RGB", (tiles[0].width, thumb_h * len(tiles)), (0, 0, 0))
        for i, row in enumerate(tiles):
            sheet.paste(row, (0, i * thumb_h))
        sheet.save(output_dir / f"grid_scale_{scale:.4f}.png")
    candidates.sort(key=lambda item: (item["corr"], item["iou"], item["matched"]), reverse=True)
    _save_json(output_dir / "grid_candidates.json", {"sourceIndex": source_index, "gridMode": grid_mode, "top": candidates[:30], "all": candidates})
    print(output_dir.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stride", type=int, default=9)
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--ply-stride", type=int, default=2)
    parser.add_argument("--motion", choices=["translation", "euclidean", "affine"], default="affine")
    parser.add_argument("--max-shift", type=int, default=42)
    parser.add_argument("--manual-translation", nargs=2, type=float, metavar=("DX", "DY"))
    parser.add_argument("--manual-scale", type=float, default=1.0)
    parser.add_argument("--grid-preview", action="store_true")
    parser.add_argument("--grid-dx", default="-70,-55,-40,-25,-10,5,20")
    parser.add_argument("--grid-dy", default="-30,-15,0,15,30,45")
    parser.add_argument("--grid-scale", default="0.96,0.98,1.00,1.02,1.04")
    parser.add_argument("--grid-mode", choices=["edge", "mask"], default="edge")
    parser.add_argument("--no-byteswap", action="store_true")
    args = parser.parse_args()
    if args.grid_preview:
        preview_grid(
            args.record_dir.resolve(),
            args.output_dir.resolve(),
            byteswap=not args.no_byteswap,
            dx_values=[float(value) for value in args.grid_dx.split(",") if value.strip()],
            dy_values=[float(value) for value in args.grid_dy.split(",") if value.strip()],
            scale_values=[float(value) for value in args.grid_scale.split(",") if value.strip()],
            grid_mode=args.grid_mode,
        )
        return
    register_record(
        args.record_dir.resolve(),
        args.output_dir.resolve(),
        stride=args.stride,
        max_frames=args.max_frames,
        byteswap=not args.no_byteswap,
        motion=args.motion,
        max_shift=args.max_shift,
        ply_stride=max(1, args.ply_stride),
        manual_translation=tuple(args.manual_translation) if args.manual_translation else None,
        manual_scale=args.manual_scale,
    )


if __name__ == "__main__":
    main()
