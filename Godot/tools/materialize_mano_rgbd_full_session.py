#!/usr/bin/env python3
"""Build a full-timeline Godot session from robust fused MANO RGB-D meshes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import struct
from pathlib import Path
from typing import Any

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fusion-dir", type=Path)
    source.add_argument("--packed-mesh-dir", type=Path)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument(
        "--asset-mode",
        choices=("hardlink", "copy"),
        default="hardlink",
    )
    parser.add_argument(
        "--mano-material-preset",
        choices=("warm_skin_pbr_v1", "soft_peach_porcelain_v1"),
        default="warm_skin_pbr_v1",
    )
    parser.add_argument("--mano-base-color", default="#f3b49e")
    parser.add_argument("--mano-shadow-color", default="#b96f67")
    parser.add_argument("--mano-highlight-color", default="#ffe2d1")
    parser.add_argument("--mano-rim-color", default="#ffede2")
    parser.add_argument("--mano-rim-strength", type=float, default=0.32)
    parser.add_argument(
        "--mano-emission-strength",
        type=float,
        default=0.035,
    )
    parser.add_argument("--mano-roughness", type=float, default=0.72)
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


def _materialize_asset(source: Path, destination: Path, mode: str) -> None:
    if destination.exists():
        return
    if mode == "hardlink":
        try:
            os.link(source, destination)
            return
        except OSError:
            pass
    shutil.copy2(source, destination)


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
    raw = b"".join(
        (
            header,
            vertices.astype("<f4", copy=False).tobytes(order="C"),
            normals.astype("<f4", copy=False).tobytes(order="C"),
            indices.tobytes(order="C"),
        )
    )
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))


def _suffix_from_depth(frame: dict[str, Any]) -> int:
    stem = Path(str(frame["cleanDepth"])).stem
    return int(stem.rsplit("_", 1)[1])


def main() -> None:
    args = _parse_args()
    if args.output_session.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_session}")

    source_root = args.source_session.parent
    source_session = json.loads(args.source_session.read_text(encoding="utf-8"))
    source_manifest_path = source_root / "processed_manifest.json"
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    mesh_source_root = (
        args.packed_mesh_dir
        if args.packed_mesh_dir is not None
        else args.fusion_dir
    )
    fusion_report_path = mesh_source_root / "hamer_rgbd_fusion_report.json"
    fusion_report = json.loads(fusion_report_path.read_text(encoding="utf-8"))
    packed_by_frame: dict[int, dict[str, Any]] = {}
    if args.packed_mesh_dir is not None:
        packed_report_path = (
            args.packed_mesh_dir / "packed_mano_mesh_report.json"
        )
        packed_report = json.loads(
            packed_report_path.read_text(encoding="utf-8")
        )
        if packed_report["fusionReportSha256"] != _sha256(fusion_report_path):
            raise ValueError("Packed mesh/fusion report hash mismatch")
        packed_by_frame = {
            int(frame["frameIndex"]): frame
            for frame in packed_report["frames"]
        }
    fusion_by_frame = {
        int(frame["frameIndex"]): frame for frame in fusion_report["frames"]
    }
    if not fusion_by_frame:
        raise ValueError("Fusion report has no frames")

    args.output_session.mkdir(parents=True)
    mesh_records: list[dict[str, Any]] = []
    output_frames: list[dict[str, Any]] = []
    linked_assets: set[str] = set()
    for source_frame in source_manifest["frames"]:
        frame_suffix = _suffix_from_depth(source_frame)
        output_frame = {
            key: value
            for key, value in source_frame.items()
            if key
            not in {
                "virtualHandOverlay",
                "virtualHandGeometry",
                "occlusionMask",
                "maskOverlay",
            }
        }
        for key in ("cleanRgb", "cleanDepth"):
            name = str(source_frame[key])
            if name not in linked_assets:
                source_path = source_root / name
                if not source_path.is_file():
                    raise FileNotFoundError(source_path)
                _materialize_asset(
                    source_path, args.output_session / name, args.asset_mode
                )
                linked_assets.add(name)

        fusion_frame = fusion_by_frame.get(frame_suffix)
        if (
            fusion_frame is not None
            or frame_suffix in packed_by_frame
        ):
            mesh_name = f"mano_rgbd_mesh_{frame_suffix:06d}.meshbin.gz"
            mesh_path = args.output_session / mesh_name
            if args.packed_mesh_dir is not None:
                packed_record = packed_by_frame.get(frame_suffix)
                if packed_record is None:
                    raise KeyError(f"No packed mesh for frame {frame_suffix}")
                source_mesh = args.packed_mesh_dir / str(
                    packed_record["mesh"]
                )
                if _sha256(source_mesh) != packed_record["meshSha256"]:
                    raise ValueError(f"Packed mesh hash mismatch: {source_mesh}")
                _materialize_asset(source_mesh, mesh_path, args.asset_mode)
            else:
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
                    or faces.max() >= len(vertices)
                ):
                    raise ValueError(f"Invalid fused MANO arrays: {arrays_path}")
                _write_binary_mesh(
                    mesh_path, frame_suffix, vertices, normals, faces
                )
            output_frame["virtualHandMesh"] = mesh_name
            mesh_records.append(
                {
                    "frameIndex": frame_suffix,
                    "mesh": mesh_name,
                    "meshSha256": _sha256(mesh_path),
                    "compressedBytes": mesh_path.stat().st_size,
                    "vertices": 778,
                    "faces": 1538,
                }
            )
        output_frames.append(output_frame)

    surface_mask_name = "surface_mask.png"
    _materialize_asset(
        source_root / surface_mask_name,
        args.output_session / surface_mask_name,
        args.asset_mode,
    )
    manifest = dict(source_manifest)
    manifest["sessionId"] = args.output_session.name
    manifest["frames"] = output_frames
    manifest["processedFrameCount"] = len(output_frames)
    manifest["sourceSession"] = str(args.source_session.resolve())
    manifest["sourceSessionSha256"] = _sha256(args.source_session)
    manifest["sourceProcessedManifest"] = str(source_manifest_path.resolve())
    manifest["sourceProcessedManifestSha256"] = _sha256(source_manifest_path)
    manifest["fusionReport"] = str(fusion_report_path.resolve())
    manifest["fusionReportSha256"] = _sha256(fusion_report_path)
    manifest["manoRgbdFullSequence"] = {
        "meshFormat": "binary_gzip",
        "meshFrameCount": len(mesh_records),
        "handAuthoredMasks": False,
        "missingMeshPolicy": "hide hand",
    }
    manifest_path = args.output_session / "processed_manifest.json"
    _write_json(manifest_path, manifest)

    source_data_sources = source_session.get("data_sources", {})
    first_frame = output_frames[0]
    session = dict(source_session)
    session["id"] = args.output_session.name
    session["title"] = (
        "Hand-only temporally fitted MANO + calibrated RGB-D virtual hand"
    )
    session["duration"] = float(source_session["duration"])
    session["production_session"] = True
    session["data_sources"] = {
        "use_video_streams": False,
        "depth_map": str(first_frame["cleanDepth"]),
        "detail_depth_map": str(first_frame["cleanDepth"]),
        "texture_map": str(first_frame["cleanRgb"]),
        "surface_mask": surface_mask_name,
        "processed_manifest": manifest_path.name,
        "audio": "",
        "calibration": source_data_sources.get("calibration", {}),
    }
    material_parameters = {
        "baseColor": args.mano_base_color,
        "shadowColor": args.mano_shadow_color,
        "highlightColor": args.mano_highlight_color,
        "rimColor": args.mano_rim_color,
        "rimStrength": args.mano_rim_strength,
        "emissionStrength": args.mano_emission_strength,
        "roughness": args.mano_roughness,
    }
    session["mano_rgbd_full_sequence"] = {
        "sourceFrameCount": len(output_frames),
        "meshFrameCount": len(mesh_records),
        "meshFormat": "MNRB v1 + deterministic gzip",
        "material": (
            "opaque session-colored porcelain hand shader; depth-write "
            "enabled; double-sided; normal-sign-stable"
            if args.mano_material_preset == "soft_peach_porcelain_v1"
            else "opaque warm skin-tone PBR; depth-write enabled; double-sided"
        ),
        "materialPreset": args.mano_material_preset,
        "materialParameters": material_parameters,
        "sourceFusionReportSha256": _sha256(fusion_report_path),
    }
    session_path = args.output_session / "session.json"
    _write_json(session_path, session)

    report = {
        "schemaVersion": 1,
        "outputSession": str(args.output_session.resolve()),
        "sourceFrameCount": len(output_frames),
        "meshFrameCount": len(mesh_records),
        "durationSeconds": float(session["duration"]),
        "meshCompressedBytes": sum(
            int(record["compressedBytes"]) for record in mesh_records
        ),
        "assetMode": args.asset_mode,
        "handAuthoredMasks": False,
        "manoMaterialPreset": args.mano_material_preset,
        "manoMaterialParameters": material_parameters,
        "sessionJsonSha256": _sha256(session_path),
        "processedManifestSha256": _sha256(manifest_path),
        "frames": mesh_records,
    }
    report_path = args.output_session / "mano_rgbd_full_report.json"
    _write_json(report_path, report)
    print(
        f"wrote {args.output_session}: {len(output_frames)} source frames, "
        f"{len(mesh_records)} MANO meshes, duration {session['duration']:.6f} s"
    )


if __name__ == "__main__":
    main()
