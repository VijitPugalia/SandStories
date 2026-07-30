#!/usr/bin/env python3
"""Clone a processed session and attach depth-reprojected MediaPipe hand tracks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


PALM_ANCHORS = (0, 5, 9, 13, 17)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def rewrite_resource_paths(value: Any, source_name: str, output_name: str) -> Any:
    if isinstance(value, dict):
        return {
            key: rewrite_resource_paths(item, source_name, output_name)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            rewrite_resource_paths(item, source_name, output_name)
            for item in value
        ]
    if isinstance(value, str):
        prefix = f"res://assets/processed_sessions/{source_name}/"
        if value.startswith(prefix):
            return (
                f"res://assets/processed_sessions/{output_name}/"
                + value[len(prefix) :]
            )
    return value


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(np.median(np.asarray(values, dtype=np.float64)))


def parse_frame_range(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"expected START:END frame range, got {value!r}"
        )
    try:
        start, end = (int(item) for item in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected integer START:END, got {value!r}"
        ) from exc
    if start < 0 or end < start:
        raise argparse.ArgumentTypeError(
            f"invalid frame range {value!r}"
        )
    return start, end


def in_frame_ranges(
    frame_index: int,
    ranges: list[tuple[int, int]],
) -> bool:
    return any(start <= frame_index <= end for start, end in ranges)


def point_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))


def smoothstep(edge_0: float, edge_1: float, value: float) -> float:
    if edge_1 <= edge_0:
        return float(value >= edge_1)
    t = max(0.0, min(1.0, (value - edge_0) / (edge_1 - edge_0)))
    return t * t * (3.0 - 2.0 * t)


def depth_profile(depth_name: str) -> tuple[float, float, float, float]:
    if depth_name.startswith("detail_depth_fused_"):
        return 3.4, 0.5, 0.012, 0.11
    if depth_name.startswith("detail_depth_"):
        return 3.0, 0.5, 0.004, 0.08
    return 11.625, 1.0, 0.08, 0.415


def sample_shader_surface_y(
    depth: np.ndarray,
    pixel_x: float,
    pixel_y: float,
    depth_name: str,
    height_scale: float,
    baseline_height_correction: float,
) -> float:
    height, width = depth.shape
    x = max(0, min(width - 1, int(round(pixel_x))))
    y = max(0, min(height - 1, int(round(pixel_y))))
    x_1 = max(0, x - 1)
    x_2 = min(width, x + 2)
    y_1 = max(0, y - 1)
    y_2 = min(height, y + 2)
    value = float(np.mean(depth[y_1:y_2, x_1:x_2]))
    arg_1, background, eps_0, eps_1 = depth_profile(depth_name)
    keep = smoothstep(eps_0, eps_1, abs(value - background))
    filtered = background * (1.0 - keep) + value * keep
    filtered += baseline_height_correction / 255.0
    return -(filtered / arg_1) * height_scale


def sample_pixels(
    sample: dict[str, Any],
    points: list[list[float]],
    plane_size: float,
    width: int,
    height: int,
) -> list[list[float]]:
    raw = sample.get("pixelLandmarks", [])
    if isinstance(raw, list) and len(raw) >= len(points):
        return [
            [float(pixel[0]), float(pixel[1])]
            for pixel in raw[: len(points)]
        ]
    return [
        [
            (float(point[0]) / plane_size + 0.5) * float(width - 1),
            (float(point[2]) / plane_size + 0.5) * float(height - 1),
        ]
        for point in points
    ]


def reproject_tracks(
    source_tracks: dict[str, Any],
    source_session: Path,
    manifest: dict[str, Any],
    session: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    frames = manifest.get("frames", [])
    if not isinstance(frames, list) or not frames:
        raise ValueError("processed manifest has no frames")
    tracks = source_tracks.get("hand_tracks", [])
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("source track sidecar has no hand_tracks")

    calibration = session.get("data_sources", {}).get("calibration", {})
    height_scale = float(calibration.get("height_scale", -5.0))
    plane_size = float(source_tracks.get("planeSize", args.plane_size))
    depth_cache: dict[int, np.ndarray] = {}
    depth_size: dict[int, tuple[int, int]] = {}
    projected_tracks: list[dict[str, Any]] = []
    projected_samples = 0
    all_y_values: list[float] = []
    intent_counts: dict[str, int] = {}
    contact_mode_counts: dict[str, int] = {}
    contact_shifts: list[float] = []
    clearance_shifts: list[float] = []
    clearance_adjusted_points = 0
    clearance_shifted_samples = 0
    rig_span_references: list[float] = []
    tool_contact_samples = 0

    for source_track in tracks:
        if not isinstance(source_track, dict):
            continue
        track = {
            key: value
            for key, value in source_track.items()
            if key != "samples"
        }
        track.update(
            {
                "color": args.color,
                "virtual_hand": True,
                "virtual_hand_style": args.style,
                "show_landmarks": False,
                "show_skeleton": False,
                "show_mesh_ghost": False,
                "interpolation": "linear",
                "max_gap_seconds": args.max_gap_seconds,
                "endpoint_hold_seconds": args.endpoint_hold_seconds,
            }
        )
        if args.handedness:
            track["handedness"] = args.handedness
        if "humanoid" in args.style.lower():
            track["use_rigged_hand"] = True
        output_samples: list[dict[str, Any]] = []
        reference_span_candidates: list[float] = []
        all_span_candidates: list[float] = []
        track_has_tool = False

        for source_sample in source_track.get("samples", []):
            if not isinstance(source_sample, dict):
                continue
            frame_index = int(source_sample.get("frameIndex", -1))
            if frame_index < 0 or frame_index >= len(frames):
                continue
            points = [
                [float(value) for value in point[:3]]
                for point in source_sample.get("landmarks", [])
                if isinstance(point, list) and len(point) >= 3
            ]
            if len(points) < 21:
                continue
            intent = str(source_sample.get("intent", "positioning")).lower()
            if (
                intent == "drawing"
                and in_frame_ranges(
                    frame_index,
                    args.tool_drawing_frame_range,
                )
            ):
                intent = "tool_drawing"

            frame = frames[frame_index]
            depth_name = str(
                frame.get("detailDepth", frame.get("cleanDepth", ""))
            )
            depth_path = source_session / depth_name
            if not depth_path.is_file():
                raise FileNotFoundError(depth_path)
            if frame_index not in depth_cache:
                image = Image.open(depth_path).convert("L")
                width, height = image.size
                depth_cache[frame_index] = (
                    np.asarray(image, dtype=np.float32) / 255.0
                )
                depth_size[frame_index] = (width, height)
            depth = depth_cache[frame_index]
            width, height = depth_size[frame_index]
            pixels = sample_pixels(
                source_sample,
                points,
                plane_size,
                width,
                height,
            )
            baseline = float(
                frame.get("baselineHeightCorrection", 0.0)
            )
            surface_y = [
                sample_shader_surface_y(
                    depth,
                    pixel[0],
                    pixel[1],
                    depth_name,
                    height_scale,
                    baseline,
                )
                for pixel in pixels
            ]

            original_palm_y = median(
                [points[index][1] for index in PALM_ANCHORS]
            )
            target_palm_surface = median(
                [surface_y[index] for index in PALM_ANCHORS]
            )
            projected = []
            for point in points:
                relative_y = point[1] - original_palm_y
                projected.append(
                    [
                        round(point[0], 5),
                        round(
                            target_palm_surface
                            + args.hand_hover
                            + relative_y,
                            5,
                        ),
                        round(point[2], 5),
                    ]
                )

            contact_mode = "hover"
            contact_shift_y = 0.0
            contact_point: list[float] | None = None
            tool_contact_point: list[float] | None = None
            if intent == "drawing":
                contact_deltas = [
                    surface_y[index]
                    + args.contact_lift
                    - projected[index][1]
                    for index in args.contact_indices
                    if 0 <= index < len(projected)
                ]
                if contact_deltas:
                    contact_mode = "finger_rigid"
                    contact_shift_y = median(contact_deltas)
                    for point in projected:
                        point[1] = round(
                            point[1] + contact_shift_y,
                            5,
                        )
                    contact_index = args.contact_indices[0]
                    contact_point = list(projected[contact_index])
            elif intent == "erasing":
                palm_deltas = [
                    surface_y[index]
                    + args.palm_contact_lift
                    - projected[index][1]
                    for index in PALM_ANCHORS
                ]
                contact_mode = "palm_rigid"
                contact_shift_y = max(palm_deltas)
                for point in projected:
                    point[1] = round(
                        point[1] + contact_shift_y,
                        5,
                    )
                contact_point = [
                    round(median([projected[index][0] for index in PALM_ANCHORS]), 5),
                    round(median([projected[index][1] for index in PALM_ANCHORS]), 5),
                    round(median([projected[index][2] for index in PALM_ANCHORS]), 5),
                ]
            elif intent == "tool_drawing":
                contact_mode = "tool_tip"
                contact_index = args.contact_indices[0]
                tool_contact_point = [
                    projected[contact_index][0],
                    round(
                        surface_y[contact_index]
                        + args.tool_tip_lift,
                        5,
                    ),
                    projected[contact_index][2],
                ]
                contact_point = list(tool_contact_point)
                track_has_tool = True
                tool_contact_samples += 1

            clearance_shift_y = 0.0
            sample_clearance_adjustments = 0
            if intent in ("positioning", "tool_drawing"):
                for index, point in enumerate(projected):
                    minimum_y = (
                        surface_y[index]
                        + args.hover_min_clearance
                    )
                    if point[1] < minimum_y:
                        point[1] = round(minimum_y, 5)
                        sample_clearance_adjustments += 1
            else:
                protected_contacts = (
                    set(PALM_ANCHORS)
                    if intent == "erasing"
                    else set(args.contact_indices)
                )
                for index, point in enumerate(projected):
                    if index in protected_contacts:
                        continue
                    minimum_y = (
                        surface_y[index]
                        + args.noncontact_min_clearance
                    )
                    if point[1] < minimum_y:
                        point[1] = round(minimum_y, 5)
                        sample_clearance_adjustments += 1

            output_sample = dict(source_sample)
            output_sample["landmarks"] = projected
            output_sample["surfaceFrameIndex"] = frame_index
            output_sample["intent"] = intent
            output_sample["intentMethod"] = (
                "rgb_evidence_tool_presence_v3"
                if intent == "tool_drawing"
                else str(
                    source_sample.get(
                        "intentMethod",
                        "source_intent",
                    )
                )
            )
            output_sample["contactMode"] = contact_mode
            output_sample["contactShiftY"] = round(contact_shift_y, 5)
            output_sample["clearanceShiftY"] = round(
                clearance_shift_y,
                5,
            )
            output_sample["clearanceAdjustedPointCount"] = (
                sample_clearance_adjustments
            )
            if contact_point is not None:
                output_sample["contactPoint"] = contact_point
            if tool_contact_point is not None:
                output_sample["toolContactPoint"] = tool_contact_point
            output_samples.append(output_sample)
            all_y_values.extend(point[1] for point in projected)
            palm_span = point_distance(projected[5], projected[17])
            all_span_candidates.append(palm_span)
            if (
                intent in ("positioning", "erasing")
                and args.rig_span_min
                <= palm_span
                <= args.rig_span_max
            ):
                reference_span_candidates.append(palm_span)
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
            contact_mode_counts[contact_mode] = (
                contact_mode_counts.get(contact_mode, 0) + 1
            )
            contact_shifts.append(contact_shift_y)
            clearance_shifts.append(clearance_shift_y)
            clearance_adjusted_points += sample_clearance_adjustments
            if sample_clearance_adjustments > 0:
                clearance_shifted_samples += 1
            projected_samples += 1

        reference_source = (
            reference_span_candidates
            if reference_span_candidates
            else all_span_candidates
        )
        rig_span_reference = median(reference_source)
        track["rig_palm_span_reference"] = round(
            rig_span_reference,
            6,
        )
        track["rig_palm_span_method"] = (
            "median_positioning_erasing_valid_span"
            if reference_span_candidates
            else "median_all_samples"
        )
        track["rig_palm_span_valid_min"] = args.rig_span_min
        track["rig_palm_span_valid_max"] = args.rig_span_max
        track["rig_max_orientation_step_degrees"] = (
            args.rig_max_orientation_step_degrees
        )
        track["supports_tool_drawing"] = track_has_tool
        rig_span_references.append(rig_span_reference)
        track["samples"] = output_samples
        projected_tracks.append(track)

    payload = {
        "schemaVersion": 2,
        "method": "mediapipe_pixel_tracks_reprojected_to_stable_depth",
        "sourceTrackSidecar": str(args.source_hand_tracks.resolve()),
        "targetSession": str(source_session.resolve()),
        "frameCount": len(frames),
        "detectedFrameCount": projected_samples,
        "planeSize": plane_size,
        "heightScale": height_scale,
        "heightMode": "stable-depth-rigid-contact",
        "handHover": args.hand_hover,
        "contactLift": args.contact_lift,
        "palmContactLift": args.palm_contact_lift,
        "toolTipLift": args.tool_tip_lift,
        "hoverMinClearance": args.hover_min_clearance,
        "noncontactMinClearance": args.noncontact_min_clearance,
        "contactIndices": args.contact_indices,
        "contactPolicy": {
            "positioning": "palm hover",
            "drawing": "rigid whole-hand index contact",
            "tool_drawing": "hovering hand plus tool-tip contact",
            "erasing": "rigid whole-hand palm contact",
        },
        "toolDrawingFrameRanges": args.tool_drawing_frame_range,
        "visualStyle": args.style,
        "hand_tracks": projected_tracks,
    }
    report = {
        "method": payload["method"],
        "visualStyle": args.style,
        "sourceTrackSidecar": str(args.source_hand_tracks.resolve()),
        "sourceTrackSha256": file_sha256(args.source_hand_tracks),
        "trackCount": len(projected_tracks),
        "sampleCount": projected_samples,
        "handHover": args.hand_hover,
        "contactLift": args.contact_lift,
        "palmContactLift": args.palm_contact_lift,
        "toolTipLift": args.tool_tip_lift,
        "contactIndices": args.contact_indices,
        "maxGapSeconds": args.max_gap_seconds,
        "intentCounts": intent_counts,
        "contactModeCounts": contact_mode_counts,
        "contactShiftMinimum": min(contact_shifts) if contact_shifts else None,
        "contactShiftMedian": median(contact_shifts),
        "contactShiftMaximum": max(contact_shifts) if contact_shifts else None,
        "clearanceShiftMinimum": (
            min(clearance_shifts) if clearance_shifts else None
        ),
        "clearanceShiftMedian": median(clearance_shifts),
        "clearanceShiftMaximum": (
            max(clearance_shifts) if clearance_shifts else None
        ),
        "clearanceAdjustedPointCount": clearance_adjusted_points,
        "clearanceShiftedSampleCount": clearance_shifted_samples,
        "toolContactSampleCount": tool_contact_samples,
        "toolDrawingFrameRanges": args.tool_drawing_frame_range,
        "rigPalmSpanReferences": rig_span_references,
        "projectedYMinimum": min(all_y_values) if all_y_values else None,
        "projectedYMaximum": max(all_y_values) if all_y_values else None,
    }
    return payload, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--source-hand-tracks", type=Path, required=True)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument(
        "--style",
        default="anatomical_capsule_glass_v1",
    )
    parser.add_argument("--color", default="#54d2c6")
    parser.add_argument("--handedness", choices=("left", "right"), default="")
    parser.add_argument("--plane-size", type=float, default=5.5)
    parser.add_argument("--hand-hover", type=float, default=0.14)
    parser.add_argument("--contact-lift", type=float, default=0.022)
    parser.add_argument("--palm-contact-lift", type=float, default=0.035)
    parser.add_argument("--tool-tip-lift", type=float, default=0.018)
    parser.add_argument("--hover-min-clearance", type=float, default=0.06)
    parser.add_argument(
        "--noncontact-min-clearance",
        type=float,
        default=0.045,
    )
    parser.add_argument(
        "--contact-indices",
        type=int,
        nargs="+",
        default=[8],
    )
    parser.add_argument("--max-gap-seconds", type=float, default=0.24)
    parser.add_argument("--endpoint-hold-seconds", type=float, default=0.05)
    parser.add_argument(
        "--tool-drawing-frame-range",
        type=parse_frame_range,
        action="append",
        default=[],
        metavar="START:END",
    )
    parser.add_argument("--rig-span-min", type=float, default=0.15)
    parser.add_argument("--rig-span-max", type=float, default=0.70)
    parser.add_argument(
        "--rig-max-orientation-step-degrees",
        type=float,
        default=42.0,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_session = args.source_session.resolve()
    output_session = args.output_session.resolve()
    source_manifest_path = source_session / "processed_manifest.json"
    source_session_path = source_session / "session.json"
    if not source_manifest_path.is_file() or not source_session_path.is_file():
        raise FileNotFoundError(
            "source session needs session.json and processed_manifest.json"
        )
    if not args.source_hand_tracks.is_file():
        raise FileNotFoundError(args.source_hand_tracks)
    if output_session.exists() and any(output_session.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {output_session}"
        )

    manifest = load_json(source_manifest_path)
    session = load_json(source_session_path)
    source_tracks = load_json(args.source_hand_tracks)
    track_payload, overlay_report = reproject_tracks(
        source_tracks,
        source_session,
        manifest,
        session,
        args,
    )

    output_session.mkdir(parents=True, exist_ok=True)
    style_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", args.style).strip("_")
    if not style_slug:
        style_slug = "virtual_hand"
    sidecar_name = f"hand_tracks_{style_slug}.json"
    skip = {
        "session.json",
        "processed_manifest.json",
        sidecar_name,
        "virtual_hand_materialization_report.json",
    }
    for source in source_session.iterdir():
        if source.is_file() and source.name not in skip:
            link_or_copy(source, output_session / source.name)

    sidecar_path = output_session / sidecar_name
    save_json(sidecar_path, track_payload)
    overlay_report["sidecar"] = sidecar_name
    overlay_report["sidecarSha256"] = file_sha256(sidecar_path)

    source_name = source_session.name
    output_name = output_session.name
    output_manifest = rewrite_resource_paths(
        manifest,
        source_name,
        output_name,
    )
    output_manifest["sessionId"] = output_name
    output_manifest["virtualHandOverlay"] = overlay_report

    frames = output_manifest.get("frames", [])
    source_depth = [
        source_session / str(frame["cleanDepth"])
        for frame in manifest["frames"]
    ]
    output_depth = [
        output_session / str(frame["cleanDepth"])
        for frame in frames
    ]
    source_rgb = [
        source_session / str(frame["cleanRgb"])
        for frame in manifest["frames"]
    ]
    output_rgb = [
        output_session / str(frame["cleanRgb"])
        for frame in frames
    ]
    overlay_report["sourceDepthSequenceSha256"] = sequence_sha256(
        source_depth
    )
    overlay_report["outputDepthSequenceSha256"] = sequence_sha256(
        output_depth
    )
    overlay_report["sourceRgbSequenceSha256"] = sequence_sha256(source_rgb)
    overlay_report["outputRgbSequenceSha256"] = sequence_sha256(output_rgb)
    overlay_report["depthUnchanged"] = (
        overlay_report["sourceDepthSequenceSha256"]
        == overlay_report["outputDepthSequenceSha256"]
    )
    overlay_report["rgbUnchanged"] = (
        overlay_report["sourceRgbSequenceSha256"]
        == overlay_report["outputRgbSequenceSha256"]
    )
    if not overlay_report["depthUnchanged"]:
        raise RuntimeError("depth sequence changed during hand materialization")
    if not overlay_report["rgbUnchanged"]:
        raise RuntimeError("RGB sequence changed during hand materialization")
    output_manifest["virtualHandOverlay"] = overlay_report
    save_json(output_session / "processed_manifest.json", output_manifest)

    output_session_json = rewrite_resource_paths(
        session,
        source_name,
        output_name,
    )
    output_session_json["id"] = output_name
    output_session_json["title"] = (
        str(session.get("title", "Kinect session"))
        + " + soft virtual hand"
    )
    output_session_json.setdefault("data_sources", {})[
        "hand_tracks"
    ] = sidecar_name
    output_session_json.setdefault("production_session", {})[
        "virtualHandOverlay"
    ] = overlay_report
    save_json(output_session / "session.json", output_session_json)
    save_json(
        output_session / "virtual_hand_materialization_report.json",
        overlay_report,
    )

    print(
        json.dumps(
            {
                "outputSession": str(output_session),
                "trackCount": overlay_report["trackCount"],
                "sampleCount": overlay_report["sampleCount"],
                "sidecarSha256": overlay_report["sidecarSha256"],
                "depthSequenceSha256": overlay_report[
                    "outputDepthSequenceSha256"
                ],
                "rgbSequenceSha256": overlay_report[
                    "outputRgbSequenceSha256"
                ],
                "depthUnchanged": overlay_report["depthUnchanged"],
                "rgbUnchanged": overlay_report["rgbUnchanged"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
