#!/usr/bin/env python3
"""Decode an Azure Kinect recording into aligned, variable-length RGB-D frames.

Azure Kinect recordings may start one stream before the other.  The historical
SandStories inputs paired the Nth color image with the Nth depth image, so this
decoder queues the streams independently and emits pairs in stream order.  RGB
is projected into the native depth-camera plane using the recording's embedded
calibration.  No recording-specific frame count or time range is assumed.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pyk4a import PyK4APlayback
from pyk4a.calibration import Calibration, CalibrationType


def decode_color(value: np.ndarray | None) -> np.ndarray | None:
    if value is None:
        return None
    image = np.asarray(value)
    if image.ndim == 1:
        return cv2.imdecode(image.astype(np.uint8, copy=False), cv2.IMREAD_COLOR)
    if image.ndim == 3 and image.shape[2] == 4:
        return image[:, :, :3].copy()
    if image.ndim == 3 and image.shape[2] == 3:
        return image.copy()
    raise RuntimeError(f"unsupported Azure Kinect color array shape: {image.shape}")


class ColorToDepthRegistration:
    """CPU registration using the SDK calibration and OpenCV's rational model."""

    def __init__(self, calibration: Calibration, depth_shape: tuple[int, int]):
        self.depth_shape = depth_shape
        self.depth_matrix = calibration.get_camera_matrix(CalibrationType.DEPTH)
        self.depth_distortion = calibration.get_distortion_coefficients(CalibrationType.DEPTH)
        self.color_matrix = calibration.get_camera_matrix(CalibrationType.COLOR)
        self.color_distortion = calibration.get_distortion_coefficients(CalibrationType.COLOR)
        rotation, translation_metres = calibration.get_extrinsic_parameters(
            CalibrationType.DEPTH, CalibrationType.COLOR
        )
        self.rotation = np.asarray(rotation, dtype=np.float64)
        self.translation_mm = np.asarray(translation_metres, dtype=np.float64).reshape(3) * 1000.0

        height, width = depth_shape
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        pixels = np.stack((xx, yy), axis=-1).reshape(-1, 1, 2)
        rays_xy = cv2.undistortPoints(
            pixels, self.depth_matrix, self.depth_distortion
        ).reshape(-1, 2)
        self.rays = np.column_stack(
            (rays_xy, np.ones(rays_xy.shape[0], dtype=np.float32))
        ).astype(np.float64)

    def apply(self, color: np.ndarray, depth: np.ndarray) -> np.ndarray:
        if depth.shape != self.depth_shape or depth.dtype != np.uint16:
            raise RuntimeError(
                f"depth changed shape/type within recording: {depth.shape} {depth.dtype}"
            )
        z = depth.reshape(-1).astype(np.float64)
        points_depth = self.rays * z[:, None]
        points_color = points_depth @ self.rotation.T + self.translation_mm
        projected, _ = cv2.projectPoints(
            points_color,
            np.zeros(3, dtype=np.float64),
            np.zeros(3, dtype=np.float64),
            self.color_matrix,
            self.color_distortion,
        )
        maps = projected.reshape(*self.depth_shape, 2).astype(np.float32)
        invalid = (depth == 0) | (points_color[:, 2].reshape(self.depth_shape) <= 0)
        maps[invalid] = -1
        return cv2.remap(
            color,
            maps[:, :, 0],
            maps[:, :, 1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )


def enum_name(value: Any) -> str:
    return getattr(value, "name", str(value))


def decode(input_path: Path, output_root: Path, max_frames: int = 0) -> dict[str, Any]:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to mix output into non-empty directory: {output_root}")
    rgb_root = output_root / "rgb"
    depth_root = output_root / "depth"
    rgb_root.mkdir(parents=True, exist_ok=True)
    depth_root.mkdir(parents=True, exist_ok=True)

    playback = PyK4APlayback(input_path)
    playback.open()
    color_queue: deque[tuple[np.ndarray, int]] = deque()
    depth_queue: deque[tuple[np.ndarray, int]] = deque()
    color_seen = 0
    depth_seen = 0
    paired = 0
    timestamp_deltas_usec: list[int] = []
    frame_timestamps: list[dict[str, int | float]] = []
    first_depth_timestamp: int | None = None
    registration: ColorToDepthRegistration | None = None
    configuration = {key: enum_name(value) for key, value in playback.configuration.items()}

    try:
        while not max_frames or paired < max_frames:
            try:
                capture = playback.get_next_capture()
            except EOFError:
                break

            encoded_color = capture.color
            if encoded_color is not None:
                color = decode_color(encoded_color)
                if color is None:
                    raise RuntimeError(f"OpenCV could not decode color frame {color_seen + 1}")
                color_seen += 1
                color_queue.append((color, int(capture.color_timestamp_usec)))

            depth = capture.depth
            if depth is not None:
                depth_seen += 1
                depth_queue.append((depth.copy(), int(capture.depth_timestamp_usec)))

            while color_queue and depth_queue and (not max_frames or paired < max_frames):
                color, color_timestamp = color_queue.popleft()
                depth, depth_timestamp = depth_queue.popleft()
                if registration is None:
                    registration = ColorToDepthRegistration(playback.calibration, depth.shape)
                aligned = registration.apply(color, depth)
                paired += 1
                if first_depth_timestamp is None:
                    first_depth_timestamp = depth_timestamp
                rgb_path = rgb_root / f"frame_{paired:06d}.jpg"
                depth_path = depth_root / f"depth_{paired:06d}.png"
                if not cv2.imwrite(str(rgb_path), aligned, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                    raise OSError(f"failed to write {rgb_path}")
                if not cv2.imwrite(str(depth_path), depth):
                    raise OSError(f"failed to write {depth_path}")
                timestamp_deltas_usec.append(color_timestamp - depth_timestamp)
                frame_timestamps.append(
                    {
                        "frameIndex": paired,
                        "colorTimestampUsec": color_timestamp,
                        "depthTimestampUsec": depth_timestamp,
                        "timeSeconds": (depth_timestamp - first_depth_timestamp) / 1_000_000.0,
                        "colorTimeSeconds": (color_timestamp - first_depth_timestamp) / 1_000_000.0,
                        "pairDeltaUsec": color_timestamp - depth_timestamp,
                    }
                )
                if paired == 1 or paired % 100 == 0:
                    print(f"decoded {paired} aligned RGB-D pairs", flush=True)
    finally:
        calibration_raw = playback.calibration_raw
        playback.close()

    if paired == 0:
        raise RuntimeError("recording contains no pairable color and depth frames")
    deltas = np.asarray(timestamp_deltas_usec, dtype=np.int64)
    depth_times = np.asarray(
        [int(record["depthTimestampUsec"]) for record in frame_timestamps], dtype=np.int64
    )
    positive_intervals = np.diff(depth_times)
    positive_intervals = positive_intervals[positive_intervals > 0]
    nominal_fps = (
        1_000_000.0 / float(np.median(positive_intervals))
        if positive_intervals.size
        else None
    )
    manifest = {
        "format": "sandstories_aligned_azure_kinect_rgbd_v1",
        "source": input_path.name,
        "frameCount": paired,
        "frameSize": {"width": registration.depth_shape[1], "height": registration.depth_shape[0]},
        "numbering": {"first": 1, "last": paired, "continuous": True},
        "timestampMetadataFile": "capture_frames.jsonl",
        "nominalFps": nominal_fps,
        "configuration": configuration,
        "streams": {
            "colorFramesRead": color_seen,
            "depthFramesRead": depth_seen,
            "unpairedColorFrames": color_seen - paired,
            "unpairedDepthFrames": depth_seen - paired,
        },
        "pairing": "Nth color frame with Nth depth frame; incomplete leading/trailing captures are queued independently",
        "colorRegistration": "color projected into native depth-camera coordinates using embedded calibration",
        "timestampDeltaUsec": {
            "minimum": int(deltas.min()),
            "median": float(np.median(deltas)),
            "maximum": int(deltas.max()),
        },
        "diagnosticFrameLimit": max_frames or None,
    }
    (output_root / "calibration.json").write_text(calibration_raw, encoding="utf-8")
    with (output_root / "capture_frames.jsonl").open("w", encoding="utf-8") as stream:
        for record in frame_timestamps:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    (output_root / "capture_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2), flush=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="diagnostic limit only; production leaves this at zero and decodes through EOF",
    )
    args = parser.parse_args()
    decode(args.input.resolve(), args.output.resolve(), max(0, args.max_frames))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
