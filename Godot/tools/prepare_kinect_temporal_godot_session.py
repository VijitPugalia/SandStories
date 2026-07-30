#!/usr/bin/env python3
"""Package an official-registered temporal Kinect reconstruction as a Godot session."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    shutil.copy2(src, dst)


def _write_mask(depth_png: Path, dst: Path) -> int:
    depth = Image.open(depth_png).convert("L")
    mask = depth.point(lambda value: 255 if value > 0 else 0)
    mask.save(dst)
    histogram = mask.histogram()
    return int(sum(histogram[1:]))


def package_session(
    temporal_dir: Path,
    project_dir: Path,
    session_id: str,
    *,
    height_scale: float,
    material_strength: float,
) -> Path:
    manifest_path = temporal_dir / "temporal_surface_mesh_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = source_manifest.get("outputs", {})

    required = {
        "rgb": "clean_rgb_000001.png",
        "metric_depth": "clean_depth_000001.png",
        "detail_depth": "detail_depth_000001.png",
        "metric_shade": "shaded_depth_000001.png",
    }

    output_dir = project_dir / "assets" / "processed_sessions" / f"session_{session_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.png", "*.json"):
        for old in output_dir.glob(pattern):
            old.unlink()

    copied: dict[str, str] = {}
    for key, target_name in required.items():
        source_name = outputs.get(key)
        if not source_name:
            raise KeyError(f"temporal manifest missing outputs.{key}")
        _copy(temporal_dir / source_name, output_dir / target_name)
        copied[key] = target_name

    surface_pixels = _write_mask(output_dir / copied["metric_depth"], output_dir / "surface_mask.png")
    _copy(output_dir / "surface_mask.png", output_dir / "valid_mask_000001.png")

    contact_sheet = outputs.get("contactSheet")
    if contact_sheet and (temporal_dir / contact_sheet).exists():
        _copy(temporal_dir / contact_sheet, output_dir / "source_contact_sheet.png")

    mesh_name = outputs.get("metricMesh")
    if mesh_name and (temporal_dir / mesh_name).exists():
        shutil.copy2(temporal_dir / mesh_name, output_dir / mesh_name)

    rel_output = f"res://assets/processed_sessions/session_{session_id}"
    processed_manifest = {
        "sourceSession": str(temporal_dir),
        "sessionId": session_id,
        "captureFormat": "kinect_official_registered_temporal_surface",
        "registeredToRgb": True,
        "depthEncoding": {
            "source": "libfreenect FREENECT_DEPTH_REGISTERED temporal median smooth metric depth",
            "units": "meters normalized to Godot height PNG",
            "rgbAligned": True,
            "note": "Depth is official libfreenect registered depth in RGB pixel coordinates. RGB is used as texture/material evidence, not as metric depth.",
        },
        "sourceTemporalManifest": source_manifest,
        "frameSize": {"width": Image.open(output_dir / copied["rgb"]).width, "height": Image.open(output_dir / copied["rgb"]).height},
        "sourceFrameCount": int(source_manifest.get("framesFused", 1)),
        "processedFrameCount": 1,
        "surfaceMask": "surface_mask.png",
        "frames": [
            {
                "frameIndex": 0,
                "time": 0.0,
                "cleanRgb": copied["rgb"],
                "cleanDepth": copied["metric_depth"],
                "detailDepth": copied["detail_depth"],
                "shadedDepth": copied["metric_shade"],
                "occlusionMask": "valid_mask_000001.png",
                "surfacePixels": surface_pixels,
            }
        ],
    }
    _save_json(output_dir / "processed_manifest.json", processed_manifest)

    godot_session = {
        "id": session_id,
        "title": "Kinect Official Registered Latest Temporal Smooth Sand Reconstruction",
        "duration": 0.0,
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{rel_output}/{copied['metric_depth']}",
            "detail_depth_map": f"{rel_output}/{copied['detail_depth']}",
            "texture_map": f"{rel_output}/{copied['rgb']}",
            "surface_mask": f"{rel_output}/surface_mask.png",
            "occlusion_mask": f"{rel_output}/valid_mask_000001.png",
            "processed_manifest": f"{rel_output}/processed_manifest.json",
            "audio": "",
            "calibration": {
                "depth_uv_offset": [0.0, 0.0],
                "texture_uv_offset": [0.0, 0.0],
                "depth_uv_scale": [1.0, 1.0],
                "texture_uv_scale": [1.0, 1.0],
                "height_scale": height_scale,
                "material_strength": material_strength,
            },
        },
        "production_session": {
            "schemaVersion": 1,
            "deviceModel": "Kinect v1",
            "processedFrameCount": 1,
            "captureFormat": "kinect_official_registered_temporal_surface",
            "registeredToRgb": True,
            "source": str(temporal_dir),
        },
        "gesture_events": [],
        "study_tasks": [
            {
                "id": "kinect_surface_review",
                "prompt": "Review Kinect official-registered temporal smooth reconstruction of sand relief.",
            }
        ],
    }
    _save_json(output_dir / "session.json", godot_session)
    return output_dir / "session.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("temporal_dir", type=Path)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--session-id", default="kinect_latest_temporal_smooth_godot")
    parser.add_argument("--height-scale", type=float, default=-3.2)
    parser.add_argument("--material-strength", type=float, default=0.72)
    args = parser.parse_args()
    print(
        package_session(
            args.temporal_dir.resolve(),
            args.project.resolve(),
            args.session_id,
            height_scale=args.height_scale,
            material_strength=args.material_strength,
        )
    )


if __name__ == "__main__":
    main()
