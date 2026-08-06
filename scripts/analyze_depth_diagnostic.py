#!/usr/bin/env python3
"""
Analyze a SandStories v2 depth diagnostic session.

Outputs:
  depth_diagnostic_report.json
  depth_diagnostic_contactsheet.png

Usage:
  python scripts/analyze_depth_diagnostic.py /path/to/session_UUID
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def load_manifest(session_dir: Path) -> dict[str, Any]:
    path = session_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing manifest.json in {session_dir}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_bytes(path: Path, offset: int, count: int) -> bytes:
    with path.open("rb") as f:
        f.seek(offset)
        data = f.read(count)
    if len(data) != count:
        raise ValueError(f"{path}: expected {count} bytes at {offset}, got {len(data)}")
    return data


def read_depth(session_dir: Path, manifest: dict[str, Any], entry: dict[str, Any], source: str):
    import numpy as np

    streams = manifest.get("v2Streams") or {}
    selected_source = entry.get("selectedDepthSource")
    if source == "raw":
        if selected_source == "smoothedSceneDepth":
            return None
        rel = streams.get("depthStreamPath", "streams/depth.f32")
        offset = entry.get("depthByteOffset")
        count = entry.get("depthByteCount")
        width = int(entry["width"])
        height = int(entry["height"])
    else:
        if entry.get("smoothedDepthByteOffset") is not None:
            rel = streams.get("smoothedDepthStreamPath", "streams/smoothed_depth.f32")
            offset = entry.get("smoothedDepthByteOffset")
            count = entry.get("smoothedDepthByteCount")
            width = int(entry.get("smoothedDepthWidth") or entry["width"])
            height = int(entry.get("smoothedDepthHeight") or entry["height"])
        elif selected_source == "smoothedSceneDepth":
            rel = streams.get("depthStreamPath", "streams/depth.f32")
            offset = entry.get("depthByteOffset")
            count = entry.get("depthByteCount")
            width = int(entry["width"])
            height = int(entry["height"])
        else:
            return None
    if offset is None or count is None:
        return None
    data = read_bytes(session_dir / rel, int(offset), int(count))
    arr = np.frombuffer(data, dtype="<f4")
    expected = width * height
    if arr.size != expected:
        raise ValueError(f"{rel}: got {arr.size} values, expected {expected}")
    out = arr.reshape((height, width)).astype("float32")
    out[~np.isfinite(out)] = np.nan
    out[out <= 0] = np.nan
    return out


def read_confidence(session_dir: Path, manifest: dict[str, Any], entry: dict[str, Any]):
    import numpy as np

    offset = entry.get("confidenceByteOffset")
    count = entry.get("confidenceByteCount")
    if offset is None or count is None:
        return None
    streams = manifest.get("v2Streams") or {}
    rel = streams.get("confidenceStreamPath", "streams/confidence.bin")
    width = int(entry.get("confidenceWidth") or entry["width"])
    height = int(entry.get("confidenceHeight") or entry["height"])
    bytes_per_row = int(entry.get("confidenceBytesPerRow") or width)
    data = read_bytes(session_dir / rel, int(offset), int(count))
    raw = np.frombuffer(data, dtype=np.uint8)
    if raw.size < height * bytes_per_row:
        return None
    return raw[: height * bytes_per_row].reshape((height, bytes_per_row))[:, :width]


def read_rgb(session_dir: Path, manifest: dict[str, Any], entry: dict[str, Any]):
    streams = manifest.get("v2Streams") or {}
    video_path = session_dir / streams.get("rgbVideoPath", "streams/rgb.mp4")
    if not video_path.is_file() or entry.get("rgbPresentationTimeSeconds") is None:
        return None
    try:
        import cv2
    except ImportError:
        return None

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, float(entry["rgbPresentationTimeSeconds"]) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def depth_stats(depth) -> dict[str, float | int | None]:
    import numpy as np

    finite = np.isfinite(depth)
    if not finite.any():
        return {"validPixelCount": 0, "medianMeters": None, "p05Meters": None, "p95Meters": None}
    values = depth[finite]
    return {
        "validPixelCount": int(values.size),
        "medianMeters": float(np.nanmedian(values)),
        "p05Meters": float(np.nanpercentile(values, 5)),
        "p95Meters": float(np.nanpercentile(values, 95)),
    }


def abs_delta_stats(current, baseline) -> dict[str, float | int | None]:
    import numpy as np

    mask = np.isfinite(current) & np.isfinite(baseline)
    if not mask.any():
        return {"validPixelCount": 0, "meanAbsDeltaMm": None, "p95AbsDeltaMm": None}
    delta_mm = np.abs(current[mask] - baseline[mask]) * 1000.0
    return {
        "validPixelCount": int(delta_mm.size),
        "meanAbsDeltaMm": float(np.mean(delta_mm)),
        "p95AbsDeltaMm": float(np.percentile(delta_mm, 95)),
    }


def high_frequency_energy(depth) -> float | None:
    import numpy as np

    arr = depth.astype("float32") * 1000.0
    if not np.isfinite(arr).any():
        return None
    med = float(np.nanmedian(arr))
    arr = np.nan_to_num(arr, nan=med)
    gx = np.abs(np.diff(arr, axis=1))
    gy = np.abs(np.diff(arr, axis=0))
    return float((np.mean(gx) + np.mean(gy)) / 2.0)


def rgb_edge_energy(rgb) -> float | None:
    if rgb is None:
        return None
    import numpy as np

    gray = rgb.astype("float32").mean(axis=2)
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    return float((np.mean(gx) + np.mean(gy)) / 2.0)


def confidence_histogram(confidence) -> dict[str, int] | None:
    if confidence is None:
        return None
    import numpy as np

    return {str(i): int(np.count_nonzero(confidence == i)) for i in range(3)}


def classify_report(frames: list[dict[str, Any]], counters: dict[str, Any] | None) -> str:
    raw_deltas = [
        f.get("rawVsBaseline", {}).get("p95AbsDeltaMm")
        for f in frames
        if f.get("rawVsBaseline", {}).get("p95AbsDeltaMm") is not None
    ]
    smoothed_deltas = [
        f.get("smoothedVsBaseline", {}).get("p95AbsDeltaMm")
        for f in frames
        if f.get("smoothedVsBaseline", {}).get("p95AbsDeltaMm") is not None
    ]
    confidence = counters or {}
    confidence_frames = int(confidence.get("confidenceFramesAvailable") or 0)
    written = int(confidence.get("framesWritten") or 0)

    raw_available = any(f.get("rawDepth") is not None for f in frames)
    smoothed_available = any(f.get("smoothedDepth") is not None for f in frames)
    if not raw_available and smoothed_available:
        return "raw_depth_unavailable_smoothed_only"
    if confidence_frames == 0 and written > 0:
        return "uncertain_no_confidence_stream"
    if raw_deltas and max(raw_deltas) >= 5.0:
        if smoothed_deltas and max(smoothed_deltas) < max(raw_deltas) * 0.5:
            return "arkit_smoothing_likely"
        return "raw_depth_change_detected"
    if raw_deltas and max(raw_deltas) < 3.0:
        return "raw_depth_signal_too_small_or_missing"
    return "uncertain"


def make_contact_sheet(session_dir: Path, rows: list[dict[str, Any]], out_path: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    if not rows:
        return
    fig, axes = plt.subplots(len(rows), 4, figsize=(16, 4 * len(rows)))
    if len(rows) == 1:
        axes = np.array([axes])

    for r, row in enumerate(rows):
        panels = [
            ("RGB", row.get("rgb")),
            ("Raw depth", row.get("rawDepth")),
            ("Raw - baseline", row.get("rawDelta")),
            ("Confidence", row.get("confidence")),
        ]
        for c, (title, image) in enumerate(panels):
            ax = axes[r, c]
            ax.axis("off")
            ax.set_title(f"{title}\nframe {row['frameIndex']}")
            if image is None:
                ax.text(0.5, 0.5, "unavailable", ha="center", va="center")
                continue
            if title == "RGB":
                ax.imshow(image)
            elif title == "Confidence":
                im = ax.imshow(image, cmap="viridis", vmin=0, vmax=2)
                fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            else:
                finite = np.isfinite(image)
                if finite.any():
                    limit = float(np.nanpercentile(np.abs(image), 98)) if "baseline" in title else None
                    if limit and limit > 0:
                        im = ax.imshow(image, cmap="coolwarm", vmin=-limit, vmax=limit)
                    else:
                        im = ax.imshow(image, cmap="turbo")
                    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    plt.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def analyze(session_dir: Path) -> dict[str, Any]:
    import numpy as np

    manifest = load_manifest(session_dir)
    streams = manifest.get("v2Streams") or {}
    if manifest.get("captureFormat") != "v2_streams" and not streams:
        raise ValueError("Depth diagnostic analysis requires a v2_streams session")
    frames = load_jsonl(session_dir / streams.get("frameMetadataFile", "v2_frames.jsonl"))
    if not frames:
        raise ValueError("No v2 frame metadata found")

    indices = sorted(set([0, len(frames) // 2, len(frames) - 1]))
    baseline_raw = read_depth(session_dir, manifest, frames[0], "raw")
    baseline_smoothed = read_depth(session_dir, manifest, frames[0], "smoothed")
    reports: list[dict[str, Any]] = []
    contact_rows: list[dict[str, Any]] = []

    for idx in indices:
        entry = frames[idx]
        raw = read_depth(session_dir, manifest, entry, "raw")
        smoothed = read_depth(session_dir, manifest, entry, "smoothed")
        confidence = read_confidence(session_dir, manifest, entry)
        rgb = read_rgb(session_dir, manifest, entry)
        raw_delta = raw - baseline_raw if raw is not None and baseline_raw is not None else None

        frame_report = {
            "frameIndex": entry.get("frameIndex"),
            "arTimestamp": entry.get("arTimestamp"),
            "monotonicElapsedSeconds": entry.get("monotonicElapsedSeconds"),
            "rawDepth": depth_stats(raw) if raw is not None else None,
            "smoothedDepth": depth_stats(smoothed) if smoothed is not None else None,
            "rawVsBaseline": abs_delta_stats(raw, baseline_raw) if raw is not None and baseline_raw is not None else {},
            "smoothedVsBaseline": abs_delta_stats(smoothed, baseline_smoothed) if smoothed is not None and baseline_smoothed is not None else {},
            "rawVsSmoothed": abs_delta_stats(raw, smoothed) if raw is not None and smoothed is not None else {},
            "rawHighFrequencyEnergyMm": high_frequency_energy(raw) if raw is not None else None,
            "smoothedHighFrequencyEnergyMm": high_frequency_energy(smoothed) if smoothed is not None else None,
            "rgbEdgeEnergy": rgb_edge_energy(rgb),
            "confidenceHistogram": confidence_histogram(confidence),
        }
        reports.append(frame_report)
        contact_rows.append(
            {
                "frameIndex": entry.get("frameIndex"),
                "rgb": rgb,
                "rawDepth": raw,
                "rawDelta": raw_delta,
                "confidence": confidence,
            }
        )

    counters = (manifest.get("diagnostic") or {}).get("counters")
    report = {
        "sessionId": manifest.get("sessionId"),
        "captureFormat": manifest.get("captureFormat"),
        "diagnostic": manifest.get("diagnostic"),
        "analysisScope": "controlled_depth_diagnostic" if (manifest.get("diagnostic") or {}).get("enabled") else "standard_session_observation",
        "v2FrameCount": len(frames),
        "firstFrame": frames[0],
        "lastFrame": frames[-1],
        "sampledFrames": reports,
        "classification": classify_report(reports, counters),
        "interpretationRules": {
            "arkit_smoothing_likely": "Raw depth changes are much stronger than smoothed depth changes.",
            "raw_depth_signal_too_small_or_missing": "Raw depth deltas are below a few millimetres in sampled frames.",
            "raw_depth_change_detected": "Raw depth contains measurable geometry change; inspect contact sheet for trace shape.",
            "raw_depth_unavailable_smoothed_only": "The primary payload is labeled smoothedSceneDepth; no raw sceneDepth payload is available in this session.",
            "uncertain_no_confidence_stream": "Depth was captured, but confidence data is missing.",
        },
    }

    report_path = session_dir / "depth_diagnostic_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    make_contact_sheet(session_dir, contact_rows, session_dir / "depth_diagnostic_contactsheet.png")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a SandStories v2 depth diagnostic session")
    parser.add_argument("session_dir", type=Path, help="Folder containing manifest.json")
    args = parser.parse_args()

    try:
        report = analyze(args.session_dir.resolve())
    except (OSError, ValueError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"classification": report["classification"], "v2FrameCount": report["v2FrameCount"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
