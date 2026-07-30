#!/usr/bin/env python3
"""Clone a processed Godot session while replacing only displayed RGB frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(paths: list[Path]) -> tuple[str, list[str]]:
    hashes = [file_sha256(path) for path in paths]
    digest = hashlib.sha256()
    for value in hashes:
        digest.update(bytes.fromhex(value))
    return digest.hexdigest(), hashes


def rewrite_resource_paths(value: Any, source_name: str, output_name: str) -> Any:
    if isinstance(value, dict):
        return {
            key: rewrite_resource_paths(item, source_name, output_name)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            rewrite_resource_paths(item, source_name, output_name)
            for item in value
        ]
    if isinstance(value, str):
        prefix = f"res://assets/processed_sessions/{source_name}/"
        if value.startswith(prefix):
            return (
                f"res://assets/processed_sessions/{output_name}/"
                + value[len(prefix) :]
            )
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument("--display-rgb-source", required=True)
    parser.add_argument("--mask-report", type=Path)
    parser.add_argument("--propainter-commit", default="")
    parser.add_argument(
        "--repair-method",
        default="ProPainter full-sequence video inpainting",
    )
    parser.add_argument(
        "--repair-note",
        default="Displayed RGB was replaced without changing depth.",
    )
    args = parser.parse_args()

    source_manifest_path = args.source_session / "processed_manifest.json"
    source_session_path = args.source_session / "session.json"
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    session = json.loads(source_session_path.read_text(encoding="utf-8"))
    frames = manifest["frames"]
    frame_count = len(frames)
    rgb_paths = sorted(args.rgb_dir.glob("*.png"))
    if len(rgb_paths) != frame_count:
        raise ValueError(
            f"RGB count {len(rgb_paths)} != manifest frame count {frame_count}"
        )
    if args.output_session.exists() and any(args.output_session.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {args.output_session}"
        )
    args.output_session.mkdir(parents=True, exist_ok=True)

    skip = {
        "processed_manifest.json",
        "session.json",
        "display_rgb_sha256.json",
        "display_rgb_materialization_report.json",
    }
    for source in args.source_session.iterdir():
        if not source.is_file() or source.name in skip:
            continue
        if source.name.startswith("clean_rgb_"):
            continue
        link_or_copy(source, args.output_session / source.name)

    output_rgb_paths: list[Path] = []
    for index, source in enumerate(rgb_paths, start=1):
        destination = (
            args.output_session / f"clean_rgb_{index:06d}.png"
        )
        link_or_copy(source, destination)
        output_rgb_paths.append(destination)
        frames[index - 1]["cleanRgb"] = destination.name

    rgb_sequence_hash, rgb_hashes = sequence_sha256(output_rgb_paths)
    hash_manifest = {
        "algorithm": "SHA-256",
        "frameCount": frame_count,
        "sequenceDigestOfBinaryFrameDigests": rgb_sequence_hash,
        "frames": [
            {
                "frameIndex": index,
                "file": path.name,
                "sha256": digest,
                "sourceFile": rgb_paths[index - 1].name,
            }
            for index, (path, digest) in enumerate(
                zip(output_rgb_paths, rgb_hashes),
                start=1,
            )
        ],
    }
    (args.output_session / "display_rgb_sha256.json").write_text(
        json.dumps(hash_manifest, indent=2),
        encoding="utf-8",
    )

    source_depth_paths = [
        args.source_session / str(frame["cleanDepth"]) for frame in frames
    ]
    output_depth_paths = [
        args.output_session / str(frame["cleanDepth"]) for frame in frames
    ]
    source_depth_hash, _ = sequence_sha256(source_depth_paths)
    output_depth_hash, _ = sequence_sha256(output_depth_paths)
    if source_depth_hash != output_depth_hash:
        raise RuntimeError("depth sequence changed during RGB materialization")

    repair = {
        "method": args.repair_method,
        "displayRgbSource": args.display_rgb_source,
        "displayRgbLocalMirror": str(args.rgb_dir.resolve()),
        "displayRgbValidation": (
            f"{frame_count}/{frame_count} materialized RGB SHA-256 hashes "
            "recorded in display_rgb_sha256.json"
        ),
        "displayRgbSequenceSha256": rgb_sequence_hash,
        "propainterCommit": args.propainter_commit or None,
        "maskReport": str(args.mask_report) if args.mask_report else None,
        "note": args.repair_note,
    }
    completion = dict(manifest.get("any2FullDepthCompletion", {}))
    completion.update(repair)
    manifest["any2FullDepthCompletion"] = completion
    manifest["sessionId"] = args.output_session.name
    manifest["displayRgbRepair"] = repair
    manifest["displayRgbSha256Manifest"] = "display_rgb_sha256.json"
    manifest["depthSequenceSha256"] = output_depth_hash
    (args.output_session / "processed_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    source_name = args.source_session.name
    output_name = args.output_session.name
    session = rewrite_resource_paths(session, source_name, output_name)
    session["id"] = output_name
    session["title"] = (
        "Kinect full-hand/forearm removed RGB - stable Any2Full depth"
    )
    production = dict(session.get("production_session", {}))
    production_completion = dict(
        production.get("any2FullDepthCompletion", {})
    )
    production_completion.update(repair)
    production["any2FullDepthCompletion"] = production_completion
    production["displayRgbRepair"] = repair
    session["production_session"] = production
    (args.output_session / "session.json").write_text(
        json.dumps(session, indent=2),
        encoding="utf-8",
    )

    if args.mask_report is not None:
        shutil.copy2(
            args.mask_report,
            args.output_session / "display_rgb_mask_report.json",
        )

    report = {
        "sourceSession": str(args.source_session.resolve()),
        "outputSession": str(args.output_session.resolve()),
        "frameCount": frame_count,
        "rgbSequenceSha256": rgb_sequence_hash,
        "sourceDepthSequenceSha256": source_depth_hash,
        "outputDepthSequenceSha256": output_depth_hash,
        "depthUnchanged": source_depth_hash == output_depth_hash,
    }
    (args.output_session / "display_rgb_materialization_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
