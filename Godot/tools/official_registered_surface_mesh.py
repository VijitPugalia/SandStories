#!/usr/bin/env python3
"""Build continuous RGB-aligned sand surface meshes from official Kinect registration.

This starts from frames dumped with FREENECT_DEPTH_REGISTERED, so the depth image
is already in RGB pixel coordinates. It outputs colored PLY meshes with faces,
plus a detail-enhanced variant that keeps the low-frequency metric shape but
amplifies Kinect depth residuals so sand-drawing grooves are visible in MeshLab.
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


def _read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _read_depth_mm(path: Path, *, byteswap: bool) -> np.ndarray:
    depth = np.asarray(Image.open(path), dtype=np.uint16)
    if byteswap:
        depth = depth.byteswap()
    return depth.astype(np.float32)


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
    mask = ndimage.binary_closing(mask, structure=np.ones((25, 25)))
    mask = ndimage.binary_fill_holes(mask)
    labels, count = ndimage.label(mask)
    if count:
        h, w = mask.shape
        center = labels[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        if ids.size:
            mask = labels == ids[int(np.argmax(freq))]
    return ndimage.binary_erosion(mask, structure=np.ones((5, 5)), iterations=1).astype(bool)


def _depth_valid_mask(depth_mm: np.ndarray) -> np.ndarray:
    valid = (depth_mm > 250.0) & (depth_mm < 1500.0)
    valid = ndimage.binary_opening(valid, structure=np.ones((3, 3)))
    valid = ndimage.binary_closing(valid, structure=np.ones((9, 9)))
    valid &= (depth_mm > 250.0) & (depth_mm < 1500.0)
    return valid.astype(bool)


def _largest_center_component(mask: np.ndarray) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask.astype(bool)
    h, w = mask.shape
    center = labels[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
    ids, freq = np.unique(center[center > 0], return_counts=True)
    if ids.size:
        return labels == ids[int(np.argmax(freq))]
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    return labels == int(np.argmax(sizes) + 1)


def _surface_mask(rgb: np.ndarray, depth_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rgb_mask = _rgb_sand_mask(rgb)
    depth_valid = _depth_valid_mask(depth_mm)
    surface = rgb_mask & ndimage.binary_dilation(depth_valid, structure=np.ones((7, 7)), iterations=1)
    surface = ndimage.binary_closing(surface, structure=np.ones((15, 15)))
    surface = ndimage.binary_fill_holes(surface)
    surface = _largest_center_component(surface)
    surface = ndimage.binary_erosion(surface, structure=np.ones((3, 3)), iterations=1)
    return surface.astype(bool), depth_valid.astype(bool)


def _fill_depth(depth_m: np.ndarray, valid: np.ndarray, surface: np.ndarray) -> np.ndarray:
    filled = depth_m.copy().astype(np.float32)
    if not np.any(valid & surface):
        return filled
    median = float(np.median(depth_m[valid & surface]))
    filled[~valid] = median
    missing = surface & ~valid
    if np.any(missing):
        normalized = filled.copy()
        lo, hi = np.percentile(normalized[valid & surface], [1.0, 99.0])
        if hi <= lo:
            hi = lo + 1e-3
        depth_u8 = np.clip((normalized - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
        repaired = cv2.inpaint(depth_u8, missing.astype(np.uint8) * 255, 5.0, cv2.INPAINT_TELEA).astype(np.float32) / 255.0
        filled[missing] = repaired[missing] * (hi - lo) + lo
    filled[~surface] = median
    return filled.astype(np.float32)


def _smooth_metric_depth(depth_m: np.ndarray, surface: np.ndarray) -> np.ndarray:
    # Bilateral filtering removes Kinect speckle while preserving broader grooves.
    lo, hi = np.percentile(depth_m[surface], [1.0, 99.0]) if np.any(surface) else (0.5, 0.8)
    norm = np.clip((depth_m - lo) / max(hi - lo, 1e-3), 0.0, 1.0).astype(np.float32)
    filtered = cv2.bilateralFilter(norm, d=7, sigmaColor=0.08, sigmaSpace=5)
    out = filtered * (hi - lo) + lo
    out[~surface] = depth_m[~surface]
    return out.astype(np.float32)


def _detail_enhance_depth(depth_m: np.ndarray, surface: np.ndarray, gain: float, max_mm: float) -> tuple[np.ndarray, np.ndarray]:
    low = cv2.GaussianBlur(depth_m.astype(np.float32), (0, 0), 8.0)
    residual = depth_m - low
    if np.any(surface):
        residual = residual.copy()
        limit = max_mm / 1000.0
        residual = np.clip(residual, -limit, limit)
        enhanced = low + residual * gain
        lo, hi = np.percentile(depth_m[surface], [0.5, 99.5])
        pad = max_mm / 1000.0
        enhanced = np.clip(enhanced, lo - pad, hi + pad)
        enhanced[~surface] = depth_m[~surface]
        return enhanced.astype(np.float32), residual.astype(np.float32)
    return depth_m.astype(np.float32), residual.astype(np.float32)


def _rgb_visual_displacement(rgb: np.ndarray, surface: np.ndarray, max_mm: float) -> np.ndarray:
    rgb_f = rgb.astype(np.float32) / 255.0
    lum = rgb_f[:, :, 0] * 0.299 + rgb_f[:, :, 1] * 0.587 + rgb_f[:, :, 2] * 0.114
    local = cv2.GaussianBlur(lum, (0, 0), 9.0)
    high = lum - local
    if not np.any(surface):
        return np.zeros(lum.shape, dtype=np.float32)
    scale = float(np.percentile(np.abs(high[surface]), 98.0))
    if scale <= 1e-6:
        return np.zeros(lum.shape, dtype=np.float32)
    visual = np.clip(high / scale, -1.0, 1.0) * (max_mm / 1000.0)
    visual[~surface] = 0.0
    # Small, signed visual cue only. This is not treated as true metric depth.
    return cv2.GaussianBlur(visual.astype(np.float32), (0, 0), 0.8)


def _shade_from_depth(depth_m: np.ndarray, surface: np.ndarray, strength: float = 160.0) -> np.ndarray:
    if not np.any(surface):
        return np.zeros(depth_m.shape, dtype=np.float32)
    lo, hi = np.percentile(depth_m[surface], [2.0, 98.0])
    height = 1.0 - np.clip((depth_m - lo) / max(hi - lo, 1e-4), 0.0, 1.0)
    height = cv2.GaussianBlur(height.astype(np.float32), (0, 0), 0.8)
    gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3) * strength
    gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3) * strength
    nx = -gx
    ny = -gy
    nz = np.ones_like(height)
    length = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    nx /= length
    ny /= length
    nz /= length
    light = np.array([-0.35, -0.55, 0.76], dtype=np.float32)
    light /= np.linalg.norm(light)
    shade = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0.0, 1.0) * 0.70 + 0.30
    shade[~surface] = 0.0
    return shade.astype(np.float32)


def _norm_view(values: np.ndarray, surface: np.ndarray) -> np.ndarray:
    if not np.any(surface):
        return np.zeros(values.shape, dtype=np.float32)
    lo, hi = np.percentile(values[surface], [2.0, 98.0])
    if hi <= lo:
        hi = lo + 1e-3
    out = 1.0 - np.clip((values - lo) / (hi - lo), 0.0, 1.0)
    out[~surface] = 0.0
    return out.astype(np.float32)


def _residual_view(residual: np.ndarray, surface: np.ndarray) -> np.ndarray:
    if not np.any(surface):
        return np.zeros(residual.shape, dtype=np.float32)
    scale = float(np.percentile(np.abs(residual[surface]), 98.0))
    if scale <= 1e-6:
        scale = 1e-3
    out = np.clip(residual / scale, -1.0, 1.0) * 0.5 + 0.5
    out[~surface] = 0.0
    return out.astype(np.float32)


def _write_mesh_ply(path: Path, rgb: np.ndarray, depth_m: np.ndarray, surface: np.ndarray, stride: int) -> tuple[int, int]:
    h, w = depth_m.shape
    vertex_index = -np.ones((h, w), dtype=np.int32)
    vertices: list[tuple[float, float, float, int, int, int]] = []
    for v in range(0, h, stride):
        for u in range(0, w, stride):
            if not surface[v, u]:
                continue
            z = float(depth_m[v, u])
            if not (0.25 <= z <= 1.5):
                continue
            x = (u - KINECT_CX) * z / KINECT_FX
            y = (v - KINECT_CY) * z / KINECT_FY
            r, g, b = rgb[v, u]
            vertex_index[v, u] = len(vertices)
            vertices.append((x, y, z, int(r), int(g), int(b)))
    faces: list[tuple[int, int, int]] = []
    max_depth_jump = 0.025
    for v in range(0, h - stride, stride):
        for u in range(0, w - stride, stride):
            ids = [vertex_index[v, u], vertex_index[v, u + stride], vertex_index[v + stride, u], vertex_index[v + stride, u + stride]]
            if min(ids) < 0:
                continue
            z = [depth_m[v, u], depth_m[v, u + stride], depth_m[v + stride, u], depth_m[v + stride, u + stride]]
            if float(np.max(z) - np.min(z)) > max_depth_jump:
                continue
            faces.append((int(ids[0]), int(ids[2]), int(ids[1])))
            faces.append((int(ids[1]), int(ids[2]), int(ids[3])))
    with path.open("w", encoding="utf-8") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(vertices)}\n")
        handle.write("property float x\nproperty float y\nproperty float z\n")
        handle.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        handle.write(f"element face {len(faces)}\n")
        handle.write("property list uchar int vertex_indices\n")
        handle.write("end_header\n")
        for x, y, z, r, g, b in vertices:
            handle.write(f"{x:.6f} {y:.6f} {z:.6f} {r} {g} {b}\n")
        for a, b, c in faces:
            handle.write(f"3 {a} {b} {c}\n")
    return len(vertices), len(faces)


def _contact_sheet(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    labels = ["rgb", "metric_depth", "detail_depth", "residual", "metric_shade", "detail_shade", "overlay"]
    tiles: list[Image.Image] = []
    for row in rows:
        images = [Image.open(output_dir / row[label]).convert("RGB") for label in labels]
        w, h = images[0].size
        tile = Image.new("RGB", (w * len(images), h + 42), (18, 18, 18))
        draw = ImageDraw.Draw(tile)
        for index, (label, image) in enumerate(zip(labels, images)):
            tile.paste(image, (index * w, 24))
            draw.text((index * w + 5, 6), label, fill=(255, 255, 255))
        draw.text((5, h + 25), row["caption"], fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (0, index * tile.height))
    sheet.save(output_dir / "surface_mesh_contact_sheet.png")


def build_meshes(
    input_dir: Path,
    output_dir: Path,
    *,
    byteswap: bool,
    stride: int,
    max_frames: int | None,
    detail_gain: float,
    max_detail_mm: float,
    rgb_visual_mm: float,
) -> None:
    rgb_paths = sorted(input_dir.glob("*_rgb_*.ppm"))
    depth_paths = sorted(input_dir.glob("*_depth_registered_*.pgm"))
    count = min(len(rgb_paths), len(depth_paths))
    if max_frames is not None:
        count = min(count, max_frames)
    if count == 0:
        raise RuntimeError(f"No official registered RGB/depth frames found in {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.png", "*.ply", "*.json"):
        for old in output_dir.glob(pattern):
            old.unlink()

    frames: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index, (rgb_path, depth_path) in enumerate(zip(rgb_paths[:count], depth_paths[:count]), start=1):
        rgb = _read_rgb(rgb_path)
        depth_mm = _read_depth_mm(depth_path, byteswap=byteswap)
        depth_m = depth_mm / 1000.0
        surface, depth_valid = _surface_mask(rgb, depth_mm)
        filled = _fill_depth(depth_m, depth_valid, surface)
        metric = _smooth_metric_depth(filled, surface)
        enhanced, residual = _detail_enhance_depth(metric, surface, gain=detail_gain, max_mm=max_detail_mm)
        if rgb_visual_mm > 0:
            enhanced = enhanced - _rgb_visual_displacement(rgb, surface, rgb_visual_mm)
            enhanced[~surface] = metric[~surface]

        stem = f"{index:06d}"
        metric_ply = f"surface_metric_{stem}.ply"
        detail_ply = f"surface_detail_enhanced_{stem}.ply"
        metric_vertices, metric_faces = _write_mesh_ply(output_dir / metric_ply, rgb, metric, surface, stride)
        detail_vertices, detail_faces = _write_mesh_ply(output_dir / detail_ply, rgb, enhanced, surface, stride)

        metric_depth_name = f"metric_depth_{stem}.png"
        detail_depth_name = f"detail_depth_{stem}.png"
        residual_name = f"depth_residual_{stem}.png"
        metric_shade_name = f"metric_shade_{stem}.png"
        detail_shade_name = f"detail_shade_{stem}.png"
        overlay_name = f"detail_overlay_{stem}.png"
        rgb_name = f"rgb_{stem}.png"
        metric_view = _norm_view(metric, surface)
        detail_view = _norm_view(enhanced, surface)
        residual_img = _residual_view(residual, surface)
        metric_shade = _shade_from_depth(metric, surface)
        detail_shade = _shade_from_depth(enhanced, surface)
        overlay = rgb.astype(np.float32) * 0.58 + np.dstack([detail_view * 255.0, detail_view * 175.0, np.zeros_like(detail_view)]) * 0.42
        Image.fromarray(rgb).save(output_dir / rgb_name)
        Image.fromarray(np.clip(metric_view * 255.0, 0, 255).astype(np.uint8)).save(output_dir / metric_depth_name)
        Image.fromarray(np.clip(detail_view * 255.0, 0, 255).astype(np.uint8)).save(output_dir / detail_depth_name)
        Image.fromarray(np.clip(residual_img * 255.0, 0, 255).astype(np.uint8)).save(output_dir / residual_name)
        Image.fromarray(np.clip(metric_shade * 255.0, 0, 255).astype(np.uint8)).save(output_dir / metric_shade_name)
        Image.fromarray(np.clip(detail_shade * 255.0, 0, 255).astype(np.uint8)).save(output_dir / detail_shade_name)
        Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8)).save(output_dir / overlay_name)

        z_values = enhanced[surface]
        frame = {
            "frame": index,
            "sourceRgb": rgb_path.name,
            "sourceDepthRegistered": depth_path.name,
            "rgb": rgb_name,
            "metricMesh": metric_ply,
            "detailEnhancedMesh": detail_ply,
            "metricVertices": metric_vertices,
            "metricFaces": metric_faces,
            "detailVertices": detail_vertices,
            "detailFaces": detail_faces,
            "metricDepthView": metric_depth_name,
            "detailDepthView": detail_depth_name,
            "residualView": residual_name,
            "metricShade": metric_shade_name,
            "detailShade": detail_shade_name,
            "overlay": overlay_name,
            "surfacePixels": int(surface.sum()),
            "validDepthPixels": int((surface & depth_valid).sum()),
            "zMinMeters": float(z_values.min()) if z_values.size else 0.0,
            "zMaxMeters": float(z_values.max()) if z_values.size else 0.0,
        }
        frames.append(frame)
        rows.append({
            "rgb": rgb_name,
            "metric_depth": metric_depth_name,
            "detail_depth": detail_depth_name,
            "residual": residual_name,
            "metric_shade": metric_shade_name,
            "detail_shade": detail_shade_name,
            "overlay": overlay_name,
            "caption": f"frame {index}: detail mesh {detail_vertices} verts/{detail_faces} faces, z {frame['zMinMeters']:.3f}-{frame['zMaxMeters']:.3f}m",
        })

    _contact_sheet(output_dir, rows)
    _save_json(output_dir / "surface_mesh_manifest.json", {
        "source": str(input_dir),
        "method": "official_registered_depth_continuous_surface_mesh",
        "depthSource": "libfreenect FREENECT_DEPTH_REGISTERED, already RGB-aligned",
        "depthUnits": "millimeters converted to meters",
        "byteswapApplied": byteswap,
        "meshStridePixels": stride,
        "detailEnhancement": {
            "kind": "low_frequency_metric_depth_plus_amplified_kinect_depth_residual",
            "gain": detail_gain,
            "maxResidualMillimeters": max_detail_mm,
            "rgbVisualDisplacementMillimeters": rgb_visual_mm,
            "rgbVisualNote": "RGB cue is optional visual displacement only, not true metric depth.",
        },
        "intrinsics": {"fx": KINECT_FX, "fy": KINECT_FY, "cx": KINECT_CX, "cy": KINECT_CY},
        "frames": frames,
        "contactSheet": "surface_mesh_contact_sheet.png",
    })
    print(output_dir.resolve())


def build_temporal_fused_mesh(
    input_dir: Path,
    output_dir: Path,
    *,
    byteswap: bool,
    stride: int,
    max_frames: int | None,
    detail_gain: float,
    max_detail_mm: float,
    rgb_visual_mm: float,
) -> None:
    rgb_paths = sorted(input_dir.glob("*_rgb_*.ppm"))
    depth_paths = sorted(input_dir.glob("*_depth_registered_*.pgm"))
    count = min(len(rgb_paths), len(depth_paths))
    if max_frames is not None:
        count = min(count, max_frames)
    if count == 0:
        raise RuntimeError(f"No official registered RGB/depth frames found in {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.png", "*.ply", "*.json"):
        for old in output_dir.glob(pattern):
            old.unlink()

    rgbs: list[np.ndarray] = []
    filled_depths: list[np.ndarray] = []
    surface_votes: list[np.ndarray] = []
    valid_votes: list[np.ndarray] = []
    for rgb_path, depth_path in zip(rgb_paths[:count], depth_paths[:count]):
        rgb = _read_rgb(rgb_path)
        depth_mm = _read_depth_mm(depth_path, byteswap=byteswap)
        depth_m = depth_mm / 1000.0
        surface, depth_valid = _surface_mask(rgb, depth_mm)
        rgbs.append(rgb)
        surface_votes.append(surface)
        valid_votes.append(depth_valid)
        filled_depths.append(_fill_depth(depth_m, depth_valid, surface))

    rgb = np.median(np.stack(rgbs).astype(np.float32), axis=0).astype(np.uint8)
    surface_score = np.mean(np.stack(surface_votes).astype(np.float32), axis=0)
    valid_score = np.mean(np.stack(valid_votes).astype(np.float32), axis=0)
    rgb_mask = _rgb_sand_mask(rgb)
    surface = rgb_mask & (surface_score >= 0.50) & (valid_score >= 0.55)
    surface = ndimage.binary_closing(surface, structure=np.ones((13, 13)))
    surface = ndimage.binary_fill_holes(surface)
    surface = _largest_center_component(surface)
    surface = ndimage.binary_erosion(surface, structure=np.ones((3, 3)), iterations=1)

    depth_stack = np.stack(filled_depths).astype(np.float32)
    median_depth = np.median(depth_stack, axis=0).astype(np.float32)
    metric = _smooth_metric_depth(median_depth, surface)
    enhanced, residual = _detail_enhance_depth(metric, surface, gain=detail_gain, max_mm=max_detail_mm)
    if rgb_visual_mm > 0:
        enhanced = enhanced - _rgb_visual_displacement(rgb, surface, rgb_visual_mm)
        enhanced[~surface] = metric[~surface]

    metric_ply = "temporal_surface_metric.ply"
    detail_ply = "temporal_surface_detail_enhanced.ply"
    metric_vertices, metric_faces = _write_mesh_ply(output_dir / metric_ply, rgb, metric, surface, stride)
    detail_vertices, detail_faces = _write_mesh_ply(output_dir / detail_ply, rgb, enhanced, surface, stride)

    metric_view = _norm_view(metric, surface)
    detail_view = _norm_view(enhanced, surface)
    residual_img = _residual_view(residual, surface)
    metric_shade = _shade_from_depth(metric, surface, strength=90.0)
    detail_shade = _shade_from_depth(enhanced, surface, strength=90.0)
    overlay = rgb.astype(np.float32) * 0.58 + np.dstack([detail_view * 255.0, detail_view * 175.0, np.zeros_like(detail_view)]) * 0.42

    outputs = {
        "rgb": "temporal_rgb.png",
        "metric_depth": "temporal_metric_depth.png",
        "detail_depth": "temporal_detail_depth.png",
        "residual": "temporal_depth_residual.png",
        "metric_shade": "temporal_metric_shade.png",
        "detail_shade": "temporal_detail_shade.png",
        "overlay": "temporal_detail_overlay.png",
    }
    Image.fromarray(rgb).save(output_dir / outputs["rgb"])
    Image.fromarray(np.clip(metric_view * 255.0, 0, 255).astype(np.uint8)).save(output_dir / outputs["metric_depth"])
    Image.fromarray(np.clip(detail_view * 255.0, 0, 255).astype(np.uint8)).save(output_dir / outputs["detail_depth"])
    Image.fromarray(np.clip(residual_img * 255.0, 0, 255).astype(np.uint8)).save(output_dir / outputs["residual"])
    Image.fromarray(np.clip(metric_shade * 255.0, 0, 255).astype(np.uint8)).save(output_dir / outputs["metric_shade"])
    Image.fromarray(np.clip(detail_shade * 255.0, 0, 255).astype(np.uint8)).save(output_dir / outputs["detail_shade"])
    Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8)).save(output_dir / outputs["overlay"])
    _contact_sheet(output_dir, [{**outputs, "caption": f"temporal median of {count} official registered frames: detail mesh {detail_vertices} verts/{detail_faces} faces"}])

    z_values = enhanced[surface]
    _save_json(output_dir / "temporal_surface_mesh_manifest.json", {
        "source": str(input_dir),
        "method": "temporal_median_official_registered_depth_surface_mesh",
        "depthSource": "libfreenect FREENECT_DEPTH_REGISTERED, already RGB-aligned",
        "framesFused": count,
        "byteswapApplied": byteswap,
        "meshStridePixels": stride,
        "detailEnhancement": {
            "kind": "temporal_median_metric_depth_plus_amplified_kinect_depth_residual",
            "gain": detail_gain,
            "maxResidualMillimeters": max_detail_mm,
            "rgbVisualDisplacementMillimeters": rgb_visual_mm,
            "rgbVisualNote": "RGB cue is optional visual displacement only, not true metric depth.",
        },
        "intrinsics": {"fx": KINECT_FX, "fy": KINECT_FY, "cx": KINECT_CX, "cy": KINECT_CY},
        "outputs": {
            "metricMesh": metric_ply,
            "detailEnhancedMesh": detail_ply,
            "contactSheet": "surface_mesh_contact_sheet.png",
            **outputs,
        },
        "stats": {
            "metricVertices": metric_vertices,
            "metricFaces": metric_faces,
            "detailVertices": detail_vertices,
            "detailFaces": detail_faces,
            "surfacePixels": int(surface.sum()),
            "zMinMeters": float(z_values.min()) if z_values.size else 0.0,
            "zMaxMeters": float(z_values.max()) if z_values.size else 0.0,
        },
    })
    print(output_dir.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--detail-gain", type=float, default=2.4)
    parser.add_argument("--max-detail-mm", type=float, default=14.0)
    parser.add_argument("--rgb-visual-mm", type=float, default=0.0)
    parser.add_argument("--temporal-fusion", action="store_true")
    parser.add_argument("--no-byteswap", action="store_true")
    args = parser.parse_args()
    if args.temporal_fusion:
        build_temporal_fused_mesh(
            args.input_dir.resolve(),
            args.output_dir.resolve(),
            byteswap=not args.no_byteswap,
            stride=max(1, args.stride),
            max_frames=args.max_frames,
            detail_gain=args.detail_gain,
            max_detail_mm=args.max_detail_mm,
            rgb_visual_mm=max(0.0, args.rgb_visual_mm),
        )
        return
    build_meshes(
        args.input_dir.resolve(),
        args.output_dir.resolve(),
        byteswap=not args.no_byteswap,
        stride=max(1, args.stride),
        max_frames=args.max_frames,
        detail_gain=args.detail_gain,
        max_detail_mm=args.max_detail_mm,
        rgb_visual_mm=max(0.0, args.rgb_visual_mm),
    )


if __name__ == "__main__":
    main()
