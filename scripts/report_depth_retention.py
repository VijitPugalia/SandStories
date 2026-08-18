#!/usr/bin/env python3
"""
Report on-device LiDAR depth retention from a SandStories v2 session manifest.

Reads `manifest.json` -> `diagnostic.counters` and reports where depth frames are
being skipped (warmup, low-quality / valid-ratio, in-flight, writing, motion gate),
plus the motion-gate auto-calibration block (`gateCalibration`) if present.

Note: the "Auto-calibrate motion gate from baseline" feature that produced
`gateCalibration` was reverted (2026-08-18) after on-device testing showed it
collapsed retention to ~5% vs ~95.5% with the gate off. This tool still reports the
field when present, and remains the way to confirm retention / skip counts.

Usage:
  python scripts/report_depth_retention.py /path/to/session_UUID
  python scripts/report_depth_retention.py --batch /dir/with/session_* --csv out.csv

Exit code 0 on success. Prints a human-readable report.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

# Skip keys that are pure accounting bookkeeping; everything else is a skip reason.
SKIP_KEYS = ("arFramesWithoutDepth", "framesSkippedInFlight", "framesSkippedWriting")


def load_manifest(session_dir: Path) -> dict[str, Any]:
    path = session_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing manifest.json in {session_dir}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def summarize_counters(counters: dict[str, Any]) -> dict[str, Any]:
    received = int(_num(counters.get("arFramesReceived")))
    written = int(_num(counters.get("framesWritten")))
    retained_rate = (written / received) if received else 0.0

    # Dominant skip reason (excluding accounting counters).
    reasons: dict[str, int] = {}
    for key, value in counters.items():
        if key in SKIP_KEYS:
            continue
        if key.startswith("framesSkipped"):
            reasons[key] = int(_num(value))
    dominant = max(reasons, key=reasons.get) if reasons and max(reasons.values()) > 0 else None

    return {
        "arFramesReceived": received,
        "framesWritten": written,
        "framesSkippedInFlight": int(_num(counters.get("framesSkippedInFlight"))),
        "framesSkippedWriting": int(_num(counters.get("framesSkippedWriting"))),
        "framesSkippedWarmup": int(_num(counters.get("framesSkippedWarmup"))),
        "framesSkippedLowQuality": int(_num(counters.get("framesSkippedLowQuality"))),
        "framesSkippedMotion": int(_num(counters.get("framesSkippedMotion"))),
        "arFramesWithoutDepth": int(_num(counters.get("arFramesWithoutDepth"))),
        "rawDepthFramesAvailable": int(_num(counters.get("rawDepthFramesAvailable"))),
        "smoothedDepthFramesAvailable": int(_num(counters.get("smoothedDepthFramesAvailable"))),
        "selectedDepthSource": counters.get("selectedDepthSource"),
        "lastDepthValidPixelRatio": counters.get("lastDepthValidPixelRatio"),
        "retainedRate": round(retained_rate, 4),
        "dominantSkip": dominant,
    }


def format_summary(session_dir: Path, counters: dict[str, Any], gate: dict[str, Any] | None) -> str:
    s = summarize_counters(counters)
    lines = [
        f"Session: {session_dir.name}",
        f"  selectedDepthSource : {s['selectedDepthSource'] or 'n/a'}",
        f"  rawAvailable        : {s['rawDepthFramesAvailable']}   smoothedAvailable: {s['smoothedDepthFramesAvailable']}",
        f"  lastDepthValidRatio : {s['lastDepthValidPixelRatio']}",
        "",
        f"  AR frames received  : {s['arFramesReceived']}",
        f"  frames written      : {s['framesWritten']}   (retained rate {s['retainedRate']:.1%})",
        f"  no-depth skipped    : {s['arFramesWithoutDepth']}",
        f"  in-flight skipped   : {s['framesSkippedInFlight']}",
        f"  writer-busy skipped : {s['framesSkippedWriting']}",
        f"  warmup skipped      : {s['framesSkippedWarmup']}",
        f"  low-quality skipped : {s['framesSkippedLowQuality']}",
        f"  motion-gate skipped : {s['framesSkippedMotion']}",
        f"  dominant skip reason: {s['dominantSkip'] or 'none (all retained)'}",
    ]
    if gate:
        lines.append("")
        lines.append("  Motion-gate calibration:")
        for k in ("mode", "floorMeanAbsDeltaU16", "multiplier", "calibrationFrameCount",
                  "finalThresholdU16", "note"):
            if k in gate and gate[k] is not None:
                lines.append(f"    {k}: {gate[k]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", nargs="?", type=Path, help="A session folder containing manifest.json")
    parser.add_argument("--batch", type=Path, help="Directory containing one or more session_* folders")
    parser.add_argument("--csv", type=Path, help="Also write a CSV of the retention summary (with --batch)")
    args = parser.parse_args(argv)

    if args.batch:
        if not args.batch.is_dir():
            raise SystemExit(f"Not a directory: {args.batch}")
        sessions = sorted(p for p in args.batch.iterdir() if (p / "manifest.json").is_file())
        if not sessions:
            raise SystemExit(f"No session folders with manifest.json under {args.batch}")
    elif args.session_dir:
        sessions = [args.session_dir]
    else:
        raise SystemExit("Provide a session_dir or --batch directory")

    rows: list[dict[str, Any]] = []
    for s in sessions:
        manifest = load_manifest(s)
        diag = (manifest.get("diagnostic") or {})
        counters = diag.get("counters") or {}
        gate = counters.get("gateCalibration")
        print(format_summary(s, counters, gate))
        print("-" * 60)
        rows.append({"session": s.name, **summarize_counters(counters)})

    if args.csv:
        if not rows:
            raise SystemExit("Nothing to write to CSV")
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            fieldnames = ["session", "selectedDepthSource", "rawDepthFramesAvailable",
                          "smoothedDepthFramesAvailable", "arFramesReceived", "framesWritten",
                          "retainedRate", "arFramesWithoutDepth", "framesSkippedInFlight",
                          "framesSkippedWriting", "framesSkippedWarmup", "framesSkippedLowQuality",
                          "framesSkippedMotion", "lastDepthValidPixelRatio", "dominantSkip"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV written: {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))