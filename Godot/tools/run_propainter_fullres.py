#!/usr/bin/env python3
"""Full-resolution (640x576) ProPainter via input-frame segmentation.

Segments <work>/rgb/ into chunks of <=SEG_LEN frames (OVERLAP overlap), runs
inference_propainter.py per segment at native resolution (no --resize_ratio),
then stitches outputs into <work>/display_rgb_full/frame_%06d.png.

Resume-aware: a per-segment .done marker is written only after the segment's
frames are stitched; on re-run, completed segments are skipped and failed ones
are redone from scratch.

Usage: run_propainter_fullres.py <session_work_dir> <gpu_id> [--seg-len N] [--overlap N]
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows can still inspect --help.
    resource = None

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("work", type=Path)
    ap.add_argument("gpu", type=str, default="0", nargs="?")
    ap.add_argument("--seg-len", type=int, default=500)
    ap.add_argument("--overlap", type=int, default=16)
    ap.add_argument("--seg-range", type=str, default="",
                    help="e.g. '1-1' to run only segment 1 (inclusive k range)")
    ap.add_argument(
        "--propainter-python",
        default=os.environ.get("PROPAINTER_PY"),
        help="ProPainter Python executable; defaults to PROPAINTER_PY",
    )
    ap.add_argument(
        "--propainter-root",
        type=Path,
        default=os.environ.get("PROPAINTER_ROOT"),
        help="ProPainter checkout; defaults to PROPAINTER_ROOT",
    )
    args = ap.parse_args()

    if not args.propainter_python:
        ap.error("set --propainter-python or PROPAINTER_PY")
    if args.propainter_root is None:
        ap.error("set --propainter-root or PROPAINTER_ROOT")

    if resource is not None:
        resource.setrlimit(resource.RLIMIT_NOFILE, (8192, 8192))

    work = args.work.resolve()
    seg_len, overlap = args.seg_len, args.overlap
    stride = seg_len - overlap
    rgb_dir = work / "rgb"
    mask_dir = work / "propainter_masks"
    out_dir = work / "display_rgb_full"
    run_root = work / "pp_seg_runs"
    out_root = work / "pp_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    frames = sorted(p.name for p in rgb_dir.glob("frame_*.jpg"))
    n = len(frames)
    if n == 0:
        print("no rgb frames", flush=True)
        return 1

    segs = []
    s = 1
    while s <= n:
        e = min(n, s + seg_len - 1)
        segs.append((len(segs) + 1, s, e))
        s += stride

    if args.seg_range:
        lo, hi = (int(x) for x in args.seg_range.split("-"))
        segs = [x for x in segs if lo <= x[0] <= hi]

    print(f"{n} frames -> plan {segs} (seg_len={seg_len} overlap={overlap})", flush=True)

    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = args.gpu

    for k, s, e in segs:
        done = work / f"pp_seg_{k}.done"
        if done.exists():
            print(f"skip seg {k} ({s}-{e}): done marker present", flush=True)
            continue
        segdir = run_root / f"pp_seg_{k}"
        segmask = run_root / f"pp_seg_{k}_masks"
        for d in (segdir, segmask):
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
        for g in range(s, e + 1):
            stem = f"{g:06d}"
            (segdir / f"frame_{stem}.jpg").symlink_to(rgb_dir / f"frame_{stem}.jpg")
            (segmask / f"{g - s + 1:06d}.png").symlink_to(mask_dir / f"{stem}.png")

        segout = out_root / f"pp_seg_{k}"
        if segout.exists():
            shutil.rmtree(segout)

        print(f"=== seg {k}: frames {s}-{e} ({e - s + 1}) gpu={args.gpu} start {__import__('datetime').datetime.now()}",
              flush=True)
        cmd = [args.propainter_python, "inference_propainter.py",
               "--video", str(segdir),
               "--mask", str(segmask),
               "--output", str(out_root),
               "--save_frames", "--fp16", "--mask_dilation", "4",
               "--ref_stride", "35", "--subvideo_length", "40"]
        try:
            subprocess.run(cmd, cwd=args.propainter_root, env=env, check=True)
        except subprocess.CalledProcessError as ex:
            print(f"seg {k} FAILED rc={ex.returncode}", flush=True)
            return ex.returncode

        frames_out = sorted((segout / "frames").glob("*.png"))
        if len(frames_out) != e - s + 1:
            print(f"seg {k} FAILED: expected {e - s + 1} output frames, got {len(frames_out)}", flush=True)
            return 1
        for i, f in enumerate(frames_out):
            shutil.copyfile(f, out_dir / f"frame_{s + i:06d}.png")
        print(f"--- seg {k}: stitched {len(frames_out)} frames -> {out_dir} end {__import__('datetime').datetime.now()}",
              flush=True)
        done.write_text("ok")
        shutil.rmtree(segout)
        for d in (segdir, segmask):
            shutil.rmtree(d)

    total = len(list(out_dir.glob("frame_*.png")))
    print(f"ALL DONE: {total} frames in {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
