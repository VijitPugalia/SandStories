#!/usr/bin/env python3
"""Sync fixed-camera experiment frames into a small Godot processed session."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _read_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def _save_gray(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8)).save(path)


def _save_rgb(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8)).save(path)


def _enhance_depth_for_web(depth: np.ndarray) -> np.ndarray:
    relief = depth.astype(np.float32) - 0.5
    pos = relief[relief > 0]
    scale = float(np.percentile(pos, 98.0)) if pos.size else 0.05
    scale = max(scale, 0.035)
    enhanced = 0.5 + np.clip(relief / scale, -1.0, 1.0) * 0.32
    return cv2.GaussianBlur(enhanced.astype(np.float32), (0, 0), 0.55)


def _enhance_texture_for_web(rgb: np.ndarray) -> np.ndarray:
    rgb8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(rgb8, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge([l2, a, b]), cv2.COLOR_LAB2RGB).astype(np.float32) / 255.0
    blur = cv2.GaussianBlur(enhanced, (0, 0), 1.2)
    return np.clip(enhanced * 1.25 - blur * 0.25, 0.0, 1.0)


def sync(experiment_dir: Path, output_dir: Path) -> None:
    manifest = _load_json(experiment_dir / "experiment_manifest.json")
    rows = manifest.get("rows", [])
    if not rows:
        raise RuntimeError(f"No contact-sheet rows found in {experiment_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("*.png"):
        old.unlink()
    for old in output_dir.glob("*.png.import"):
        old.unlink()

    shutil.copy2(experiment_dir / "surface_mask.png", output_dir / "surface_mask.png")
    if (experiment_dir / "contact_sheet.png").exists():
        shutil.copy2(experiment_dir / "contact_sheet.png", output_dir / "contact_sheet.png")
    for optional in ["baseline_rgb.png", "baseline_relief.png", "baseline_foreground_mask.png"]:
        src = experiment_dir / optional
        if src.exists():
            shutil.copy2(src, output_dir / optional)

    frames: list[dict[str, Any]] = []
    for out_index, row in enumerate(rows, start=1):
        stem = f"{out_index:06d}"
        rgb = _enhance_texture_for_web(_read_rgb(experiment_dir / row["clean_rgb"]))
        fused = _enhance_depth_for_web(_read_gray(experiment_dir / row["fused"]))
        occlusion = _read_gray(experiment_dir / row["occlusion"])
        persistent = _read_gray(experiment_dir / row["persistent"])
        baseline_relief = _read_gray(experiment_dir / row["baseline_relief"])
        _save_rgb(output_dir / f"clean_rgb_{stem}.png", rgb)
        _save_gray(output_dir / f"detail_depth_fused_{stem}.png", fused)
        _save_gray(output_dir / f"clean_depth_{stem}.png", fused)
        _save_gray(output_dir / f"occlusion_mask_{stem}.png", occlusion)
        _save_gray(output_dir / f"persistent_change_{stem}.png", persistent)
        _save_gray(output_dir / f"baseline_relief_{stem}.png", baseline_relief)
        if "overlay" in row:
            shutil.copy2(experiment_dir / row["overlay"], output_dir / f"mask_overlay_{stem}.png")
        frames.append({
            "frameIndex": int(row["frameIndex"]),
            "time": float(row["time"]),
            "cleanRgb": f"clean_rgb_{stem}.png",
            "cleanDepth": f"clean_depth_{stem}.png",
            "detailDepth": f"detail_depth_fused_{stem}.png",
            "occlusionMask": f"occlusion_mask_{stem}.png",
            "maskOverlay": f"mask_overlay_{stem}.png",
            "baselineRelief": f"baseline_relief_{stem}.png",
            "persistentChange": f"persistent_change_{stem}.png",
            "occlusionPixels": int(np.count_nonzero(occlusion > 0.5)),
        })

    duration = float(frames[-1]["time"])
    session_id = "7969C412-E9DB-4666-8C48-11312A750035_fused_experiment"
    session_res = f"res://assets/processed_sessions/session_{session_id}"
    last = len(frames)
    _save_json(output_dir / "session.json", {
        "id": f"production_{session_id}",
        "title": "Production v2 Fused RGB/LiDAR Experiment",
        "duration": duration,
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{session_res}/detail_depth_fused_{last:06d}.png",
            "detail_depth_map": f"{session_res}/detail_depth_fused_{last:06d}.png",
            "texture_map": f"{session_res}/clean_rgb_{last:06d}.png",
            "surface_mask": f"{session_res}/surface_mask.png",
            "occlusion_mask": f"{session_res}/occlusion_mask_{last:06d}.png",
            "processed_manifest": f"{session_res}/processed_manifest.json",
            "audio": "",
            "calibration": {
                "depth_uv_offset": [0.0, 0.0],
                "texture_uv_offset": [0.0, 0.0],
                "depth_uv_scale": [1.0, 1.0],
                "texture_uv_scale": [1.0, 1.0],
                "height_scale": 2.15,
                "material_strength": 0.82,
            },
        },
        "production_session": {
            "schemaVersion": 1,
            "deviceModel": "iPad",
            "sourceFolder": "res://assets/sessions/session_7969C412-E9DB-4666-8C48-11312A750035",
            "processedFrameCount": len(frames),
            "experiment": "fixed_camera_conservative_contact_stride6_web",
        },
        "gesture_events": [],
        "study_tasks": [{"id": "fused_surface_review", "prompt": "Review conservative-contact fused RGB/LiDAR displacement."}],
    })
    _save_json(output_dir / "processed_manifest.json", {
        "sourceSession": manifest.get("sourceSession", ""),
        "sourceExperiment": str(experiment_dir),
        "sessionId": session_id,
        "captureFormat": "fixed_camera_fused_experiment",
        "frameSize": {"width": 960, "height": 720},
        "method": "fixed_camera_conservative_contact_stride6_web",
        "notes": manifest.get("notes", []) + ["Synced with conservative contact traces and Web contrast enhancement."],
        "surfaceMask": "surface_mask.png",
        "contactSheet": "contact_sheet.png",
        "frames": frames,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    sync(args.experiment_dir.resolve(), args.output_dir.resolve())
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
