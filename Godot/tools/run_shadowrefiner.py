#!/usr/bin/env python3
"""Run the official mask-free ShadowRefiner model on a frame sequence."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import torch
from PIL import Image
from torchvision.transforms.functional import pil_to_tensor, to_pil_image


def parse_indices(value: str) -> list[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError(f"invalid range: {item}")
            result.update(range(start, end + 1))
        else:
            result.add(int(item))
    if not result or min(result) < 0:
        raise argparse.ArgumentTypeError("indices must be non-negative")
    return sorted(result)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", type=parse_indices)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    import sys

    sys.path.insert(0, str(args.repo.resolve()))
    from model import final_net  # type: ignore[import-not-found]

    input_paths = sorted(
        path
        for path in args.input_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not input_paths:
        raise FileNotFoundError(f"no input images in {args.input_dir}")
    indices = args.frames or list(range(len(input_paths)))
    if indices[-1] >= len(input_paths):
        raise IndexError(
            f"frame {indices[-1]} outside {len(input_paths)} images"
        )

    removal_path = args.repo / "weights" / "shadowremoval.pkl"
    refinement_path = args.repo / "weights" / "refinement.pkl"
    model = final_net()
    model.remove_model.load_state_dict(
        torch.load(removal_path, map_location="cpu"),
        strict=True,
    )
    model.enhancement_model.load_state_dict(
        torch.load(refinement_path, map_location="cpu"),
        strict=True,
    )
    model = model.to(args.device).eval()

    records: list[dict[str, object]] = []
    with torch.inference_mode():
        for ordinal, frame_index in enumerate(indices, start=1):
            input_path = input_paths[frame_index]
            image = Image.open(input_path).convert("RGB")
            width, height = image.size
            if width % 32 or height % 32:
                raise ValueError(
                    f"{input_path.name} size {width}x{height} is not "
                    "divisible by 32"
                )
            tensor = pil_to_tensor(image).float().div_(255.0)[None].to(
                args.device
            )
            if args.device.startswith("cuda"):
                torch.cuda.synchronize()
            started = time.perf_counter()
            output = torch.clamp(model(tensor), 0.0, 1.0)
            if args.device.startswith("cuda"):
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - started
            output_path = args.output_dir / f"clean_rgb_{frame_index + 1:06d}.png"
            to_pil_image(output[0].cpu()).save(output_path)
            records.append(
                {
                    "frameIndex": frame_index,
                    "input": str(input_path),
                    "output": str(output_path),
                    "seconds": elapsed,
                    "inputSha256": file_sha256(input_path),
                    "outputSha256": file_sha256(output_path),
                }
            )
            print(
                f"{ordinal}/{len(indices)} frame={frame_index} "
                f"seconds={elapsed:.3f}",
                flush=True,
            )

    report = {
        "method": "official mask-free ShadowRefiner inference",
        "inputFrameCount": len(input_paths),
        "processedFrameCount": len(indices),
        "device": args.device,
        "repo": str(args.repo.resolve()),
        "weights": {
            "shadowremoval": {
                "file": str(removal_path.resolve()),
                "sha256": file_sha256(removal_path),
            },
            "refinement": {
                "file": str(refinement_path.resolve()),
                "sha256": file_sha256(refinement_path),
            },
        },
        "meanSecondsPerFrame": float(
            sum(float(record["seconds"]) for record in records) / len(records)
        ),
        "frames": records,
    }
    report_path = args.report or args.output_dir / "shadowrefiner_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
