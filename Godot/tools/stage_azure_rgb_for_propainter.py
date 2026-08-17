#!/usr/bin/env python3
"""Stage clean_rgb PNGs from a processed session into a ProPainter input folder
(numbered 00001.png ...) so the frame order matches the mask folder."""
import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--rgb-output", type=Path, required=True)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=None)
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    out = args.rgb_output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    import json

    manifest = json.loads((session_dir / "processed_manifest.json").read_text(encoding="utf-8"))
    frames = manifest["frames"]
    if args.start_frame > 0:
        frames = frames[args.start_frame:]
    if args.max_frames is not None:
        frames = frames[: args.max_frames]

    for idx, frame in enumerate(frames, start=1):
        src = session_dir / frame["cleanRgb"]
        dst = out / f"{idx:05d}.png"
        if not src.exists():
            raise FileNotFoundError(src)
        shutil.copy2(src, dst)
    print(json.dumps({"staged": len(frames), "rgbDir": str(out)}))


if __name__ == "__main__":
    main()
