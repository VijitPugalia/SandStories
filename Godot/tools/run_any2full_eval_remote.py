#!/usr/bin/env python3
"""Run and evaluate Any2Full on prepared sparse metric-depth anchors."""

from __future__ import annotations

import argparse
import json
import time
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import torch
from PIL import Image

# torchvision 0.16 imports torch.onnx, which imports current Transformers.
# Transformers >=4.57 calls the public PyTorch 2.2 pytree registration name,
# while the retained Any2Full CUDA environment uses PyTorch 2.1.  Both APIs
# have the same core contract here; the old private API simply has no
# serialized_type_name metadata argument.
if not hasattr(torch.utils._pytree, "register_pytree_node"):
    def _register_pytree_node_compat(
        typ,
        flatten_fn,
        unflatten_fn,
        *,
        serialized_type_name=None,
        **kwargs,
    ):
        del serialized_type_name
        return torch.utils._pytree._register_pytree_node(
            typ,
            flatten_fn,
            unflatten_fn,
            **kwargs,
        )

    torch.utils._pytree.register_pytree_node = _register_pytree_node_compat

from torchvision import transforms as vision_transforms

from model.ours.any2full import Any2Full


def load_model(encoder: str, checkpoint_path: Path, device: str) -> Any2Full:
    model_args = SimpleNamespace(
        stage=1,
        init_scailing=True,
        max_depth=1000.0,
        min_depth=1e-6,
    )
    model = Any2Full(encoder=encoder, da_ckpt_path=None, args=model_args)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    state = checkpoint.get("state_dict", checkpoint)
    cleaned = OrderedDict((key.replace("module.", ""), value) for key, value in state.items())
    model.load_state_dict(cleaned, strict=True)
    return model.to(device).eval()


