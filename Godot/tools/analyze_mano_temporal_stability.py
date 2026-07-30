#!/usr/bin/env python3
"""Measure high-frequency motion in a fitted MANO sequence.

The analyzer separates screen-space translation, global rotation, articulated
shape, and RGB-D surface-height motion. It only compares consecutive source
frames and reports both second differences and a centered five-frame
high-pass residual, so real low-frequency drawing motion is not counted as
jitter.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np


FRAME_RE = re.compile(r"mano_hand_only_(\d{6})\.npz$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--fusion-report", type=Path)
    parser.add_argument("--track-json", type=Path)
    parser.add_argument("--minimum-frame", type=int, default=0)
    parser.add_argument("--maximum-frame", type=int, default=10**9)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--outlier-count", type=int, default=20)
    return parser.parse_args()


def _percentiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "maximum": None,
        }
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "mean": float(np.mean(array)),
        "p50": float(np.percentile(array, 50.0)),
        "p90": float(np.percentile(array, 90.0)),
        "p95": float(np.percentile(array, 95.0)),
        "maximum": float(np.max(array)),
    }


def _rotation_matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = np.sqrt(trace + 1.0) * 2.0
        quaternion = np.array(
            [
                0.25 * scale,
                (matrix[2, 1] - matrix[1, 2]) / scale,
                (matrix[0, 2] - matrix[2, 0]) / scale,
                (matrix[1, 0] - matrix[0, 1]) / scale,
            ],
            dtype=np.float64,
        )
    else:
        diagonal = np.diag(matrix)
        axis = int(np.argmax(diagonal))
        if axis == 0:
            scale = np.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2.0
            quaternion = np.array(
                [
                    (matrix[2, 1] - matrix[1, 2]) / scale,
                    0.25 * scale,
                    (matrix[0, 1] + matrix[1, 0]) / scale,
                    (matrix[0, 2] + matrix[2, 0]) / scale,
                ],
                dtype=np.float64,
            )
        elif axis == 1:
            scale = np.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2.0
            quaternion = np.array(
                [
                    (matrix[0, 2] - matrix[2, 0]) / scale,
                    (matrix[0, 1] + matrix[1, 0]) / scale,
                    0.25 * scale,
                    (matrix[1, 2] + matrix[2, 1]) / scale,
                ],
                dtype=np.float64,
            )
        else:
            scale = np.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2.0
            quaternion = np.array(
                [
                    (matrix[1, 0] - matrix[0, 1]) / scale,
                    (matrix[0, 2] + matrix[2, 0]) / scale,
                    (matrix[1, 2] + matrix[2, 1]) / scale,
                    0.25 * scale,
                ],
                dtype=np.float64,
            )
    return quaternion / max(float(np.linalg.norm(quaternion)), 1e-12)


def _quaternion_log(quaternion: np.ndarray) -> np.ndarray:
    quaternion = np.asarray(quaternion, dtype=np.float64)
    if quaternion[0] < 0.0:
        quaternion = -quaternion
    vector = quaternion[1:]
    vector_norm = float(np.linalg.norm(vector))
    if vector_norm < 1e-12:
        return np.zeros(3, dtype=np.float64)
    angle = 2.0 * np.arctan2(vector_norm, np.clip(quaternion[0], -1.0, 1.0))
    return vector * (angle / vector_norm)


def _quaternion_inverse(quaternion: np.ndarray) -> np.ndarray:
    result = np.asarray(quaternion, dtype=np.float64).copy()
    result[1:] *= -1.0
    return result


def _quaternion_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return np.array(
        [
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ],
        dtype=np.float64,
    )


def _rms(array: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(array, dtype=np.float64))))


def _centered_high_pass(values: list[np.ndarray], index: int) -> np.ndarray:
    smooth = (
        values[index - 2]
        + 4.0 * values[index - 1]
        + 6.0 * values[index]
        + 4.0 * values[index + 1]
        + values[index + 2]
    ) / 16.0
    return values[index] - smooth


def _load_fit_frames(
    fit_dir: Path,
    minimum_frame: int,
    maximum_frame: int,
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for path in sorted(fit_dir.glob("mano_hand_only_*.npz")):
        match = FRAME_RE.search(path.name)
        if match is None:
            continue
        frame_index = int(match.group(1))
        if not minimum_frame <= frame_index <= maximum_frame:
            continue
        with np.load(path) as arrays:
            joint_uv = np.asarray(arrays["joint_uv"], dtype=np.float64)
            vertices_model = np.asarray(arrays["vertices_model"], dtype=np.float64)
            joints_model = np.asarray(arrays["joints_model"], dtype=np.float64)
            quaternion = _rotation_matrix_to_quaternion(
                np.asarray(arrays["global_orient"], dtype=np.float64).reshape(3, 3)
            )
            frames.append(
                {
                    "frameIndex": frame_index,
                    "wristUv": joint_uv[0],
                    "jointShapeUv": joint_uv - joint_uv[0],
                    "verticesModelRooted": vertices_model - joints_model[0],
                    "poseCoefficients": np.asarray(
                        arrays["mano_pca_coefficients"],
                        dtype=np.float64,
                    ),
                    "quaternion": quaternion,
                }
            )
    for index in range(1, len(frames)):
        previous = frames[index - 1]["quaternion"]
        current = frames[index]["quaternion"]
        if float(np.dot(previous, current)) < 0.0:
            frames[index]["quaternion"] = -current
    return frames


def _analyze_fit(frames: list[dict[str, Any]], outlier_count: int) -> dict[str, Any]:
    metrics: dict[str, list[float]] = {
        "wristUvAccelerationPixels": [],
        "jointShapeUvAccelerationPixelsRms": [],
        "verticesModelAccelerationMillimetersRms": [],
        "poseCoefficientAccelerationL2": [],
        "globalRotationVelocityDegrees": [],
        "globalRotationAccelerationDegrees": [],
        "wristUvFiveFrameHighPassPixels": [],
        "jointShapeUvFiveFrameHighPassPixelsRms": [],
        "verticesModelFiveFrameHighPassMillimetersRms": [],
        "poseCoefficientFiveFrameHighPassL2": [],
    }
    per_frame: list[dict[str, Any]] = []
    angular_velocities: dict[int, np.ndarray] = {}

    for index in range(1, len(frames)):
        if frames[index]["frameIndex"] != frames[index - 1]["frameIndex"] + 1:
            continue
        delta = _quaternion_multiply(
            _quaternion_inverse(frames[index - 1]["quaternion"]),
            frames[index]["quaternion"],
        )
        angular_velocity = _quaternion_log(delta)
        angular_velocities[index] = angular_velocity
        metrics["globalRotationVelocityDegrees"].append(
            float(np.linalg.norm(angular_velocity) * 180.0 / np.pi)
        )

    for index in range(1, len(frames) - 1):
        if (
            frames[index]["frameIndex"] != frames[index - 1]["frameIndex"] + 1
            or frames[index + 1]["frameIndex"] != frames[index]["frameIndex"] + 1
        ):
            continue
        wrist_acceleration = (
            frames[index + 1]["wristUv"]
            - 2.0 * frames[index]["wristUv"]
            + frames[index - 1]["wristUv"]
        )
        joint_acceleration = (
            frames[index + 1]["jointShapeUv"]
            - 2.0 * frames[index]["jointShapeUv"]
            + frames[index - 1]["jointShapeUv"]
        )
        vertex_acceleration = (
            frames[index + 1]["verticesModelRooted"]
            - 2.0 * frames[index]["verticesModelRooted"]
            + frames[index - 1]["verticesModelRooted"]
        )
        pose_acceleration = (
            frames[index + 1]["poseCoefficients"]
            - 2.0 * frames[index]["poseCoefficients"]
            + frames[index - 1]["poseCoefficients"]
        )
        wrist_value = float(np.linalg.norm(wrist_acceleration))
        joint_value = _rms(joint_acceleration)
        vertex_value = _rms(vertex_acceleration) * 1000.0
        pose_value = float(np.linalg.norm(pose_acceleration))
        metrics["wristUvAccelerationPixels"].append(wrist_value)
        metrics["jointShapeUvAccelerationPixelsRms"].append(joint_value)
        metrics["verticesModelAccelerationMillimetersRms"].append(vertex_value)
        metrics["poseCoefficientAccelerationL2"].append(pose_value)
        rotation_acceleration = None
        if index in angular_velocities and index + 1 in angular_velocities:
            rotation_acceleration = float(
                np.linalg.norm(
                    angular_velocities[index + 1] - angular_velocities[index]
                )
                * 180.0
                / np.pi
            )
            metrics["globalRotationAccelerationDegrees"].append(
                rotation_acceleration
            )
        per_frame.append(
            {
                "frameIndex": frames[index]["frameIndex"],
                "wristUvAccelerationPixels": wrist_value,
                "jointShapeUvAccelerationPixelsRms": joint_value,
                "verticesModelAccelerationMillimetersRms": vertex_value,
                "poseCoefficientAccelerationL2": pose_value,
                "globalRotationAccelerationDegrees": rotation_acceleration,
            }
        )

    for index in range(2, len(frames) - 2):
        frame_indices = [frames[offset]["frameIndex"] for offset in range(index - 2, index + 3)]
        if frame_indices != list(range(frame_indices[0], frame_indices[0] + 5)):
            continue
        wrist_values = [frame["wristUv"] for frame in frames]
        joint_values = [frame["jointShapeUv"] for frame in frames]
        vertex_values = [frame["verticesModelRooted"] for frame in frames]
        pose_values = [frame["poseCoefficients"] for frame in frames]
        wrist_high_pass = _centered_high_pass(wrist_values, index)
        joint_high_pass = _centered_high_pass(joint_values, index)
        vertex_high_pass = _centered_high_pass(vertex_values, index)
        pose_high_pass = _centered_high_pass(pose_values, index)
        metrics["wristUvFiveFrameHighPassPixels"].append(
            float(np.linalg.norm(wrist_high_pass))
        )
        metrics["jointShapeUvFiveFrameHighPassPixelsRms"].append(
            _rms(joint_high_pass)
        )
        metrics["verticesModelFiveFrameHighPassMillimetersRms"].append(
            _rms(vertex_high_pass) * 1000.0
        )
        metrics["poseCoefficientFiveFrameHighPassL2"].append(
            float(np.linalg.norm(pose_high_pass))
        )

    sorted_outliers = sorted(
        per_frame,
        key=lambda item: item["verticesModelAccelerationMillimetersRms"],
        reverse=True,
    )
    wrist_outliers = sorted(
        per_frame,
        key=lambda item: item["wristUvAccelerationPixels"],
        reverse=True,
    )
    rotation_outliers = sorted(
        (
            item
            for item in per_frame
            if item["globalRotationAccelerationDegrees"] is not None
        ),
        key=lambda item: item["globalRotationAccelerationDegrees"],
        reverse=True,
    )
    return {
        "frameCount": len(frames),
        "minimumFrame": frames[0]["frameIndex"] if frames else None,
        "maximumFrame": frames[-1]["frameIndex"] if frames else None,
        "metrics": {
            metric_name: _percentiles(values)
            for metric_name, values in metrics.items()
        },
        "largestShapeAccelerationFrames": sorted_outliers[:outlier_count],
        "largestWristAccelerationFrames": wrist_outliers[:outlier_count],
        "largestRotationAccelerationFrames": rotation_outliers[:outlier_count],
    }


def _analyze_track(
    track_path: Path | None,
    minimum_frame: int,
    maximum_frame: int,
    outlier_count: int,
) -> dict[str, Any] | None:
    if track_path is None:
        return None
    document = json.loads(track_path.read_text(encoding="utf-8"))
    tracks = document.get("hand_tracks", [])
    if len(tracks) != 1:
        raise ValueError(f"Expected exactly one hand track, found {len(tracks)}")
    samples = [
        sample
        for sample in tracks[0].get("samples", [])
        if minimum_frame <= int(sample["frameIndex"]) <= maximum_frame
    ]
    samples.sort(key=lambda item: int(item["frameIndex"]))
    frames = [
        {
            "frameIndex": int(sample["frameIndex"]),
            "wristUv": np.asarray(sample["pixelLandmarks"][0], dtype=np.float64),
            "jointShapeUv": (
                np.asarray(sample["pixelLandmarks"], dtype=np.float64)
                - np.asarray(sample["pixelLandmarks"][0], dtype=np.float64)
            ),
            "confidence": float(sample.get("confidence", 0.0)),
            "densified": bool(sample.get("densified", False)),
        }
        for sample in samples
    ]
    wrist_acceleration: list[float] = []
    joint_acceleration: list[float] = []
    wrist_high_pass: list[float] = []
    joint_high_pass: list[float] = []
    per_frame: list[dict[str, Any]] = []
    for index in range(1, len(frames) - 1):
        if (
            frames[index]["frameIndex"] != frames[index - 1]["frameIndex"] + 1
            or frames[index + 1]["frameIndex"] != frames[index]["frameIndex"] + 1
        ):
            continue
        wrist_value = float(
            np.linalg.norm(
                frames[index + 1]["wristUv"]
                - 2.0 * frames[index]["wristUv"]
                + frames[index - 1]["wristUv"]
            )
        )
        joint_value = _rms(
            frames[index + 1]["jointShapeUv"]
            - 2.0 * frames[index]["jointShapeUv"]
            + frames[index - 1]["jointShapeUv"]
        )
        wrist_acceleration.append(wrist_value)
        joint_acceleration.append(joint_value)
        per_frame.append(
            {
                "frameIndex": frames[index]["frameIndex"],
                "wristUvAccelerationPixels": wrist_value,
                "jointShapeUvAccelerationPixelsRms": joint_value,
                "confidence": frames[index]["confidence"],
                "densified": frames[index]["densified"],
            }
        )
    wrist_values = [frame["wristUv"] for frame in frames]
    joint_values = [frame["jointShapeUv"] for frame in frames]
    for index in range(2, len(frames) - 2):
        frame_indices = [
            frames[offset]["frameIndex"]
            for offset in range(index - 2, index + 3)
        ]
        if frame_indices != list(range(frame_indices[0], frame_indices[0] + 5)):
            continue
        wrist_high_pass.append(
            float(np.linalg.norm(_centered_high_pass(wrist_values, index)))
        )
        joint_high_pass.append(
            _rms(_centered_high_pass(joint_values, index))
        )
    return {
        "frameCount": len(frames),
        "densifiedFrameCount": sum(frame["densified"] for frame in frames),
        "metrics": {
            "wristUvAccelerationPixels": _percentiles(wrist_acceleration),
            "jointShapeUvAccelerationPixelsRms": _percentiles(
                joint_acceleration
            ),
            "wristUvFiveFrameHighPassPixels": _percentiles(wrist_high_pass),
            "jointShapeUvFiveFrameHighPassPixelsRms": _percentiles(
                joint_high_pass
            ),
        },
        "largestWristAccelerationFrames": sorted(
            per_frame,
            key=lambda item: item["wristUvAccelerationPixels"],
            reverse=True,
        )[:outlier_count],
        "largestJointShapeAccelerationFrames": sorted(
            per_frame,
            key=lambda item: item["jointShapeUvAccelerationPixelsRms"],
            reverse=True,
        )[:outlier_count],
    }


def _analyze_surface_height(
    report_path: Path | None,
    minimum_frame: int,
    maximum_frame: int,
) -> dict[str, Any] | None:
    if report_path is None:
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    frames = [
        frame
        for frame in report["frames"]
        if minimum_frame <= int(frame["frameIndex"]) <= maximum_frame
        and frame.get("surfaceAnchorWorldY") is not None
    ]
    frames.sort(key=lambda item: int(item["frameIndex"]))
    velocity: list[float] = []
    acceleration: list[float] = []
    high_pass: list[float] = []
    for index in range(1, len(frames)):
        if int(frames[index]["frameIndex"]) != int(frames[index - 1]["frameIndex"]) + 1:
            continue
        velocity.append(
            abs(
                float(frames[index]["surfaceAnchorWorldY"])
                - float(frames[index - 1]["surfaceAnchorWorldY"])
            )
            * 1000.0
        )
    for index in range(1, len(frames) - 1):
        indices = [int(frames[offset]["frameIndex"]) for offset in range(index - 1, index + 2)]
        if indices != list(range(indices[0], indices[0] + 3)):
            continue
        values = [float(frames[offset]["surfaceAnchorWorldY"]) for offset in range(index - 1, index + 2)]
        acceleration.append(abs(values[2] - 2.0 * values[1] + values[0]) * 1000.0)
    for index in range(2, len(frames) - 2):
        indices = [int(frames[offset]["frameIndex"]) for offset in range(index - 2, index + 3)]
        if indices != list(range(indices[0], indices[0] + 5)):
            continue
        values = [
            np.array(float(frame["surfaceAnchorWorldY"]), dtype=np.float64)
            for frame in frames
        ]
        high_pass.append(abs(float(_centered_high_pass(values, index))) * 1000.0)
    return {
        "frameCount": len(frames),
        "velocityMillimeters": _percentiles(velocity),
        "accelerationMillimeters": _percentiles(acceleration),
        "fiveFrameHighPassMillimeters": _percentiles(high_pass),
    }


def main() -> None:
    args = _parse_args()
    frames = _load_fit_frames(
        args.fit_dir,
        args.minimum_frame,
        args.maximum_frame,
    )
    if not frames:
        raise SystemExit("No fitted MANO NPZ frames found in the requested range")
    report = {
        "schemaVersion": 1,
        "method": "centered five-frame and second-difference MANO stability audit",
        "fitDirectory": str(args.fit_dir.resolve()),
        "fusionReport": (
            str(args.fusion_report.resolve())
            if args.fusion_report is not None
            else None
        ),
        "trackJson": (
            str(args.track_json.resolve())
            if args.track_json is not None
            else None
        ),
        "track": _analyze_track(
            args.track_json,
            args.minimum_frame,
            args.maximum_frame,
            args.outlier_count,
        ),
        "fit": _analyze_fit(frames, args.outlier_count),
        "surfaceHeight": _analyze_surface_height(
            args.fusion_report,
            args.minimum_frame,
            args.maximum_frame,
        ),
    }
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
