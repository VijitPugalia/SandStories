#!/usr/bin/env python3
"""Repair unreliable temporal surface anchors in a fused MANO RGB-D sequence.

The rigid RGB-D fusion stores one measured sand-surface Y anchor per frame.
When most projected hand vertices leave the reconstructed tray support, nearest
support sampling can switch from the sand top to a tray rim or background mode.
This tool keeps every reliable measured anchor unchanged and only replaces
low-support anchors by interpolation (or a one-sided hold at a segment end).
Missing source frames remain missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from fuse_hamer_mano_with_rgbd import _write_obj


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fusion-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-frame", type=int)
    parser.add_argument("--maximum-frame", type=int)
    parser.add_argument(
        "--minimum-direct-vertex-ratio",
        type=float,
        default=0.80,
    )
    parser.add_argument(
        "--maximum-nearest-distance-p50-pixels",
        type=float,
        default=0.50,
    )
    parser.add_argument(
        "--minimum-visible-supported-vertices",
        type=int,
        default=20,
    )
    parser.add_argument("--image-width", type=int, default=640)
    parser.add_argument("--image-height", type=int, default=480)
    parser.add_argument(
        "--asset-mode",
        choices=("hardlink", "copy"),
        default="hardlink",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _materialize(source: Path, destination: Path, mode: str) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    if mode == "hardlink":
        os.link(source, destination)
    else:
        shutil.copy2(source, destination)


def _consecutive_segments(frame_indices: list[int]) -> list[list[int]]:
    segments: list[list[int]] = []
    for frame_index in sorted(frame_indices):
        if not segments or frame_index != segments[-1][-1] + 1:
            segments.append([frame_index])
        else:
            segments[-1].append(frame_index)
    return segments


def _in_requested_range(
    frame_index: int,
    minimum_frame: int | None,
    maximum_frame: int | None,
) -> bool:
    return (
        (minimum_frame is None or frame_index >= minimum_frame)
        and (maximum_frame is None or frame_index <= maximum_frame)
    )


def _anchor_reliability(
    record: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    anchor = record.get("surfaceAnchorWorldY")
    if anchor is None or not np.isfinite(float(anchor)):
        reasons.append("missing_or_nonfinite_anchor")
    direct_ratio = float(record.get("surfaceMaskDirectVertexRatio", 0.0))
    if direct_ratio < args.minimum_direct_vertex_ratio:
        reasons.append("low_direct_surface_support")
    distances = record.get("surfaceMaskNearestDistancePixelsP50P90P95", [])
    distance_p50 = float(distances[0]) if distances else float("inf")
    if distance_p50 > args.maximum_nearest_distance_p50_pixels:
        reasons.append("distant_nearest_surface_support")
    visible_vertices = int(record.get("visibleSupportedVertices", 0))
    if visible_vertices < args.minimum_visible_supported_vertices:
        reasons.append("insufficient_visible_rgbd_support")
    return not reasons, reasons


def _replacement_anchors(
    records_by_frame: dict[int, dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[dict[int, float], dict[int, dict[str, Any]]]:
    replacements: dict[int, float] = {}
    decisions: dict[int, dict[str, Any]] = {}
    frame_indices = sorted(records_by_frame)
    reliable: dict[int, bool] = {}
    reasons_by_frame: dict[int, list[str]] = {}
    for frame_index, record in records_by_frame.items():
        is_reliable, reasons = _anchor_reliability(record, args)
        reliable[frame_index] = is_reliable
        reasons_by_frame[frame_index] = reasons

    for segment in _consecutive_segments(frame_indices):
        reliable_frames = [
            frame_index for frame_index in segment if reliable[frame_index]
        ]
        for frame_index in segment:
            if not _in_requested_range(
                frame_index,
                args.minimum_frame,
                args.maximum_frame,
            ):
                continue
            raw_anchor = records_by_frame[frame_index].get(
                "surfaceAnchorWorldY"
            )
            if reliable[frame_index]:
                decisions[frame_index] = {
                    "reliable": True,
                    "reasons": [],
                    "method": "measured_anchor_unchanged",
                    "sourceFrameIndices": [frame_index],
                }
                continue

            before = [
                candidate
                for candidate in reliable_frames
                if candidate < frame_index
            ]
            after = [
                candidate
                for candidate in reliable_frames
                if candidate > frame_index
            ]
            before_frame = before[-1] if before else None
            after_frame = after[0] if after else None
            source_frames: list[int]
            if before_frame is not None and after_frame is not None:
                before_anchor = float(
                    records_by_frame[before_frame]["surfaceAnchorWorldY"]
                )
                after_anchor = float(
                    records_by_frame[after_frame]["surfaceAnchorWorldY"]
                )
                alpha = (frame_index - before_frame) / (
                    after_frame - before_frame
                )
                replacement = (
                    (1.0 - alpha) * before_anchor + alpha * after_anchor
                )
                method = "linear_between_reliable_measured_anchors"
                source_frames = [before_frame, after_frame]
            elif before_frame is not None:
                replacement = float(
                    records_by_frame[before_frame]["surfaceAnchorWorldY"]
                )
                method = "hold_previous_reliable_measured_anchor"
                source_frames = [before_frame]
            elif after_frame is not None:
                replacement = float(
                    records_by_frame[after_frame]["surfaceAnchorWorldY"]
                )
                method = "hold_next_reliable_measured_anchor"
                source_frames = [after_frame]
            else:
                decisions[frame_index] = {
                    "reliable": False,
                    "reasons": reasons_by_frame[frame_index],
                    "method": "unmodified_no_reliable_anchor_in_segment",
                    "sourceFrameIndices": [],
                }
                continue

            replacements[frame_index] = replacement
            decisions[frame_index] = {
                "reliable": False,
                "reasons": reasons_by_frame[frame_index],
                "method": method,
                "sourceFrameIndices": source_frames,
                "rawAnchorWorldY": (
                    None if raw_anchor is None else float(raw_anchor)
                ),
                "replacementAnchorWorldY": float(replacement),
            }
    return replacements, decisions


def main() -> None:
    args = _parse_args()
    args.fusion_dir = args.fusion_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    if args.output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_dir}")
    if (
        args.minimum_frame is not None
        and args.maximum_frame is not None
        and args.minimum_frame > args.maximum_frame
    ):
        raise ValueError("--minimum-frame exceeds --maximum-frame")
    if not 0.0 <= args.minimum_direct_vertex_ratio <= 1.0:
        raise ValueError("--minimum-direct-vertex-ratio must be in [0, 1]")
    if args.maximum_nearest_distance_p50_pixels < 0.0:
        raise ValueError(
            "--maximum-nearest-distance-p50-pixels must be non-negative"
        )
    if args.minimum_visible_supported_vertices < 1:
        raise ValueError(
            "--minimum-visible-supported-vertices must be positive"
        )

    source_report_path = (
        args.fusion_dir / "hamer_rgbd_fusion_report.json"
    )
    source_report = json.loads(
        source_report_path.read_text(encoding="utf-8")
    )
    if source_report.get("liftFusionMode") != "mano_rigid_offset":
        raise ValueError(
            "Surface-anchor repair requires mano_rigid_offset fusion"
        )
    records_by_frame = {
        int(record["frameIndex"]): record
        for record in source_report["frames"]
    }
    replacements, decisions = _replacement_anchors(
        records_by_frame,
        args,
    )

    args.output_dir.mkdir(parents=True)
    material_name = "hamer_rgbd_fused.mtl"
    material_source = args.fusion_dir / material_name
    if material_source.exists():
        _materialize(
            material_source,
            args.output_dir / material_name,
            args.asset_mode,
        )

    output_records: list[dict[str, Any]] = []
    applied_corrections: list[dict[str, Any]] = []
    for source_record in source_report["frames"]:
        frame_index = int(source_record["frameIndex"])
        output_record = dict(source_record)
        source_npz = args.fusion_dir / str(source_record["npz"])
        source_obj = args.fusion_dir / str(source_record["obj"])
        output_npz = args.output_dir / source_npz.name
        output_obj = args.output_dir / source_obj.name
        decision = decisions.get(frame_index)
        if decision is not None:
            output_record["temporalSurfaceAnchorDecision"] = decision

        replacement = replacements.get(frame_index)
        raw_anchor_value = source_record.get("surfaceAnchorWorldY")
        raw_anchor = (
            None if raw_anchor_value is None else float(raw_anchor_value)
        )
        if (
            replacement is None
            or raw_anchor is None
            or np.isclose(replacement, raw_anchor, rtol=0.0, atol=1.0e-12)
        ):
            _materialize(source_npz, output_npz, args.asset_mode)
            _materialize(source_obj, output_obj, args.asset_mode)
        else:
            delta_world_y = float(replacement - raw_anchor)
            with np.load(source_npz) as source_arrays:
                arrays = {
                    key: source_arrays[key] for key in source_arrays.files
                }
            vertices = arrays["vertices_world"].astype(
                np.float32,
                copy=True,
            )
            vertices[:, 1] += np.float32(delta_world_y)
            arrays["vertices_world"] = vertices
            np.savez_compressed(output_npz, **arrays)
            _write_obj(
                output_obj,
                vertices,
                arrays["faces"].astype(np.int32),
                arrays["image_uv"].astype(np.float32),
                arrays["normals"].astype(np.float32),
                args.image_width,
                args.image_height,
            )
            output_record["surfaceAnchorWorldYRaw"] = raw_anchor
            output_record["surfaceAnchorWorldY"] = float(replacement)
            output_record["surfaceHeightPolicy"] = (
                "temporally_repaired_reliable_measured_anchor"
            )
            minimum = np.asarray(
                source_record["worldBoundsMinimum"],
                dtype=np.float64,
            )
            maximum = np.asarray(
                source_record["worldBoundsMaximum"],
                dtype=np.float64,
            )
            minimum[1] += delta_world_y
            maximum[1] += delta_world_y
            output_record["worldBoundsMinimum"] = minimum.tolist()
            output_record["worldBoundsMaximum"] = maximum.tolist()
            applied_corrections.append(
                {
                    "frameIndex": frame_index,
                    "rawAnchorWorldY": raw_anchor,
                    "replacementAnchorWorldY": float(replacement),
                    "deltaWorldY": delta_world_y,
                    "method": decision["method"] if decision else None,
                    "sourceFrameIndices": (
                        decision["sourceFrameIndices"] if decision else []
                    ),
                }
            )

        output_record["npzSha256"] = _sha256(output_npz)
        output_record["objSha256"] = _sha256(output_obj)
        output_records.append(output_record)
        print(
            f"frame {frame_index}: "
            + (
                f"anchor {raw_anchor:.6f} -> {replacement:.6f}"
                if replacement is not None
                and raw_anchor is not None
                and not np.isclose(
                    replacement,
                    raw_anchor,
                    rtol=0.0,
                    atol=1.0e-12,
                )
                else "measured anchor unchanged"
            )
        )

    correction_deltas = np.asarray(
        [abs(record["deltaWorldY"]) for record in applied_corrections],
        dtype=np.float64,
    )
    output_report = dict(source_report)
    output_report.update(
        {
            "method": (
                str(source_report["method"])
                + "; unreliable rigid sand-surface anchors are replaced "
                "only by interpolation or endpoint hold from reliable "
                "measured anchors within the same consecutive source segment"
            ),
            "sourceFusionReport": str(source_report_path),
            "sourceFusionReportSha256": _sha256(source_report_path),
            "surfaceSamplingPolicy": (
                str(source_report["surfaceSamplingPolicy"])
                + "; temporal post-pass preserves every reliable measured "
                "anchor and rejects low-support nearest-surface mode switches"
            ),
            "temporalSurfaceAnchorPolicy": {
                "minimumFrame": args.minimum_frame,
                "maximumFrame": args.maximum_frame,
                "minimumDirectVertexRatio": (
                    args.minimum_direct_vertex_ratio
                ),
                "maximumNearestDistanceP50Pixels": (
                    args.maximum_nearest_distance_p50_pixels
                ),
                "minimumVisibleSupportedVertices": (
                    args.minimum_visible_supported_vertices
                ),
                "missingSourceFramesPreserved": True,
                "reliableMeasuredAnchorsModified": False,
                "correctedFrameCount": len(applied_corrections),
                "correctedFrameIndices": [
                    record["frameIndex"]
                    for record in applied_corrections
                ],
                "absoluteCorrectionWorldYP50P90P95Maximum": (
                    [
                        float(value)
                        for value in np.percentile(
                            correction_deltas,
                            [50, 90, 95, 100],
                        )
                    ]
                    if correction_deltas.size
                    else [0.0, 0.0, 0.0, 0.0]
                ),
                "corrections": applied_corrections,
            },
            "frames": output_records,
        }
    )
    output_report_path = (
        args.output_dir / "hamer_rgbd_fusion_report.json"
    )
    _write_json(output_report_path, output_report)
    print(output_report_path)
    print(
        f"corrected {len(applied_corrections)} / "
        f"{len(output_records)} fused frames"
    )


if __name__ == "__main__":
    main()
