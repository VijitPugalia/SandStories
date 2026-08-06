from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _resolve_executable(value: str) -> str | None:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return shutil.which(value)


@dataclass(frozen=True)
class Any2FullConfig:
    enabled: bool
    python_executable: str
    repository_dir: Path
    checkpoint: Path
    encoder: str
    depth_source: str
    target_resolution: str
    stride: int
    max_frames: int
    denoise: bool
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "Any2FullConfig":
        return cls(
            enabled=_env_bool("SANDSTORIES_ANY2FULL_ENABLED"),
            python_executable=os.environ.get("SANDSTORIES_ANY2FULL_PYTHON", sys.executable),
            repository_dir=Path(
                os.environ.get("SANDSTORIES_ANY2FULL_DIR", "")
            ).expanduser(),
            checkpoint=Path(
                os.environ.get("SANDSTORIES_ANY2FULL_CHECKPOINT", "")
            ).expanduser(),
            encoder=os.environ.get("SANDSTORIES_ANY2FULL_ENCODER", "auto"),
            depth_source=os.environ.get("SANDSTORIES_ANY2FULL_DEPTH_SOURCE", "selected"),
            target_resolution=os.environ.get(
                "SANDSTORIES_ANY2FULL_TARGET_RESOLUTION", "depth"
            ),
            stride=_env_int("SANDSTORIES_ANY2FULL_STRIDE", 10, 1),
            max_frames=_env_int("SANDSTORIES_ANY2FULL_MAX_FRAMES", 60, 0),
            denoise=_env_bool("SANDSTORIES_ANY2FULL_DENOISE"),
            timeout_seconds=_env_int("SANDSTORIES_ANY2FULL_TIMEOUT_SECONDS", 3600, 1),
        )

    def readiness_errors(self, repository_root: Path) -> list[str]:
        if not self.enabled:
            return []
        errors: list[str] = []
        if _resolve_executable(self.python_executable) is None:
            errors.append(f"Python executable not found: {self.python_executable}")
        if not (self.repository_dir / "run_any2full.py").is_file():
            errors.append(f"Any2Full checkout missing run_any2full.py: {self.repository_dir}")
        if not self.checkpoint.is_file():
            errors.append(f"Any2Full checkpoint not found: {self.checkpoint}")
        if not (repository_root / "scripts" / "complete_depth_any2full.py").is_file():
            errors.append("SandStories Any2Full adapter is missing")
        if self.encoder not in {"auto", "vits", "vitb", "vitl"}:
            errors.append(f"Unsupported encoder: {self.encoder}")
        if self.depth_source not in {"selected", "smoothed"}:
            errors.append(f"Unsupported depth source: {self.depth_source}")
        if self.target_resolution not in {"depth", "rgb"}:
            errors.append(f"Unsupported target resolution: {self.target_resolution}")
        return errors

    def public_status(self, repository_root: Path) -> dict[str, Any]:
        errors = self.readiness_errors(repository_root)
        return {
            "enabled": self.enabled,
            "ready": self.enabled and not errors,
            "errors": errors,
            "encoder": self.encoder,
            "depthSource": self.depth_source,
            "targetResolution": self.target_resolution,
            "stride": self.stride,
            "maxFrames": self.max_frames or None,
            "denoise": self.denoise,
        }


class CompletionError(RuntimeError):
    pass


def build_completion_command(
    config: Any2FullConfig,
    repository_root: Path,
    session_dir: Path,
    output_dir: Path,
) -> list[str]:
    executable = _resolve_executable(config.python_executable)
    if executable is None:
        raise CompletionError(f"Python executable not found: {config.python_executable}")
    command = [
        executable,
        str(repository_root / "scripts" / "complete_depth_any2full.py"),
        str(session_dir),
        "--output-dir",
        str(output_dir),
        "--any2full-dir",
        str(config.repository_dir.resolve()),
        "--checkpoint",
        str(config.checkpoint.resolve()),
        "--python",
        executable,
        "--encoder",
        config.encoder,
        "--depth-source",
        config.depth_source,
        "--target-resolution",
        config.target_resolution,
        "--stride",
        str(config.stride),
        "--overwrite",
    ]
    if config.max_frames:
        command.extend(["--max-frames", str(config.max_frames)])
    if config.denoise:
        command.append("--denoise")
    return command


def run_completion(
    package: dict[str, Any],
    config: Any2FullConfig,
    repository_root: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    errors = config.readiness_errors(repository_root)
    if errors:
        raise CompletionError("; ".join(errors))
    extracted_value = package.get("extracted_path")
    if not extracted_value:
        raise CompletionError("Package has no extracted session path")
    session_dir = Path(str(extracted_value)).resolve()
    if not (session_dir / "manifest.json").is_file():
        raise CompletionError(f"Extracted session is missing manifest.json: {session_dir}")

    output_dir = session_dir / "derived" / "any2full"
    command = build_completion_command(config, repository_root, session_dir, output_dir)
    result = subprocess.run(
        command,
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "worker.log"
    log_path.write_text(
        "COMMAND\n"
        + json.dumps(command)
        + "\n\nSTDOUT\n"
        + result.stdout
        + "\n\nSTDERR\n"
        + result.stderr,
        encoding="utf-8",
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip()[-2000:]
        raise CompletionError(
            f"Any2Full exited with code {result.returncode}: {tail or 'see worker.log'}"
        )

    completion_manifest_path = output_dir / "completion_manifest.json"
    quality_report_path = output_dir / "quality_report.json"
    if not completion_manifest_path.is_file() or not quality_report_path.is_file():
        raise CompletionError("Any2Full finished without completion manifest or quality report")

    completion_manifest = json.loads(completion_manifest_path.read_text(encoding="utf-8"))
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    if completion_manifest.get("status") != "completed":
        raise CompletionError(
            f"Completion manifest status is {completion_manifest.get('status')!r}"
        )

    artifact_root.mkdir(parents=True, exist_ok=True)
    archive_base = artifact_root / f"{package['id']}_any2full"
    archive_path = archive_base.with_suffix(".zip")
    if archive_path.exists():
        archive_path.unlink()
    created_archive = Path(
        shutil.make_archive(str(archive_base), "zip", root_dir=output_dir)
    )
    return {
        "outputPath": str(output_dir),
        "reportPath": str(quality_report_path),
        "artifactPath": str(created_archive),
        "logPath": str(log_path),
        "pairCount": completion_manifest.get("pairCount"),
        "aggregateAnchorMetrics": quality_report.get("aggregate"),
    }
