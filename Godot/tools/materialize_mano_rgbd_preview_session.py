#!/usr/bin/env python3
"""Build a compact Godot preview session from fused MANO RGB-D meshes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--fusion-dir", type=Path, required=True)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument("--preview-fps", type=float, default=1.0)
    parser.add_argument(
        "--mesh-format",
        choices=("json", "binary_gzip"),
        default="json",
        help="binary_gzip avoids per-frame JSON parsing and is preferred for playback",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _flatten_rounded(values: np.ndarray, decimals: int = 8) -> list[float]:
    return np.round(values.astype(np.float64), decimals=decimals).reshape(-1).tolist()


def _write_binary_mesh(
    path: Path,
    frame_index: int,
    vertices: np.ndarray,
    normals: np.ndarray,
    faces: np.ndarray,
) -> None:
    indices = faces.astype("<u4", copy=False).reshape(-1)
    header = struct.pack(
        "<4sIIII",
        b"MNRB",
        1,
        int(vertices.shape[0]),
        int(indices.size),
        frame_index,
    )
    payload = b"".join(
        (
            header,
            vertices.astype("<f4", copy=False).tobytes(order="C"),
            normals.astype("<f4", copy=False).tobytes(order="C"),
            indices.tobytes(order="C"),
        )
    )
    path.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))


def main() -> None:
    args = _parse_args()
    if args.preview_fps <= 0.0:
        raise ValueError("--preview-fps must be positive")
    if args.output_session.exists():
        raise FileExistsError(
            f"Refusing to overwrite preview session: {args.output_session}"
        )

    source_root = args.source_session.parent
    source_session = json.loads(args.source_session.read_text(encoding="utf-8"))
    source_manifest_path = source_root / "processed_manifest.json"
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    source_by_depth = {
        str(frame["cleanDepth"]): frame for frame in source_manifest["frames"]
    }
    fusion_report_path = args.fusion_dir / "hamer_rgbd_fusion_report.json"
    fusion_report = json.loads(fusion_report_path.read_text(encoding="utf-8"))
    lift_fusion_mode = str(fusion_report.get("liftFusionMode", "per_vertex"))

    args.output_session.mkdir(parents=True)
    asset_prefix = (
        "res://assets/processed_sessions/" + args.output_session.name
    )
    output_frames: list[dict[str, Any]] = []
    mesh_records: list[dict[str, Any]] = []

    for preview_index, fusion_frame in enumerate(fusion_report["frames"]):
        frame_index = int(fusion_frame["frameIndex"])
        depth_name = f"clean_depth_{frame_index:06d}.png"
        if depth_name not in source_by_depth:
            raise KeyError(f"No source manifest frame for {depth_name}")
        source_frame = source_by_depth[depth_name]
        rgb_name = str(source_frame["cleanRgb"])
        for name in (rgb_name, depth_name):
            source_path = source_root / name
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            shutil.copy2(source_path, args.output_session / name)

        arrays_path = args.fusion_dir / str(fusion_frame["npz"])
        arrays = np.load(arrays_path)
        vertices = arrays["vertices_world"].astype(np.float32)
        normals = arrays["normals"].astype(np.float32)
        faces = arrays["faces"].astype(np.int32)
        if (
            vertices.shape != (778, 3)
            or normals.shape != vertices.shape
            or faces.shape != (1538, 3)
            or not np.isfinite(vertices).all()
            or not np.isfinite(normals).all()
            or faces.min() < 0
            or faces.max() >= vertices.shape[0]
        ):
            raise ValueError(f"Invalid fused MANO arrays: {arrays_path}")

        mesh_name = (
            f"mano_rgbd_mesh_{frame_index:06d}.meshbin.gz"
            if args.mesh_format == "binary_gzip"
            else f"mano_rgbd_mesh_{frame_index:06d}.json"
        )
        mesh_path = args.output_session / mesh_name
        if args.mesh_format == "binary_gzip":
            _write_binary_mesh(
                mesh_path, frame_index, vertices, normals, faces
            )
        else:
            mesh_payload = {
                "schemaVersion": 1,
                "frameIndex": frame_index,
                "vertices": _flatten_rounded(vertices),
                "normals": _flatten_rounded(normals),
                "indices": faces.reshape(-1).tolist(),
                "sourceNpz": arrays_path.name,
                "sourceNpzSha256": _sha256(arrays_path),
            }
            _write_json(mesh_path, mesh_payload)
        mesh_records.append(
            {
                "frameIndex": frame_index,
                "mesh": mesh_name,
                "meshSha256": _sha256(mesh_path),
                "encoding": args.mesh_format,
                "vertices": int(vertices.shape[0]),
                "faces": int(faces.shape[0]),
            }
        )

        output_frame = {
            key: value
            for key, value in source_frame.items()
            if key
            not in {
                "virtualHandOverlay",
                "virtualHandGeometry",
                "maskOverlay",
            }
        }
        output_frame["frameIndex"] = frame_index
        output_frame["sourceCaptureFrameIndex"] = source_frame.get("frameIndex")
        output_frame["time"] = preview_index / args.preview_fps
        output_frame["cleanRgb"] = rgb_name
        output_frame["cleanDepth"] = depth_name
        output_frame["virtualHandMesh"] = mesh_name
        output_frames.append(output_frame)

    surface_mask_name = "surface_mask.png"
    source_surface_mask = source_root / surface_mask_name
    if not source_surface_mask.is_file():
        raise FileNotFoundError(source_surface_mask)
    shutil.copy2(
        source_surface_mask, args.output_session / surface_mask_name
    )

    preview_manifest = {
        "schemaVersion": 1,
        "sessionId": args.output_session.name,
        "sourceSession": str(args.source_session.resolve()),
        "sourceSessionSha256": _sha256(args.source_session),
        "sourceProcessedManifest": str(source_manifest_path.resolve()),
        "sourceProcessedManifestSha256": _sha256(source_manifest_path),
        "fusionReport": str(fusion_report_path.resolve()),
        "fusionReportSha256": _sha256(fusion_report_path),
        "frameSize": source_manifest.get("frameSize", [640, 480]),
        "processedFrameCount": len(output_frames),
        "previewFps": args.preview_fps,
        "meshFormat": args.mesh_format,
        "surfaceMask": surface_mask_name,
        "frames": output_frames,
        "manoRgbdPreview": {
            "sharedShape": True,
            "handAuthoredMasks": False,
            "meshRecords": mesh_records,
        },
    }
    preview_manifest_path = args.output_session / "processed_manifest.json"
    _write_json(preview_manifest_path, preview_manifest)

    source_data_sources = source_session.get("data_sources", {})
    first_frame = output_frames[0]
    duration = len(output_frames) / args.preview_fps
    preview_session = {
        "id": args.output_session.name,
        "title": (
            "MANO + robust RGB-D metric anchor hard-9 preview"
            if lift_fusion_mode == "mano_rigid_offset"
            else "MANO + registered RGB-D 3D hand hard-9 preview"
        ),
        "duration": duration,
        "production_session": False,
        "data_sources": {
            "use_video_streams": False,
            "depth_map": f"{asset_prefix}/{first_frame['cleanDepth']}",
            "detail_depth_map": f"{asset_prefix}/{first_frame['cleanDepth']}",
            "texture_map": f"{asset_prefix}/{first_frame['cleanRgb']}",
            "surface_mask": f"{asset_prefix}/{surface_mask_name}",
            "processed_manifest": (
                f"{asset_prefix}/{preview_manifest_path.name}"
            ),
            "virtual_hand_mesh": (
                f"{asset_prefix}/{first_frame['virtualHandMesh']}"
            ),
            "audio": "",
            "calibration": source_data_sources.get("calibration", {}),
        },
        "gesture_events": [],
        "study_tasks": [],
        "mano_rgbd_preview": {
            "frames": [
                int(frame["frameIndex"]) for frame in output_frames
            ],
            "material": (
                "opaque warm-clay PBR; depth-write enabled; double-sided"
            ),
            "sourceFusionReportSha256": _sha256(fusion_report_path),
        },
    }
    preview_session_path = args.output_session / "session.json"
    _write_json(preview_session_path, preview_session)

    report = {
        "schemaVersion": 1,
        "outputSession": str(args.output_session.resolve()),
        "sessionJson": preview_session_path.name,
        "sessionJsonSha256": _sha256(preview_session_path),
        "processedManifest": preview_manifest_path.name,
        "processedManifestSha256": _sha256(preview_manifest_path),
        "frameCount": len(output_frames),
        "durationSeconds": duration,
        "frames": mesh_records,
        "handAuthoredMasks": False,
    }
    report_path = args.output_session / "mano_rgbd_preview_report.json"
    _write_json(report_path, report)
    print(f"wrote {preview_session_path}")
    print(f"wrote {preview_manifest_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
