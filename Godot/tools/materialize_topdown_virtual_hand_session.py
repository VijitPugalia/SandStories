#!/usr/bin/env python3
"""Build a top-down 2.5D virtual-hand session from model-generated masks.

The output keeps source RGB and depth files byte-identical. Each frame gains a
separate RGBA overlay selected from the Grounded-SAM-2 union mask by maximum
overlap with the study's valid sand surface. This data association excludes
unrelated foreground instances without hand-authored masks or image-position
rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage


PRESERVATION_MARKER = "PRESERVED_BASELINE.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
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


def rewrite_resource_paths(
    value: Any,
    source_name: str,
    output_name: str,
) -> Any:
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


def parse_hex_color(value: str) -> np.ndarray:
    text = value.strip().lstrip("#")
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise argparse.ArgumentTypeError(
            f"expected a six-digit RGB hex color, got {value!r}"
        )
    return np.asarray(
        [int(text[index : index + 2], 16) for index in (0, 2, 4)],
        dtype=np.float32,
    )


def load_binary_mask(path: Path, expected_size: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("L")
        if image.size != expected_size:
            raise ValueError(
                f"{path} is {image.size}, expected {expected_size}"
            )
        return np.asarray(image, dtype=np.uint8) > 0


def select_surface_actor(
    union_mask: np.ndarray,
    surface_mask: np.ndarray,
    association_max_gap_pixels: float,
) -> tuple[np.ndarray, int, int, int, int]:
    labels, component_count = ndimage.label(
        union_mask,
        structure=np.ones((3, 3), dtype=np.uint8),
    )
    if component_count == 0:
        return np.zeros_like(union_mask), 0, 0, 0, 0
    overlap = np.bincount(
        labels[surface_mask].ravel(),
        minlength=component_count + 1,
    )
    overlap[0] = 0
    selected_label = int(np.argmax(overlap))
    selected_overlap = int(overlap[selected_label])
    if selected_overlap <= 0:
        return np.zeros_like(union_mask), component_count, 0, 0, 0
    selected = labels == selected_label
    associated_labels = [selected_label]
    if association_max_gap_pixels > 0.0 and component_count > 1:
        distance = ndimage.distance_transform_edt(labels != selected_label)
        for label in range(1, component_count + 1):
            if label == selected_label:
                continue
            label_distance = float(distance[labels == label].min())
            if label_distance <= association_max_gap_pixels:
                selected |= labels == label
                associated_labels.append(label)
    return (
        selected,
        component_count,
        len(associated_labels),
        int(np.count_nonzero(selected)),
        selected_overlap,
    )


def styled_overlay(
    mask: np.ndarray,
    color: np.ndarray,
    appearance: np.ndarray | None,
) -> Image.Image:
    height, width = mask.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    if not np.any(mask):
        return Image.fromarray(rgba)

    distance = ndimage.distance_transform_edt(mask)
    soft_alpha = ndimage.gaussian_filter(
        mask.astype(np.float32),
        sigma=0.72,
    )
    center = np.clip(distance / 14.0, 0.0, 1.0)
    rim = np.exp(-distance / 1.7) * mask
    highlight = np.asarray([128.0, 218.0, 204.0], dtype=np.float32)
    if appearance is not None:
        source = appearance.astype(np.float32)
        luminance = (
            source[:, :, 0] * 0.2126
            + source[:, :, 1] * 0.7152
            + source[:, :, 2] * 0.0722
        )
        values = luminance[mask]
        low, high = np.percentile(values, [5.0, 95.0])
        scale = max(1.0, float(high - low))
        tone = np.clip((luminance - low) / scale, 0.0, 1.0)
    else:
        tone = np.full(mask.shape, 0.55, dtype=np.float32)
    base_gain = 0.72 + tone * 0.28 + center * 0.08
    highlight_gain = 0.08 + tone * 0.14 + rim * 0.12
    rgb = color[None, None, :] * base_gain[:, :, None]
    rgb += highlight[None, None, :] * highlight_gain[:, :, None]
    rgb = np.clip(rgb, 0.0, 255.0)

    alpha = np.clip(soft_alpha * 0.74, 0.0, 0.74)
    alpha[mask] = np.maximum(alpha[mask], 0.64)
    rgba[:, :, :3] = rgb.astype(np.uint8)
    rgba[:, :, 3] = np.round(alpha * 255.0).astype(np.uint8)
    return Image.fromarray(rgba)


def track_samples_by_frame(payload: Any) -> tuple[dict[int, dict], float]:
    if isinstance(payload, dict):
        tracks = payload.get("hand_tracks", [])
        plane_size = float(payload.get("planeSize", 5.5))
    else:
        tracks = payload if isinstance(payload, list) else []
        plane_size = 5.5
    samples: dict[int, dict] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        for sample in track.get("samples", []):
            if not isinstance(sample, dict) or "frameIndex" not in sample:
                continue
            samples[int(sample["frameIndex"])] = sample
        if samples:
            break
    return samples, plane_size


def landmark_component(
    union_mask: np.ndarray,
    sample: dict,
    plane_size: float,
) -> int:
    labels, component_count = ndimage.label(
        union_mask,
        structure=np.ones((3, 3), dtype=np.uint8),
    )
    if component_count == 0:
        return 0
    height, width = union_mask.shape
    votes = np.zeros(component_count + 1, dtype=np.int32)
    for point in sample.get("landmarks", []):
        if not isinstance(point, list) or len(point) < 3:
            continue
        px = int(round((float(point[0]) / plane_size + 0.5) * (width - 1)))
        py = int(round((float(point[2]) / plane_size + 0.5) * (height - 1)))
        if 0 <= px < width and 0 <= py < height:
            votes[int(labels[py, px])] += 1
    if votes[1:].size == 0 or int(votes[1:].max()) == 0:
        return 0
    return int(np.argmax(votes[1:]) + 1)


def selected_component_label(
    union_mask: np.ndarray,
    surface_mask: np.ndarray,
) -> int:
    labels, component_count = ndimage.label(
        union_mask,
        structure=np.ones((3, 3), dtype=np.uint8),
    )
    if component_count == 0:
        return 0
    overlap = np.bincount(
        labels[surface_mask].ravel(),
        minlength=component_count + 1,
    )
    overlap[0] = 0
    if int(overlap.max()) == 0:
        return 0
    return int(np.argmax(overlap))


def tool_only_tracks(payload: Any, color: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("tool-track payload must be a JSON object")
    output = json.loads(json.dumps(payload))
    tracks = output.get("hand_tracks", [])
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track["virtual_hand"] = False
        track["virtual_hand_style"] = "topdown_mask_2p5d_tool_v1"
        track["show_landmarks"] = False
        track["show_skeleton"] = False
        track["color"] = color
    output["method"] = (
        str(output.get("method", ""))
        + " + topdown mask overlay; 3D hand disabled, tool retained"
    ).strip(" +")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--source-masks", type=Path, required=True)
    parser.add_argument("--source-appearance-session", type=Path)
    parser.add_argument("--source-tool-tracks", type=Path, required=True)
    parser.add_argument("--validation-hand-tracks", type=Path)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument("--color", default="#4a8f84")
    parser.add_argument(
        "--association-max-gap-pixels",
        type=float,
        default=26.0,
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue an interrupted output without rewriting completed PNGs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_session = args.source_session.resolve()
    source_masks = args.source_masks.resolve()
    appearance_session = (
        args.source_appearance_session.resolve()
        if args.source_appearance_session
        else None
    )
    source_tool_tracks = args.source_tool_tracks.resolve()
    output_session = args.output_session.resolve()
    preservation_marker = output_session / PRESERVATION_MARKER
    if preservation_marker.is_file():
        raise FileExistsError(
            "refusing to modify a preserved baseline; choose a new "
            f"--output-session instead: {output_session}"
        )
    manifest_path = source_session / "processed_manifest.json"
    session_path = source_session / "session.json"
    if not manifest_path.is_file() or not session_path.is_file():
        raise FileNotFoundError(
            "source session needs session.json and processed_manifest.json"
        )
    if not source_masks.is_dir():
        raise FileNotFoundError(source_masks)
    if not source_tool_tracks.is_file():
        raise FileNotFoundError(source_tool_tracks)
    if (
        output_session.exists()
        and any(output_session.iterdir())
        and not args.resume
    ):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {output_session}"
        )

    manifest = load_json(manifest_path)
    session = load_json(session_path)
    frames = manifest.get("frames", [])
    if not isinstance(frames, list) or not frames:
        raise ValueError("processed manifest has no frames")
    mask_paths = sorted(source_masks.glob("*.png"))
    if len(mask_paths) != len(frames):
        raise ValueError(
            f"mask/frame count mismatch: {len(mask_paths)} vs {len(frames)}"
        )
    frame_size = manifest.get("frameSize", {})
    expected_size = (
        int(frame_size.get("width", 640)),
        int(frame_size.get("height", 480)),
    )
    surface_mask_path = source_session / str(manifest["surfaceMask"])
    with Image.open(surface_mask_path) as image:
        image = image.convert("L")
        if image.size != expected_size:
            raise ValueError("surface-mask dimensions do not match manifest")
        surface_mask = np.asarray(image, dtype=np.uint8) > 127
    appearance_paths: list[Path | None] = [None] * len(frames)
    if appearance_session is not None:
        appearance_manifest = load_json(
            appearance_session / "processed_manifest.json"
        )
        appearance_frames = appearance_manifest.get("frames", [])
        if len(appearance_frames) != len(frames):
            raise ValueError(
                "appearance/source frame counts do not match: "
                f"{len(appearance_frames)} vs {len(frames)}"
            )
        appearance_paths = [
            appearance_session / str(frame["cleanRgb"])
            for frame in appearance_frames
        ]

    validation_samples: dict[int, dict] = {}
    validation_plane_size = 5.5
    if args.validation_hand_tracks:
        validation_samples, validation_plane_size = track_samples_by_frame(
            load_json(args.validation_hand_tracks.resolve())
        )

    output_session.mkdir(parents=True, exist_ok=True)
    source_name = source_session.name
    output_name = output_session.name
    sidecar_name = "hand_tracks_topdown_tool_only_v1.json"
    skip = {
        "session.json",
        "processed_manifest.json",
        sidecar_name,
        "topdown_virtual_hand_report.json",
    }
    for source in source_session.iterdir():
        if source.is_file() and source.name not in skip:
            destination = output_session / source.name
            if not destination.exists():
                link_or_copy(source, destination)

    color = parse_hex_color(args.color)
    output_frames = rewrite_resource_paths(
        frames,
        source_name,
        output_name,
    )
    component_counts: list[int] = []
    associated_component_counts: list[int] = []
    selected_areas: list[int] = []
    selected_overlaps: list[int] = []
    active_frames = 0
    agreement = 0
    agreement_compared = 0
    overlay_paths: list[Path] = []
    for frame_index, (frame, mask_path, appearance_path) in enumerate(
        zip(output_frames, mask_paths, appearance_paths)
    ):
        union_mask = load_binary_mask(mask_path, expected_size)
        (
            selected,
            component_count,
            associated_component_count,
            selected_area,
            selected_overlap,
        ) = select_surface_actor(
            union_mask,
            surface_mask,
            args.association_max_gap_pixels,
        )
        component_counts.append(component_count)
        associated_component_counts.append(associated_component_count)
        selected_areas.append(selected_area)
        selected_overlaps.append(selected_overlap)
        if selected_area > 0:
            active_frames += 1

        sample = validation_samples.get(frame_index)
        if sample is not None:
            landmark_label = landmark_component(
                union_mask,
                sample,
                validation_plane_size,
            )
            surface_label = selected_component_label(
                union_mask,
                surface_mask,
            )
            if landmark_label > 0 and surface_label > 0:
                agreement_compared += 1
                if landmark_label == surface_label:
                    agreement += 1

        overlay_name = f"virtual_hand_overlay_{frame_index + 1:06d}.png"
        overlay_path = output_session / overlay_name
        if not (args.resume and overlay_path.is_file()):
            appearance = None
            if appearance_path is not None:
                with Image.open(appearance_path) as image:
                    image = image.convert("RGB")
                    if image.size != expected_size:
                        raise ValueError(
                            f"{appearance_path} is {image.size}, "
                            f"expected {expected_size}"
                        )
                    appearance = np.asarray(image, dtype=np.uint8)
            styled_overlay(selected, color, appearance).save(
                overlay_path,
                format="PNG",
                optimize=True,
            )
        overlay_paths.append(overlay_path)
        frame["virtualHandOverlay"] = overlay_name

    tool_tracks = tool_only_tracks(
        load_json(source_tool_tracks),
        args.color,
    )
    sidecar_path = output_session / sidecar_name
    save_json(sidecar_path, tool_tracks)

    source_depth = [
        source_session / str(frame["cleanDepth"])
        for frame in frames
    ]
    output_depth = [
        output_session / str(frame["cleanDepth"])
        for frame in output_frames
    ]
    source_rgb = [
        source_session / str(frame["cleanRgb"])
        for frame in frames
    ]
    output_rgb = [
        output_session / str(frame["cleanRgb"])
        for frame in output_frames
    ]
    report = {
        "schemaVersion": 1,
        "method": "grounded_sam2_surface_associated_topdown_2p5d",
        "sourceSession": str(source_session),
        "sourceMasks": str(source_masks),
        "frameCount": len(output_frames),
        "activeOverlayFrameCount": active_frames,
        "selector": (
            "8-connected model-mask component with maximum pixel overlap "
            "with the authoritative surface mask"
        ),
        "maskPostprocessing": "none; visual edge antialiasing only",
        "appearanceSource": (
            str(appearance_session) if appearance_session else None
        ),
        "appearanceTransfer": (
            "robust raw-RGB luminance colorized inside selected model pixels"
            if appearance_session
            else "synthetic center/rim shading"
        ),
        "handAuthoredMasks": False,
        "imagePositionRules": False,
        "associationMaxGapPixels": args.association_max_gap_pixels,
        "associationPolicy": (
            "retain original model pixels from adjacent components only; "
            "never fill or dilate the gap"
        ),
        "componentCountMaximum": max(component_counts),
        "multiComponentAssociationFrameCount": int(
            np.count_nonzero(
                np.asarray(associated_component_counts) > 1
            )
        ),
        "selectedAreaMedianPixels": float(np.median(selected_areas)),
        "selectedAreaMaximumPixels": max(selected_areas),
        "selectedSurfaceOverlapMedianPixels": float(
            np.median(selected_overlaps)
        ),
        "surfaceSelectorLandmarkAgreement": {
            "agree": agreement,
            "compared": agreement_compared,
            "ratio": (
                float(agreement / agreement_compared)
                if agreement_compared
                else None
            ),
        },
        "color": args.color,
        "sourceMaskSequenceSha256": sequence_sha256(mask_paths),
        "overlaySequenceSha256": sequence_sha256(overlay_paths),
        "toolTrackSidecar": sidecar_name,
        "toolTrackSidecarSha256": file_sha256(sidecar_path),
        "sourceRgbSequenceSha256": sequence_sha256(source_rgb),
        "outputRgbSequenceSha256": sequence_sha256(output_rgb),
        "sourceDepthSequenceSha256": sequence_sha256(source_depth),
        "outputDepthSequenceSha256": sequence_sha256(output_depth),
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
        raise RuntimeError("RGB/depth identity gate failed")

    output_manifest = rewrite_resource_paths(
        manifest,
        source_name,
        output_name,
    )
    output_manifest["sessionId"] = output_name
    output_manifest["frames"] = output_frames
    output_manifest["topdownVirtualHand"] = report
    save_json(output_session / "processed_manifest.json", output_manifest)

    output_session_json = rewrite_resource_paths(
        session,
        source_name,
        output_name,
    )
    output_session_json["id"] = output_name
    output_session_json["title"] = (
        str(session.get("title", "Kinect session"))
        + " + top-down 2.5D virtual hand"
    )
    data_sources = output_session_json.setdefault("data_sources", {})
    data_sources["hand_tracks"] = sidecar_name
    data_sources["virtual_hand_overlay"] = (
        "virtual_hand_overlay_000001.png"
    )
    output_session_json.setdefault("production_session", {})[
        "topdownVirtualHand"
    ] = report
    save_json(output_session / "session.json", output_session_json)
    save_json(output_session / "topdown_virtual_hand_report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
