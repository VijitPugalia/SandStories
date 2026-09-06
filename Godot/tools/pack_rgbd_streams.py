#!/usr/bin/env python3
"""Pack a processed RGB-D PNG sequence into, or restore it from, a stream bundle.

RGB may be FFV1 (pixel-lossless) or H.264 (compact). Depth is always FFV1
gray16 because lossy depth is not suitable for metric reconstruction. Frame
timing is carried in frames.jsonl; no constant recording frame rate is assumed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import zipfile


BUNDLE_FORMAT = "sandstories_rgbd_stream_bundle_v1"


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ffconcat_quote(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")


def frame_times(frames: list[dict], fallback_fps: float) -> list[float]:
    if fallback_fps <= 0:
        raise ValueError("fallback_fps must be positive")
    values: list[float] = []
    for index, frame in enumerate(frames):
        raw = frame.get("time")
        if raw is None:
            raw = frame.get("timeSeconds")
        values.append(float(raw) if raw is not None else index / fallback_fps)
    origin = values[0]
    values = [value - origin for value in values]
    if any(current <= previous for previous, current in zip(values, values[1:])):
        raise ValueError("frame timestamps must be strictly increasing")
    return values


def write_concat(path: Path, files: list[Path], times: list[float]) -> None:
    if len(files) != len(times) or not files:
        raise ValueError("concat input must contain a non-empty file/time pair sequence")
    lines = ["ffconcat version 1.0"]
    for index, file_path in enumerate(files):
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        lines.append(f"file '{ffconcat_quote(file_path)}'")
        if index + 1 < len(times):
            lines.append(f"duration {times[index + 1] - times[index]:.9f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def scale_filter(resolution: str) -> str | None:
    factors = {"native": 1.0, "75-percent": 0.75, "50-percent": 0.5}
    factor = factors.get(resolution)
    if factor is None:
        raise ValueError(f"unsupported RGB resolution: {resolution}")
    if factor == 1.0:
        return None
    return f"scale=trunc(iw*{factor}/2)*2:trunc(ih*{factor}/2)*2:flags=lanczos"


def probe_count(ffprobe: str, path: Path) -> int:
    raw = subprocess.check_output(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        text=True,
    ).strip()
    return int(raw)


def pack(
    session: Path,
    output: Path,
    mode: str,
    rgb_resolution: str,
    fallback_fps: float,
    ffmpeg: str,
    ffprobe: str,
) -> dict:
    manifest_path = session / "processed_manifest.json"
    manifest = read_json(manifest_path)
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("processed manifest contains no frames")
    if mode not in {"lossless", "compact"}:
        raise ValueError("mode must be lossless or compact")
    times = frame_times(frames, fallback_fps)
    rgb_files = [session / str(frame["cleanRgb"]) for frame in frames]
    depth_files = [session / str(frame["cleanDepth"]) for frame in frames]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(output.name + ".tmp")
    temporary_output.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="sandstories-streams-", dir=output.parent) as raw_tmp:
        root = Path(raw_tmp)
        streams = root / "streams"
        streams.mkdir()
        rgb_concat = root / "rgb.ffconcat"
        depth_concat = root / "depth.ffconcat"
        write_concat(rgb_concat, rgb_files, times)
        write_concat(depth_concat, depth_files, times)
        rgb_stream = streams / "rgb.mkv"
        depth_stream = streams / "depth.mkv"

        rgb_command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(rgb_concat),
            "-map",
            "0:v:0",
            "-fps_mode",
            "vfr",
        ]
        selected_scale = scale_filter(rgb_resolution)
        if selected_scale:
            rgb_command.extend(["-vf", selected_scale])
        if mode == "lossless":
            rgb_command.extend(
                ["-c:v", "ffv1", "-level", "3", "-coder", "1", "-context", "1", "-g", "1", "-slicecrc", "1", "-pix_fmt", "bgr0"]
            )
        else:
            rgb_command.extend(
                ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
            )
        rgb_command.extend(["-metadata:s:v:0", "sandstories_role=rgb", str(rgb_stream)])
        run(rgb_command)
        run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(depth_concat),
                "-map",
                "0:v:0",
                "-fps_mode",
                "vfr",
                "-c:v",
                "ffv1",
                "-level",
                "3",
                "-coder",
                "1",
                "-context",
                "1",
                "-g",
                "1",
                "-slicecrc",
                "1",
                "-pix_fmt",
                "gray16le",
                "-metadata:s:v:0",
                "sandstories_role=depth_uint16_mm",
                str(depth_stream),
            ]
        )
        expected = len(frames)
        for stream in (rgb_stream, depth_stream):
            actual = probe_count(ffprobe, stream)
            if actual != expected:
                raise RuntimeError(f"encoded stream frame count mismatch: {stream}: {actual} != {expected}")

        records = []
        for index, (frame, timestamp) in enumerate(zip(frames, times), start=1):
            records.append(
                {
                    "frameIndex": index,
                    "timeSeconds": timestamp,
                    "sourceFrameIndex": frame.get("sourceFrameIndex", frame.get("frameIndex", index)),
                }
            )
        with (root / "frames.jsonl").open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        shutil.copy2(manifest_path, root / "processed_manifest.json")
        width = int((manifest.get("frameSize") or {}).get("width", 0))
        height = int((manifest.get("frameSize") or {}).get("height", 0))
        bundle = {
            "format": BUNDLE_FORMAT,
            "frameCount": expected,
            "frameSize": {"width": width, "height": height},
            "timing": {"metadataFile": "frames.jsonl", "semantics": "per-frame presentation timestamps"},
            "rgb": {
                "path": "streams/rgb.mkv",
                "codec": "ffv1" if mode == "lossless" else "h264_crf18",
                "pixelLossless": mode == "lossless",
                "resolution": rgb_resolution,
            },
            "depth": {
                "path": "streams/depth.mkv",
                "codec": "ffv1_gray16le",
                "units": "millimetres",
                "invalidValue": 0,
                "pixelLossless": True,
            },
        }
        write_json(root / "bundle_manifest.json", bundle)
        with zipfile.ZipFile(temporary_output, "w", allowZip64=True) as archive:
            for item in sorted(root.rglob("*")):
                if not item.is_file() or item.name.endswith(".ffconcat"):
                    continue
                compression = zipfile.ZIP_STORED if item.suffix == ".mkv" else zipfile.ZIP_DEFLATED
                archive.write(item, item.relative_to(root).as_posix(), compress_type=compression)
        os.replace(temporary_output, output)
    return bundle


def safe_extract(archive: zipfile.ZipFile, root: Path) -> None:
    for info in archive.infolist():
        target = (root / info.filename).resolve()
        target.relative_to(root.resolve())
        mode = info.external_attr >> 16
        if mode & 0o170000 == 0o120000:
            raise ValueError(f"bundle symlink is not permitted: {info.filename}")
    archive.extractall(root)


def unpack(bundle_path: Path, output: Path, ffmpeg: str, ffprobe: str) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to mix output into non-empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sandstories-unpack-", dir=output.parent) as raw_tmp:
        root = Path(raw_tmp)
        with zipfile.ZipFile(bundle_path, "r") as archive:
            safe_extract(archive, root)
        manifest = read_json(root / "bundle_manifest.json")
        if manifest.get("format") != BUNDLE_FORMAT:
            raise ValueError("not a supported SandStories RGB-D stream bundle")
        expected = int(manifest.get("frameCount", 0))
        if expected <= 0:
            raise ValueError("bundle frameCount must be positive")
        rgb_stream = root / str(manifest["rgb"]["path"])
        depth_stream = root / str(manifest["depth"]["path"])
        for stream in (rgb_stream, depth_stream):
            stream.resolve().relative_to(root.resolve())
            if probe_count(ffprobe, stream) != expected:
                raise ValueError(f"bundle stream frame count mismatch: {stream.name}")
        rgb_root = output / "rgb"
        depth_root = output / "depth"
        rgb_root.mkdir()
        depth_root.mkdir()
        rgb_command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(rgb_stream), "-fps_mode", "passthrough"]
        native_width = int((manifest.get("frameSize") or {}).get("width", 0))
        native_height = int((manifest.get("frameSize") or {}).get("height", 0))
        if manifest["rgb"].get("resolution") != "native":
            if native_width <= 0 or native_height <= 0:
                raise ValueError("scaled RGB bundle lacks native frameSize")
            rgb_command.extend(["-vf", f"scale={native_width}:{native_height}:flags=lanczos"])
        rgb_command.extend(["-q:v", "2", str(rgb_root / "frame_%06d.jpg")])
        run(rgb_command)
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(depth_stream), "-fps_mode", "passthrough", "-pix_fmt", "gray16le", str(depth_root / "depth_%06d.png")])
        if len(list(rgb_root.glob("frame_*.jpg"))) != expected or len(list(depth_root.glob("depth_*.png"))) != expected:
            raise RuntimeError("decoded bundle frame count mismatch")
        frame_records = []
        for line in (root / "frames.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                frame_records.append(json.loads(line))
        if len(frame_records) != expected:
            raise ValueError("frames.jsonl count differs from bundle frameCount")
        shutil.copy2(root / "frames.jsonl", output / "capture_frames.jsonl")
        times = [float(record["timeSeconds"]) for record in frame_records]
        deltas = [current - previous for previous, current in zip(times, times[1:]) if current > previous]
        capture = {
            "format": BUNDLE_FORMAT,
            "source": bundle_path.name,
            "frameCount": expected,
            "frameSize": manifest.get("frameSize", {}),
            "timestampMetadataFile": "capture_frames.jsonl",
            "nominalFps": 1.0 / statistics.median(deltas) if deltas else None,
            "rgbSourceCodec": manifest["rgb"].get("codec"),
            "depthSourceCodec": manifest["depth"].get("codec"),
        }
        write_json(output / "capture_manifest.json", capture)
        return capture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pack_parser = sub.add_parser("pack")
    pack_parser.add_argument("--session", type=Path, required=True)
    pack_parser.add_argument("--output", type=Path, required=True)
    pack_parser.add_argument("--mode", choices=("lossless", "compact"), required=True)
    pack_parser.add_argument("--rgb-resolution", choices=("native", "75-percent", "50-percent"), default="native")
    pack_parser.add_argument("--fallback-fps", type=float, default=30.0)
    unpack_parser = sub.add_parser("unpack")
    unpack_parser.add_argument("--input", type=Path, required=True)
    unpack_parser.add_argument("--output", type=Path, required=True)
    for command_parser in (pack_parser, unpack_parser):
        command_parser.add_argument("--ffmpeg", default="ffmpeg")
        command_parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    if args.command == "pack":
        result = pack(args.session.resolve(), args.output.resolve(), args.mode, args.rgb_resolution, args.fallback_fps, args.ffmpeg, args.ffprobe)
    else:
        result = unpack(args.input.resolve(), args.output.resolve(), args.ffmpeg, args.ffprobe)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
