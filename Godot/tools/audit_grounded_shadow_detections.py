#!/usr/bin/env python3
"""Audit open-vocabulary Grounding DINO shadow detections on selected frames.

This tool intentionally stops at model detections.  It does not draw, extend,
clip, or replace any mask, and is used to choose whether a standard model is a
credible source of prompts for the downstream SAM 2 video segmenter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor


def parse_frames(value: str) -> list[int]:
    frames = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not frames or frames[0] < 0:
        raise argparse.ArgumentTypeError("frames must be non-negative integers")
    return frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--frames", type=parse_frames, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text", default="shadow.")
    parser.add_argument(
        "--grounding-model",
        default="IDEA-Research/grounding-dino-tiny",
    )
    parser.add_argument("--box-threshold", type=float, default=0.0)
    parser.add_argument("--text-threshold", type=float, default=0.0)
    args = parser.parse_args()

    if not args.text.islower() or not args.text.endswith("."):
        raise ValueError("--text must be lowercase and end with a period")

    image_paths = sorted(
        path
        for path in args.input_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if args.frames[-1] >= len(image_paths):
        raise IndexError(
            f"frame {args.frames[-1]} is outside {len(image_paths)} inputs"
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(args.grounding_model)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(
        args.grounding_model
    ).to(device)
    model.eval()

    records: list[dict[str, object]] = []
    for frame_index in args.frames:
        image_path = image_paths[frame_index]
        image = Image.open(image_path).convert("RGB")
        inputs = processor(
            images=image,
            text=args.text,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        result = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
            target_sizes=[image.size[::-1]],
        )[0]
        detections = []
        for score, label, box in zip(
            result["scores"],
            result["labels"],
            result["boxes"],
        ):
            detections.append(
                {
                    "label": str(label),
                    "score": float(score.cpu()),
                    "boxXyxy": [float(value) for value in box.cpu().tolist()],
                }
            )
        detections.sort(key=lambda item: float(item["score"]), reverse=True)
        records.append(
            {
                "frameIndex": frame_index,
                "file": image_path.name,
                "detections": detections,
            }
        )
        top_score = detections[0]["score"] if detections else None
        print(frame_index, image_path.name, top_score, flush=True)

    report = {
        "model": args.grounding_model,
        "text": args.text,
        "boxThreshold": args.box_threshold,
        "textThreshold": args.text_threshold,
        "device": device,
        "frameCount": len(records),
        "frames": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