def load_rgb(path: Path, device: str) -> torch.Tensor:
    image = Image.open(path).convert("RGB")
    transform = vision_transforms.Compose(
        [
            vision_transforms.ToTensor(),
            vision_transforms.Normalize(
                (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
            ),
        ]
    )
    return transform(image).unsqueeze(0).to(device)


def metric_to_godot_height(
    metric: np.ndarray,
    surface: np.ndarray,
    metric_low: float,
    metric_high: float,
) -> np.ndarray:
    normalized = np.clip((metric_high - metric) / (metric_high - metric_low), 0.0, 1.0)
    height = np.rint((0.14 + normalized * 0.78) * 255.0).astype(np.uint8)
    height[~surface] = 255
    return height


def frame_metrics(
    prediction: np.ndarray,
    reference: dict[str, np.ndarray],
    density: int,
) -> dict:
    metric = reference["metric"]
    surface = reference["surface"].astype(bool)
    quality = reference["quality"].astype(bool)
    anchors = reference[f"grid{density}"].astype(bool)
    holdout = quality & ~anchors
    anchor_error = prediction[anchors] - metric[anchors]
    holdout_error = prediction[holdout] - metric[holdout]
    quality_error = prediction[quality] - metric[quality]
    return {
        "anchorCount": int(np.count_nonzero(anchors)),
        "holdoutCount": int(np.count_nonzero(holdout)),
        "anchorMaeMeters": float(np.abs(anchor_error).mean()),
        "holdoutMaeMeters": float(np.abs(holdout_error).mean()),
        "holdoutRmseMeters": float(np.sqrt(np.square(holdout_error).mean())),
        "qualityMedianBiasMeters": float(np.median(quality_error)),
        "qualityP95AbsErrorMeters": float(np.percentile(np.abs(quality_error), 95)),
        "predictionSurfacePercentilesMeters": np.percentile(
            prediction[surface], [0, 2, 10, 50, 90, 98, 100]
        ).tolist(),
        "predictionSurfaceStdMeters": float(prediction[surface].std()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--any2full-root", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--encoder", choices=["vits", "vitb", "vitl"], required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path)
    parser.add_argument("--densities", default="4,6")
    parser.add_argument("--frames")
    parser.add_argument("--frame-start", type=int)
    parser.add_argument("--frame-end", type=int)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--metric-low", type=float, default=0.8128636457361647)
    parser.add_argument("--metric-high", type=float, default=0.9216704175465102)
    args = parser.parse_args()

    if args.metric_high <= args.metric_low:
        raise ValueError("--metric-high must be greater than --metric-low")

    if args.frames:
        frames = [int(value) for value in args.frames.split(",") if value.strip()]
    elif args.frame_start is not None and args.frame_end is not None:
        if args.frame_end < args.frame_start:
            raise ValueError("--frame-end must be >= --frame-start")
        frames = list(range(args.frame_start, args.frame_end + 1))
    else:
        parser.error("provide --frames or both --frame-start and --frame-end")
    densities = [int(value) for value in args.densities.split(",") if value.strip()]
    rgb_dir = args.rgb_dir if args.rgb_dir is not None else args.input_root / "rgb"
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    load_started = time.monotonic()
    model = load_model(args.encoder, args.checkpoint, args.device)
    load_seconds = time.monotonic() - load_started
    report = {
        "encoder": args.encoder,
        "repositoryCommit": "780edf6be2bf9260f1cce8e4ddbcb52d7bcdae9e",
        "checkpoint": str(args.checkpoint),
        "rgbDir": str(rgb_dir),
        "frames": frames,
        "densities": densities,
        "metricDepthRange": [args.metric_low, args.metric_high],
        "evaluationBoundary": "agreement with held-out quality-filtered sensor samples, not external ground truth",
        "loadSeconds": load_seconds,
        "results": {},
    }

    for density in densities:
        density_output = args.output_root / f"grid{density}"
        density_output.mkdir(parents=True, exist_ok=True)
        results = []
        for frame in frames:
            stem = f"frame_{frame:06d}"
            rgb = load_rgb(rgb_dir / f"{stem}.png", args.device)
            sparse = np.load(args.input_root / f"depth_grid{density}" / f"{stem}.npy")
            depth = torch.from_numpy(sparse).unsqueeze(0).unsqueeze(0).to(args.device)
            started = time.monotonic()
            with torch.inference_mode():
                prediction = model({"rgb": rgb, "dep": depth})["pred"]
            if args.device.startswith("cuda"):
                torch.cuda.synchronize()
            inference_seconds = time.monotonic() - started
            prediction_np = prediction[0, 0].float().cpu().numpy()
            with np.load(args.input_root / "reference" / f"{stem}.npz") as reference_npz:
                reference = {key: reference_npz[key] for key in reference_npz.files}
            metrics = frame_metrics(prediction_np, reference, density)
            metrics["frame"] = frame
            metrics["inferenceSeconds"] = inference_seconds
            results.append(metrics)
            np.save(density_output / f"{stem}.npy", prediction_np)
            godot_height = metric_to_godot_height(
                prediction_np,
                reference["surface"].astype(bool),
                args.metric_low,
                args.metric_high,
            )
            cv2.imwrite(
                str(density_output / f"{stem}_godot_height.png"), godot_height
            )
            print(json.dumps(metrics), flush=True)
        report["results"][f"grid{density}"] = results

    all_results = [
        item
        for density_results in report["results"].values()
        for item in density_results
    ]
    report["meanInferenceSeconds"] = float(
        np.mean([item["inferenceSeconds"] for item in all_results])
    )
    report["aggregate"] = {
        "meanHeldoutMaeMeters": float(np.mean([item["holdoutMaeMeters"] for item in all_results])),
        "meanHeldoutRmseMeters": float(np.mean([item["holdoutRmseMeters"] for item in all_results])),
        "meanQualityP95AbsErrorMeters": float(
            np.mean([item["qualityP95AbsErrorMeters"] for item in all_results])
        ),
        "maximumAbsoluteQualityMedianBiasMeters": float(
            np.max(np.abs([item["qualityMedianBiasMeters"] for item in all_results]))
        ),
    }
    report["peakGpuMemoryBytes"] = (
        int(torch.cuda.max_memory_allocated()) if args.device.startswith("cuda") else 0
    )
    report["peakGpuReservedBytes"] = (
        int(torch.cuda.max_memory_reserved()) if args.device.startswith("cuda") else 0
    )
    (args.output_root / "evaluation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
