#!/usr/bin/env python3
"""Convert a libfreenect Kinect recording folder into a Godot processed session.

The libfreenect recorder binary is named fakenect-record because its output can
later be replayed by fakenect. The files are still captured from a real Kinect.
Its raw depth PGM files store 16-bit samples little-endian even though normal PGM
readers expect network byte order. PIL can therefore show plausible-looking but
wrong values such as 17922 instead of 582. This adapter byte-swaps by default and
records that decision in the manifest.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_rgb(path: Path, target_size: tuple[int, int]) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    if image.size != target_size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)
    return np.asarray(image, dtype=np.float32) / 255.0


def _load_fakenect_depth(path: Path, *, byteswap: bool) -> np.ndarray:
    depth = np.asarray(Image.open(path), dtype=np.uint16)
    if byteswap:
        depth = depth.byteswap()
    return depth.astype(np.float32)


def _largest_component(mask: np.ndarray, prefer_center: bool = True) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    if prefer_center:
        h, w = mask.shape
        center = labels[h // 4 : (h * 3) // 4, w // 4 : (w * 3) // 4]
        ids, freq = np.unique(center[center > 0], return_counts=True)
        if ids.size:
            return labels == ids[int(np.argmax(freq))]
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    return labels == int(np.argmax(sizes) + 1)


def _surface_mask(rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
    valid_depth = (depth > 0) & (depth < 2047)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    blue_bias = rgb[:, :, 2] - np.maximum(rgb[:, :, 0], rgb[:, :, 1])
    red_floor_bias = rgb[:, :, 0] - rgb[:, :, 2]

    sand_like = (sat < 0.48) & (lum > 0.16) & (lum < 0.92)
    sand_like &= blue_bias < 0.24
    sand_like &= red_floor_bias < 0.42
    mask = valid_depth & sand_like
    mask = ndimage.binary_opening(mask, structure=np.ones((3, 3)))
    mask = ndimage.binary_closing(mask, structure=np.ones((11, 11)))
    mask = ndimage.binary_fill_holes(mask)
    mask = _largest_component(mask, prefer_center=True)
    mask = ndimage.binary_erosion(mask, structure=np.ones((3, 3)), iterations=1)
    mask = ndimage.binary_dilation(mask, structure=np.ones((5, 5)), iterations=1)
    return mask.astype(bool)


def _mask_to_png(mask: np.ndarray) -> np.ndarray:
    return mask.astype(np.uint8) * 255


def _rgb_to_png(rgb: np.ndarray) -> np.ndarray:
    return np.clip(rgb * 255.0, 0, 255).astype(np.uint8)


def _depth_stats(depth: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    valid = depth[mask & (depth > 0) & (depth < 2047)]
    if valid.size == 0:
        return {"min": 0.0, "mean": 0.0, "max": 0.0, "p02": 0.0, "p98": 0.0, "validRatio": 0.0}
    return {
        "min": float(valid.min()),
        "mean": float(valid.mean()),
        "max": float(valid.max()),
        "p02": float(np.percentile(valid, 2)),
        "p98": float(np.percentile(valid, 98)),
        "validRatio": float(valid.size / max(1, int(mask.sum()))),
    }


def _fixed_depth_range(depths: list[np.ndarray], mask: np.ndarray) -> tuple[float, float]:
    values: list[np.ndarray] = []
    for depth in depths[: min(12, len(depths))]:
        valid = mask & (depth > 0) & (depth < 2047)
        if np.any(valid):
            values.append(depth[valid])
    if not values:
        return 0.0, 2047.0
    merged = np.concatenate(values)
    lo = float(np.percentile(merged, 2))
    hi = float(np.percentile(merged, 98))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _depth_to_height_png(depth: np.ndarray, mask: np.ndarray, depth_range: tuple[float, float]) -> np.ndarray:
    lo, hi = depth_range
    if hi <= lo:
        hi = lo + 1.0
    valid = mask & (depth > 0) & (depth < 2047)
    norm = np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
    height = 1.0 - norm
    out = np.full(depth.shape, 255, dtype=np.uint8)
    out[valid] = np.clip((0.14 + height[valid] * 0.78) * 255.0, 0, 255).astype(np.uint8)
    return out


def _fill_invalid_height_png(height_png: np.ndarray, valid: np.ndarray, surface_mask: np.ndarray) -> np.ndarray:
    missing = surface_mask & ~valid
    if not np.any(missing):
        return height_png
    inpaint_mask = missing.astype(np.uint8) * 255
    filled = cv2.inpaint(height_png, inpaint_mask, 3.0, cv2.INPAINT_TELEA)
    filled[~surface_mask] = 255
    return filled.astype(np.uint8)


def _detail_png(depth: np.ndarray, baseline: np.ndarray, mask: np.ndarray, scale_raw: float) -> np.ndarray:
    valid = mask & (depth > 0) & (depth < 2047)
    detail = np.full(depth.shape, 128, dtype=np.uint8)
    if not np.any(valid):
        return detail
    delta = depth - baseline
    encoded = 128.0 + np.clip(-delta / scale_raw, -1.0, 1.0) * 96.0
    detail[valid] = np.clip(encoded[valid], 0, 255).astype(np.uint8)
    return detail


def _shaded_height(height_png: np.ndarray, mask: np.ndarray) -> np.ndarray:
    height = height_png.astype(np.float32) / 255.0
    height = cv2.medianBlur((height * 65535).astype(np.uint16), 5).astype(np.float32) / 65535.0
    height = cv2.GaussianBlur(height, (0, 0), 0.7)
    gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3) * 8.0
    gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3) * 8.0
    nx = -gx
    ny = -gy
    nz = np.ones_like(height)
    length = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    nx /= length
    ny /= length
    nz /= length
    light = np.array([-0.35, -0.55, 0.76], dtype=np.float32)
    light /= np.linalg.norm(light)
    shade = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0.0, 1.0) * 0.72 + 0.28
    shade[~mask] = 0.0
    return np.clip(shade * 255.0, 0, 255).astype(np.uint8)


def _pair_frames(record_dir: Path) -> list[tuple[int, Path, Path]]:
    depth_paths = sorted(record_dir.glob("d-*.pgm"))
    rgb_paths = sorted(record_dir.glob("r-*.ppm"))
    count = min(len(depth_paths), len(rgb_paths))
    return [(index, rgb_paths[index], depth_paths[index]) for index in range(count)]


def _write_contact_sheet(output_dir: Path, frames: list[dict[str, Any]], max_rows: int = 6) -> None:
    if not frames:
        return
    picks = np.linspace(0, len(frames) - 1, min(max_rows, len(frames)), dtype=int)
    rows: list[Image.Image] = []
    labels = ["rgb", "height", "shaded", "detail", "valid"]
    for frame_index in picks:
        frame = frames[int(frame_index)]
        images = [
            Image.open(output_dir / frame["cleanRgb"]).convert("RGB"),
            Image.open(output_dir / frame["cleanDepth"]).convert("L").convert("RGB"),
            Image.open(output_dir / frame["shadedDepth"]).convert("L").convert("RGB"),
            Image.open(output_dir / frame["detailDepth"]).convert("L").convert("RGB"),
            Image.open(output_dir / frame["occlusionMask"]).convert("L").convert("RGB"),
        ]
        w, h = images[0].size
        row = Image.new("RGB", (w * len(images), h + 34), (18, 18, 18))
        draw = ImageDraw.Draw(row)
        for column, (label, image) in enumerate(zip(labels, images)):
            row.paste(image, (column * w, 24))
            draw.text((column * w + 5, 6), label, fill=(255, 255, 255))
        draw.text((5, h + 20), f"frame {frame['frameIndex']} rawDepth {frame['rawDepthStats']}", fill=(255, 255, 255))
        rows.append(row)
    sheet = Image.new("RGB", (rows[0].width, rows[0].height * len(rows)), (0, 0, 0))
    for row_index, row in enumerate(rows):
        sheet.paste(row, (0, row_index * row.height))
    sheet.save(output_dir / "frame_contact_sheet.png")


def convert_record(
    record_dir: Path,
    project_dir: Path,
    session_id: str,
    *,
    stride: int,
    byteswap: bool,
    fill_invalid: bool,
    max_frames: int | None,
    detail_scale_raw: float,
) -> Path:
    pairs = _pair_frames(record_dir)
    if not pairs:
        raise RuntimeError(f"No Kinect rgb/depth pairs found in {record_dir}")
    pairs = pairs[::stride]
    if max_frames is not None:
        pairs = pairs[:max_frames]

    output_dir = project_dir / "assets" / "processed_sessions" / f"session_{session_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("*.png"):
        old.unlink()
    for old in output_dir.glob("*.json"):
        old.unlink()

    first_depth = _load_fakenect_depth(pairs[0][2], byteswap=byteswap)
    height, width = first_depth.shape
    target_size = (width, height)
    first_rgb = _load_rgb(pairs[0][1], target_size)
    surface_mask = _surface_mask(first_rgb, first_depth)
    if int(surface_mask.sum()) < width * height * 0.15:
        surface_mask = (first_depth > 0) & (first_depth < 2047)
        surface_mask = _largest_component(surface_mask, prefer_center=True)
    Image.fromarray(_mask_to_png(surface_mask)).save(output_dir / "surface_mask.png")

    sample_depths = [_load_fakenect_depth(depth_path, byteswap=byteswap) for _, _, depth_path in pairs[: min(12, len(pairs))]]
    depth_range = _fixed_depth_range(sample_depths, surface_mask)
    baseline = np.median(np.stack(sample_depths[: min(5, len(sample_depths))]), axis=0)

    processed_frames: list[dict[str, Any]] = []
    for out_index, (source_index, rgb_path, depth_path) in enumerate(pairs, start=1):
        rgb = _load_rgb(rgb_path, target_size)
        depth = _load_fakenect_depth(depth_path, byteswap=byteswap)
        valid = surface_mask & (depth > 0) & (depth < 2047)
        height_png = _depth_to_height_png(depth, surface_mask, depth_range)
        clean_height_png = _fill_invalid_height_png(height_png, valid, surface_mask) if fill_invalid else height_png
        shaded = _shaded_height(clean_height_png, surface_mask if fill_invalid else valid)
        detail = _detail_png(depth, baseline, surface_mask, detail_scale_raw)

        stem = f"{out_index:06d}"
        clean_rgb_name = f"clean_rgb_{stem}.png"
        clean_depth_name = f"clean_depth_{stem}.png"
        shaded_name = f"shaded_depth_{stem}.png"
        detail_name = f"detail_depth_{stem}.png"
        valid_name = f"valid_mask_{stem}.png"

        Image.fromarray(_rgb_to_png(rgb)).save(output_dir / clean_rgb_name)
        Image.fromarray(clean_height_png).save(output_dir / clean_depth_name)
        Image.fromarray(shaded).save(output_dir / shaded_name)
        Image.fromarray(detail).save(output_dir / detail_name)
        Image.fromarray(_mask_to_png(valid)).save(output_dir / valid_name)

        processed_frames.append({
            "frameIndex": source_index,
            "time": float((out_index - 1) / 30.0 * stride),
            "sourceRgb": str(rgb_path.relative_to(record_dir)),
            "sourceDepth": str(depth_path.relative_to(record_dir)),
            "cleanRgb": clean_rgb_name,
            "cleanDepth": clean_depth_name,
            "detailDepth": detail_name,
            "shadedDepth": shaded_name,
            "occlusionMask": valid_name,
            "maskOverlay": shaded_name,
            "rawDepthStats": _depth_stats(depth, surface_mask),
            "validPixels": int(valid.sum()),
        })

    _write_contact_sheet(output_dir, processed_frames)
    final_frame = processed_frames[-1]
    rel_output = f"res://assets/processed_sessions/session_{session_id}"
    processed_manifest = {
        "sourceSession": str(record_dir),
        "sessionId": session_id,
        "captureFormat": "kinect_libfreenect_record",
        "frameSize": {"width": width, "height": height},
        "sourceFrameCount": len(_pair_frames(record_dir)),
        "processedFrameCount": len(processed_frames),
        "stride": stride,
        "depthEncoding": {
            "source": "libfreenect Kinect raw depth PGM",
            "recorderBinary": "fakenect-record",
            "invalidRawValue": 2047,
            "byteswapApplied": byteswap,
            "invalidDepthFillAppliedToHeightMaps": fill_invalid,
            "note": "The recorder binary is named fakenect-record for replay support; these files are real Kinect captures. Depth PGM samples are little-endian, so common PGM readers may require byte swap.",
        },
        "depthNormalization": {
            "method": "fixed_percentile_range_on_surface_mask",
            "p02Raw": depth_range[0],
            "p98Raw": depth_range[1],
            "detailScaleRaw": detail_scale_raw,
        },
        "surfaceMask": "surface_mask.png",
        "contactSheet": "frame_contact_sheet.png",
        "frames": processed_frames,
    }
    _save_json(output_dir / "processed_manifest.json", processed_manifest)

    godot_session = {
        "id": f"kinect_{session_id}",
        "title": f"Kinect libfreenect recording {session_id}",
        "duration": final_frame["time"],
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{rel_output}/{final_frame['cleanDepth']}",
            "detail_depth_map": f"{rel_output}/{final_frame['detailDepth']}",
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
                "height_scale": -1.9,
                "material_strength": 0.65,
            },
        },
        "production_session": {
            "schemaVersion": 1,
            "deviceModel": "Kinect v1",
            "sourceFolder": str(record_dir),
            "processedFrameCount": len(processed_frames),
            "experiment": "libfreenect_record_raw_depth_decode",
        },
        "gesture_events": [],
        "study_tasks": [{"id": "kinect_surface_review", "prompt": "Review Kinect raw depth reconstruction of sand relief."}],
    }
    _save_json(output_dir / "session.json", godot_session)

    source_readme = record_dir / "README"
    if source_readme.exists():
        shutil.copy2(source_readme, output_dir / "source_README")
    return output_dir / "session.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record_dir", type=Path, help="libfreenect fakenect-record output directory")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--session-id", default="kinect_eval_record")
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--detail-scale-raw", type=float, default=22.0)
    parser.add_argument("--no-byteswap", action="store_true", help="Disable fakenect depth byte swap")
    parser.add_argument("--no-fill-invalid", action="store_true", help="Keep invalid Kinect speckles as holes in height maps")
    args = parser.parse_args()

    session_json = convert_record(
        args.record_dir.resolve(),
        args.project.resolve(),
        args.session_id,
        stride=max(1, args.stride),
        byteswap=not args.no_byteswap,
        fill_invalid=not args.no_fill_invalid,
        max_frames=args.max_frames,
        detail_scale_raw=args.detail_scale_raw,
    )
    print(session_json)


if __name__ == "__main__":
    main()
