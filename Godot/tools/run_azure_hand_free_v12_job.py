#!/usr/bin/env python3
"""Run the variable-length Azure hand-free v12 profile as a resumable job.

This is an orchestration layer for AZURE_HAND_FREE_V12_PRODUCTION_RUNBOOK.md.
It accepts an Azure Kinect MKV, an aligned RGB/depth frame archive, or a
SandStories stream bundle. Recording length, frame dimensions, timing, and the
processing range are discovered from the input; the historical 2,275/201-frame
capture is only a regression fixture. High-I/O intermediate work stays in
configured scratch storage and the final v12 session is materialized into the
job's configured durable output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import zipfile
from typing import Callable

import cv2
import numpy as np


EXPECTED_REVISIONS = {
    "SAM2_ROOT": "b7a9c29f196edff0eb54dbe14588d7ae5e3dde28",
    "PROPAINTER_ROOT": "e870e79321c31b733e2031af5aa2fb1fe3ac7eec",
    "ANY2FULL_ROOT": "780edf6be2bf9260f1cce8e4ddbcb52d7bcdae9e",
}

REQUIRED_TOOL_FILES = (
    "audit_hand_edge_terraces.py",
    "azure_bidirectional_filter.py",
    "azure_clean_rgb_handfree.py",
    "azure_depth_actor_mask.py",
    "azure_prepare_input.py",
    "azure_sam2_prep.py",
    "build_persistent_substrate_v5.py",
    "build_robust_normal_sidecar.py",
    "decode_azure_kinect_mkv.py",
    "grounded_sam2_tracking_sandiv.py",
    "materialize_intrinsic_albedo_session_v12.py",
    "merge_sam2_masks.py",
    "pack_rgbd_streams.py",
    "remove_spatial_shadow_intrinsic_v12.py",
    "run_any2full_eval_remote.py",
    "run_propainter_fullres.py",
    "run_sam2_arm_pass.sh",
    "test_audit_hand_edge_terraces.py",
    "test_materialize_intrinsic_albedo_session_v12.py",
)


class Pipeline:
    def __init__(self, args: argparse.Namespace):
        self.job_id = os.environ.get("SANDSTORIES_JOB_ID", args.job_id)
        self.job_root = Path(os.environ.get("SANDSTORIES_JOB_ROOT", args.job_root)).resolve()
        self.input_path = Path(args.input).resolve()
        self.input_format = os.environ.get("SANDSTORIES_INPUT_FORMAT", args.input_format)
        self.output_format = os.environ.get("SANDSTORIES_OUTPUT_FORMAT", args.output_format)
        self.rgb_resolution = os.environ.get("SANDSTORIES_RGB_RESOLUTION", args.rgb_resolution)
        self.fallback_fps = float(os.environ.get("SANDSTORIES_FALLBACK_FPS", args.fallback_fps))
        if self.input_format not in {"auto", "azure-mkv", "frame-archive", "stream-bundle"}:
            raise ValueError(f"unsupported input format: {self.input_format}")
        if self.output_format not in {"png-sequence", "lossless-streams", "compact-streams", "both"}:
            raise ValueError(f"unsupported output format: {self.output_format}")
        if self.rgb_resolution not in {"native", "75-percent", "50-percent"}:
            raise ValueError(f"unsupported RGB resolution: {self.rgb_resolution}")
        if not 0.1 <= self.fallback_fps <= 240:
            raise ValueError("fallback FPS must be between 0.1 and 240")
        self.scratch_root = Path(args.scratch_root).resolve()
        self.tools = Path(__file__).resolve().parent
        self.progress_file = Path(
            os.environ.get("SANDSTORIES_PROGRESS_FILE", self.job_root / "progress.json")
        )
        self.result_file = Path(
            os.environ.get("SANDSTORIES_RESULT_FILE", self.job_root / "result.json")
        )
        self.stage_root = self.job_root / "stages"
        self.stage_root.mkdir(parents=True, exist_ok=True)
        self.scratch = self.scratch_root / self.job_id
        self.work = self.scratch / "work"
        self.derived = self.scratch / "derived"
        self.output = self.job_root / "output" / "final_v12"
        self.tar_artifact = self.job_root / "artifacts" / f"{self.job_id}-final-v12.tar.zst"
        self.zip_artifact = self.job_root / "artifacts" / f"{self.job_id}-final-v12.zip"
        self.stream_artifact = self.job_root / "artifacts" / f"{self.job_id}-final-v12-streams.zip"
        self.review_root = self.job_root / "review"
        self.current_stage = "starting"
        self.last_command: list[str] | None = None
        self.cpu_py = required_path("CPU_PY", executable=True)
        self.sam2_root = required_path("SAM2_ROOT")
        self.sam2_py = required_path("SAM2_PY", executable=True)
        self.propainter_root = required_path("PROPAINTER_ROOT")
        self.propainter_py = required_path("PROPAINTER_PY", executable=True)
        self.any2full_root = required_path("ANY2FULL_ROOT")
        self.any2full_py = required_path("ANY2FULL_PY", executable=True)
        self.any2full_ckpt = required_path("ANY2FULL_CKPT")
        self.gpu = required_text("SANDSTORIES_GPU_ID")
        self.env = os.environ.copy()
        self.env.update(
            {
                "SAM2_ROOT": str(self.sam2_root),
                "SAM2_PY": str(self.sam2_py),
                "PROPAINTER_ROOT": str(self.propainter_root),
                "PROPAINTER_PY": str(self.propainter_py),
                "ANY2FULL_ROOT": str(self.any2full_root),
                "ANY2FULL_PY": str(self.any2full_py),
                "ANY2FULL_CKPT": str(self.any2full_ckpt),
                "CUDA_VISIBLE_DEVICES": self.gpu,
                "HF_HUB_OFFLINE": "1",
                "MPLCONFIGDIR": str(self.scratch / "runtime_cache" / "matplotlib"),
                "TORCH_EXTENSIONS_DIR": str(self.scratch / "runtime_cache" / "torch_extensions"),
                "TRANSFORMERS_OFFLINE": "1",
            }
        )
        existing_python_path = self.env.get("PYTHONPATH", "")
        self.env["PYTHONPATH"] = os.pathsep.join(
            [str(self.sam2_root), *([existing_python_path] if existing_python_path else [])]
        )
        if os.environ.get("AZURE_KINECT_LIBRARY_PATH"):
            current = self.env.get("LD_LIBRARY_PATH", "")
            self.env["LD_LIBRARY_PATH"] = os.environ["AZURE_KINECT_LIBRARY_PATH"] + (
                f":{current}" if current else ""
            )

    def input_frame_count(self) -> int:
        return len(list((self.work / "rgb").glob("frame_*.jpg")))

    def output_frame_count(self) -> int:
        manifest = json.loads((self.output / "processed_manifest.json").read_text(encoding="utf-8"))
        count = len(manifest.get("frames", []))
        if count <= 0:
            raise RuntimeError("final manifest contains no frames")
        return count

    @staticmethod
    def session_frame_count(path: Path) -> int:
        try:
            manifest = json.loads(
                (path / "processed_manifest.json").read_text(encoding="utf-8")
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return 0
        frames = manifest.get("frames", [])
        return len(frames) if isinstance(frames, list) else 0

    @staticmethod
    def sequence_complete(directory: Path, stem: str, count: int) -> bool:
        return count > 0 and all(
            (directory / f"{stem}_{index:06d}.png").is_file()
            for index in range(1, count + 1)
        )

    def v9_complete(self, frame_count: int) -> bool:
        return self.session_frame_count(self.v9) == frame_count and all(
            self.sequence_complete(self.v9 / directory, stem, frame_count)
            for directory, stem in (
                ("clean_depth", "clean_depth"),
                ("normal_map", "normal"),
                ("normal_confidence", "normal_confidence"),
            )
        )

    def v12_rgb_complete(self, frame_count: int) -> bool:
        return self.sequence_complete(self.v12_rgb, "clean_rgb", frame_count)

    def final_v12_complete(self, frame_count: int) -> bool:
        return self.session_frame_count(self.output) == frame_count and all(
            self.sequence_complete(self.output / directory, stem, frame_count)
            for directory, stem in (
                ("clean_rgb", "clean_rgb"),
                ("clean_depth", "clean_depth"),
                ("normal_map", "normal"),
                ("normal_confidence", "normal_confidence"),
            )
        )

    def remove_incomplete_output(self, path: Path, root: Path) -> None:
        if not path.exists():
            return
        ensure_child(path, root)
        print(f"removing incomplete output: {path}", flush=True)
        shutil.rmtree(path)

    @staticmethod
    def review_indices(count: int, samples: int = 9) -> list[int]:
        if count <= 0:
            return []
        return sorted({int(round(value)) for value in np.linspace(1, count, min(samples, count))})

    @classmethod
    def review_csv(cls, count: int, samples: int = 9) -> str:
        return ",".join(str(value) for value in cls.review_indices(count, samples))

    def marker(self, name: str) -> Path:
        return self.stage_root / f"{name}.done"

    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def resolved_input_format(self) -> str:
        if self.input_format != "auto":
            return self.input_format
        lower = self.input_path.name.lower()
        if lower.endswith(".mkv"):
            return "azure-mkv"
        if lower.endswith(".zip"):
            with zipfile.ZipFile(self.input_path, "r") as archive:
                names = {name.lstrip("./") for name in archive.namelist()}
            return "stream-bundle" if "bundle_manifest.json" in names else "frame-archive"
        return "frame-archive"

    def timestamp_records(self) -> list[dict]:
        path = self.work / "capture_frames.jsonl"
        if not path.is_file():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise RuntimeError("capture_frames.jsonl must contain JSON objects")
                records.append(value)
        return records

    def capture_times(self, frame_count: int) -> tuple[list[float], str]:
        records = self.timestamp_records()
        if records:
            if len(records) != frame_count:
                raise RuntimeError(
                    f"capture timestamp count mismatch: {len(records)} != {frame_count}"
                )
            values = []
            for record in records:
                raw = record.get("timeSeconds")
                if raw is None and record.get("depthTimestampUsec") is not None:
                    raw = float(record["depthTimestampUsec"]) / 1_000_000.0
                if raw is None:
                    raise RuntimeError("capture timestamp record lacks timeSeconds/depthTimestampUsec")
                values.append(float(raw))
            origin = values[0]
            values = [value - origin for value in values]
            if any(current <= previous for previous, current in zip(values, values[1:])):
                raise RuntimeError("capture timestamps must be strictly increasing")
            return values, "capture"
        return [index / self.fallback_fps for index in range(frame_count)], "fallback_fps"

    def nominal_fps(self, frame_count: int) -> float:
        times, _ = self.capture_times(frame_count)
        deltas = [current - previous for previous, current in zip(times, times[1:])]
        return 1.0 / statistics.median(deltas) if deltas else self.fallback_fps

    def apply_capture_timing(self, session: Path, frame_count: int) -> None:
        times, source = self.capture_times(frame_count)
        path = session / "processed_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        frames = manifest.get("frames")
        if not isinstance(frames, list) or len(frames) != frame_count:
            raise RuntimeError("cannot apply capture timing to incomplete processed manifest")
        for index, (frame, timestamp) in enumerate(zip(frames, times), start=1):
            frame["time"] = round(timestamp, 9)
            frame["sourceTime"] = round(timestamp, 9)
            frame["captureFrameIndex"] = index
        manifest["duration"] = (
            times[-1] + (times[-1] - times[-2] if len(times) > 1 else 1.0 / self.fallback_fps)
        )
        manifest["timing"] = {
            "source": source,
            "perFrame": True,
            "metadataFile": "capture_frames.jsonl" if source == "capture" else None,
            "fallbackFps": self.fallback_fps if source == "fallback_fps" else None,
        }
        self.write_json(path, manifest)

    def progress(self, stage: str, value: float, message: str) -> None:
        self.write_json(
            self.progress_file,
            {"stage": stage, "progress": value, "message": message},
        )

    def finish_stage(self, name: str, details: dict | None = None) -> None:
        self.write_json(self.marker(name), details or {"completed": True})

    def stage(
        self,
        name: str,
        progress: float,
        message: str,
        action: Callable[[], None],
    ) -> None:
        if self.marker(name).is_file():
            return
        self.current_stage = name
        self.progress(name, progress, message)
        try:
            action()
        except Exception as exc:
            failure = {
                "stage": name,
                "message": str(exc),
                "command": self.last_command,
                "pipelineLog": str(self.job_root / "pipeline.log"),
            }
            self.write_json(self.job_root / "failure.json", failure)
            self.progress(name, progress, f"failed in {name}: {exc}")
            raise
        self.finish_stage(name)

    def run(self, command: list[str], *, cwd: Path | None = None) -> None:
        self.last_command = command
        printable = " ".join(command)
        print(f"+ {printable}", flush=True)
        subprocess.run(command, cwd=cwd, env=self.env, check=True)

    def preflight(self) -> None:
        if not self.input_path.is_file():
            raise FileNotFoundError(self.input_path)
        missing_tools = [
            name for name in REQUIRED_TOOL_FILES if not (self.tools / name).is_file()
        ]
        if missing_tools:
            raise RuntimeError(
                "pipeline deployment is missing required tools: " + ", ".join(missing_tools)
            )
        durable_root = os.environ.get("SANDSTORIES_DURABLE_OUTPUT_ROOT", "").strip()
        if durable_root and not os.environ.get("SANDSTORIES_ALLOW_NON_DURABLE_OUTPUT"):
            try:
                ensure_child(self.job_root, Path(durable_root).resolve())
            except ValueError as exc:
                raise RuntimeError(
                    "job root must be below SANDSTORIES_DURABLE_OUTPUT_ROOT"
                ) from exc
        self.scratch_root.mkdir(parents=True, exist_ok=True)
        (self.scratch / "runtime_cache").mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.scratch_root).free < 25 * 1024**3:
            raise RuntimeError("local scratch free-space gate failed: 25 GiB required")
        if shutil.disk_usage(self.job_root).free < 25 * 1024**3:
            raise RuntimeError("durable output free-space gate failed: 25 GiB required")
        for key, expected in EXPECTED_REVISIONS.items():
            root = Path(self.env[key])
            actual = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            if actual != expected:
                raise RuntimeError(f"{key} revision mismatch: {actual} != {expected}")
        environment_checks = (
            (
                "CPU_PY",
                [str(self.cpu_py), "-c", "import cv2, numpy"],
                None,
            ),
            (
                "SAM2_PY",
                [
                    str(self.sam2_py),
                    str(self.tools / "grounded_sam2_tracking_sandiv.py"),
                    "--help",
                ],
                self.sam2_root,
            ),
            (
                "PROPAINTER_PY",
                [str(self.propainter_py), "inference_propainter.py", "--help"],
                self.propainter_root,
            ),
            (
                "ANY2FULL_PY",
                [
                    str(self.any2full_py),
                    "-c",
                    "import cv2, numpy, torch, torchvision; from PIL import Image; "
                    "from model.ours.any2full import Any2Full",
                ],
                self.any2full_root,
            ),
        )
        for label, command, cwd in environment_checks:
            check = subprocess.run(
                command,
                cwd=cwd,
                env=self.env,
                text=True,
                capture_output=True,
            )
            if check.returncode != 0:
                detail = (check.stderr or check.stdout).strip()
                raise RuntimeError(f"{label} dependency preflight failed: {detail}")
        if self.resolved_input_format() == "azure-mkv":
            mkv_py = required_path("AZURE_KINECT_PY", executable=True)
            check = subprocess.run(
                [
                    str(mkv_py),
                    "-c",
                    "import cv2, numpy, pyk4a; print('Azure Kinect Python environment OK')",
                ],
                env=self.env,
                text=True,
                capture_output=True,
            )
            if check.returncode != 0:
                detail = (check.stderr or check.stdout).strip()
                raise RuntimeError(
                    f"AZURE_KINECT_PY cannot import cv2/numpy/pyk4a: {mkv_py}: {detail}"
                )

    def ingest(self) -> None:
        if self.work.exists():
            ensure_child(self.work, self.scratch_root)
            shutil.rmtree(self.work)
        self.work.parent.mkdir(parents=True, exist_ok=True)
        selected_format = self.resolved_input_format()
        if selected_format == "azure-mkv":
            mkv_py = required_path("AZURE_KINECT_PY", executable=True)
            self.run(
                [
                    str(mkv_py),
                    str(self.tools / "decode_azure_kinect_mkv.py"),
                    "--input",
                    str(self.input_path),
                    "--output",
                    str(self.work),
                ]
            )
            return

        if selected_format == "stream-bundle":
            self.run(
                [
                    str(self.cpu_py),
                    str(self.tools / "pack_rgbd_streams.py"),
                    "unpack",
                    "--input",
                    str(self.input_path),
                    "--output",
                    str(self.work),
                ]
            )
            return

        extract_root = self.scratch / "extract"
        if extract_root.exists():
            ensure_child(extract_root, self.scratch_root)
            shutil.rmtree(extract_root)
        extract_root.mkdir(parents=True)
        if self.input_path.name.lower().endswith(".zip"):
            with zipfile.ZipFile(self.input_path, "r") as archive:
                if len(archive.infolist()) > 200_000:
                    raise RuntimeError("archive contains too many entries")
                for member in archive.infolist():
                    ensure_child(extract_root / member.filename, extract_root)
                    mode = member.external_attr >> 16
                    if mode & 0o170000 == 0o120000:
                        raise RuntimeError(f"archive symlinks are not permitted: {member.filename}")
                archive.extractall(extract_root)
        else:
            with tarfile.open(self.input_path, "r:*") as archive:
                members = archive.getmembers()
                if len(members) > 200_000:
                    raise RuntimeError("archive contains too many entries")
                for member in members:
                    target = (extract_root / member.name).resolve()
                    ensure_child(target, extract_root)
                    if member.issym() or member.islnk() or member.isdev():
                        raise RuntimeError(f"archive links/devices are not permitted: {member.name}")
                archive.extractall(extract_root)
        candidates = [extract_root]
        top_dirs = [item for item in extract_root.iterdir() if item.is_dir()]
        if len(top_dirs) == 1:
            candidates.append(top_dirs[0])
        source = next(
            (candidate for candidate in candidates if (candidate / "rgb").is_dir() and (candidate / "depth").is_dir()),
            None,
        )
        if source is None:
            raise RuntimeError("archive must contain rgb/ and depth/ at its root or one wrapper directory")
        if source == extract_root:
            os.replace(extract_root, self.work)
        else:
            shutil.move(str(source), self.work)
        if extract_root.exists():
            shutil.rmtree(extract_root)
        self.normalize_frame_archive()

    def normalize_frame_archive(self) -> None:
        rgb_root = self.work / "rgb"
        candidates: dict[int, Path] = {}
        pattern = re.compile(r"^frame_(\d{6})\.(jpg|jpeg|png)$", re.IGNORECASE)
        for path in rgb_root.iterdir():
            match = pattern.match(path.name)
            if match:
                index = int(match.group(1))
                if index in candidates:
                    raise RuntimeError(f"multiple RGB encodings supplied for frame {index}")
                candidates[index] = path
        if not candidates:
            raise RuntimeError("frame archive contains no frame_XXXXXX JPG/PNG RGB images")
        for index in range(1, len(candidates) + 1):
            source = candidates.get(index)
            if source is None:
                raise RuntimeError(f"RGB numbering is not continuous at frame {index}")
            target = rgb_root / f"frame_{index:06d}.jpg"
            if source.suffix.lower() in {".jpg", ".jpeg"}:
                if source != target:
                    os.replace(source, target)
                continue
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if image is None or not cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f"failed to normalize RGB frame: {source}")
            source.unlink()

    def validate_input(self) -> None:
        rgb_files = sorted((self.work / "rgb").glob("frame_*.jpg"))
        depth_files = sorted((self.work / "depth").glob("depth_*.png"))
        frame_count = len(rgb_files)
        if frame_count <= 0 or len(depth_files) != frame_count:
            raise RuntimeError(
                f"input must contain the same non-zero number of RGB and depth frames: "
                f"rgb={frame_count}, depth={len(depth_files)}"
            )
        expected_rgb = [f"frame_{index:06d}.jpg" for index in range(1, frame_count + 1)]
        expected_depth = [f"depth_{index:06d}.png" for index in range(1, frame_count + 1)]
        if [path.name for path in rgb_files] != expected_rgb:
            raise RuntimeError(
                f"RGB numbering must be continuous frame_000001.jpg through frame_{frame_count:06d}.jpg"
            )
        if [path.name for path in depth_files] != expected_depth:
            raise RuntimeError(
                f"depth numbering must be continuous depth_000001.png through depth_{frame_count:06d}.png"
            )
        expected_shape: tuple[int, int] | None = None
        for index in self.review_indices(frame_count, 5):
            rgb = cv2.imread(str(self.work / "rgb" / f"frame_{index:06d}.jpg"), cv2.IMREAD_COLOR)
            depth = cv2.imread(
                str(self.work / "depth" / f"depth_{index:06d}.png"), cv2.IMREAD_UNCHANGED
            )
            if rgb is None or rgb.ndim != 3 or rgb.shape[2] != 3:
                raise RuntimeError(f"unexpected RGB frame at index {index}")
            if depth is None or depth.ndim != 2 or depth.dtype != np.uint16:
                raise RuntimeError(f"unexpected uint16 depth frame at index {index}")
            if rgb.shape[:2] != depth.shape:
                raise RuntimeError(f"RGB/depth dimensions differ at frame {index}: {rgb.shape[:2]} != {depth.shape}")
            if expected_shape is None:
                expected_shape = depth.shape
            elif depth.shape != expected_shape:
                raise RuntimeError(f"frame dimensions changed at frame {index}: {depth.shape} != {expected_shape}")
        first = cv2.imread(str(self.work / "depth" / "depth_000001.png"), cv2.IMREAD_UNCHANGED)
        valid = first[first > 0]
        if not valid.size:
            raise RuntimeError("first depth frame contains no valid samples")
        percentiles = np.percentile(valid, [1, 50, 99]).tolist()
        if percentiles[0] < 300 or percentiles[2] > 800:
            raise RuntimeError(f"capture is outside the calibrated tray depth envelope: {percentiles}")
        self.write_json(
            self.job_root / "input_validation.json",
            {
                "pairs": frame_count,
                "firstFrame": 1,
                "lastFrame": frame_count,
                "continuous": True,
                "frameSize": {"width": expected_shape[1], "height": expected_shape[0]},
                "inputFormat": self.resolved_input_format(),
                "timingSource": self.capture_times(frame_count)[1],
                "nominalFps": self.nominal_fps(frame_count),
                "depth_percentiles_mm": percentiles,
            },
        )

    def prepare_masks(self) -> None:
        frame_count = self.input_frame_count()
        for name in ("sam2_input", "propainter_input"):
            path = self.work / name
            if path.exists():
                shutil.rmtree(path)
        self.run([str(self.cpu_py), str(self.tools / "azure_sam2_prep.py"), str(self.work)])
        frames = sorted((self.work / "sam2_input").glob("*.jpg"))
        if len(frames) != frame_count:
            raise RuntimeError(
                f"SAM2 preparation frame count mismatch: {len(frames)} != {frame_count}"
            )
        for segment in self.work.glob("sam2_seg_*"):
            if segment.is_dir():
                shutil.rmtree(segment)
        for segment_index, start in enumerate(range(0, len(frames), 550), 1):
            destination = self.work / f"sam2_seg_{segment_index}"
            destination.mkdir()
            for frame in frames[start : start + 550]:
                (destination / frame.name).symlink_to(frame)

    def sam_pass_one(self) -> None:
        frame_count = self.input_frame_count()
        combined = self.work / "sam2_output" / "binary_masks"
        if combined.parent.exists():
            shutil.rmtree(combined.parent)
        combined.mkdir(parents=True)
        for segment in sorted(self.work.glob("sam2_seg_*")):
            output = self.work / f"sam2_output_{segment.name}"
            if output.exists():
                shutil.rmtree(output)
            self.run(
                [
                    str(self.sam2_py), str(self.tools / "grounded_sam2_tracking_sandiv.py"),
                    "--video-dir", str(segment), "--output-dir", str(output),
                    "--text", "hand. arm.", "--step", "10", "--box-threshold", "0.35",
                    "--text-threshold", "0.20", "--sam2-checkpoint", "checkpoints/sam2.1_hiera_large.pt",
                    "--sam2-config", "configs/sam2.1/sam2.1_hiera_l.yaml",
                    "--grounding-model", "IDEA-Research/grounding-dino-tiny",
                ],
                cwd=self.sam2_root,
            )
            for mask in (output / "binary_masks").glob("*.png"):
                shutil.copy2(mask, combined / mask.name)
        if len(list(combined.glob("*.png"))) != frame_count:
            raise RuntimeError("Grounded-SAM-2 pass one mask count mismatch")

    def sam_pass_two_and_merge(self) -> None:
        frame_count = self.input_frame_count()
        arm = self.work / "sam2_output_arm"
        if arm.exists():
            shutil.rmtree(arm)
        for path in self.work.glob("sam2_output_arm_sam2_seg_*"):
            shutil.rmtree(path)
        self.run(["bash", str(self.tools / "run_sam2_arm_pass.sh"), str(self.work), self.gpu])
        merged = self.work / "propainter_masks"
        if merged.exists():
            shutil.rmtree(merged)
        self.run([str(self.cpu_py), str(self.tools / "merge_sam2_masks.py"), str(self.work)])
        if len(list(merged.glob("*.png"))) != frame_count:
            raise RuntimeError("merged mask count mismatch")
        self.make_mask_review()

    def make_mask_review(self) -> None:
        frame_count = self.input_frame_count()
        self.review_root.mkdir(parents=True, exist_ok=True)
        tiles = []
        coverage = {}
        for index in self.review_indices(frame_count, 6):
            rgb = cv2.imread(str(self.work / "rgb" / f"frame_{index:06d}.jpg"))
            mask = cv2.imread(str(self.work / "propainter_masks" / f"{index:06d}.png"), cv2.IMREAD_GRAYSCALE)
            overlay = rgb.copy()
            fraction = float(np.count_nonzero(mask) / mask.size)
            coverage[str(index)] = fraction
            if fraction >= 0.50:
                raise RuntimeError(f"automatic mask gate rejected tray-sized coverage at frame {index}: {fraction:.3f}")
            overlay[mask > 0] = (0.35 * overlay[mask > 0] + 0.65 * np.array([0, 0, 255])).astype(np.uint8)
            cv2.putText(overlay, str(index), (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            tiles.append(overlay)
        while len(tiles) < 6:
            tiles.append(tiles[-1].copy())
        sheet = np.vstack((np.hstack(tiles[:3]), np.hstack(tiles[3:6])))
        cv2.imwrite(str(self.review_root / "mask_review.png"), sheet)
        self.write_json(self.review_root / "mask_gate.json", {"passed": True, "coverage_fraction": coverage, "maximum_allowed": 0.50})

    def propainter(self) -> None:
        frame_count = self.input_frame_count()
        self.run(
            [str(self.propainter_py), str(self.tools / "run_propainter_fullres.py"), str(self.work), self.gpu, "--seg-len", "500", "--overlap", "16"]
        )
        if len(list((self.work / "display_rgb_full").glob("frame_*.png"))) != frame_count:
            raise RuntimeError("ProPainter output count mismatch")

    def any2full_prepare(self) -> None:
        frame_count = self.input_frame_count()
        output = self.work / "any2full_input"
        if output.exists():
            shutil.rmtree(output)
        self.run(
            [str(self.cpu_py), str(self.tools / "azure_prepare_input.py"),
             "--rgb-dir", str(self.work / "rgb"), "--depth-dir", str(self.work / "depth"),
             "--object-mask-dir", str(self.work / "propainter_masks"), "--output-root", str(output),
             "--band-mm", "400", "630", "--object-dilate", "8", "--local-residual-mm", "8",
             "--gradient-mm", "30", "--frames", str(frame_count)]
        )
        shutil.copy2(output / "surface_mask.png", self.work / "surface_mask.png")
        clean = self.work / "rgb_clean_handfree"
        if clean.exists():
            shutil.rmtree(clean)
        self.run(
            [str(self.cpu_py), str(self.tools / "azure_clean_rgb_handfree.py"), "--session", str(self.work),
             "--mask-dir", str(self.work / "propainter_masks"), "--rgb-dir", str(self.work / "display_rgb_full"),
             "--out-dir", str(clean), "--dilate", "8", "--radius", "5", "--mode", "inpaint",
             "--frames", str(frame_count)]
        )

    def any2full(self) -> None:
        frame_count = self.input_frame_count()
        output = self.work / "predictions_handfree"
        if output.exists():
            shutil.rmtree(output)
        self.run(
            [str(self.any2full_py), str(self.tools / "run_any2full_eval_remote.py"),
             "--any2full-root", str(self.any2full_root), "--input-root", str(self.work / "any2full_input"),
             "--rgb-dir", str(self.work / "rgb_clean_handfree"), "--output-root", str(output),
             "--encoder", "vitl", "--checkpoint", str(self.any2full_ckpt), "--frame-start", "1",
              "--frame-end", str(frame_count), "--densities", "4", "--metric-low", "0.400",
             "--metric-high", "0.630", "--device", "cuda"],
            cwd=self.any2full_root,
        )
        if len(list((output / "grid4").glob("frame_*.npy"))) != frame_count:
            raise RuntimeError("Any2Full output count mismatch")

    def depth_masks(self) -> None:
        frame_count = self.input_frame_count()
        output = self.work / "depth_actor_masks"
        if output.exists():
            shutil.rmtree(output)
        self.run(
            [str(self.cpu_py), str(self.tools / "azure_depth_actor_mask.py"), "--session", str(self.work),
             "--depth-dir", str(self.work / "depth"), "--out-dir", str(output), "--threshold-mm", "420",
             "--min-area", "100", "--frames", str(frame_count)]
        )

    @property
    def v3(self) -> Path:
        return self.derived / "v3"

    @property
    def v4(self) -> Path:
        return self.derived / "v4"

    @property
    def v9(self) -> Path:
        return self.derived / "v9"

    @property
    def v12_rgb(self) -> Path:
        return self.derived / "v12_rgb"

    def v3_v4(self) -> None:
        frame_count = self.input_frame_count()
        nominal_fps = self.nominal_fps(frame_count)
        review_frames = self.review_csv(frame_count, 10)
        self.derived.mkdir(parents=True, exist_ok=True)
        for path in (self.v3, self.v4):
            if path.exists():
                shutil.rmtree(path)
        self.run(
            [str(self.cpu_py), str(self.tools / "azure_bidirectional_filter.py"), str(self.work),
             "--start", "1", "--end", str(frame_count), "--post-end", str(frame_count),
             "--output-session", str(self.v3),
             "--session-id", f"{self.job_id}_v3", "--title", "Azure bidirectional v3 temporal donors / gated ProPainter",
             "--fps", f"{nominal_fps:.9g}", "--sample-stride", "10", "--margin-mm", "15", "--large-margin-mm", "30",
             "--short-horizon", "45", "--long-horizon", "120", "--support-threshold", "0.55",
             "--tolerance-mm", "3", "--min-component-area", "120", "--dilation", "11",
             "--temporal-radius", "3", "--inner-feather", "4", "--outer-feather", "12",
             "--propainter-max-weight", "0.25", "--metric-low", "0.400", "--metric-high", "0.630",
              "--review-frames", review_frames]
        )
        self.apply_capture_timing(self.v3, frame_count)
        self.run(
            [str(self.cpu_py), str(self.tools / "build_robust_normal_sidecar.py"), str(self.v3), str(self.v4),
             "--session-id", f"{self.job_id}_v4", "--title", "Azure bidirectional v4 / robust temporal normals",
             "--temporal-radius", "2", "--fine-diameter", "7", "--fine-sigma-mm", "1.5",
             "--coarse-diameter", "15", "--coarse-sigma-mm", "4.0", "--coarse-spatial-sigma", "5.0",
             "--masked-normal-confidence", "0.68", "--plane-width", "5.5", "--plane-depth", "5.5",
             "--shader-arg-1", "11.625", "--displacement", "-5.0", "--metric-range-mm", "230",
              "--review-frames", self.review_csv(frame_count, 7)]
        )

    def v9_v12(self) -> None:
        frame_count = len(
            json.loads((self.v4 / "processed_manifest.json").read_text(encoding="utf-8"))["frames"]
        )
        if self.v9_complete(frame_count):
            print(f"reusing complete v9 output: {self.v9}", flush=True)
        else:
            self.remove_incomplete_output(self.v9, self.scratch_root)
            self.run(
                [str(self.cpu_py), str(self.tools / "build_persistent_substrate_v5.py"), str(self.v4), str(self.v9),
                 "--reuse-rgb-session", str(self.v4), "--minimum-free-gb", "25", "--session-id", f"{self.job_id}_v9",
                 "--title", "Azure spatial-activation substrate v9 / progressive trench geometry",
                 "--revision-version", "9", "--geometry-guard-radius", "24", "--geometry-residual-support-radius", "60",
                 "--geometry-residual-threshold-mm", "3.0", "--geometry-temporal-union",
                 "--geometry-temporal-union-margin", "14", "--spatial-activation", "--activation-exclusion-radius", "22",
                 "--activation-vote-window", "5", "--activation-vote-minimum", "2", "--activation-ramp-frames", "3",
                 "--boundary-expansion-radius", "18", "--boundary-inpaint-radius", "20", "--boundary-bias-sigma", "9",
                  "--transition-radius", "30", "--workers", "4",
                  "--review-frames", self.review_csv(frame_count, 9)]
            )
            if not self.v9_complete(frame_count):
                raise RuntimeError("v9 producer exited successfully but output is incomplete")

        if self.v12_rgb_complete(frame_count):
            print(f"reusing complete v12 RGB output: {self.v12_rgb}", flush=True)
        else:
            self.remove_incomplete_output(self.v12_rgb, self.scratch_root)
            self.run(
                [str(self.cpu_py), str(self.tools / "remove_spatial_shadow_intrinsic_v12.py"), "--session", str(self.v4),
                 "--output", str(self.v12_rgb), "--close-size", "251", "--maximum-gain", "6",
                 "--matte-threshold", "2", "--matte-softness", "12", "--neutralize-albedo",
                  "--detail-sigma", "5", "--analysis-scale", "0.5",
                  "--review-frames", self.review_csv(frame_count, 9)]
            )
            if not self.v12_rgb_complete(frame_count):
                raise RuntimeError("v12 RGB producer exited successfully but output is incomplete")

        if self.final_v12_complete(frame_count):
            print(f"reusing complete final v12 output: {self.output}", flush=True)
        else:
            self.remove_incomplete_output(self.output, self.job_root)
            self.run(
                [str(self.cpu_py), str(self.tools / "materialize_intrinsic_albedo_session_v12.py"),
                 "--source-session", str(self.v9), "--rgb-dir", str(self.v12_rgb),
                 "--output-session", str(self.output), "--min-free-gib", "25"]
            )
            if not self.final_v12_complete(frame_count):
                raise RuntimeError("v12 materializer exited successfully but output is incomplete")

    def audit(self) -> None:
        frame_count = self.output_frame_count()
        audit_frames = self.review_indices(frame_count, 8)
        audit = self.output / "hand_edge_terrace_audit.json"
        self.run(
            [str(self.cpu_py), str(self.tools / "audit_hand_edge_terraces.py"), str(self.v3), str(self.v9),
              str(self.output), "--change-reference", str(self.output),
              "--frames", ",".join(str(value) for value in audit_frames), "--profile-radius", "48",
             "--maximum-profiles", "900", "--prominence-mm", "0.20", "--maximum-profile-range-mm", "12",
             "--change-threshold-mm", "2.0", "--change-margin", "10", "--output", str(audit)]
        )
        report = json.loads(audit.read_text(encoding="utf-8"))
        comparisons = report.get("comparisonsToBaseline")
        if not isinstance(comparisons, list) or not comparisons:
            raise RuntimeError("terrace audit produced no baseline comparison")
        print(
            "terrace audit is observational and does not gate release: "
            + json.dumps(comparisons[-1], sort_keys=True),
            flush=True,
        )
        self.run(
            [
                str(self.cpu_py),
                "-m",
                "unittest",
                "-v",
                "test_audit_hand_edge_terraces.py",
                "test_materialize_intrinsic_albedo_session_v12.py",
            ],
            cwd=self.tools,
        )
        self.verify_geometry()
        review_items = {
            "final_session": str(self.output),
            "v12_rgb_review": str(self.v12_rgb / "review.png"),
            "v9_review": str(self.v9 / "latent_substrate_v9_review.png"),
            "terrace_audit": str(audit),
            "required_frames": audit_frames,
        }
        self.write_json(self.review_root / "final_review.json", review_items)

    def verify_geometry(self) -> None:
        frame_count = self.output_frame_count()
        groups = (("clean_depth", "clean_depth"), ("normal_map", "normal"), ("normal_confidence", "normal_confidence"))
        checked = 0
        for directory, stem in groups:
            for index in range(1, frame_count + 1):
                name = f"{stem}_{index:06d}.png"
                if sha256(self.v9 / directory / name) != sha256(self.output / directory / name):
                    raise RuntimeError(f"v12 geometry mismatch: {directory}/{name}")
                checked += 1
        rgb_count = len(list((self.output / "clean_rgb").glob("clean_rgb_*.png")))
        if checked != 3 * frame_count or rgb_count != frame_count:
            raise RuntimeError(f"incomplete v12: geometry={checked}, rgb={rgb_count}")
        self.write_json(self.output / "automated_integrity.json", {"geometry_files_verified": checked, "rgb_frames": rgb_count})

    def publish(self) -> None:
        self.zip_artifact.parent.mkdir(parents=True, exist_ok=True)
        if self.output_format == "png-sequence":
            self.publish_png()
        elif self.output_format == "lossless-streams":
            self.publish_streams(self.zip_artifact, "lossless")
        elif self.output_format == "compact-streams":
            self.publish_streams(self.zip_artifact, "compact")
        elif self.output_format == "both":
            self.publish_png()
            self.publish_streams(self.stream_artifact, "compact")
        else:
            raise RuntimeError(f"unsupported output format: {self.output_format}")

    def publish_streams(self, artifact: Path, mode: str) -> None:
        if artifact.is_file():
            print(f"reusing published stream artifact: {artifact}", flush=True)
        else:
            self.run(
                [
                    str(self.cpu_py),
                    str(self.tools / "pack_rgbd_streams.py"),
                    "pack",
                    "--session",
                    str(self.output),
                    "--output",
                    str(artifact),
                    "--mode",
                    mode,
                    "--rgb-resolution",
                    self.rgb_resolution,
                    "--fallback-fps",
                    str(self.fallback_fps),
                ]
            )
        self.write_artifact_receipt(artifact)

    def publish_png(self) -> None:
        if self.zip_artifact.is_file():
            print(f"reusing published artifact: {self.zip_artifact}", flush=True)
        else:
            temporary_zip = self.zip_artifact.with_name(
                self.zip_artifact.stem + ".tmp.zip"
            )
            temporary_zip.unlink(missing_ok=True)
            try:
                subprocess.run(
                    [
                        "7z",
                        "a",
                        "-tzip",
                        "-mx=0",
                        "-bd",
                        "-y",
                        str(temporary_zip),
                        self.output.name,
                    ],
                    cwd=self.output.parent,
                    env=self.env,
                    check=True,
                )
                os.replace(temporary_zip, self.zip_artifact)
            except Exception:
                temporary_zip.unlink(missing_ok=True)
                raise
            self.write_artifact_receipt(self.zip_artifact)

        if self.tar_artifact.is_file():
            print(f"reusing published artifact: {self.tar_artifact}", flush=True)
        else:
            temporary_tar = self.tar_artifact.with_name(self.tar_artifact.name + ".tmp")
            temporary_tar.unlink(missing_ok=True)
            publish_env = self.env.copy()
            publish_env["ZSTD_CLEVEL"] = "1"
            try:
                subprocess.run(
                    [
                        "tar",
                        "--zstd",
                        "-cf",
                        str(temporary_tar),
                        "-C",
                        str(self.output.parent),
                        self.output.name,
                    ],
                    env=publish_env,
                    check=True,
                )
                os.replace(temporary_tar, self.tar_artifact)
            except Exception:
                temporary_tar.unlink(missing_ok=True)
                raise
            self.write_artifact_receipt(self.tar_artifact)

    def write_artifact_receipt(self, artifact: Path) -> None:
        digest = sha256(artifact)
        self.write_json(
            artifact.with_suffix(artifact.suffix + ".json"),
            {
                "path": str(artifact),
                "sizeBytes": artifact.stat().st_size,
                "sha256": digest,
            },
        )

    def execute(self) -> None:
        self.stage("preflight", 0.01, "checking capacity, models, and revisions", self.preflight)
        self.stage("ingest", 0.03, "decoding MKV or extracting archive to local scratch", self.ingest)
        self.stage("validate_input", 0.05, "validating the variable-length Azure sequence", self.validate_input)
        self.stage("prepare_masks", 0.08, "preparing bounded SAM inputs", self.prepare_masks)
        self.stage("sam_pass_one", 0.14, "Grounded-SAM-2 hand and arm pass", self.sam_pass_one)
        self.stage("sam_pass_two_merge", 0.24, "Grounded-SAM-2 arm pass and mask merge", self.sam_pass_two_and_merge)
        self.stage("propainter", 0.34, "generating full-resolution gated ProPainter candidate", self.propainter)
        self.stage("any2full_prepare", 0.45, "preparing metric anchors and conditioning RGB", self.any2full_prepare)
        self.stage("any2full", 0.58, "running Any2Full VIT-L on all frames", self.any2full)
        self.stage("depth_masks", 0.68, "building conservative post-roll actor masks", self.depth_masks)
        self.stage("v3_v4", 0.76, "building v3 bidirectional reconstruction and v4 normals", self.v3_v4)
        self.stage("v9_v12", 0.88, "building v9 geometry and materializing v12 to durable storage", self.v9_v12)
        self.stage("audit", 0.97, "running terrace regression and byte-identity audits", self.audit)
        self.stage("publish", 0.99, "packing resumable final download in durable storage", self.publish)
        self.progress("completed", 1.0, "all automated v12 stages and audits passed")
        self.write_json(
            self.result_file,
            {
                "pipeline_complete": True,
                "review_required": False,
                "progress": 1.0,
                "input_frame_count": self.input_frame_count(),
                "output_frame_count": self.output_frame_count(),
                "output_path": str(self.output),
                "input_format": self.resolved_input_format(),
                "output_format": self.output_format,
                "rgb_resolution": self.rgb_resolution,
                "timing_source": self.capture_times(self.input_frame_count())[1],
                "artifacts": [
                    str(path)
                    for path in (self.zip_artifact, self.stream_artifact, self.tar_artifact)
                    if path.is_file()
                ],
                "pipeline_log": str(self.job_root / "pipeline.log"),
            },
        )


def required_text(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is unset: {name}")
    return value


def required_path(name: str, *, executable: bool = False) -> Path:
    # Do not resolve executable symlinks here.  A venv's bin/python commonly
    # points at the system interpreter, but Python needs the venv entry path in
    # argv[0] to discover pyvenv.cfg and its site-packages.  realpath/resolve
    # silently turns a working venv into a dependency-free system Python.
    path = Path(os.path.abspath(os.path.expanduser(required_text(name))))
    if not path.exists() or (executable and not os.access(path, os.X_OK)):
        raise RuntimeError(f"required path is unavailable: {name}={path}")
    return path


def ensure_child(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", default="")
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--scratch-root", required=True)
    parser.add_argument("--input-format", choices=("auto", "azure-mkv", "frame-archive", "stream-bundle"), default="auto")
    parser.add_argument("--output-format", choices=("png-sequence", "lossless-streams", "compact-streams", "both"), default="compact-streams")
    parser.add_argument("--rgb-resolution", choices=("native", "75-percent", "50-percent"), default="native")
    parser.add_argument("--fallback-fps", type=float, default=30.0)
    args = parser.parse_args()
    pipeline = Pipeline(args)
    pipeline.execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
