#!/usr/bin/env python3
"""Convert an Azure Kinect DK MKV recording into a SandStories v2 session.

The source MKV remains the immutable sensor recording.  This adapter extracts
native metric depth into ``streams/depth.f32`` and calibration-aligned colour
into ``streams/rgb.mp4`` so the existing evaluator and Godot production adapter
can consume the result without pretending the device is an iPhone/ARKit source.

Azure Kinect playback support is imported lazily.  Install the archived Sensor
SDK first, then install ``scripts/requirements-azure-kinect.txt`` into the
Windows Python environment that can load ``k4a.dll``.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import numpy as np


IDENTITY_4X4_COLUMN_MAJOR = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


class FFmpegVideoSink:
    """Stream depth-aligned BGR frames to a constant-rate H.264 MP4."""

    def __init__(self, path: Path, width: int, height: int, fps: float, ffmpeg: str = "ffmpeg") -> None:
        executable = shutil.which(ffmpeg) or (ffmpeg if Path(ffmpeg).is_file() else None)
        if not executable:
            raise FileNotFoundError(
                "ffmpeg was not found. Install ffmpeg or pass --ffmpeg with its full path."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.width = width
        self.height = height
        self.frame_count = 0
        self.process = subprocess.Popen(
            [
                str(executable),
                "-y",
                "-loglevel", "error",
                "-f", "rawvideo",
                "-pixel_format", "bgr24",
                "-video_size", f"{width}x{height}",
                "-framerate", f"{fps:g}",
                "-i", "-",
                "-an",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def write(self, frame_bgr: np.ndarray) -> None:
        if frame_bgr.shape != (self.height, self.width, 3):
            raise ValueError(
                f"RGB frame shape changed: expected {(self.height, self.width, 3)}, "
                f"got {frame_bgr.shape}"
            )
        if self.process.stdin is None:
            raise RuntimeError("ffmpeg stdin is unavailable")
        self.process.stdin.write(np.ascontiguousarray(frame_bgr, dtype=np.uint8).tobytes())
        self.frame_count += 1

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
            self.process.stdin = None
        stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
        return_code = self.process.wait(timeout=60)
        if return_code != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {return_code}: {stderr.strip()}")
        if self.frame_count == 0 or not self.path.is_file() or self.path.stat().st_size == 0:
            raise RuntimeError("ffmpeg produced no RGB video")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "name"):
        return str(value.name)
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _media_duration(path: Path, ffprobe: str = "ffprobe") -> float:
    if not path.is_file() or path.stat().st_size == 0:
        return 0.0
    executable = shutil.which(ffprobe) or (ffprobe if Path(ffprobe).is_file() else None)
    if not executable:
        return 0.0
    try:
        result = subprocess.run(
            [
                str(executable),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return max(0.0, float(result.stdout.strip())) if result.returncode == 0 else 0.0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _capture_array(capture: Any, name: str) -> np.ndarray | None:
    try:
        value = getattr(capture, name)
    except Exception:
        return None
    if value is None:
        return None
    array = np.asarray(value)
    return array if array.size else None


def _decode_color(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3 and image.shape[2] == 4:
        return np.ascontiguousarray(image[:, :, :3], dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 3:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim in (1, 2):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv-python is required to decode Azure Kinect MJPEG colour") from exc
        decoded = cv2.imdecode(np.asarray(image, dtype=np.uint8).reshape(-1), cv2.IMREAD_COLOR)
        if decoded is None:
            raise RuntimeError("Could not decode Azure Kinect colour frame")
        return decoded
    raise RuntimeError(f"Unsupported Azure Kinect colour shape: {image.shape}")


def _aligned_color(
    capture: Any,
    depth_image: np.ndarray,
    *,
    allow_resized_color: bool,
    color_to_depth_transform: Callable[[np.ndarray, np.ndarray], np.ndarray | None] | None = None,
) -> tuple[np.ndarray, str]:
    depth_shape = depth_image.shape
    transformed = _capture_array(capture, "transformed_color")
    if transformed is not None:
        decoded = _decode_color(transformed)
        if decoded.shape[:2] == depth_shape:
            return decoded, "k4a_calibration_transformed_color_to_depth"

    raw = _capture_array(capture, "color")
    if raw is None:
        raise RuntimeError("Capture has depth but no colour frame")
    decoded = _decode_color(raw)
    if decoded.shape[:2] == depth_shape:
        return decoded, "color_already_matches_depth_geometry"
    if color_to_depth_transform is not None:
        calibrated = color_to_depth_transform(decoded, depth_image)
        if calibrated is not None:
            calibrated_decoded = _decode_color(np.asarray(calibrated))
            if calibrated_decoded.shape[:2] == depth_shape:
                return calibrated_decoded, "k4a_calibration_decoded_mjpeg_color_to_depth"
    if not allow_resized_color:
        raise RuntimeError(
            "Calibration-aligned transformed_color was unavailable. Refusing an uncalibrated "
            "resize; install a working pyk4a/OpenCV stack or explicitly pass --allow-resized-color."
        )
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python is required for --allow-resized-color") from exc
    height, width = depth_shape
    return cv2.resize(decoded, (width, height), interpolation=cv2.INTER_AREA), "uncalibrated_resize"


def _timestamp_usec(capture: Any, name: str) -> int | None:
    try:
        value = getattr(capture, name)
    except Exception:
        return None
    if isinstance(value, (int, np.integer)) and int(value) >= 0:
        return int(value)
    return None


def _matrix3(value: Any, label: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.size != 9:
        raise RuntimeError(f"Azure Kinect {label} intrinsics are unavailable or invalid")
    matrix = matrix.reshape((3, 3))
    if not np.all(np.isfinite(matrix)) or matrix[0, 0] <= 0 or matrix[1, 1] <= 0:
        raise RuntimeError(f"Azure Kinect {label} intrinsics are invalid")
    return matrix


def _column_major(matrix: np.ndarray) -> list[float]:
    return [float(value) for value in matrix.flatten(order="F")]


def extract_playback_calibration(playback: Any) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    try:
        from pyk4a import CalibrationType
    except ImportError as exc:
        raise RuntimeError("pyk4a is required to extract Azure Kinect calibration") from exc

    calibration = playback.calibration
    depth_matrix = _matrix3(
        calibration.get_camera_matrix(CalibrationType.DEPTH),
        "depth",
    )
    color_matrix = _matrix3(
        calibration.get_camera_matrix(CalibrationType.COLOR),
        "colour",
    )
    info: dict[str, Any] = {
        "depthCameraMatrix": depth_matrix.tolist(),
        "colorCameraMatrix": color_matrix.tolist(),
    }
    for key, camera_type in (("depthDistortion", CalibrationType.DEPTH), ("colorDistortion", CalibrationType.COLOR)):
        try:
            info[key] = _json_safe(calibration.get_distortion_coefficients(camera_type))
        except Exception:
            info[key] = None
    try:
        info["depthToColorExtrinsics"] = _json_safe(
            calibration.get_extrinsics(CalibrationType.DEPTH, CalibrationType.COLOR)
        )
    except Exception:
        info["depthToColorExtrinsics"] = None
    return depth_matrix, color_matrix, info


def _audio_entry(
    session_dir: Path,
    audio_path: Path | None,
    recording_metadata: dict[str, Any],
    *,
    ffprobe: str,
    duration_override: float | None,
) -> tuple[dict[str, Any] | None, float | None]:
    if audio_path is None:
        return None, None
    audio_path = audio_path.resolve()
    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        raise RuntimeError(f"Audio file is missing or empty: {audio_path}")
    try:
        relative = audio_path.relative_to(session_dir.resolve()).as_posix()
    except ValueError:
        destination = session_dir / f"audio{audio_path.suffix.lower() or '.wav'}"
        shutil.copy2(audio_path, destination)
        audio_path = destination
        relative = destination.relative_to(session_dir).as_posix()

    duration = duration_override if duration_override is not None else _media_duration(audio_path, ffprobe)
    audio_start = _parse_utc(recording_metadata.get("audioStartedUtc"))
    kinect_start = _parse_utc(recording_metadata.get("kinectStartedUtc"))
    exact_offset = (audio_start - kinect_start).total_seconds() if audio_start and kinect_start else 0.0
    return (
        {
            "relativePath": relative,
            "startMonotonicElapsedSeconds": max(0.0, exact_offset),
            "durationSeconds": max(0.0, float(duration)),
            "sampleRate": int(recording_metadata.get("audioSampleRate", 48_000)),
            "channelCount": int(recording_metadata.get("audioChannels", 1)),
            "format": audio_path.suffix.lower().lstrip(".") or "wav",
        },
        exact_offset,
    )


def convert_capture_sequence(
    captures: Iterable[Any],
    session_dir: Path,
    *,
    session_id: str,
    fps: float,
    depth_intrinsics: np.ndarray,
    color_intrinsics: np.ndarray | None = None,
    calibration_info: dict[str, Any] | None = None,
    source_mkv: str = "source/azure_kinect.mkv",
    recording_metadata: dict[str, Any] | None = None,
    recording_configuration: dict[str, Any] | None = None,
    audio_path: Path | None = None,
    audio_duration_seconds: float | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    allow_resized_color: bool = False,
    video_sink_factory: Callable[[Path, int, int, float], Any] | None = None,
    color_to_depth_transform: Callable[[np.ndarray, np.ndarray], np.ndarray | None] | None = None,
    baseline_seconds: float = 3.0,
) -> dict[str, Any]:
    """Convert decoded captures. This core is injectable so it can be tested without hardware."""
    if baseline_seconds < 0.0:
        raise ValueError("baseline_seconds must be non-negative")
    if fps <= 0:
        raise ValueError("fps must be positive")
    session_dir = session_dir.resolve()
    streams_dir = session_dir / "streams"
    streams_dir.mkdir(parents=True, exist_ok=True)
    depth_path = streams_dir / "depth.f32"
    rgb_path = streams_dir / "rgb.mp4"
    metadata_path = session_dir / "v2_frames.jsonl"

    depth_matrix = _matrix3(depth_intrinsics, "depth")
    color_matrix = _matrix3(color_intrinsics if color_intrinsics is not None else depth_matrix, "colour")
    depth_matrix_column_major = _column_major(depth_matrix)
    color_matrix_column_major = _column_major(color_matrix)
    recording_metadata = dict(recording_metadata or {})
    recording_configuration = dict(recording_configuration or {})

    sink = None
    sink_factory = video_sink_factory or (
        lambda path, width, height, rate: FFmpegVideoSink(path, width, height, rate, ffmpeg)
    )
    frame_records: list[dict[str, Any]] = []
    alignment_methods: set[str] = set()
    first_depth_timestamp: int | None = None
    depth_offset = 0
    skipped_missing_depth = 0
    skipped_missing_color = 0

    try:
        with depth_path.open("wb") as depth_handle:
            for capture in captures:
                depth_mm = _capture_array(capture, "depth")
                if depth_mm is None or depth_mm.ndim != 2:
                    skipped_missing_depth += 1
                    continue
                depth_mm = np.asarray(depth_mm, dtype=np.uint16)
                height, width = depth_mm.shape
                try:
                    color_bgr, alignment_method = _aligned_color(
                        capture,
                        depth_mm,
                        allow_resized_color=allow_resized_color,
                        color_to_depth_transform=color_to_depth_transform,
                    )
                except RuntimeError as exc:
                    skipped_missing_color += 1
                    if "no colour frame" in str(exc):
                        continue
                    raise

                alignment_methods.add(alignment_method)
                if sink is None:
                    sink = sink_factory(rgb_path, width, height, fps)
                sink.write(color_bgr)

                depth_timestamp = _timestamp_usec(capture, "depth_timestamp_usec")
                if depth_timestamp is None:
                    depth_timestamp = int(round(len(frame_records) * 1_000_000.0 / fps))
                if first_depth_timestamp is None:
                    first_depth_timestamp = depth_timestamp
                elapsed = max(0.0, (depth_timestamp - first_depth_timestamp) / 1_000_000.0)
                color_timestamp = _timestamp_usec(capture, "color_timestamp_usec")
                rgb_elapsed = (
                    max(0.0, (color_timestamp - first_depth_timestamp) / 1_000_000.0)
                    if color_timestamp is not None
                    else elapsed
                )

                valid = depth_mm > 0
                depth_m = depth_mm.astype(np.float32) * 0.001
                depth_m[~valid] = np.nan
                encoded = np.asarray(depth_m, dtype="<f4").tobytes(order="C")
                depth_handle.write(encoded)
                valid_values = depth_m[valid]
                frame_index = len(frame_records) + 1
                is_baseline_phase = elapsed <= baseline_seconds
                record: dict[str, Any] = {
                    "frameIndex": frame_index,
                    "baselinePhase": is_baseline_phase,
                    "arTimestamp": depth_timestamp / 1_000_000.0,
                    "monotonicElapsedSeconds": elapsed,
                    "width": width,
                    "height": height,
                    "selectedDepthSource": "azureKinectDepth",
                    "sourceDepthPixelFormat": "K4A_IMAGE_FORMAT_DEPTH16_MILLIMETERS",
                    "depthBytesPerRow": width * 4,
                    "storedDepthFormat": "float32_little_endian_meters_contiguous",
                    "depthByteOffset": depth_offset,
                    "depthByteCount": len(encoded),
                    "depthValidPixelRatio": float(valid.mean()),
                    "depthMinMeters": float(np.min(valid_values)) if valid_values.size else None,
                    "depthMedianMeters": float(np.median(valid_values)) if valid_values.size else None,
                    "depthMaxMeters": float(np.max(valid_values)) if valid_values.size else None,
                    "smoothedDepthByteOffset": None,
                    "smoothedDepthByteCount": None,
                    "confidenceByteOffset": None,
                    "confidenceByteCount": None,
                    "confidenceAvailable": False,
                    "rgbPresentationTimeSeconds": rgb_elapsed,
                    "cameraTransformColumnMajor": IDENTITY_4X4_COLUMN_MAJOR,
                    "cameraIntrinsicsColumnMajor": depth_matrix_column_major,
                    "cameraIntrinsicsReference": "azure_kinect_calibration_depth_camera",
                    "rgbCameraIntrinsicsColumnMajor": depth_matrix_column_major,
                    "cameraImageResolutionWidth": width,
                    "cameraImageResolutionHeight": height,
                    "enabledFrameSemantics": ["depth", "color_aligned_to_depth"],
                    "captureProfile": "azure_kinect_dk",
                }
                try:
                    temperature = float(getattr(capture, "temperature"))
                    record["sensorTemperatureCelsius"] = temperature if math.isfinite(temperature) else None
                except Exception:
                    pass
                frame_records.append(record)
                depth_offset += len(encoded)
    finally:
        if sink is not None:
            sink.close()

    if not frame_records:
        raise RuntimeError("No synchronized Azure Kinect depth/colour captures were decoded")

    baseline_frame_count = sum(1 for record in frame_records if record.get("baselinePhase"))
    baseline_window_seconds = float(baseline_seconds)
    if baseline_frame_count == 0 and frame_records:
        baseline_window_seconds = 0.0

    with metadata_path.open("w", encoding="utf-8") as metadata_handle:
        for record in frame_records:
            metadata_handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")

    (session_dir / "objects.jsonl").touch(exist_ok=True)
    (session_dir / "boundary_samples.jsonl").touch(exist_ok=True)
    if not (session_dir / "strokes.json").exists():
        (session_dir / "strokes.json").write_text("[]\n", encoding="utf-8")

    audio, audio_exact_offset = _audio_entry(
        session_dir,
        audio_path,
        recording_metadata,
        ffprobe=ffprobe,
        duration_override=audio_duration_seconds,
    )
    last_elapsed = float(frame_records[-1]["monotonicElapsedSeconds"])
    duration = max(last_elapsed + 1.0 / fps, len(frame_records) / fps)
    kinect_started = _parse_utc(recording_metadata.get("kinectStartedUtc"))
    wall_start = kinect_started.timestamp() if kinect_started else time.time()

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "captureFormat": "v2_streams",
        "captureDeviceFamily": "azure_kinect_dk",
        "sessionId": session_id,
        "deviceModel": "Azure Kinect DK",
        "osVersion": str(recording_metadata.get("osVersion", "Windows")),
        "appVersion": "azure-kinect-adapter-v1",
        "wallClockStartUnix": wall_start,
        "wallClockEndUnix": wall_start + duration,
        "monotonicSessionStart": {
            "description": "Azure Kinect depth_timestamp_usec, anchored to first retained capture"
        },
        "monotonicSessionEndElapsedSeconds": duration,
        "sensorTimeReference": {
            "source": "K4A capture timestamps in microseconds",
            "firstDepthTimestampUsec": first_depth_timestamp,
        },
        "storage": {
            "destination": "windows_filesystem",
            "sessionFolderRelative": session_dir.name,
            "securityScopedExternal": False,
        },
        "depthEncoding": {
            "format": "v2_streams_float32",
            "maxDepthMeters": float(recording_metadata.get("maxDepthMeters", 5.46)),
            "deltaMeanAbsThresholdU16": 0.0,
            "note": "Azure Kinect DEPTH16 millimetres converted losslessly to Float32 metres; zero samples are stored as NaN.",
        },
        "baselinePhase": {
            "windowSeconds": baseline_window_seconds,
            "frameCount": baseline_frame_count,
            "note": "Frames within the first baselinePhase.windowSeconds of retained depth time are marked baselinePhase=true in v2_frames.jsonl. The offline pipeline uses these (stability-gated) to fix the untouched sand baseline so later grooves/drawings are encoded as deltas.",
        },
        "depthFrames": [],
        "rgbFrames": [],
        "audio": audio,
        "strokesFile": "strokes.json",
        "trayBoundary": {
            "status": "pending",
            "cornersNormalized": None,
            "note": "Azure Kinect recording does not perform on-device tray detection.",
        },
        "objectDetectionsFile": "objects.jsonl",
        "objectDetectionProvenance": "postprocessed_yolo_world_v1",
        "boundarySamplesFile": "boundary_samples.jsonl",
        "v2Streams": {
            "formatVersion": 2,
            "frameMetadataFile": "v2_frames.jsonl",
            "rgbVideoPath": "streams/rgb.mp4",
            "rgbVideoCodec": "h264_mp4_depth_aligned",
            "depthStreamPath": "streams/depth.f32",
            "depthFormat": "float32_little_endian_meters_contiguous",
            "smoothedDepthStreamPath": None,
            "confidenceStreamPath": None,
            "note": "Depth is native Azure Kinect metric depth. RGB is calibration-transformed into depth geometry before H.264 encoding. The source MKV remains authoritative.",
        },
        "azureKinect": {
            "sourceMkv": source_mkv,
            "recordingConfiguration": _json_safe(recording_configuration),
            "calibration": _json_safe(calibration_info or {}),
            "depthCameraIntrinsics": depth_matrix.tolist(),
            "originalColorCameraIntrinsics": color_matrix.tolist(),
            "rgbAlignmentMethods": sorted(alignment_methods),
            "audioStartOffsetSecondsExact": audio_exact_offset,
            "skippedCapturesMissingDepth": skipped_missing_depth,
            "skippedCapturesMissingColor": skipped_missing_color,
            "confidenceNote": "Azure Kinect SDK provides validity through zero/non-zero DEPTH16 samples, not ARKit-style confidence levels.",
        },
    }
    _write_json(session_dir / "manifest.json", manifest)
    return manifest


def _recording_fps(configuration: dict[str, Any], fallback: float) -> float:
    value = str(configuration.get("camera_fps", configuration.get("cameraFps", ""))).upper()
    for candidate in (30, 15, 5):
        if str(candidate) in value:
            return float(candidate)
    return fallback


def _playback_captures(playback: Any) -> Iterator[Any]:
    while True:
        try:
            yield playback.get_next_capture()
        except EOFError:
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Azure Kinect DK MKV to SandStories v2 streams")
    parser.add_argument("mkv", type=Path, help="Azure Kinect k4arecorder MKV")
    parser.add_argument("--session-dir", type=Path, required=True, help="SandStories output session folder")
    parser.add_argument("--session-id", help="Stable session identifier; defaults to the output folder name")
    parser.add_argument("--audio", type=Path, help="Separately recorded microphone audio")
    parser.add_argument("--recording-metadata", type=Path, help="Recorder timing/configuration JSON")
    parser.add_argument("--fps", type=float, default=30.0, help="Fallback/output video frame rate")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--sensor-height-cm", type=int, default=80)
    parser.add_argument("--lighting", choices=["shade", "direct_sun", "overcast", "indoor"], default="indoor")
    parser.add_argument("--surface-type", choices=["dry", "wet"], default="dry")
    parser.add_argument("--replicate", type=int, default=1)
    parser.add_argument("--allow-resized-color", action="store_true", help="Permit uncalibrated RGB resize only for diagnostics")
    parser.add_argument("--no-copy-source", action="store_true", help="Reference an external MKV instead of copying it into the package")
    parser.add_argument("--baseline-seconds", type=float, default=3.0, help="Untouched-sand baseline window in seconds; frames in this window are marked baselinePhase=true in v2_frames.jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mkv = args.mkv.resolve()
    if not mkv.is_file() or mkv.stat().st_size == 0:
        print(f"Error: Azure Kinect MKV is missing or empty: {mkv}", file=sys.stderr)
        return 1
    session_dir = args.session_dir.resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    source_dir = session_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    packaged_mkv = source_dir / "azure_kinect.mkv"
    if args.no_copy_source:
        try:
            source_reference = mkv.relative_to(session_dir).as_posix()
        except ValueError:
            source_reference = str(mkv)
    else:
        if mkv != packaged_mkv.resolve():
            shutil.copy2(mkv, packaged_mkv)
        source_reference = packaged_mkv.relative_to(session_dir).as_posix()

    conditions_path = session_dir / "conditions.json"
    if not conditions_path.exists():
        _write_json(
            conditions_path,
            {
                "sensorHeightCm": args.sensor_height_cm,
                "lighting": args.lighting,
                "surfaceType": args.surface_type,
                "replicate": args.replicate,
            },
        )

    try:
        from pyk4a import PyK4APlayback
    except ImportError:
        print(
            "Error: pyk4a is not installed. Use the Windows Python environment and run "
            "'python -m pip install -r scripts/requirements-azure-kinect.txt'.",
            file=sys.stderr,
        )
        return 2

    playback = PyK4APlayback(str(mkv))
    try:
        playback.open()
        depth_matrix, color_matrix, calibration_info = extract_playback_calibration(playback)
        configuration_value = getattr(playback, "configuration", None)
        if configuration_value is None:
            configuration_value = getattr(playback, "record_configuration", {})
        configuration = _json_safe(configuration_value)
        if not isinstance(configuration, dict):
            configuration = {"value": configuration}
        fps = _recording_fps(configuration, args.fps)

        def transform_mjpeg_color_to_depth(color_bgr: np.ndarray, depth_mm: np.ndarray) -> np.ndarray | None:
            import cv2
            from pyk4a.transformation import color_image_to_depth_camera

            color_bgra = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2BGRA)
            return color_image_to_depth_camera(color_bgra, depth_mm, playback.calibration, True)

        manifest = convert_capture_sequence(
            _playback_captures(playback),
            session_dir,
            session_id=args.session_id or session_dir.name.removeprefix("session_"),
            fps=fps,
            depth_intrinsics=depth_matrix,
            color_intrinsics=color_matrix,
            calibration_info=calibration_info,
            source_mkv=source_reference,
            recording_metadata=_read_json(args.recording_metadata),
            recording_configuration=configuration,
            audio_path=args.audio,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            allow_resized_color=args.allow_resized_color,
            baseline_seconds=args.baseline_seconds,
            color_to_depth_transform=transform_mjpeg_color_to_depth,
        )
    except Exception as exc:
        print(f"Error converting Azure Kinect recording: {exc}", file=sys.stderr)
        return 3
    finally:
        try:
            playback.close()
        except Exception:
            pass

    with (session_dir / "v2_frames.jsonl").open("r", encoding="utf-8") as handle:
        frame_count = sum(1 for _ in handle)
    print(json.dumps({
        "sessionDir": str(session_dir),
        "sessionId": manifest["sessionId"],
        "durationSeconds": manifest["monotonicSessionEndElapsedSeconds"],
        "frameCount": frame_count,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
