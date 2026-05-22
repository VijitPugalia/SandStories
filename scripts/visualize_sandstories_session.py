#!/usr/bin/env python3
"""
Visualize SandStories session: load manifest.json, decode 16-bit depth PNG to meters, show with RGB.

Usage:
  pip install numpy pillow matplotlib
  python visualize_sandstories_session.py "C:/path/to/session_UUID"
  python visualize_sandstories_session.py /path/to/session_UUID --frame 3 --save out.png
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


def depth_png_to_meters(path: Path, max_depth_m: float):
    """Return (meters_float32_HxW, valid_mask). 0 in PNG = invalid."""
    import numpy as np
    from PIL import Image

    img = Image.open(path)
    arr = np.array(img)
    if arr.dtype != np.uint16:
        # Some decoders may return uint8; warn
        if arr.dtype == np.uint8:
            raise ValueError(f"{path}: expected 16-bit PNG, got 8-bit")
        arr = arr.astype(np.uint16)
    raw = arr.astype(np.float32)
    meters = (raw / 65535.0) * float(max_depth_m)
    valid = raw > 0
    meters[~valid] = float("nan")
    return meters, valid


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize SandStories depth + RGB session")
    parser.add_argument("session_dir", type=Path, help="Folder containing manifest.json")
    parser.add_argument("--frame", type=int, default=0, help="Index into depthFrames/rgbFrames (0-based)")
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

    depth_info = manifest.get("depthEncoding") or {}
    max_m = float(depth_info.get("maxDepthMeters", 8.0))

    depth_frames = manifest.get("depthFrames") or []
    rgb_frames = manifest.get("rgbFrames") or []

    if not depth_frames:
        print("No depthFrames in manifest.", file=sys.stderr)
        return 1

    i = max(0, min(args.frame, len(depth_frames) - 1))
    d_entry = depth_frames[i]
    r_entry = rgb_frames[i] if i < len(rgb_frames) else None

    depth_rel = d_entry["relativePath"]
    depth_path = session_dir / depth_rel.replace("\\", "/")
    if not depth_path.is_file():
        print(f"Missing depth file: {depth_path}", file=sys.stderr)
        return 1

    meters, _ = depth_png_to_meters(depth_path, max_m)

    import numpy as np

    try:
        from PIL import Image
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2 if r_entry else 1, figsize=(12, 5))
        if r_entry is None:
            ax_d = axes
        else:
            ax_d, ax_rgb = axes

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

        for ax in (axes if r_entry else [axes]):
            ax.axis("off")

        plt.tight_layout()
        if args.save:
            plt.savefig(args.save, dpi=150, bbox_inches="tight")
            print(f"Wrote {args.save}")
        else:
            plt.show()
    except ImportError:
        print("Install: pip install numpy pillow matplotlib", file=sys.stderr)
        return 1

    return 0


def frame_label(entry: dict) -> str:
    return f"idx={entry.get('frameIndex')} ar_t={entry.get('arTimestamp', 0):.3f}s mono={entry.get('monotonicElapsedSeconds', 0):.3f}s"


if __name__ == "__main__":
    raise SystemExit(main())
