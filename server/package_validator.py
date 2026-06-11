from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile


def sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract_zip(zip_file: Path, destination: Path) -> None:
    root = destination.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_file) as zf:
        bad_member = zf.testzip()
        if bad_member is not None:
            raise BadZipFile(f"bad member: {bad_member}")
        for member in zf.infolist():
            target = (root / member.filename).resolve()
            if root != target and root not in target.parents:
                raise BadZipFile(f"unsafe member path: {member.filename}")
        zf.extractall(root)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def validate_package(zip_path: Path, extract_root: Path, expected_zip_sha256: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {}

    actual_zip_sha = sha256_hex(zip_path)
    summary["zipSHA256"] = actual_zip_sha
    summary["zipBytes"] = zip_path.stat().st_size
    if expected_zip_sha256 and actual_zip_sha.lower() != expected_zip_sha256.lower():
        errors.append("zip sha256 mismatch")

    try:
        safe_extract_zip(zip_path, extract_root)
    except Exception as exc:
        return {
            "status": "invalid",
            "errors": [f"zip extraction failed: {exc}"],
            "warnings": warnings,
            "summary": summary,
        }

    package_manifest_path = extract_root / "package_manifest.json"
    manifest_path = extract_root / "manifest.json"
    arkit_frames_path = extract_root / "arkit_frames.jsonl"

    for rel in ["manifest.json", "package_manifest.json", "strokes.json", "objects.jsonl", "boundary_samples.jsonl"]:
        if not (extract_root / rel).exists():
            errors.append(f"missing required file: {rel}")

    package_manifest: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    arkit_frames: list[dict[str, Any]] = []
    v2_frames: list[dict[str, Any]] = []

    if package_manifest_path.exists():
        try:
            package_manifest = load_json(package_manifest_path)
        except Exception as exc:
            errors.append(f"package_manifest.json invalid: {exc}")

    if manifest_path.exists():
        try:
            manifest = load_json(manifest_path)
        except Exception as exc:
            errors.append(f"manifest.json invalid: {exc}")

    if arkit_frames_path.exists():
        try:
            arkit_frames = load_jsonl(arkit_frames_path)
        except Exception as exc:
            errors.append(f"arkit_frames.jsonl invalid: {exc}")

    capture_format = manifest.get("captureFormat") if manifest else None
    v2_info = manifest.get("v2Streams") if manifest else None
    v2_frames_path = extract_root / str((v2_info or {}).get("frameMetadataFile", "v2_frames.jsonl"))
    if capture_format == "v2_streams":
        if not isinstance(v2_info, dict):
            errors.append("manifest missing v2Streams")
        if not v2_frames_path.exists():
            errors.append("missing required file: v2_frames.jsonl")
        else:
            try:
                v2_frames = load_jsonl(v2_frames_path)
            except Exception as exc:
                errors.append(f"v2_frames.jsonl invalid: {exc}")

    if package_manifest:
        listed_paths: set[str] = set()
        for entry in package_manifest.get("files", []):
            rel = entry.get("relativePath")
            if not isinstance(rel, str) or not rel:
                errors.append("package_manifest contains an invalid relativePath")
                continue
            if rel.startswith("/") or ".." in Path(rel).parts:
                errors.append(f"package_manifest contains unsafe path: {rel}")
                continue
            listed_paths.add(rel)
            path = extract_root / rel
            if not path.exists():
                errors.append(f"package_manifest file missing: {rel}")
                continue
            expected_size = entry.get("size")
            if isinstance(expected_size, int) and path.stat().st_size != expected_size:
                errors.append(f"size mismatch: {rel}")
            expected_sha = entry.get("sha256")
            if isinstance(expected_sha, str) and sha256_hex(path).lower() != expected_sha.lower():
                errors.append(f"sha256 mismatch: {rel}")

        actual_paths = {
            str(path.relative_to(extract_root)).replace("\\", "/")
            for path in extract_root.rglob("*")
            if path.is_file() and path.name != "package_manifest.json"
        }
        missing_from_manifest = sorted(actual_paths - listed_paths)
        if missing_from_manifest:
            warnings.append(f"files not listed in package_manifest: {len(missing_from_manifest)}")

    depth_frames = manifest.get("depthFrames", []) if manifest else []
    rgb_frames = manifest.get("rgbFrames", []) if manifest else []
    summary["sessionId"] = manifest.get("sessionId") if manifest else None
    summary["captureFormat"] = capture_format or "v1_frames"
    summary["depthFrames"] = len(depth_frames)
    summary["rgbFrames"] = len(rgb_frames)
    summary["rawDepthFrames"] = len(arkit_frames)
    summary["v2Frames"] = len(v2_frames)

    if len(depth_frames) != len(rgb_frames):
        errors.append("depthFrames and rgbFrames counts differ")
    if arkit_frames and len(arkit_frames) != len(depth_frames):
        errors.append("arkit_frames.jsonl count differs from depthFrames count")

    if capture_format == "v2_streams":
        if depth_frames or rgb_frames or arkit_frames:
            warnings.append("v2 package contains legacy frame metadata")
        if v2_info:
            rgb_video = extract_root / str(v2_info.get("rgbVideoPath", "streams/rgb.mp4"))
            depth_stream = extract_root / str(v2_info.get("depthStreamPath", "streams/depth.f32"))
            confidence_path_value = v2_info.get("confidenceStreamPath")
            confidence_stream = extract_root / str(confidence_path_value) if confidence_path_value else None
            if not rgb_video.exists() or rgb_video.stat().st_size <= 0:
                errors.append("missing or empty v2 RGB video stream")
            if not depth_stream.exists() or depth_stream.stat().st_size <= 0:
                errors.append("missing or empty v2 depth stream")
            if confidence_stream is not None and not confidence_stream.exists():
                warnings.append("v2 confidence stream missing")

            depth_size = depth_stream.stat().st_size if depth_stream.exists() else 0
            confidence_size = confidence_stream.stat().st_size if confidence_stream is not None and confidence_stream.exists() else 0
            expected_depth_offset = 0
            expected_confidence_offset = 0
            previous_index = 0
            for record in v2_frames:
                idx = record.get("frameIndex", "?")
                if isinstance(idx, int):
                    if previous_index and idx != previous_index + 1:
                        errors.append(f"v2 frame index gap before frame {idx}")
                    previous_index = idx
                width = record.get("width")
                height = record.get("height")
                depth_offset = record.get("depthByteOffset")
                depth_count = record.get("depthByteCount")
                if not all(isinstance(v, int) for v in [width, height, depth_offset, depth_count]):
                    errors.append(f"v2 frame {idx} missing depth dimensions/offset/count")
                    continue
                expected_count = width * height * 4
                if depth_count != expected_count:
                    errors.append(f"v2 depth byte count mismatch frame {idx}: expected {expected_count}, got {depth_count}")
                if depth_offset != expected_depth_offset:
                    errors.append(f"v2 depth offset mismatch frame {idx}: expected {expected_depth_offset}, got {depth_offset}")
                if depth_offset + depth_count > depth_size:
                    errors.append(f"v2 depth range exceeds stream frame {idx}")
                expected_depth_offset = depth_offset + depth_count

                if len(record.get("cameraTransformColumnMajor", [])) != 16:
                    errors.append(f"camera transform length invalid frame {idx}")
                if len(record.get("cameraIntrinsicsColumnMajor", [])) != 9:
                    errors.append(f"camera intrinsics length invalid frame {idx}")

                confidence_offset = record.get("confidenceByteOffset")
                confidence_count = record.get("confidenceByteCount")
                if confidence_offset is None and confidence_count is None:
                    continue
                if not isinstance(confidence_offset, int) or not isinstance(confidence_count, int):
                    errors.append(f"v2 confidence offset/count invalid frame {idx}")
                    continue
                if confidence_offset != expected_confidence_offset:
                    errors.append(f"v2 confidence offset mismatch frame {idx}: expected {expected_confidence_offset}, got {confidence_offset}")
                if confidence_offset + confidence_count > confidence_size:
                    errors.append(f"v2 confidence range exceeds stream frame {idx}")
                if isinstance(record.get("confidenceBytesPerRow"), int) and isinstance(height, int):
                    expected_conf = record["confidenceBytesPerRow"] * height
                    if confidence_count != expected_conf:
                        errors.append(f"v2 confidence byte count mismatch frame {idx}: expected {expected_conf}, got {confidence_count}")
                expected_confidence_offset = confidence_offset + confidence_count

            if v2_frames and expected_depth_offset != depth_size:
                errors.append(f"v2 depth stream has trailing or missing bytes: indexed {expected_depth_offset}, file {depth_size}")
            if confidence_size and expected_confidence_offset != confidence_size:
                errors.append(f"v2 confidence stream has trailing or missing bytes: indexed {expected_confidence_offset}, file {confidence_size}")

        summary["depthFrames"] = len(v2_frames)
        summary["rgbFrames"] = len(v2_frames)

    for frame in depth_frames:
        rel = frame.get("relativePath")
        if not isinstance(rel, str) or not (extract_root / rel).exists():
            errors.append(f"missing depth frame: {rel}")

    for frame in rgb_frames:
        rel = frame.get("relativePath")
        if not isinstance(rel, str) or not (extract_root / rel).exists():
            errors.append(f"missing rgb frame: {rel}")

    confidence_missing = 0
    for record in arkit_frames:
        idx = record.get("frameIndex", "?")
        raw_rel = record.get("rawDepthRelativePath")
        width = record.get("width")
        height = record.get("height")
        if not isinstance(raw_rel, str) or not (extract_root / raw_rel).exists():
            errors.append(f"missing raw depth frame {idx}: {raw_rel}")
        elif isinstance(width, int) and isinstance(height, int):
            expected = width * height * 4
            actual = (extract_root / raw_rel).stat().st_size
            if actual != expected:
                errors.append(f"raw depth size mismatch frame {idx}: expected {expected}, got {actual}")
        else:
            errors.append(f"raw depth frame {idx} missing width/height")

        if len(record.get("cameraTransformColumnMajor", [])) != 16:
            errors.append(f"camera transform length invalid frame {idx}")
        if len(record.get("cameraIntrinsicsColumnMajor", [])) != 9:
            errors.append(f"camera intrinsics length invalid frame {idx}")

        conf_rel = record.get("confidenceRelativePath")
        if conf_rel:
            conf_path = extract_root / conf_rel
            if not conf_path.exists():
                errors.append(f"missing confidence frame {idx}: {conf_rel}")
            elif isinstance(record.get("confidenceBytesPerRow"), int) and isinstance(height, int):
                expected = record["confidenceBytesPerRow"] * height
                actual = conf_path.stat().st_size
                if actual != expected:
                    errors.append(f"confidence size mismatch frame {idx}: expected {expected}, got {actual}")
        else:
            confidence_missing += 1

    if confidence_missing:
        warnings.append(f"confidence map missing for {confidence_missing} raw frames")

    if manifest:
        start = manifest.get("wallClockStartUnix")
        end = manifest.get("wallClockEndUnix")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            summary["durationSeconds"] = max(0.0, float(end) - float(start))
        else:
            warnings.append("manifest missing wall-clock end/start")

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }
