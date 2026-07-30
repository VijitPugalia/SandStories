#!/usr/bin/env python3
"""Measure MANO inference 2D pose and motion agreement with track evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference-dir", type=Path, required=True)
    parser.add_argument("--track-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument(
        "--manifest-name",
        help=(
            "Inference manifest filename. If omitted, select the single "
            "*_inference_manifest.json file in the inference directory."
        ),
    )
    return parser.parse_args()


def _percentiles(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return {}
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "p50": float(np.percentile(array, 50)),
        "p90": float(np.percentile(array, 90)),
        "p95": float(np.percentile(array, 95)),
        "max": float(array.max()),
    }


def _track_samples(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    tracks = payload.get("hand_tracks", payload.get("tracks", []))
    if len(tracks) != 1:
        raise ValueError(f"Expected one hand track, found {len(tracks)}")
    return {int(sample["frameIndex"]): sample for sample in tracks[0]["samples"]}


def main() -> None:
    args = _parse_args()
    inference_dir = args.inference_dir.resolve()
    track_json = args.track_json.resolve()
    if args.manifest_name:
        manifest_path = inference_dir / args.manifest_name
    else:
        manifest_candidates = sorted(
            inference_dir.glob("*_inference_manifest.json")
        )
        if len(manifest_candidates) != 1:
            raise ValueError(
                "Expected exactly one *_inference_manifest.json in "
                f"{inference_dir}, found {len(manifest_candidates)}"
            )
        manifest_path = manifest_candidates[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = _track_samples(json.loads(track_json.read_text(encoding="utf-8")))

    frame_rows: list[dict[str, Any]] = []
    per_intent: dict[str, list[float]] = defaultdict(list)
    previous: dict[str, Any] | None = None
    motion_errors: list[float] = []

    for record in manifest["frames"]:
        frame_index = int(record["frameIndex"])
        sample = samples.get(frame_index)
        if sample is None:
            raise ValueError(f"Frame {frame_index} is absent from the track")
        arrays = np.load(inference_dir / record["arrays"])
        predicted = np.asarray(arrays["joint_uv"], dtype=np.float64)
        tracked = np.asarray(arrays["crop_landmarks_xy"], dtype=np.float64)
        if predicted.shape != (21, 2) or tracked.shape != (21, 2):
            raise ValueError(
                f"Frame {frame_index} has invalid joint arrays "
                f"{predicted.shape} and {tracked.shape}"
            )
        errors = np.linalg.norm(predicted - tracked, axis=1)
        mpjpe = float(errors.mean())
        intent = str(sample.get("intent", "unknown"))
        per_intent[intent].append(mpjpe)
        row: dict[str, Any] = {
            "frameIndex": frame_index,
            "intent": intent,
            "meanJointErrorPixels": mpjpe,
            "p95JointErrorPixels": float(np.percentile(errors, 95)),
            "maximumJointErrorPixels": float(errors.max()),
        }
        if (
            previous is not None
            and frame_index - int(previous["frameIndex"]) <= 3
        ):
            predicted_step = predicted - previous["predicted"]
            tracked_step = tracked - previous["tracked"]
            motion_error = float(
                np.linalg.norm(predicted_step - tracked_step, axis=1).mean()
            )
            row["motionStepErrorPixels"] = motion_error
            motion_errors.append(motion_error)
        frame_rows.append(row)
        previous = {
            "frameIndex": frame_index,
            "predicted": predicted,
            "tracked": tracked,
        }

    joint_errors = [row["meanJointErrorPixels"] for row in frame_rows]
    worst = sorted(
        frame_rows,
        key=lambda row: float(row["meanJointErrorPixels"]),
        reverse=True,
    )[:20]
    report = {
        "schemaVersion": 1,
        "method": (
            "Direct 2D comparison between inferred MANO joint_uv and the "
            "model-produced crop_landmarks_xy stored in each inference NPZ. "
            "Motion error compares consecutive predicted and tracked 2D steps."
        ),
        "inferenceDir": str(inference_dir),
        "inferenceManifest": str(manifest_path),
        "inferenceMethod": manifest.get("method"),
        "inferenceRgbDir": manifest.get("rgbDir"),
        "trackJson": str(track_json),
        "frameCount": len(frame_rows),
        "jointErrorPixels": _percentiles(joint_errors),
        "motionStepErrorPixels": _percentiles(motion_errors),
        "jointErrorPixelsByIntent": {
            intent: _percentiles(values)
            for intent, values in sorted(per_intent.items())
        },
        "worstFrames": worst,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        output_json = args.output_json.resolve()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
