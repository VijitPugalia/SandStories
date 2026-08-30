#!/usr/bin/env python3
"""Materialize a Godot session with new RGB while preserving geometry byte-for-byte.

The source session is mirrored with hardlinks wherever possible.  Geometry and
mask sequences are never decoded or rewritten, so a successful run cannot
change the validated depth/normal reconstruction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any


FRAME_COUNT = 201
MIN_FREE_GIB = 25.0
RGB_DIR_NAME = "clean_rgb"
SKIP_TOP_LEVEL = {
    RGB_DIR_NAME,
    "session.json",
    "processed_manifest.json",
    "intrinsic_albedo_v12_receipt.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument("--min-free-gib", type=float, default=MIN_FREE_GIB)
    return parser.parse_args()


def free_gib(path: Path) -> float:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1024**3)


def link_or_copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return "hardlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy"


def mirror_entry(source: Path, destination: Path, counters: dict[str, int]) -> None:
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            mirror_entry(child, destination / child.name, counters)
        return
    mode = link_or_copy(source, destination)
    counters[mode] += 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_session_path(value: Any, old_name: str, new_name: str) -> Any:
    if isinstance(value, dict):
        return {key: replace_session_path(item, old_name, new_name) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_session_path(item, old_name, new_name) for item in value]
    if isinstance(value, str):
        return value.replace(
            f"res://assets/processed_sessions/{old_name}/",
            f"res://assets/processed_sessions/{new_name}/",
        )
    return value


def require_sequence(directory: Path, stem: str, count: int = FRAME_COUNT) -> list[Path]:
    files = [directory / f"{stem}_{index:06d}.png" for index in range(1, count + 1)]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} sequence files; first: {missing[0]}")
    return files


def main() -> None:
    args = parse_args()
    source = args.source_session.resolve()
    rgb_dir = args.rgb_dir.resolve()
    output = args.output_session.resolve()

    if not source.is_dir():
        raise FileNotFoundError(source)
    require_sequence(rgb_dir, "clean_rgb")
    require_sequence(source / "clean_depth", "clean_depth")
    require_sequence(source / "normal_map", "normal")
    require_sequence(source / "normal_confidence", "normal_confidence")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    if free_gib(output) < args.min_free_gib:
        raise RuntimeError(
            f"Free-space gate failed: {free_gib(output):.2f} GiB < {args.min_free_gib:.2f} GiB"
        )

    output.mkdir(parents=True)
    counters = {"hardlink": 0, "copy": 0}
    try:
        for entry in source.iterdir():
            if entry.name in SKIP_TOP_LEVEL or entry.name.endswith(".import"):
                continue
            mirror_entry(entry, output / entry.name, counters)

        output_rgb = output / RGB_DIR_NAME
        output_rgb.mkdir()
        for index in range(1, FRAME_COUNT + 1):
            mode = link_or_copy(
                rgb_dir / f"clean_rgb_{index:06d}.png",
                output_rgb / f"clean_rgb_{index:06d}.png",
            )
            counters[mode] += 1

        with (source / "processed_manifest.json").open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if len(manifest.get("frames", [])) != FRAME_COUNT:
            raise ValueError("Source manifest does not contain exactly 201 frames")
        for index, frame in enumerate(manifest["frames"], start=1):
            frame["cleanRgb"] = f"clean_rgb/clean_rgb_{index:06d}.png"
        manifest["sessionId"] = output.name
        manifest["intrinsicAlbedoV12"] = {
            "version": 12,
            "method": "robust temporal sand chroma with low-frequency shadow removal",
            "detailPolicy": "retain original high-frequency RGB detail; neutralize only low-frequency cast-shadow albedo",
            "parameters": {
                "closeSize": 251,
                "maximumGain": 6.0,
                "matteThreshold": 2.0,
                "matteSoftness": 12.0,
                "detailSigma": 5.0,
                "analysisScale": 0.5,
                "neutralizeAlbedo": True,
            },
            "geometrySource": source.name,
            "depthUnchanged": True,
        }
        with (output / "processed_manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        with (source / "session.json").open("r", encoding="utf-8") as handle:
            session = json.load(handle)
        session = replace_session_path(session, source.name, output.name)
        session["id"] = output.name
        session["title"] = "Azure intrinsic-albedo v12 / progressive trench geometry"
        session.setdefault("data_sources", {})["texture_map"] = (
            f"res://assets/processed_sessions/{output.name}/clean_rgb/clean_rgb_000001.png"
        )
        session["data_sources"]["processed_manifest"] = (
            f"res://assets/processed_sessions/{output.name}/processed_manifest.json"
        )
        session.setdefault("production_session", {})["intrinsicAlbedoV12"] = deepcopy(
            manifest["intrinsicAlbedoV12"]
        )
        with (output / "session.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(session, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        samples: list[dict[str, Any]] = []
        for index in (1, 101, 201):
            source_depth = source / "clean_depth" / f"clean_depth_{index:06d}.png"
            output_depth = output / "clean_depth" / source_depth.name
            source_hash = sha256(source_depth)
            output_hash = sha256(output_depth)
            if source_hash != output_hash:
                raise RuntimeError(f"Depth changed at frame {index}")
            samples.append(
                {
                    "frame": index,
                    "sha256": source_hash,
                    "sameFile": os.path.samefile(source_depth, output_depth),
                }
            )

        receipt = {
            "version": 12,
            "sourceGeometrySession": str(source),
            "rgbSource": str(rgb_dir),
            "outputSession": str(output),
            "frameCount": FRAME_COUNT,
            "depthUnchanged": True,
            "depthVerification": samples,
            "fileMaterialization": counters,
            "freeGiBBeforeGate": round(free_gib(output), 3),
            "minimumFreeGiB": args.min_free_gib,
        }
        with (output / "intrinsic_albedo_v12_receipt.json").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    except Exception:
        # Output was newly created by this process and is incomplete.  Remove
        # only that exact directory so a retry cannot accidentally mix files.
        shutil.rmtree(output)
        raise


if __name__ == "__main__":
    main()
