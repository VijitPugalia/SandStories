#!/usr/bin/env python3
"""Merge SAM2 pass-1 (hand. arm.) + pass-2 (arm.) masks and rebuild
propainter_masks at 640x576 with a vertical (downward) extension so the whole
hand+arm silhouette (incl. fingertips below the arm box) is covered.

Usage: merge_sam2_masks.py <session_work_dir>
"""
import sys
from pathlib import Path

import cv2
import numpy as np

VERT_EXT_PX = 17  # vertical extension at 320x288 scale (~34px at 640x576)


def main() -> int:
    work = Path(sys.argv[1]).resolve()
    p1 = work / "sam2_output" / "binary_masks"          # pass 1 (hand. arm.)
    p2 = work / "sam2_output_arm" / "binary_masks"       # pass 2 (arm.)
    dst = work / "propainter_masks"
    if dst.exists():
        raise FileExistsError(f"refusing to overwrite {dst}")
    dst.mkdir(parents=True)

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, VERT_EXT_PX * 2 + 1))
    n = 0
    for m1 in sorted(p1.glob("*.png")):
        a = cv2.imread(str(m1), cv2.IMREAD_GRAYSCALE) > 0
        bp = p2 / m1.name
        b = (cv2.imread(str(bp), cv2.IMREAD_GRAYSCALE) > 0) if bp.exists() else np.zeros_like(a)
        u = (a | b).astype(np.uint8) * 255
        # extend downward (arms enter from the top; swallows fingertips below the arm box)
        u = cv2.dilate(u, kern)
        big = cv2.resize(u, (640, 576), interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(dst / m1.name), big)
        n += 1
    print(f"merged {n} masks -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
