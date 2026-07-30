#!/usr/bin/env python3
"""Annotate hand intent samples in a MediaPipe hand sidecar.

This is intentionally session-specific for the current Kinect example. The RGB
review shows initial positioning, rod-tool drawing while the rod is absent from
its tray-rest position, open-palm erasing/smoothing while the rod is returned
to the top of the tray, a short repositioning transition, then finger drawing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def smooth_track_landmarks(track: dict[str, Any], radius: int = 2) -> None:
    samples = track.get("samples", [])
    if not isinstance(samples, list) or len(samples) < 3:
        return
    smoothed: list[list[list[float]]] = []
    for index, sample in enumerate(samples):
        landmarks = sample.get("landmarks", [])
        if not isinstance(landmarks, list) or len(landmarks) != 21:
            smoothed.append(landmarks)
            continue
        start = max(0, index - radius)
        end = min(len(samples), index + radius + 1)
        window = [item.get("landmarks", []) for item in samples[start:end]]
        window = [item for item in window if isinstance(item, list) and len(item) == 21]
        if not window:
            smoothed.append(landmarks)
            continue
        next_points: list[list[float]] = []
        for joint_index in range(21):
            coords = []
            for axis in range(3):
                coords.append(round(sum(float(item[joint_index][axis]) for item in window) / len(window), 5))
            next_points.append(coords)
        smoothed.append(next_points)
    for sample, landmarks in zip(samples, smoothed):
        sample["landmarks"] = landmarks


def attach_pixel_landmarks(payload: dict[str, Any]) -> None:
    pixels_by_frame: dict[int, list[list[float]]] = {}
    for frame in payload.get("mediapipe_hands", []):
        if not isinstance(frame, dict):
            continue
        hands = frame.get("hands", [])
        if not hands or not isinstance(hands[0], dict):
            continue
        pixels = hands[0].get("pixels", [])
        if not isinstance(pixels, list) or len(pixels) != 21:
            continue
        pixels_by_frame[int(frame.get("frameIndex", -1))] = [
            [round(float(item.get("x", 0.0)), 3), round(float(item.get("y", 0.0)), 3)]
            for item in pixels
            if isinstance(item, dict)
        ]
    for track in payload.get("hand_tracks", []):
        if not isinstance(track, dict):
            continue
        for sample in track.get("samples", []):
            if not isinstance(sample, dict):
                continue
            frame_index = int(sample.get("frameIndex", -1))
            pixels = pixels_by_frame.get(frame_index)
            if pixels is not None and len(pixels) == 21:
                sample["pixelLandmarks"] = pixels


def classify_frame(frame_index: int) -> tuple[str, float]:
    if frame_index < 82:
        return "positioning", 0.82
    if frame_index < 300:
        return "tool_drawing", 0.94
    if 300 <= frame_index <= 411:
        return "erasing", 0.9
    if 412 <= frame_index <= 426:
        return "positioning", 0.78
    return "drawing", 0.9


def annotate(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    attach_pixel_landmarks(payload)
    counts: dict[str, int] = {
        "drawing": 0,
        "tool_drawing": 0,
        "pointing": 0,
        "erasing": 0,
        "positioning": 0,
    }
    segments: list[dict[str, Any]] = []

    for track in payload.get("hand_tracks", []):
        if not isinstance(track, dict):
            continue
        track["semantic_markers"] = True
        track["virtual_hand"] = True
        track["show_mesh_ghost"] = False
        track["show_landmarks"] = False
        track["show_skeleton"] = False
        track.pop("model_path", None)
        track.pop("model_scale", None)
        track.pop("model_rotation_degrees", None)
        smooth_track_landmarks(track)
        for sample in track.get("samples", []):
            if not isinstance(sample, dict):
                continue
            frame_index = int(sample.get("frameIndex", 0))
            intent, confidence = classify_frame(frame_index)
            sample["intent"] = intent
            sample["intentConfidence"] = confidence
            sample["intentMethod"] = "rgb_review_tool_presence_segment_v3"
            counts[intent] = counts.get(intent, 0) + 1

            if not segments or segments[-1]["intent"] != intent:
                segments.append({
                    "intent": intent,
                    "start": float(sample.get("time", 0.0)),
                    "end": float(sample.get("time", 0.0)),
                    "startFrame": frame_index,
                    "endFrame": frame_index,
                })
            else:
                segments[-1]["end"] = float(sample.get("time", segments[-1]["end"]))
                segments[-1]["endFrame"] = frame_index

    payload["intentMethod"] = "rgb_review_tool_presence_segment_v3"
    payload["intentCounts"] = counts
    payload["intentSegments"] = segments
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    args = parser.parse_args()
    payload = annotate(args.sidecar)
    args.sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("intentCounts", payload.get("intentCounts", {}))
    for segment in payload.get("intentSegments", []):
        print(segment)


if __name__ == "__main__":
    main()
