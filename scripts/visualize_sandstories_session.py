#!/usr/bin/env python3
"""
Visualize a SandStories session.

Supports both legacy PNG sessions and v2 stream sessions:
  python scripts/visualize_sandstories_session.py /path/to/session --frame 0
  python scripts/visualize_sandstories_session.py /path/to/session --frame 4 --depth-source smoothed
  python scripts/visualize_sandstories_session.py /path/to/session --frame 4 --save frame_4.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_manifest(session_dir: Path) -> dict:
    p = session_dir / "manifest.json"
    if not p.is_file():
        raise FileNotFoundError(f"Missing manifest.json in {session_dir}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def depth_png_to_meters(path: Path, max_depth_m: float):
    """Return (meters_float32_HxW, valid_mask). 0 in PNG = invalid."""
    import numpy as np
    from PIL import Image

    img = Image.open(path)
    arr = np.array(img)
    if arr.dtype != np.uint16:
        if arr.dtype == np.uint8:
            raise ValueError(f"{path}: expected 16-bit PNG, got 8-bit")
        arr = arr.astype(np.uint16)
    raw = arr.astype(np.float32)
    meters = (raw / 65535.0) * float(max_depth_m)
    valid = raw > 0
    meters[~valid] = float("nan")
    return meters, valid


def read_stream_bytes(path: Path, offset: int, count: int) -> bytes:
    with path.open("rb") as f:
        f.seek(int(offset))
        data = f.read(int(count))
    if len(data) != int(count):
        raise ValueError(f"{path}: expected {count} bytes at {offset}, got {len(data)}")
    return data


def read_v2_depth(session_dir: Path, manifest: dict, entry: dict, source: str):
    import numpy as np

    streams = manifest.get("v2Streams") or {}
    selected_source = entry.get("selectedDepthSource")
    if source == "raw":
        if selected_source == "smoothedSceneDepth":
            raise ValueError("Selected frame stores smoothedSceneDepth as the primary payload; raw sceneDepth is unavailable")
        rel = streams.get("depthStreamPath", "streams/depth.f32")
        offset_key = "depthByteOffset"
        count_key = "depthByteCount"
        width = int(entry["width"])
        height = int(entry["height"])
    elif source == "smoothed":
        if entry.get("smoothedDepthByteOffset") is not None:
            rel = streams.get("smoothedDepthStreamPath", "streams/smoothed_depth.f32")
            offset_key = "smoothedDepthByteOffset"
            count_key = "smoothedDepthByteCount"
            width = int(entry.get("smoothedDepthWidth") or entry["width"])
            height = int(entry.get("smoothedDepthHeight") or entry["height"])
        elif selected_source == "smoothedSceneDepth":
            rel = streams.get("depthStreamPath", "streams/depth.f32")
            offset_key = "depthByteOffset"
            count_key = "depthByteCount"
            width = int(entry["width"])
            height = int(entry["height"])
        else:
            raise ValueError("Selected frame has no smoothed depth payload")
    else:
        raw = read_v2_depth(session_dir, manifest, entry, "raw")
        smoothed = read_v2_depth(session_dir, manifest, entry, "smoothed")
        return raw - smoothed

    data = read_stream_bytes(session_dir / rel, int(entry[offset_key]), int(entry[count_key]))
    arr = np.frombuffer(data, dtype="<f4")
    expected = width * height
    if arr.size != expected:
        raise ValueError(f"{rel}: frame has {arr.size} float32 values, expected {expected}")
    meters = arr.reshape((height, width)).astype("float32")
    meters[~np.isfinite(meters)] = np.nan
    meters[meters <= 0] = np.nan
    return meters


def read_v2_confidence(session_dir: Path, manifest: dict, entry: dict):
    import numpy as np

    if entry.get("confidenceByteOffset") is None or entry.get("confidenceByteCount") is None:
        return None
    streams = manifest.get("v2Streams") or {}
    rel = streams.get("confidenceStreamPath", "streams/confidence.bin")
    data = read_stream_bytes(session_dir / rel, int(entry["confidenceByteOffset"]), int(entry["confidenceByteCount"]))
    width = int(entry.get("confidenceWidth") or entry["width"])
    height = int(entry.get("confidenceHeight") or entry["height"])
    bytes_per_row = int(entry.get("confidenceBytesPerRow") or width)
    raw = np.frombuffer(data, dtype=np.uint8)
    if raw.size < height * bytes_per_row:
        return None
    return raw[: height * bytes_per_row].reshape((height, bytes_per_row))[:, :width]


def read_v2_rgb(session_dir: Path, manifest: dict, entry: dict):
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


def frame_label(entry: dict) -> str:
    return f"idx={entry.get('frameIndex')} ar_t={entry.get('arTimestamp', 0):.3f}s mono={entry.get('monotonicElapsedSeconds', 0):.3f}s"


def visualize_v2(session_dir: Path, manifest: dict, frame_index: int, depth_source: str, save: Path | None) -> int:
    import numpy as np
    import matplotlib.pyplot as plt

    streams = manifest.get("v2Streams") or {}
    frames = load_jsonl(session_dir / streams.get("frameMetadataFile", "v2_frames.jsonl"))
    if not frames:
        print("No v2 frame metadata found.", file=sys.stderr)
        return 1

    i = max(0, min(frame_index, len(frames) - 1))
    entry = frames[i]
    meters = read_v2_depth(session_dir, manifest, entry, depth_source)
    confidence = read_v2_confidence(session_dir, manifest, entry)
    rgb = read_v2_rgb(session_dir, manifest, entry)

    panels = 2 + (1 if confidence is not None else 0)
    fig, axes = plt.subplots(1, panels, figsize=(5 * panels, 5))
    if panels == 1:
        axes = [axes]

    ax_d = axes[0]
    finite = np.isfinite(meters)
    if finite.any():
        vmin = float(np.nanpercentile(meters, 2))
        vmax = float(np.nanpercentile(meters, 98))
    else:
        vmin, vmax = 0.0, 1.0
    im = ax_d.imshow(meters, cmap="turbo", vmin=vmin, vmax=vmax)
    ax_d.set_title(f"{depth_source} depth (m)\n{frame_label(entry)}")
    fig.colorbar(im, ax=ax_d, fraction=0.046, pad=0.04)

    ax_rgb = axes[1]
    if rgb is not None:
        ax_rgb.imshow(rgb)
        ax_rgb.set_title("RGB video frame")
    else:
        ax_rgb.text(0.5, 0.5, "RGB unavailable\ninstall opencv-python", ha="center", va="center")
        ax_rgb.set_title("RGB")

    if confidence is not None:
        ax_c = axes[2]
        ci = ax_c.imshow(confidence, cmap="viridis", vmin=0, vmax=2)
        ax_c.set_title("Depth confidence")
        fig.colorbar(ci, ax=ax_c, fraction=0.046, pad=0.04)

    for ax in axes:
        ax.axis("off")
    plt.tight_layout()
    if save:
        plt.savefig(save, dpi=150, bbox_inches="tight")
        print(f"Wrote {save}")
    else:
        plt.show()
    return 0


def visualize_legacy_png(session_dir: Path, manifest: dict, frame_index: int, save: Path | None) -> int:
    import numpy as np
    from PIL import Image
    import matplotlib.pyplot as plt

    depth_info = manifest.get("depthEncoding") or {}
    max_m = float(depth_info.get("maxDepthMeters", 8.0))
    depth_frames = manifest.get("depthFrames") or []
    rgb_frames = manifest.get("rgbFrames") or []
    if not depth_frames:
        print("No depthFrames in manifest.", file=sys.stderr)
        return 1

    i = max(0, min(frame_index, len(depth_frames) - 1))
    d_entry = depth_frames[i]
    r_entry = rgb_frames[i] if i < len(rgb_frames) else None
    depth_path = session_dir / d_entry["relativePath"].replace("\\", "/")
    if not depth_path.is_file():
        print(f"Missing depth file: {depth_path}", file=sys.stderr)
        return 1

    meters, _ = depth_png_to_meters(depth_path, max_m)
    fig, axes = plt.subplots(1, 2 if r_entry else 1, figsize=(12, 5))
    if r_entry is None:
        ax_d = axes
        axes_iter = [axes]
    else:
        ax_d, ax_rgb = axes
        axes_iter = axes

    im = ax_d.imshow(meters, cmap="turbo", vmin=np.nanmin(meters), vmax=np.nanmax(meters))
    ax_d.set_title(f"Depth (m), maxDepth={max_m}m\n{frame_label(d_entry)}")
    plt.colorbar(im, ax=ax_d, fraction=0.046, pad=0.04)

    if r_entry:
        rgb_path = session_dir / r_entry["relativePath"].replace("\\", "/")
        if rgb_path.is_file():
            rgb = np.array(Image.open(rgb_path).convert("RGB"))
            ax_rgb.imshow(rgb)
            ax_rgb.set_title(f"RGB\n{frame_label(r_entry)}")
        else:
            ax_rgb.set_title(f"RGB missing\n{r_entry.get('relativePath')}")

    for ax in axes_iter:
        ax.axis("off")
    plt.tight_layout()
    if save:
        plt.savefig(save, dpi=150, bbox_inches="tight")
        print(f"Wrote {save}")
    else:
        plt.show()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize SandStories depth + RGB session")
    parser.add_argument("session_dir", type=Path, help="Folder containing manifest.json")
    parser.add_argument("--frame", type=int, default=0, help="Index into saved frames (0-based)")
    parser.add_argument("--depth-source", choices=["raw", "smoothed", "delta"], default="raw", help="v2 stream depth source")
    parser.add_argument("--save", type=Path, default=None, help="Save figure to PNG instead of showing")
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    if not session_dir.is_dir():
        print(f"Not a directory: {session_dir}", file=sys.stderr)
        return 1

    try:
        manifest = load_manifest(session_dir)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    try:
        if manifest.get("captureFormat") == "v2_streams" or manifest.get("v2Streams"):
            return visualize_v2(session_dir, manifest, args.frame, args.depth_source, args.save)
        return visualize_legacy_png(session_dir, manifest, args.frame, args.save)
    except ImportError:
        print("Install: pip install numpy pillow matplotlib opencv-python", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
