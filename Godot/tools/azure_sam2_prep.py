#!/usr/bin/env python3
"""Prepare SAM2 inputs for the Azure pipeline: downscale rgb -> sam2_input
(320x288 numeric jpg, to fit the video predictor in 22 GB), and symlink
full-res rgb -> propainter_input (numeric jpg) for ProPainter."""
import sys, cv2, os
from pathlib import Path

work = Path(sys.argv[1])
sam2_in = work / "sam2_input"
pp_in = work / "propainter_input"
for d in (sam2_in, pp_in):
    if d.exists():
        raise FileExistsError(f"refusing to overwrite {d}")
    d.mkdir(parents=True)

n = 0
for f in sorted((work / "rgb").glob("frame_*.jpg")):
    num = int(f.stem.split("_")[1])
    img = cv2.imread(str(f))
    small = cv2.resize(img, (320, 288), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(sam2_in / f"{num:06d}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 95])
    os.symlink(str(f), pp_in / f"{num:06d}.jpg")
    n += 1
print(f"prepared {n} frames: sam2_input 320x288, propainter_input symlinks")
