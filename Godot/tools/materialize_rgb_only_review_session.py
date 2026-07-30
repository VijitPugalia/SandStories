#!/usr/bin/env python3
"""Clone a processed session and replace only a bounded displayed-RGB window."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--replacement-frames", type=Path, required=True)
    parser.add_argument("--replacement-start", type=int, required=True)
    parser.add_argument("--replacement-end", type=int, required=True)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument(
        "--method",
        default=(
            "Generative Omnimatte/Casper CogVideoX-5B low-frequency "
            "shadow removal with measured-detail fusion"
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def link_or_copy(source: Path, destination: Path) -> str:
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def frame_suffix(frame: dict[str, Any], key: str) -> int:
    return int(Path(str(frame[key])).stem.rsplit("_", 1)[1])


def main() -> None:
    args = parse_args()
    source = args.source_session.resolve()
    replacement = args.replacement_frames.resolve()
    output = args.output_session.resolve()

    if args.replacement_start < 1:
        raise ValueError("replacement-start must be >= 1")
    if args.replacement_end < args.replacement_start:
        raise ValueError("replacement-end must be >= replacement-start")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")

    source_manifest_path = source / "processed_manifest.json"
    source_session_path = source / "session.json"
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    session = json.loads(source_session_path.read_text(encoding="utf-8"))
    frames = manifest["frames"]
    expected_count = args.replacement_end - args.replacement_start + 1
    replacement_paths = [
        replacement / f"frame_{index:03d}.png"
        for index in range(1, expected_count + 1)
    ]
    missing = [path for path in replacement_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"missing {len(missing)} replacement frames; first: {missing[0]}"
        )
    if args.replacement_end > len(frames):
        raise ValueError(
            f"replacement-end {args.replacement_end} exceeds "
            f"{len(frames)} manifest frames"
        )

    for index, frame in enumerate(frames, start=1):
        if frame_suffix(frame, "cleanRgb") != index:
            raise ValueError(f"RGB filename/index mismatch at frame {index}")
        if frame_suffix(frame, "cleanDepth") != index:
            raise ValueError(f"depth filename/index mismatch at frame {index}")

    output.mkdir(parents=True)
    materialization_counts = {"hardlink": 0, "copy": 0}
    rewritten_names = {"processed_manifest.json", "session.json"}
    for source_path in source.iterdir():
        if not source_path.is_file() or source_path.name in rewritten_names:
            continue
        if source_path.name.startswith("clean_rgb_"):
            suffix = int(source_path.stem.rsplit("_", 1)[1])
            if args.replacement_start <= suffix <= args.replacement_end:
                continue
        mode = link_or_copy(source_path, output / source_path.name)
        materialization_counts[mode] += 1

    replacement_hashes: list[str] = []
    for offset, replacement_path in enumerate(replacement_paths):
        frame_index = args.replacement_start + offset
        destination = output / f"clean_rgb_{frame_index:06d}.png"
        mode = link_or_copy(replacement_path, destination)
        materialization_counts[mode] += 1
        replacement_hashes.append(sha256(destination))

    source_depth_paths = [
        source / str(frame["cleanDepth"]) for frame in frames
    ]
    output_depth_paths = [
        output / str(frame["cleanDepth"]) for frame in frames
    ]
    source_depth_hash = sequence_sha256(source_depth_paths)
    output_depth_hash = sequence_sha256(output_depth_paths)
    if source_depth_hash != output_depth_hash:
        raise RuntimeError("depth sequence changed in RGB-only materialization")

    mesh_names = [
        str(frame["virtualHandMesh"])
        for frame in frames
        if frame.get("virtualHandMesh")
    ]
    source_mesh_hash = sequence_sha256(
        [source / name for name in mesh_names]
    )
    output_mesh_hash = sequence_sha256(
        [output / name for name in mesh_names]
    )
    if source_mesh_hash != output_mesh_hash:
        raise RuntimeError("MANO mesh sequence changed in RGB-only materialization")

    outside_indices = [
        index
        for index in range(1, len(frames) + 1)
        if not args.replacement_start <= index <= args.replacement_end
    ]
    source_outside_rgb_hash = sequence_sha256(
        [
            source / str(frames[index - 1]["cleanRgb"])
            for index in outside_indices
        ]
    )
    output_outside_rgb_hash = sequence_sha256(
        [
            output / str(frames[index - 1]["cleanRgb"])
            for index in outside_indices
        ]
    )
    if source_outside_rgb_hash != output_outside_rgb_hash:
        raise RuntimeError("RGB outside the replacement window changed")

    replacement_sequence_hash = hashlib.sha256(
        b"".join(bytes.fromhex(value) for value in replacement_hashes)
    ).hexdigest()
    output_rgb_hash = sequence_sha256(
        [output / str(frame["cleanRgb"]) for frame in frames]
    )
    override = {
        "mode": "display-rgb-only",
        "method": args.method,
        "sourceSession": str(source),
        "sourceSessionId": str(session.get("id", source.name)),
        "replacementFrames": {
            "start": args.replacement_start,
            "end": args.replacement_end,
            "count": expected_count,
            "sourceDirectory": str(replacement),
            "sequenceSha256": replacement_sequence_hash,
        },
        "outputRgbSequenceSha256": output_rgb_hash,
        "outsideWindowRgbSequenceSha256": output_outside_rgb_hash,
        "depthSequenceSha256": output_depth_hash,
        "manoMeshSequenceSha256": output_mesh_hash,
        "depthRecomputed": False,
        "manoRecomputed": False,
        "rgbdFusionRecomputed": False,
        "any2FullRecomputed": False,
        "reviewCandidate": True,
    }

    output_manifest = dict(manifest)
    output_manifest["sessionId"] = output.name
    output_manifest["sourceSession"] = str(source)
    output_manifest["sourceProcessedManifestSha256"] = sha256(
        source_manifest_path
    )
    output_manifest["displayRgbOverride"] = override
    write_json(output / "processed_manifest.json", output_manifest)

    output_session = dict(session)
    output_session["id"] = output.name
    output_session["title"] = (
        "v20d geometry + RGB-only Casper shadow-removal review probe"
    )
    output_session["production_session"] = False
    output_session["review_candidate"] = True
    output_session["display_rgb_override"] = override
    write_json(output / "session.json", output_session)

    report = {
        "schemaVersion": 1,
        "sourceSession": str(source),
        "outputSession": str(output),
        "sourceFrameCount": len(frames),
        "replacementStart": args.replacement_start,
        "replacementEnd": args.replacement_end,
        "replacementCount": expected_count,
        "meshFrameCount": len(mesh_names),
        "materializationCounts": materialization_counts,
        "depthUnchanged": True,
        "manoMeshesUnchanged": True,
        "outsideWindowRgbUnchanged": True,
        "depthSequenceSha256": output_depth_hash,
        "manoMeshSequenceSha256": output_mesh_hash,
        "outsideWindowRgbSequenceSha256": output_outside_rgb_hash,
        "replacementRgbSequenceSha256": replacement_sequence_hash,
        "outputRgbSequenceSha256": output_rgb_hash,
        "sessionJsonSha256": sha256(output / "session.json"),
        "processedManifestSha256": sha256(
            output / "processed_manifest.json"
        ),
    }
    write_json(output / "rgb_only_display_override_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
