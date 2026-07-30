#!/usr/bin/env python3
"""Merge a replacement interval into a fitted MANO sequence.

The output is additive and preserves the base sequence outside the requested
frame interval. Arrays and optional diagnostic overlays are copied or
hard-linked, and the merged inference manifest records both source reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-fit-dir", type=Path, required=True)
    parser.add_argument("--replacement-fit-dir", type=Path, required=True)
    parser.add_argument("--minimum-frame", type=int, required=True)
    parser.add_argument("--maximum-frame", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--asset-mode",
        choices=("hardlink", "copy"),
        default="hardlink",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_report(directory: Path) -> tuple[Path, dict[str, Any]]:
    path = directory / "mano_hand_only_sequence_report.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _materialize(source: Path, destination: Path, mode: str) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    if mode == "hardlink":
        os.link(source, destination)
    else:
        shutil.copy2(source, destination)


def main() -> None:
    args = _parse_args()
    args.base_fit_dir = args.base_fit_dir.resolve()
    args.replacement_fit_dir = args.replacement_fit_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    if args.minimum_frame > args.maximum_frame:
        raise ValueError("--minimum-frame exceeds --maximum-frame")

    base_report_path, base_report = _load_report(args.base_fit_dir)
    replacement_report_path, replacement_report = _load_report(
        args.replacement_fit_dir
    )
    base_records = {
        int(record["frameIndex"]): record
        for record in base_report["frames"]
    }
    replacement_records = {
        int(record["frameIndex"]): record
        for record in replacement_report["frames"]
    }
    replacement_frames = [
        frame
        for frame in sorted(base_records)
        if args.minimum_frame <= frame <= args.maximum_frame
    ]
    missing = [
        frame
        for frame in replacement_frames
        if frame not in replacement_records
    ]
    if missing:
        raise KeyError(f"Replacement fit is missing frames: {missing}")
    if not replacement_frames:
        raise ValueError("No base frames fall inside the requested interval")
    if not np.allclose(
        np.asarray(base_report["sharedBetas"], dtype=np.float64),
        np.asarray(replacement_report["sharedBetas"], dtype=np.float64),
        rtol=0.0,
        atol=1e-8,
    ):
        raise ValueError("Replacement shared MANO shape differs from the base")
    if not np.isclose(
        float(base_report["sharedCameraZ"]),
        float(replacement_report["sharedCameraZ"]),
        rtol=0.0,
        atol=1e-8,
    ):
        raise ValueError("Replacement shared camera depth differs from the base")

    args.output_dir.mkdir(parents=True)
    merged_records: list[dict[str, Any]] = []
    for frame in sorted(base_records):
        use_replacement = frame in replacement_frames
        source_directory = (
            args.replacement_fit_dir
            if use_replacement
            else args.base_fit_dir
        )
        source_record = (
            replacement_records[frame]
            if use_replacement
            else base_records[frame]
        )
        arrays_source = source_directory / source_record["arrays"]
        arrays_destination = args.output_dir / arrays_source.name
        _materialize(arrays_source, arrays_destination, args.asset_mode)
        merged_record = dict(source_record)
        merged_record["arrays"] = arrays_destination.name
        merged_record["arraysSha256"] = _sha256(arrays_destination)
        merged_record["mergedFrom"] = (
            "replacement" if use_replacement else "base"
        )
        overlay_name = source_record.get("overlay")
        if overlay_name:
            overlay_source = source_directory / overlay_name
            overlay_destination = args.output_dir / overlay_source.name
            _materialize(
                overlay_source,
                overlay_destination,
                args.asset_mode,
            )
            merged_record["overlay"] = overlay_destination.name
        merged_records.append(merged_record)

    final_mean = np.asarray(
        [
            float(record["finalMeanLandmarkErrorPixels"])
            for record in merged_records
        ],
        dtype=np.float64,
    )
    merged_report = dict(base_report)
    merged_report.update(
        {
            "method": (
                str(base_report["method"])
                + "; one bracketed interval replaced by a separately fitted "
                "sequence with the same shared MANO shape and camera depth"
            ),
            "baseFitReport": str(base_report_path),
            "baseFitReportSha256": _sha256(base_report_path),
            "replacementFitReport": str(replacement_report_path),
            "replacementFitReportSha256": _sha256(
                replacement_report_path
            ),
            "replacementFrameRange": [
                args.minimum_frame,
                args.maximum_frame,
            ],
            "replacementFrameCount": len(replacement_frames),
            "frameCount": len(merged_records),
            "framesRequested": [
                int(record["frameIndex"]) for record in merged_records
            ],
            "finalLandmarkErrorPixels": {
                "mean": float(final_mean.mean()),
                "p50": float(np.percentile(final_mean, 50)),
                "p90": float(np.percentile(final_mean, 90)),
                "p95": float(np.percentile(final_mean, 95)),
                "maximum": float(final_mean.max()),
            },
            "frames": merged_records,
        }
    )
    report_path = args.output_dir / "mano_hand_only_sequence_report.json"
    report_text = json.dumps(merged_report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(report_text, encoding="utf-8")
    (args.output_dir / "hamer_inference_manifest.json").write_text(
        report_text,
        encoding="utf-8",
    )
    print(
        f"wrote {len(merged_records)} frames to {args.output_dir}; "
        f"replaced {replacement_frames[0]}-{replacement_frames[-1]} "
        f"({len(replacement_frames)} frames)",
        flush=True,
    )


if __name__ == "__main__":
    main()
