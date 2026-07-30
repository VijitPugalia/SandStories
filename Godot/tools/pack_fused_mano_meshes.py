#!/usr/bin/env python3
"""Pack fused MANO NPZ frames into deterministic gzip binary playback meshes."""

from __future__ import annotations

import argparse
import bisect
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
    parser.add_argument("--fusion-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--maximum-interpolation-gap", type=int, default=8)
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


def main() -> None:
    args = _parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_dir}")
    fusion_report_path = args.fusion_dir / "hamer_rgbd_fusion_report.json"
    fusion_report = json.loads(fusion_report_path.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True)
    shutil.copy2(
        fusion_report_path,
        args.output_dir / fusion_report_path.name,
    )

    records: list[dict[str, Any]] = []
    arrays_by_frame: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for frame in fusion_report["frames"]:
        frame_index = int(frame["frameIndex"])
        arrays_path = args.fusion_dir / str(frame["npz"])
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
        mesh_name = f"mano_rgbd_mesh_{frame_index:06d}.meshbin.gz"
        mesh_path = args.output_dir / mesh_name
        _write_binary_mesh(
            mesh_path, frame_index, vertices, normals, faces
        )
        arrays_by_frame[frame_index] = (vertices, normals, faces)
        records.append(
            {
                "frameIndex": frame_index,
                "mesh": mesh_name,
                "meshSha256": _sha256(mesh_path),
                "compressedBytes": mesh_path.stat().st_size,
                "sourceNpz": arrays_path.name,
                "sourceNpzSha256": _sha256(arrays_path),
                "vertices": 778,
                "faces": 1538,
            }
        )
        print(f"frame {frame_index}: {mesh_name}")

    actual_frame_indices = sorted(arrays_by_frame)
    skipped_frame_indices = {
        int(frame["frameIndex"])
        for frame in fusion_report.get("skippedFrames", [])
    }
    interpolated_count = 0
    for frame_index in sorted(skipped_frame_indices):
        position = bisect.bisect_left(actual_frame_indices, frame_index)
        if position == 0 or position == len(actual_frame_indices):
            continue
        before_index = actual_frame_indices[position - 1]
        after_index = actual_frame_indices[position]
        gap = after_index - before_index
        missing_between = set(range(before_index + 1, after_index))
        if (
            gap > args.maximum_interpolation_gap
            or not missing_between.issubset(skipped_frame_indices)
        ):
            continue
        before_vertices, before_normals, before_faces = arrays_by_frame[
            before_index
        ]
        after_vertices, after_normals, after_faces = arrays_by_frame[
            after_index
        ]
        if not np.array_equal(before_faces, after_faces):
            raise ValueError(
                f"MANO topology changed between {before_index} and {after_index}"
            )
        alpha = (frame_index - before_index) / gap
        vertices = (
            (1.0 - alpha) * before_vertices + alpha * after_vertices
        ).astype(np.float32)
        normals = (
            (1.0 - alpha) * before_normals + alpha * after_normals
        ).astype(np.float32)
        normal_lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        normals /= np.maximum(normal_lengths, 1.0e-8)
        mesh_name = f"mano_rgbd_mesh_{frame_index:06d}.meshbin.gz"
        mesh_path = args.output_dir / mesh_name
        _write_binary_mesh(
            mesh_path, frame_index, vertices, normals, before_faces
        )
        records.append(
            {
                "frameIndex": frame_index,
                "mesh": mesh_name,
                "meshSha256": _sha256(mesh_path),
                "compressedBytes": mesh_path.stat().st_size,
                "interpolated": True,
                "interpolatedFromFrameIndices": [
                    before_index,
                    after_index,
                ],
                "interpolationAlpha": float(alpha),
                "vertices": 778,
                "faces": 1538,
            }
        )
        interpolated_count += 1
        print(
            f"frame {frame_index}: {mesh_name} "
            f"(interpolated {before_index}->{after_index})"
        )

    records.sort(key=lambda record: int(record["frameIndex"]))
    report = {
        "schemaVersion": 1,
        "format": "MNRB v1 + deterministic gzip",
        "frameCount": len(records),
        "actualFusedFrameCount": len(actual_frame_indices),
        "interpolatedFrameCount": interpolated_count,
        "maximumInterpolationGap": args.maximum_interpolation_gap,
        "compressedBytes": sum(
            int(record["compressedBytes"]) for record in records
        ),
        "fusionReport": fusion_report_path.name,
        "fusionReportSha256": _sha256(fusion_report_path),
        "frames": records,
    }
    report_path = args.output_dir / "packed_mano_mesh_report.json"
    _write_json(report_path, report)
    print(
        f"wrote {report_path}: {len(records)} frames, "
        f"{report['compressedBytes']} bytes"
    )


if __name__ == "__main__":
    main()
