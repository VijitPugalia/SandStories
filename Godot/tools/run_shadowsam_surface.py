#!/usr/bin/env python3
"""Probe official fine-tuned ShadowSAM with the registered sand-surface box."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image


def parse_indices(value: str) -> list[int]:
    result = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not result or result[0] < 0:
        raise argparse.ArgumentTypeError("frames must be non-negative")
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", type=parse_indices, required=True)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {args.output_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    import sys

    sys.path.insert(0, str(args.repo.resolve()))
    from sam import sam_model_registry  # type: ignore[import-not-found]
    from sam.utils.transforms import ResizeLongestSide  # type: ignore[import-not-found]

    input_paths = sorted(
        path
        for path in args.input_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if args.frames[-1] >= len(input_paths):
        raise IndexError(args.frames[-1])

    surface = np.asarray(Image.open(args.surface_mask).convert("L")) > 127
    ys, xs = np.nonzero(surface)
    surface_box = np.asarray(
        [[float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]],
        dtype=np.float32,
    )

    model = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint))
    model.to(device=args.device).eval()
    transform = ResizeLongestSide(model.image_encoder.img_size)
    records: list[dict[str, object]] = []
    with torch.inference_mode():
        for frame_index in args.frames:
            input_path = input_paths[frame_index]
            image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
            if image is None:
                raise FileNotFoundError(input_path)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            resized = transform.apply_image(image)
            tensor = torch.as_tensor(resized, device=args.device)
            tensor = tensor.permute(2, 0, 1).contiguous()[None]
            input_size = tuple(tensor.shape[-2:])
            original_size = image.shape[:2]
            input_tensor = model.preprocess(tensor)

            transformed_box = transform.apply_boxes(surface_box, original_size)
            box_tensor = torch.as_tensor(
                transformed_box,
                dtype=torch.float32,
                device=args.device,
            )[:, None, :]
            image_embedding = model.image_encoder(input_tensor)
            sparse, dense = model.prompt_encoder(
                points=None,
                boxes=box_tensor,
                masks=None,
            )
            low_res, predicted_iou = model.mask_decoder(
                image_embeddings=image_embedding,
                image_pe=model.prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse,
                dense_prompt_embeddings=dense,
                multimask_output=False,
            )
            logits = model.postprocess_masks(
                low_res,
                input_size,
                original_size,
            )[0, 0]
            probability = torch.sigmoid(logits).cpu().numpy()
            probability *= surface.astype(np.float32)
            output_path = (
                args.output_dir / f"shadow_probability_{frame_index + 1:06d}.png"
            )
            Image.fromarray(
                np.clip(np.round(probability * 255.0), 0, 255).astype(np.uint8),
                mode="L",
            ).save(output_path)
            records.append(
                {
                    "frameIndex": frame_index,
                    "input": str(input_path),
                    "output": str(output_path),
                    "predictedIou": float(predicted_iou[0, 0].cpu()),
                    "probabilityMean": float(np.mean(probability[surface])),
                    "areaAt05": float(np.mean(probability[surface] >= 0.5)),
                    "areaAt075": float(np.mean(probability[surface] >= 0.75)),
                }
            )
            print(json.dumps(records[-1]), flush=True)

    report = {
        "method": "official fine-tuned ShadowSAM with registered surface box",
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpointSha256": file_sha256(args.checkpoint),
        "surfaceMask": str(args.surface_mask.resolve()),
        "surfaceMaskSha256": file_sha256(args.surface_mask),
        "surfaceBoxXyxy": surface_box[0].tolist(),
        "frames": records,
    }
    (args.output_dir / "shadowsam_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
