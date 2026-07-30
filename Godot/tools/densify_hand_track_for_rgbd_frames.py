#!/usr/bin/env python3
"""Densify a model-produced hand track only where RGB-D hand support exists.

The registered RGB-D geometry is used as a binary presence gate, never as a
hand-authored crop or pose. Missing crop landmarks are linearly interpolated
from the surrounding model-produced track samples.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-json", type=Path, required=True)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--processed-manifest", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--minimum-support-pixels", type=int, default=256)
    parser.add_argument("--maximum-endpoint-hold-frames", type=int, default=4)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _interpolate_array(
    before: dict[str, Any],
    after: dict[str, Any],
    key: str,
    alpha: float,
) -> list:
    first = np.asarray(before[key], dtype=np.float64)
    second = np.asarray(after[key], dtype=np.float64)
    if first.shape != second.shape or not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError(f"Cannot interpolate {key}: incompatible samples")
    return ((1.0 - alpha) * first + alpha * second).round(6).tolist()


def _sample_for_frame(
    frame_index: int,
    source_samples: list[dict[str, Any]],
    source_indices: list[int],
    frame_time: float,
    maximum_endpoint_hold_frames: int,
) -> dict[str, Any]:
    position = bisect.bisect_left(source_indices, frame_index)
    if position < len(source_indices) and source_indices[position] == frame_index:
        sample = dict(source_samples[position])
        sample["time"] = frame_time
        return sample

    if position == 0:
        before = after = source_samples[0]
        if source_indices[0] - frame_index > maximum_endpoint_hold_frames:
            raise ValueError(f"Frame {frame_index} is too far before the source track")
        alpha = 0.0
    elif position == len(source_indices):
        before = after = source_samples[-1]
        if frame_index - source_indices[-1] > maximum_endpoint_hold_frames:
            raise ValueError(f"Frame {frame_index} is too far after the source track")
        alpha = 0.0
    else:
        before = source_samples[position - 1]
        after = source_samples[position]
        first_index = source_indices[position - 1]
        second_index = source_indices[position]
        alpha = (frame_index - first_index) / (second_index - first_index)

    nearest = before if alpha <= 0.5 else after
    sample = dict(nearest)
    sample["frameIndex"] = frame_index
    sample["surfaceFrameIndex"] = frame_index
    sample["time"] = frame_time
    sample["pixelLandmarks"] = _interpolate_array(
        before, after, "pixelLandmarks", alpha
    )
    sample["landmarks"] = _interpolate_array(
        before, after, "landmarks", alpha
    )
    sample["confidence"] = round(
        (1.0 - alpha) * float(before.get("confidence", 0.0))
        + alpha * float(after.get("confidence", 0.0)),
        6,
    )
    sample["densified"] = True
    sample["densifiedFromFrameIndices"] = [
        int(before["frameIndex"]),
        int(after["frameIndex"]),
    ]
    sample["densifiedAlpha"] = round(float(alpha), 6)
    pixel_landmarks = np.asarray(sample["pixelLandmarks"], dtype=np.float64)
    crop_extent = np.ptp(pixel_landmarks, axis=0)
    if np.any(crop_extent < 8.0):
        sample["pixelLandmarks"] = nearest["pixelLandmarks"]
        sample["densifiedCropFallback"] = "nearest_model_sample"
    return sample


def main() -> None:
    args = _parse_args()
    if args.output_json.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_json}")
    if args.minimum_support_pixels <= 0:
        raise ValueError("--minimum-support-pixels must be positive")

    track_payload = json.loads(args.track_json.read_text(encoding="utf-8"))
    tracks = track_payload.get("hand_tracks", [])
    if len(tracks) != 1:
        raise ValueError(f"Expected one hand track, found {len(tracks)}")
    source_track = tracks[0]
    source_samples = sorted(
        source_track["samples"], key=lambda sample: int(sample["frameIndex"])
    )
    source_indices = [int(sample["frameIndex"]) for sample in source_samples]

    manifest = json.loads(args.processed_manifest.read_text(encoding="utf-8"))
    time_by_suffix: dict[int, float] = {}
    for frame in manifest["frames"]:
        depth_name = Path(str(frame["cleanDepth"])).stem
        suffix = int(depth_name.rsplit("_", 1)[1])
        time_by_suffix[suffix] = float(frame["time"])

    dense_samples: list[dict[str, Any]] = []
    presence_records: list[dict[str, Any]] = []
    for frame_index in sorted(time_by_suffix):
        geometry_path = (
            args.geometry_dir
            / f"virtual_hand_geometry_{frame_index:06d}.png"
        )
        if not geometry_path.is_file():
            raise FileNotFoundError(geometry_path)
        geometry = np.asarray(Image.open(geometry_path).convert("RGB"))
        support_pixels = int(np.count_nonzero(geometry[:, :, 1]))
        if support_pixels < args.minimum_support_pixels:
            continue
        dense_samples.append(
            _sample_for_frame(
                frame_index,
                source_samples,
                source_indices,
                time_by_suffix[frame_index],
                args.maximum_endpoint_hold_frames,
            )
        )
        presence_records.append(
            {
                "frameIndex": frame_index,
                "supportPixels": support_pixels,
                "geometry": geometry_path.name,
            }
        )

    output_track = dict(source_track)
    output_track["samples"] = dense_samples
    output_payload = dict(track_payload)
    output_payload["method"] = (
        "Existing model hand-track crops linearly densified only on frames "
        "with registered RGB-D hand presence"
    )
    output_payload["handAuthoredMasks"] = False
    output_payload["sourceTrackJson"] = str(args.track_json.resolve())
    output_payload["sourceTrackJsonSha256"] = _sha256(args.track_json)
    output_payload["sourceProcessedManifest"] = str(
        args.processed_manifest.resolve()
    )
    output_payload["sourceProcessedManifestSha256"] = _sha256(
        args.processed_manifest
    )
    output_payload["minimumSupportPixels"] = args.minimum_support_pixels
    output_payload["originalSampleCount"] = len(source_samples)
    output_payload["denseSampleCount"] = len(dense_samples)
    output_payload["interpolatedSampleCount"] = sum(
        bool(sample.get("densified", False)) for sample in dense_samples
    )
    output_payload["rgbdPresence"] = presence_records
    output_payload["hand_tracks"] = [output_track]
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(output_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.output_json}: {len(dense_samples)} frames, "
        f"{output_payload['interpolatedSampleCount']} interpolated crops"
    )


if __name__ == "__main__":
    main()
