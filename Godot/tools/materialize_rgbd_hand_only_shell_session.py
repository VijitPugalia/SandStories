#!/usr/bin/env python3
"""Create a hand-only review session from measured RGB-D hand geometry.

The source v7 visible-hand silhouette and registered RGB-D lift remain
byte-identical on non-tool frames. Existing tool-drawing ranges are hidden with
one shared transparent overlay/zero geometry pair, and the virtual tool node is
disabled. No hand mask, pose, depth, or gesture is synthesized.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from materialize_topdown_virtual_hand_session import (
    PRESERVATION_MARKER,
    file_sha256,
    link_or_copy,
    load_json,
    parse_hex_color,
    rewrite_resource_paths,
    save_json,
    sequence_sha256,
)


REPORT_NAME = "rgbd_hand_only_shell_report.json"
SIDECAR_NAME = "hand_tracks_measured_shell_hand_only_v2.json"
EMPTY_OVERLAY_NAME = "virtual_hand_overlay_hidden_tool.png"
EMPTY_GEOMETRY_NAME = "virtual_hand_geometry_hidden_tool.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument("--shell-color", default="#b86e57")
    parser.add_argument("--shell-texture-strength", type=float, default=0.58)
    parser.add_argument("--shell-edge-extension-texels", type=float, default=2.0)
    parser.add_argument("--shell-normal-radius-texels", type=float, default=2.0)
    return parser.parse_args()


def normalize_ranges(value: Any) -> list[tuple[int, int]]:
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(item, (int, float)) for item in value):
        if len(value) != 2:
            raise ValueError("flat toolDrawingFrameRanges must contain start/end")
        return [(int(value[0]), int(value[1]))]
    output: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("toolDrawingFrameRanges entries must be [start, end]")
        output.append((int(item[0]), int(item[1])))
    return output


def frame_in_ranges(frame_index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= frame_index <= end for start, end in ranges)


def hand_only_sidecar(payload: dict[str, Any]) -> dict[str, Any]:
    output = json.loads(json.dumps(payload))
    output["method"] = (
        str(output.get("method", ""))
        + " + measured RGB-D visible hand shell; tool node disabled"
    ).strip(" +")
    for track in output.get("hand_tracks", []):
        if not isinstance(track, dict):
            continue
        track["supports_tool_drawing"] = False
        track["virtual_hand"] = False
        track["show_landmarks"] = False
        track["show_skeleton"] = False
        track["virtual_hand_style"] = "measured_rgbd_visible_shell_v2"
        track["samples"] = [
            sample
            for sample in track.get("samples", [])
            if isinstance(sample, dict)
            and str(sample.get("intent", "")) != "tool_drawing"
        ]
    return output


def main() -> None:
    args = parse_args()
    source_session = args.source_session.resolve()
    output_session = args.output_session.resolve()
    if not source_session.is_dir():
        raise FileNotFoundError(source_session)
    if (output_session / PRESERVATION_MARKER).is_file():
        raise FileExistsError(
            "refusing to modify a preserved baseline; choose a new "
            f"--output-session instead: {output_session}"
        )
    if output_session.exists() and any(output_session.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output_session}")

    source_manifest = load_json(source_session / "processed_manifest.json")
    source_session_json = load_json(source_session / "session.json")
    source_frames = source_manifest.get("frames", [])
    if not isinstance(source_frames, list) or not source_frames:
        raise ValueError("source processed manifest has no frames")

    data_sources = source_session_json.get("data_sources", {})
    sidecar_path = source_session / str(data_sources.get("hand_tracks", ""))
    if not sidecar_path.is_file():
        raise FileNotFoundError(f"source hand-track sidecar missing: {sidecar_path}")
    source_sidecar = load_json(sidecar_path)
    tool_ranges = normalize_ranges(source_sidecar.get("toolDrawingFrameRanges", []))
    if not tool_ranges:
        raise ValueError("source sidecar has no toolDrawingFrameRanges to exclude")

    frame_size = source_manifest.get("frameSize", {})
    width = int(frame_size.get("width", 640))
    height = int(frame_size.get("height", 480))
    output_session.mkdir(parents=True)
    source_name = source_session.name
    output_name = output_session.name

    skip_names = {
        "session.json",
        "processed_manifest.json",
        REPORT_NAME,
        SIDECAR_NAME,
        EMPTY_OVERLAY_NAME,
        EMPTY_GEOMETRY_NAME,
    }
    for source in source_session.iterdir():
        if source.is_file() and source.name not in skip_names:
            link_or_copy(source, output_session / source.name)

    Image.fromarray(
        np.zeros((height, width, 4), dtype=np.uint8),
    ).save(output_session / EMPTY_OVERLAY_NAME, format="PNG", optimize=True)
    Image.fromarray(
        np.zeros((height, width, 3), dtype=np.uint8),
    ).save(output_session / EMPTY_GEOMETRY_NAME, format="PNG", optimize=True)

    output_frames = rewrite_resource_paths(source_frames, source_name, output_name)
    hidden_frames: list[int] = []
    retained_overlay_paths: list[Path] = []
    retained_geometry_paths: list[Path] = []
    for frame in output_frames:
        frame_index = int(frame.get("frameIndex", len(hidden_frames)))
        if frame_in_ranges(frame_index, tool_ranges):
            frame["virtualHandOverlay"] = EMPTY_OVERLAY_NAME
            frame["virtualHandGeometry"] = EMPTY_GEOMETRY_NAME
            hidden_frames.append(frame_index)
            continue
        overlay_path = output_session / str(frame.get("virtualHandOverlay", ""))
        geometry_path = output_session / str(frame.get("virtualHandGeometry", ""))
        if not overlay_path.is_file() or not geometry_path.is_file():
            raise FileNotFoundError(
                f"retained frame {frame_index} is missing measured hand assets"
            )
        retained_overlay_paths.append(overlay_path)
        retained_geometry_paths.append(geometry_path)

    output_sidecar = hand_only_sidecar(source_sidecar)
    save_json(output_session / SIDECAR_NAME, output_sidecar)

    output_manifest = rewrite_resource_paths(
        source_manifest,
        source_name,
        output_name,
    )
    output_manifest["sessionId"] = output_name
    output_manifest["frames"] = output_frames

    source_rgb_paths = [
        source_session / str(frame["cleanRgb"])
        for frame in source_frames
    ]
    output_rgb_paths = [
        output_session / str(frame["cleanRgb"])
        for frame in output_frames
    ]
    source_depth_paths = [
        source_session / str(frame["cleanDepth"])
        for frame in source_frames
    ]
    output_depth_paths = [
        output_session / str(frame["cleanDepth"])
        for frame in output_frames
    ]
    report = {
        "schemaVersion": 1,
        "method": "registered_rgbd_measured_visible_hand_shell_v2",
        "interpretation": (
            "Observed top-facing hand/forearm surface only; no inferred occluded "
            "finger articulation and no closed 3D hand mesh"
        ),
        "sourceSession": str(source_session),
        "frameCount": len(output_frames),
        "toolDrawingFrameRangesExcluded": [
            [start, end] for start, end in tool_ranges
        ],
        "toolFramesHidden": len(hidden_frames),
        "retainedReviewFrames": len(output_frames) - len(hidden_frames),
        "retainedGeometryPolicy": (
            "byte-identical v7 Grounded-SAM-2 visible actor silhouette and "
            "registered RGB-D measured lift"
        ),
        "handAuthoredMasks": False,
        "handAuthoredPoses": False,
        "toolConstraintUsed": False,
        "toolNodeEnabled": False,
        "surfaceMode": "measured_shell_v2",
        "shellMaterial": {
            "color": args.shell_color,
            "rawRgbLuminanceStrength": float(args.shell_texture_strength),
            "edgeExtensionTexels": float(args.shell_edge_extension_texels),
            "normalRadiusTexels": float(args.shell_normal_radius_texels),
        },
        "emptyOverlaySha256": file_sha256(output_session / EMPTY_OVERLAY_NAME),
        "emptyGeometrySha256": file_sha256(output_session / EMPTY_GEOMETRY_NAME),
        "retainedOverlaySequenceSha256": sequence_sha256(retained_overlay_paths),
        "retainedGeometrySequenceSha256": sequence_sha256(retained_geometry_paths),
        "sourceRgbSequenceSha256": sequence_sha256(source_rgb_paths),
        "outputRgbSequenceSha256": sequence_sha256(output_rgb_paths),
        "sourceDepthSequenceSha256": sequence_sha256(source_depth_paths),
        "outputDepthSequenceSha256": sequence_sha256(output_depth_paths),
        "sidecarSha256": file_sha256(output_session / SIDECAR_NAME),
    }
    report["rgbUnchanged"] = (
        report["sourceRgbSequenceSha256"]
        == report["outputRgbSequenceSha256"]
    )
    report["depthUnchanged"] = (
        report["sourceDepthSequenceSha256"]
        == report["outputDepthSequenceSha256"]
    )
    if not report["rgbUnchanged"] or not report["depthUnchanged"]:
        raise RuntimeError("source RGB/depth identity gate failed")
    output_manifest["rgbdHandOnlyShell"] = report
    save_json(output_session / "processed_manifest.json", output_manifest)

    output_session_json = rewrite_resource_paths(
        source_session_json,
        source_name,
        output_name,
    )
    output_session_json["id"] = output_name
    output_session_json["title"] = (
        str(source_session_json.get("title", "Kinect session"))
        + " + measured hand-only shell"
    )
    output_data_sources = output_session_json.setdefault("data_sources", {})
    shell_color_rgb = [
        float(value / 255.0)
        for value in parse_hex_color(args.shell_color)
    ]
    output_data_sources["hand_tracks"] = SIDECAR_NAME
    output_data_sources["virtual_hand_measured_shell_v2"] = True
    output_data_sources["virtual_hand_shell_color_rgb"] = shell_color_rgb
    output_data_sources["virtual_hand_shell_texture_strength"] = float(
        args.shell_texture_strength
    )
    output_data_sources["virtual_hand_shell_edge_extension_texels"] = float(
        args.shell_edge_extension_texels
    )
    output_data_sources["virtual_hand_shell_normal_radius_texels"] = float(
        args.shell_normal_radius_texels
    )
    output_session_json.setdefault("production_session", {})[
        "rgbdHandOnlyShell"
    ] = report
    save_json(output_session / "session.json", output_session_json)
    save_json(output_session / REPORT_NAME, report)

    print(json.dumps({
        "outputSession": str(output_session),
        "frameCount": len(output_frames),
        "toolFramesHidden": len(hidden_frames),
        "retainedReviewFrames": len(output_frames) - len(hidden_frames),
        "rgbUnchanged": report["rgbUnchanged"],
        "depthUnchanged": report["depthUnchanged"],
        "retainedOverlaySequenceSha256": report[
            "retainedOverlaySequenceSha256"
        ],
        "retainedGeometrySequenceSha256": report[
            "retainedGeometrySequenceSha256"
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
