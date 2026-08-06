#!/usr/bin/env python3
"""
Prepare synchronized SandStories v2 RGB/depth pairs and optionally run Any2Full.

Raw LiDAR streams are never modified. Generated inputs, predictions, provenance,
and quality metrics are written below ``derived/any2full`` by default.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image

from scripts import visualize_sandstories_session as session_io


ANY2FULL_REPOSITORY = "https://github.com/zhiyuandaily/Any2Full"
INTEGRATION_FORMAT_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run optional Any2Full depth completion on a SandStories v2 session"
    )
    parser.add_argument("session_dir", type=Path, help="Session folder containing manifest.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Derived-data root (default: SESSION/derived/any2full)",
    )
    parser.add_argument(
        "--any2full-dir",
        type=Path,
        default=None,
        help="Any2Full checkout containing run_any2full.py",
    )
    parser.add_argument("--checkpoint", type=Path, default=None, help="Any2Full checkpoint")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable for Any2Full (use its Python 3.9 environment)",
    )
    parser.add_argument(
        "--encoder",
        choices=["auto", "vits", "vitb", "vitl"],
        default="auto",
        help="Any2Full encoder; auto infers it from the checkpoint filename",
    )
    parser.add_argument(
        "--depth-source",
        choices=["selected", "smoothed"],
        default="selected",
        help="Selected capture stream or optional smoothed sidecar",
    )
    parser.add_argument(
        "--target-resolution",
        choices=["depth", "rgb"],
        default="depth",
        help="Resize RGB to LiDAR resolution (recommended) or depth to RGB resolution",
    )
    parser.add_argument("--start", type=int, default=0, help="First metadata row (inclusive)")
    parser.add_argument("--stop", type=int, default=None, help="Last metadata row (exclusive)")
    parser.add_argument("--stride", type=int, default=1, help="Process every Nth metadata row")
    parser.add_argument("--max-frames", type=int, default=None, help="Maximum number of pairs")
    parser.add_argument("--denoise", action="store_true", help="Enable Any2Full sparse-depth denoising")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write paired RGB PNG/depth NPY inputs without running Any2Full",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing derived/any2full output directory",
    )
    return parser.parse_args()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _select_entries(
    frames: list[dict],
    start: int,
    stop: Optional[int],
    stride: int,
    max_frames: Optional[int],
) -> list[tuple[int, dict]]:
    if start < 0:
        raise ValueError("--start must be >= 0")
    if stride < 1:
        raise ValueError("--stride must be >= 1")
    if max_frames is not None and max_frames < 1:
        raise ValueError("--max-frames must be >= 1")

    selected = list(enumerate(frames))[start:stop:stride]
    if max_frames is not None:
        selected = selected[:max_frames]
    if not selected:
        raise ValueError("Frame selection produced no RGB/depth pairs")
    return selected


def _resize_rgb(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(np.asarray(rgb, dtype=np.uint8), mode="RGB")
    return np.asarray(image.resize((width, height), Image.Resampling.BILINEAR))


def _resize_sparse_depth(depth: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(np.asarray(depth, dtype=np.float32), mode="F")
    return np.asarray(image.resize((width, height), Image.Resampling.NEAREST), dtype=np.float32)


def prepare_inputs(
    session_dir: Path,
    output_root: Path,
    *,
    depth_source: str = "selected",
    target_resolution: str = "depth",
    start: int = 0,
    stop: Optional[int] = None,
    stride: int = 1,
    max_frames: Optional[int] = None,
    rgb_reader: Callable[[Path, dict, dict], Optional[np.ndarray]] = session_io.read_v2_rgb,
) -> dict:
    """Extract paired inputs and return the completion manifest."""
    session_dir = session_dir.resolve()
    output_root = output_root.resolve()
    manifest = session_io.load_manifest(session_dir)
    streams = manifest.get("v2Streams") or {}
    if manifest.get("captureFormat") != "v2_streams" and not streams:
        raise ValueError("Any2Full integration currently requires a v2_streams session")

    metadata_path = session_dir / streams.get("frameMetadataFile", "v2_frames.jsonl")
    frames = session_io.load_jsonl(metadata_path)
    selected = _select_entries(frames, start, stop, stride, max_frames)

    rgb_dir = output_root / "inputs" / "rgb"
    depth_dir = output_root / "inputs" / "depth"
    predictions_dir = output_root / "predictions"
    rgb_dir.mkdir(parents=True, exist_ok=True)
    depth_dir.mkdir(parents=True, exist_ok=True)
    predictions_dir.mkdir(parents=True, exist_ok=True)

    pairs: list[dict] = []
    for metadata_row, entry in selected:
        stream_source = (
            "smoothed"
            if depth_source == "smoothed"
            or entry.get("selectedDepthSource") == "smoothedSceneDepth"
            else "raw"
        )
        depth = session_io.read_v2_depth(session_dir, manifest, entry, stream_source)
        rgb = rgb_reader(session_dir, manifest, entry)
        if rgb is None:
            raise RuntimeError(
                f"Could not decode RGB for metadata row {metadata_row}; "
                "verify streams/rgb.mp4 and install opencv-python"
            )

        sparse_depth = np.where(np.isfinite(depth) & (depth > 0), depth, 0).astype(np.float32)
        original_depth_shape = [int(sparse_depth.shape[0]), int(sparse_depth.shape[1])]
        original_rgb_shape = [int(rgb.shape[0]), int(rgb.shape[1])]

        if target_resolution == "depth":
            target_height, target_width = sparse_depth.shape
            paired_rgb = _resize_rgb(rgb, target_width, target_height)
            paired_depth = sparse_depth
        elif target_resolution == "rgb":
            target_height, target_width = rgb.shape[:2]
            paired_rgb = np.asarray(rgb, dtype=np.uint8)
            paired_depth = _resize_sparse_depth(sparse_depth, target_width, target_height)
        else:
            raise ValueError(f"Unsupported target resolution: {target_resolution}")

        frame_index = int(entry.get("frameIndex", metadata_row + 1))
        stem = f"frame_{frame_index:06d}"
        rgb_path = rgb_dir / f"{stem}.png"
        depth_path = depth_dir / f"{stem}.npy"
        Image.fromarray(paired_rgb, mode="RGB").save(rgb_path)
        np.save(depth_path, paired_depth.astype(np.float32))

        valid = paired_depth > 0
        pairs.append(
            {
                "stem": stem,
                "metadataRow": metadata_row,
                "frameIndex": frame_index,
                "arTimestamp": entry.get("arTimestamp"),
                "monotonicElapsedSeconds": entry.get("monotonicElapsedSeconds"),
                "rgbPresentationTimeSeconds": entry.get("rgbPresentationTimeSeconds"),
                "selectedDepthSource": entry.get("selectedDepthSource"),
                "inputDepthSource": depth_source,
                "inputRGB": _relative(rgb_path, output_root),
                "inputDepth": _relative(depth_path, output_root),
                "predictionDepth": f"predictions/{stem}.npy",
                "originalDepthShape": original_depth_shape,
                "originalRGBShape": original_rgb_shape,
                "modelInputShape": [int(target_height), int(target_width)],
                "inputValidPixelRatio": float(valid.mean()),
            }
        )

    result = {
        "format": "sandstories_any2full_completion",
        "formatVersion": INTEGRATION_FORMAT_VERSION,
        "status": "prepared",
        "sourceSession": str(session_dir),
        "sourceCaptureFormat": manifest.get("captureFormat"),
        "sourceFrameMetadata": _relative(metadata_path, session_dir),
        "rawDataModified": False,
        "derivedDataNotice": (
            "Predictions are model-derived depth estimates, not physical LiDAR measurements. "
            "Use the original session streams as authoritative data."
        ),
        "model": {"repository": ANY2FULL_REPOSITORY},
        "settings": {
            "depthSource": depth_source,
            "targetResolution": target_resolution,
            "start": start,
            "stop": stop,
            "stride": stride,
            "maxFrames": max_frames,
        },
        "pairCount": len(pairs),
        "pairs": pairs,
    }
    _write_json(output_root / "completion_manifest.json", result)
    return result


def infer_encoder(checkpoint: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    name = checkpoint.name.lower()
    for encoder in ("vits", "vitb", "vitl"):
        if encoder in name:
            return encoder
    raise ValueError("Could not infer encoder from checkpoint name; pass --encoder vits|vitb|vitl")


def build_any2full_command(
    python_executable: str,
    any2full_dir: Path,
    checkpoint: Path,
    rgb_dir: Path,
    depth_dir: Path,
    predictions_dir: Path,
    encoder: str,
    denoise: bool,
) -> list[str]:
    command = [
        python_executable,
        str(any2full_dir / "run_any2full.py"),
        "--rgb_dir",
        str(rgb_dir),
        "--depth_dir",
        str(depth_dir),
        "--checkpoint",
        str(checkpoint),
        "--encoder",
        encoder,
        "--out_dir",
        str(predictions_dir),
    ]
    if denoise:
        command.append("--denoise")
    return command


def _git_revision(repository: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _checkpoint_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"name": path.name, "sizeBytes": stat.st_size, "path": str(path.resolve())}


def compute_quality_report(output_root: Path, completion_manifest: dict) -> dict:
    """
    Measure agreement at pixels where LiDAR supplied an anchor.

    This cannot validate predictions in missing regions because no ground truth
    exists there; the report states that limitation explicitly.
    """
    output_root = output_root.resolve()
    frame_reports: list[dict] = []
    total_anchors = 0
    total_abs_error = 0.0
    total_squared_error = 0.0
    total_abs_relative_error = 0.0

    for pair in completion_manifest["pairs"]:
        input_depth = np.load(output_root / pair["inputDepth"]).astype(np.float32).squeeze()
        prediction_path = output_root / pair["predictionDepth"]
        if not prediction_path.is_file():
            raise FileNotFoundError(f"Missing Any2Full prediction: {prediction_path}")
        prediction = np.load(prediction_path).astype(np.float32).squeeze()
        if input_depth.ndim != 2 or prediction.ndim != 2:
            raise ValueError(f"{pair['stem']}: expected 2D input and prediction arrays")
        if input_depth.shape != prediction.shape:
            input_depth = _resize_sparse_depth(
                input_depth, int(prediction.shape[1]), int(prediction.shape[0])
            )

        anchors = np.isfinite(input_depth) & (input_depth > 0)
        completed = np.isfinite(prediction) & (prediction > 0)
        errors = np.abs(prediction[anchors] - input_depth[anchors])
        anchor_count = int(anchors.sum())
        if anchor_count:
            anchor_values = input_depth[anchors]
            mae = float(errors.mean())
            rmse = float(np.sqrt(np.square(errors).mean()))
            abs_rel = float((errors / np.maximum(anchor_values, 1e-6)).mean())
            total_anchors += anchor_count
            total_abs_error += float(errors.sum())
            total_squared_error += float(np.square(errors).sum())
            total_abs_relative_error += float(
                (errors / np.maximum(anchor_values, 1e-6)).sum()
            )
        else:
            mae = rmse = abs_rel = None

        frame_reports.append(
            {
                "stem": pair["stem"],
                "anchorPixelCount": anchor_count,
                "inputValidPixelRatio": float(anchors.mean()),
                "completedValidPixelRatio": float(completed.mean()),
                "anchorMAEMeters": mae,
                "anchorRMSEMeters": rmse,
                "anchorAbsRel": abs_rel,
            }
        )

    aggregate = {
        "anchorPixelCount": total_anchors,
        "anchorMAEMeters": total_abs_error / total_anchors if total_anchors else None,
        "anchorRMSEMeters": (
            (total_squared_error / total_anchors) ** 0.5 if total_anchors else None
        ),
        "anchorAbsRel": total_abs_relative_error / total_anchors if total_anchors else None,
    }
    report = {
        "format": "sandstories_any2full_quality_report",
        "formatVersion": 1,
        "scope": (
            "Agreement is measured only at valid source-LiDAR pixels. "
            "Completed pixels without LiDAR anchors remain unvalidated estimates."
        ),
        "aggregate": aggregate,
        "frames": frame_reports,
    }
    _write_json(output_root / "quality_report.json", report)
    return report


def main() -> int:
    args = parse_args()
    session_dir = args.session_dir.resolve()
    if not session_dir.is_dir():
        print(f"Not a session directory: {session_dir}", file=sys.stderr)
        return 2

    output_root = (
        args.output_dir.resolve()
        if args.output_dir
        else session_dir / "derived" / "any2full"
    )
    if output_root.exists():
        if not args.overwrite:
            print(f"Output already exists: {output_root}; pass --overwrite", file=sys.stderr)
            return 2
        shutil.rmtree(output_root)

    try:
        completion_manifest = prepare_inputs(
            session_dir,
            output_root,
            depth_source=args.depth_source,
            target_resolution=args.target_resolution,
            start=args.start,
            stop=args.stop,
            stride=args.stride,
            max_frames=args.max_frames,
        )
        if args.prepare_only:
            print(f"Prepared {completion_manifest['pairCount']} pairs in {output_root}")
            return 0

        if args.any2full_dir is None or args.checkpoint is None:
            raise ValueError("--any2full-dir and --checkpoint are required unless --prepare-only")
        any2full_dir = args.any2full_dir.resolve()
        checkpoint = args.checkpoint.resolve()
        if not (any2full_dir / "run_any2full.py").is_file():
            raise FileNotFoundError(f"Missing {any2full_dir / 'run_any2full.py'}")
        if not checkpoint.is_file():
            raise FileNotFoundError(f"Missing checkpoint: {checkpoint}")

        encoder = infer_encoder(checkpoint, args.encoder)
        command = build_any2full_command(
            args.python,
            any2full_dir,
            checkpoint,
            output_root / "inputs" / "rgb",
            output_root / "inputs" / "depth",
            output_root / "predictions",
            encoder,
            args.denoise,
        )
        completion_manifest["status"] = "running"
        completion_manifest["model"].update(
            {
                "revision": _git_revision(any2full_dir),
                "checkpoint": _checkpoint_fingerprint(checkpoint),
                "encoder": encoder,
            }
        )
        completion_manifest["command"] = command
        _write_json(output_root / "completion_manifest.json", completion_manifest)

        subprocess.run(command, cwd=any2full_dir, check=True)
        report = compute_quality_report(output_root, completion_manifest)
        completion_manifest["status"] = "completed"
        completion_manifest["qualityReport"] = "quality_report.json"
        completion_manifest["aggregateAnchorMetrics"] = report["aggregate"]
        _write_json(output_root / "completion_manifest.json", completion_manifest)
        print(f"Completed {completion_manifest['pairCount']} pairs in {output_root}")
        return 0
    except Exception as error:
        if output_root.exists():
            manifest_path = output_root / "completion_manifest.json"
            if manifest_path.is_file():
                try:
                    failed = json.loads(manifest_path.read_text(encoding="utf-8"))
                    failed["status"] = "failed"
                    failed["error"] = str(error)
                    _write_json(manifest_path, failed)
                except (OSError, ValueError):
                    pass
        print(f"Any2Full integration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
