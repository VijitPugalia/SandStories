#!/usr/bin/env python3
"""Render fused height maps and compare them against RGB visual evidence.

This is a diagnostic tool, intentionally independent from the CV fusion code.
It answers: does the produced height map contain relief where the image has
stable visual structure, and does it avoid relief where the image is flat?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _read_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def _save_rgb(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8)).save(path)


def _save_gray(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8)).save(path)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114


def _local_normalize(lum: np.ndarray, sigma: float = 10.0) -> np.ndarray:
    mean = cv2.GaussianBlur(lum.astype(np.float32), (0, 0), sigma)
    sq = cv2.GaussianBlur((lum * lum).astype(np.float32), (0, 0), sigma)
    std = np.sqrt(np.maximum(sq - mean * mean, 1e-5))
    return np.clip((lum - mean) / (std + 1e-4), -3.0, 3.0) / 6.0 + 0.5


def _norm01(image: np.ndarray, mask: np.ndarray | None = None, lo: float = 2.0, hi: float = 98.0) -> np.ndarray:
    values = image[mask] if mask is not None and np.any(mask) else image.reshape(-1)
    p0 = float(np.percentile(values, lo))
    p1 = float(np.percentile(values, hi))
    if p1 <= p0:
        return np.zeros_like(image, dtype=np.float32)
    return np.clip((image - p0) / (p1 - p0), 0.0, 1.0).astype(np.float32)


def _gradient(image: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(image.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return np.hypot(gx, gy).astype(np.float32)


def _render_height(height: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    h = cv2.GaussianBlur((height - 0.5).astype(np.float32), (0, 0), 0.7)
    dzdx = cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3) * strength
    dzdy = cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3) * strength
    nx = -dzdx
    ny = -dzdy
    nz = np.ones_like(h)
    nlen = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    nx /= nlen
    ny /= nlen
    nz /= nlen
    light = np.array([-0.35, -0.55, 0.76], dtype=np.float32)
    light /= np.linalg.norm(light)
    diffuse = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0.0, 1.0)
    ambient = 0.34
    shade = ambient + diffuse * (1.0 - ambient)
    shade[~mask] = 0.0
    return shade.astype(np.float32)


def _top_mask(score: np.ndarray, mask: np.ndarray, percentile: float) -> np.ndarray:
    if not np.any(mask):
        return np.zeros_like(mask, dtype=bool)
    threshold = float(np.percentile(score[mask], percentile))
    return (score >= threshold) & mask


def _mismatch_overlay(rgb: np.ndarray, rgb_edges: np.ndarray, height_edges: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = rgb.copy() * 0.55
    both = rgb_edges & height_edges
    height_only = height_edges & ~rgb_edges
    rgb_only = rgb_edges & ~height_edges
    out[height_only] = np.array([1.0, 0.08, 0.02], dtype=np.float32)
    out[rgb_only] = np.array([0.05, 0.35, 1.0], dtype=np.float32)
    out[both] = np.array([0.05, 1.0, 0.18], dtype=np.float32)
    out[~mask] *= 0.15
    return out


def _contact_sheet(output_dir: Path, rows: list[dict[str, str]]) -> None:
    labels = ["rgb", "height", "shaded", "rgb_edges", "height_edges", "mismatch", "persistent"]
    tiles: list[Image.Image] = []
    for row in rows:
        images = [Image.open(output_dir / row[label]).convert("RGB") for label in labels]
        w, h = images[0].size
        tile = Image.new("RGB", (w * len(labels), h + 30), (18, 18, 18))
        draw = ImageDraw.Draw(tile)
        for i, (label, image) in enumerate(zip(labels, images)):
            tile.paste(image, (i * w, 30))
            draw.text((i * w + 5, 8), label, fill=(255, 255, 255))
        draw.text((5, h + 12), f"frame {row['frameIndex']} corr {float(row['corr']):.3f} iou {float(row['iou']):.3f}", fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new("RGB", (tiles[0].width, tiles[0].height * len(tiles)), (0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (0, i * tile.height))
    sheet.save(output_dir / "height_visual_contact_sheet.png")


def diagnose(session_dir: Path, output_dir: Path, edge_percentile: float, render_strength: float) -> None:
    manifest = _load_json(session_dir / "processed_manifest.json")
    frames = manifest.get("frames", [])
    if not frames:
        raise RuntimeError(f"No frames in {session_dir / 'processed_manifest.json'}")
    output_dir.mkdir(parents=True, exist_ok=True)

    mask_path = session_dir / manifest.get("surfaceMask", "surface_mask.png")
    mask = _read_gray(mask_path) > 0.5 if mask_path.exists() else None
    rows: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for i, frame in enumerate(frames, start=1):
        rgb = _read_rgb(session_dir / frame["cleanRgb"])
        height = _read_gray(session_dir / frame["detailDepth"])
        persistent_path = session_dir / frame.get("persistentChange", "")
        persistent = _read_gray(persistent_path) if persistent_path.exists() else np.zeros(height.shape, dtype=np.float32)
        frame_mask = mask
        if frame_mask is None or frame_mask.shape != height.shape:
            frame_mask = np.ones(height.shape, dtype=bool)

        lum_norm = _local_normalize(_luminance(rgb))
        rgb_grad = _norm01(_gradient(lum_norm), frame_mask, 50.0, 99.5)
        height_grad = _norm01(_gradient(height), frame_mask, 50.0, 99.5)
        rgb_edges = _top_mask(rgb_grad, frame_mask, edge_percentile)
        height_edges = _top_mask(height_grad, frame_mask, edge_percentile)
        intersection = int(np.count_nonzero(rgb_edges & height_edges))
        union = int(np.count_nonzero(rgb_edges | height_edges))
        rgb_count = int(np.count_nonzero(rgb_edges))
        height_count = int(np.count_nonzero(height_edges))
        height_only = int(np.count_nonzero(height_edges & ~rgb_edges))
        rgb_only = int(np.count_nonzero(rgb_edges & ~height_edges))
        values_a = rgb_grad[frame_mask].reshape(-1)
        values_b = height_grad[frame_mask].reshape(-1)
        corr = float(np.corrcoef(values_a, values_b)[0, 1]) if values_a.size > 3 and np.std(values_a) > 1e-6 and np.std(values_b) > 1e-6 else 0.0
        iou = float(intersection / union) if union else 0.0

        shade = _render_height(height, frame_mask, render_strength)
        mismatch = _mismatch_overlay(rgb, rgb_edges, height_edges, frame_mask)
        stem = f"frame_{int(frame['frameIndex']):06d}"
        files = {
            "rgb": f"{stem}_rgb.png",
            "height": f"{stem}_height.png",
            "shaded": f"{stem}_shaded.png",
            "rgb_edges": f"{stem}_rgb_edges.png",
            "height_edges": f"{stem}_height_edges.png",
            "mismatch": f"{stem}_mismatch.png",
            "persistent": f"{stem}_persistent.png",
        }
        _save_rgb(output_dir / files["rgb"], rgb)
        _save_gray(output_dir / files["height"], height)
        _save_gray(output_dir / files["shaded"], shade)
        _save_gray(output_dir / files["rgb_edges"], rgb_edges.astype(np.float32))
        _save_gray(output_dir / files["height_edges"], height_edges.astype(np.float32))
        _save_rgb(output_dir / files["mismatch"], mismatch)
        _save_gray(output_dir / files["persistent"], persistent)
        metric = {
            "frameIndex": int(frame["frameIndex"]),
            "time": float(frame.get("time", 0.0)),
            "corr": corr,
            "edgeIou": iou,
            "rgbEdgePixels": rgb_count,
            "heightEdgePixels": height_count,
            "matchedEdgePixels": intersection,
            "heightOnlyPixels": height_only,
            "rgbOnlyPixels": rgb_only,
            "persistentPixels": int(np.count_nonzero(persistent > 0.1)),
        }
        metrics.append(metric)
        rows.append({**files, "frameIndex": str(frame["frameIndex"]), "corr": str(corr), "iou": str(iou)})

    _contact_sheet(output_dir, rows)
    summary = {
        "sourceSession": str(session_dir),
        "edgePercentile": edge_percentile,
        "renderStrength": render_strength,
        "meanCorr": float(np.mean([m["corr"] for m in metrics])) if metrics else 0.0,
        "meanEdgeIou": float(np.mean([m["edgeIou"] for m in metrics])) if metrics else 0.0,
        "meanHeightOnlyPixels": float(np.mean([m["heightOnlyPixels"] for m in metrics])) if metrics else 0.0,
        "meanRgbOnlyPixels": float(np.mean([m["rgbOnlyPixels"] for m in metrics])) if metrics else 0.0,
        "metrics": metrics,
        "legend": {
            "mismatchGreen": "RGB edge and height edge agree",
            "mismatchRed": "Height edge without RGB support",
            "mismatchBlue": "RGB edge missing from height",
        },
    }
    _save_json(output_dir / "height_visual_diagnostics.json", summary)
    print(output_dir.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--edge-percentile", type=float, default=92.0)
    parser.add_argument("--render-strength", type=float, default=16.0)
    args = parser.parse_args()
    session_dir = args.session_dir.resolve()
    output_dir = args.output or session_dir.parent / f"{session_dir.name}_height_visual_diagnostic"
    diagnose(session_dir, output_dir.resolve(), args.edge_percentile, args.render_strength)


if __name__ == "__main__":
    main()
