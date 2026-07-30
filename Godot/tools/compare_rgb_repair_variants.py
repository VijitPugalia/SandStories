#!/usr/bin/env python3
"""Render compact contact sheets for SandStories RGB repair variants."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


DEFAULT_RANGES = (
    ("early", (16, 24, 32, 40, 60, 80, 100, 120, 150, 170, 200)),
    ("mid", (240, 260, 280, 300, 320, 340, 360, 400)),
    ("late", (420, 440, 460, 480, 500, 520, 540, 560, 600, 620, 640, 660, 680, 713)),
)


def read_bgr(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def label(image: np.ndarray, text: str) -> np.ndarray:
    tile = cv2.resize(image, (320, 240), interpolation=cv2.INTER_AREA)
    cv2.rectangle(tile, (0, 0), (tile.shape[1], 24), (0, 0, 0), -1)
    cv2.putText(
        tile,
        text,
        (6, 17),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return tile


def parse_ranges(value: str) -> list[tuple[str, tuple[int, ...]]]:
    if not value.strip():
        return list(DEFAULT_RANGES)
    output: list[tuple[str, tuple[int, ...]]] = []
    for section in value.split(";"):
        tag, frame_text = section.split(":", 1)
        output.append(
            (
                tag.strip(),
                tuple(int(item) for item in frame_text.split(",") if item.strip()),
            )
        )
    return output


def candidate_path(root: Path, frame_index: int) -> Path:
    local = root / f"{frame_index:05d}.png"
    if local.exists():
        return local
    propainter = root / f"{frame_index:04d}.png"
    if propainter.exists():
        return propainter
    clean = root / f"clean_rgb_{frame_index + 1:06d}.png"
    if clean.exists():
        return clean
    raise FileNotFoundError(local)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-session", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--mask-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--baseline-label", default="v44")
    parser.add_argument("--ranges", default="")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    sources: list[tuple[str, Path | None]] = [("raw", args.raw_session)]
    if args.baseline_dir is not None:
        sources.append((args.baseline_label, args.baseline_dir))
    sources.extend((("mask", None), (args.candidate_label, args.candidate_dir)))

    for tag, frames in parse_ranges(args.ranges):
        rows: list[np.ndarray] = []
        for source_label, source_root in sources:
            tiles: list[np.ndarray] = []
            for frame_index in frames:
                raw_path = args.raw_session / f"clean_rgb_{frame_index + 1:06d}.png"
                raw = read_bgr(raw_path)
                if source_label == "mask":
                    mask_path = args.mask_dir / f"{frame_index:05d}.png"
                    mask = read_bgr(mask_path)[:, :, 0] > 0
                    image = raw.copy()
                    image[mask] = (
                        image[mask].astype(np.float32) * 0.35
                        + np.array([25.0, 25.0, 255.0], dtype=np.float32) * 0.65
                    ).astype(np.uint8)
                elif source_label == "raw":
                    image = raw
                elif source_root is not None:
                    image = read_bgr(candidate_path(source_root, frame_index))
                else:
                    raise AssertionError(source_label)
                tiles.append(label(image, f"{source_label} f{frame_index}"))
            rows.append(np.hstack(tiles))
        sheet = np.vstack(rows)
        destination = args.output_dir / f"{tag}.jpg"
        cv2.imwrite(
            str(destination),
            sheet,
            [int(cv2.IMWRITE_JPEG_QUALITY), 95],
        )
        print(destination, flush=True)


if __name__ == "__main__":
    main()
