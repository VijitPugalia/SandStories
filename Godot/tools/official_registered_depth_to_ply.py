#!/usr/bin/env python3
"""Convert official libfreenect registered depth dumps to RGB-aligned PLYs."""

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


def _read_ppm(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _read_registered_depth_mm(path: Path, *, byteswap: bool) -> np.ndarray:
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
    mask = ndimage.binary_closing(mask, structure=np.ones((23, 23)))
    mask = ndimage.binary_fill_holes(mask)
    labels, count = ndimage.label(mask)
    if count:
        h, w = mask.shape
        center = labels[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        if ids.size:
            mask = labels == ids[int(np.argmax(freq))]
    return ndimage.binary_erosion(mask, structure=np.ones((5, 5)), iterations=1).astype(bool)


def _depth_mask(depth_mm: np.ndarray) -> np.ndarray:
    valid = (depth_mm > 250.0) & (depth_mm < 1500.0)
    valid = ndimage.binary_opening(valid, structure=np.ones((3, 3)))
    valid = ndimage.binary_closing(valid, structure=np.ones((9, 9)))
    valid &= (depth_mm > 250.0) & (depth_mm < 1500.0)
    return valid.astype(bool)


def _normalize_depth(depth_m: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not np.any(mask):
        return np.zeros(depth_m.shape, dtype=np.float32)
    lo, hi = np.percentile(depth_m[mask], [2.0, 98.0])
    if hi <= lo:
        hi = lo + 1e-3
    out = 1.0 - np.clip((depth_m - lo) / (hi - lo), 0.0, 1.0)
    out[~mask] = 0.0
    return out.astype(np.float32)


def _residual_view(depth_m: np.ndarray, mask: np.ndarray) -> np.ndarray:
    filled = depth_m.copy()
    if np.any(mask):
        filled[~mask] = float(np.median(depth_m[mask]))
    low = cv2.GaussianBlur(filled.astype(np.float32), (0, 0), 9.0)
    residual = low - filled
    if not np.any(mask):
        return np.zeros(depth_m.shape, dtype=np.float32)
    scale = float(np.percentile(np.abs(residual[mask]), 98.0))
    if scale <= 1e-6:
        scale = 1e-3
    out = np.clip(residual / scale, -1.0, 1.0) * 0.5 + 0.5
    out[~mask] = 0.0
    return out.astype(np.float32)


def _write_ply(path: Path, rgb: np.ndarray, depth_m: np.ndarray, mask: np.ndarray, stride: int) -> int:
    h, w = depth_m.shape
    vertices: list[tuple[float, float, float, int, int, int]] = []
    for v in range(0, h, stride):
        for u in range(0, w, stride):
            if not mask[v, u]:
                continue
            z = float(depth_m[v, u])
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
        for x, y, z, r, g, b in vertices:
            handle.write(f"{x:.6f} {y:.6f} {z:.6f} {r} {g} {b}\n")
    return len(vertices)


def _contact_sheet(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    labels = ["rgb", "depth", "residual", "overlay"]
    tiles: list[Image.Image] = []
    for row in rows:
        images = [Image.open(output_dir / row[label]).convert("RGB") for label in labels]
        w, h = images[0].size
        tile = Image.new("RGB", (w * len(images), h + 36), (18, 18, 18))
        draw = ImageDraw.Draw(tile)
        for index, (label, image) in enumerate(zip(labels, images)):
            tile.paste(image, (index * w, 24))
            draw.text((index * w + 5, 6), label, fill=(255, 255, 255))
        draw.text((5, h + 22), row["caption"], fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (0, index * tile.height))
    sheet.save(output_dir / "official_registered_contact_sheet.png")


def convert(input_dir: Path, output_dir: Path, *, byteswap: bool, ply_stride: int, max_frames: int | None) -> None:
    rgb_paths = sorted(input_dir.glob("*_rgb_*.ppm"))
    depth_paths = sorted(input_dir.glob("*_depth_registered_*.pgm"))
    count = min(len(rgb_paths), len(depth_paths))
    if max_frames is not None:
        count = min(count, max_frames)
    if count == 0:
        raise RuntimeError(f"No official RGB/depth pairs found in {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("*.png"):
        old.unlink()
    for old in output_dir.glob("*.ply"):
        old.unlink()

    frames: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index, (rgb_path, depth_path) in enumerate(zip(rgb_paths[:count], depth_paths[:count]), start=1):
        rgb = _read_ppm(rgb_path)
        depth_mm = _read_registered_depth_mm(depth_path, byteswap=byteswap)
        depth_m = depth_mm / 1000.0
        rgb_mask = _rgb_sand_mask(rgb)
        valid = _depth_mask(depth_mm) & rgb_mask
        depth_view = _normalize_depth(depth_m, valid)
        residual_view = _residual_view(depth_m, valid)
        overlay = rgb.astype(np.float32) * 0.62 + np.dstack([depth_view * 255.0, depth_view * 175.0, np.zeros_like(depth_view)]) * 0.38

        stem = f"{index:06d}"
        rgb_name = f"rgb_{stem}.png"
        depth_name = f"official_registered_depth_{stem}.png"
        residual_name = f"official_registered_residual_{stem}.png"
        overlay_name = f"official_registered_overlay_{stem}.png"
        ply_name = f"official_registered_rgb_{stem}.ply"
        Image.fromarray(rgb).save(output_dir / rgb_name)
        Image.fromarray(np.clip(depth_view * 255.0, 0, 255).astype(np.uint8)).save(output_dir / depth_name)
        Image.fromarray(np.clip(residual_view * 255.0, 0, 255).astype(np.uint8)).save(output_dir / residual_name)
        Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8)).save(output_dir / overlay_name)
        vertices = _write_ply(output_dir / ply_name, rgb, depth_m, valid, ply_stride)
        valid_values = depth_m[valid]
        stats = {
            "minMeters": float(valid_values.min()) if valid_values.size else 0.0,
            "meanMeters": float(valid_values.mean()) if valid_values.size else 0.0,
            "maxMeters": float(valid_values.max()) if valid_values.size else 0.0,
            "validRatio": float(valid.mean()),
        }
        caption = f"frame {index}: vertices {vertices}, z {stats['minMeters']:.3f}-{stats['maxMeters']:.3f}m, valid {stats['validRatio']:.3f}"
        rows.append({"rgb": rgb_name, "depth": depth_name, "residual": residual_name, "overlay": overlay_name, "caption": caption})
        frames.append({
            "frame": index,
            "sourceRgb": rgb_path.name,
            "sourceDepthRegistered": depth_path.name,
            "rgb": rgb_name,
            "registeredDepth": depth_name,
            "residual": residual_name,
            "overlay": overlay_name,
            "pointCloud": ply_name,
            "vertices": vertices,
            "stats": stats,
        })

    _contact_sheet(output_dir, rows)
    _save_json(output_dir / "official_registered_manifest.json", {
        "source": str(input_dir),
        "method": "libfreenect_FREENECT_DEPTH_REGISTERED_to_rgb_colored_ply",
        "depthEncoding": {
            "source": "FREENECT_DEPTH_REGISTERED dumped by fakenect_registered_dump.c",
            "byteswapApplied": byteswap,
            "interpretation": "registered depth values are treated as millimeters, then converted to meters for PLY",
        },
        "intrinsics": {"fx": KINECT_FX, "fy": KINECT_FY, "cx": KINECT_CX, "cy": KINECT_CY},
        "plyStride": ply_stride,
        "frames": frames,
        "contactSheet": "official_registered_contact_sheet.png",
    })
    print(output_dir.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ply-stride", type=int, default=2)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--no-byteswap", action="store_true")
    args = parser.parse_args()
    convert(args.input_dir.resolve(), args.output_dir.resolve(), byteswap=not args.no_byteswap, ply_stride=max(1, args.ply_stride), max_frames=args.max_frames)


if __name__ == "__main__":
    main()
