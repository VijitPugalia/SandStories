#!/usr/bin/env python3
"""Train and run a sand-specific mask-free RGB-D cast-shadow remover.

Training pairs are generated only from automatically identified actor-free
surface frames.  Synthetic cast-shadow fields come from standard-model actor
silhouettes under randomized affine light projections and penumbra blur.  The
network predicts a smooth positive illumination gain instead of RGB pixels, so
it cannot redraw or inpaint sand texture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset


LUMA_WEIGHTS = torch.tensor([0.2126, 0.7152, 0.0722]).view(1, 3, 1, 1)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def srgb_to_linear(value: np.ndarray) -> np.ndarray:
    value = value.astype(np.float32) / 255.0
    return np.where(
        value <= 0.04045,
        value / 12.92,
        ((value + 0.055) / 1.055) ** 2.4,
    )


def linear_to_srgb(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    encoded = np.where(
        value <= 0.0031308,
        value * 12.92,
        1.055 * np.power(value, 1.0 / 2.4) - 0.055,
    )
    return np.clip(np.round(encoded * 255.0), 0, 255).astype(np.uint8)


def list_images(directory: Path, prefix: str = "") -> list[Path]:
    paths = sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
        and (not prefix or path.name.startswith(prefix))
    )
    if not paths:
        raise FileNotFoundError(directory)
    return paths


def derive_controls_and_casters(
    actor_mask_paths: list[Path],
    surface: np.ndarray,
) -> tuple[list[int], list[int], list[int]]:
    intersections: list[int] = []
    caster_indices: list[int] = []
    for index, path in enumerate(actor_mask_paths):
        actor = np.asarray(Image.open(path).convert("L")) > 0
        area = int(np.count_nonzero(actor & surface))
        intersections.append(area)
        if area > 128:
            caster_indices.append(index)

    prefix: list[int] = []
    for index, area in enumerate(intersections):
        if area != 0:
            break
        prefix.append(index)
    suffix: list[int] = []
    for index in range(len(intersections) - 1, -1, -1):
        if intersections[index] != 0:
            break
        suffix.append(index)
    suffix.reverse()
    if len(prefix) < 5 or len(suffix) < 5 or len(caster_indices) < 20:
        raise RuntimeError(
            f"insufficient automatic evidence: prefix={len(prefix)} "
            f"suffix={len(suffix)} casters={len(caster_indices)}"
        )
    return prefix, suffix, caster_indices


def normalize_depth(depth: np.ndarray, surface: np.ndarray) -> np.ndarray:
    valid = surface & (depth < 254)
    median = float(np.median(depth[valid]))
    scale = float(np.percentile(np.abs(depth[valid] - median), 90))
    normalized = np.clip((depth - median) / max(scale, 1.0), -2.0, 2.0)
    normalized[~surface] = 0.0
    return normalized.astype(np.float32)


class ConvBlock(nn.Module):
    def __init__(self, input_channels: int, output_channels: int) -> None:
        super().__init__()
        groups = min(8, output_channels)
        self.block = nn.Sequential(
            nn.Conv2d(input_channels, output_channels, 3, padding=1),
            nn.GroupNorm(groups, output_channels),
            nn.SiLU(inplace=True),
            nn.Conv2d(output_channels, output_channels, 3, padding=1),
            nn.GroupNorm(groups, output_channels),
            nn.SiLU(inplace=True),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.block(value)


class GainUNet(nn.Module):
    def __init__(self, base_channels: int = 32, maximum_log_gain: float = 0.92):
        super().__init__()
        self.maximum_log_gain = maximum_log_gain
        self.enc0 = ConvBlock(4, base_channels)
        self.enc1 = ConvBlock(base_channels, base_channels * 2)
        self.enc2 = ConvBlock(base_channels * 2, base_channels * 4)
        self.enc3 = ConvBlock(base_channels * 4, base_channels * 8)
        self.bottleneck = ConvBlock(base_channels * 8, base_channels * 16)
        self.dec3 = ConvBlock(base_channels * 24, base_channels * 8)
        self.dec2 = ConvBlock(base_channels * 12, base_channels * 4)
        self.dec1 = ConvBlock(base_channels * 6, base_channels * 2)
        self.dec0 = ConvBlock(base_channels * 3, base_channels)
        self.output = nn.Conv2d(base_channels, 1, 1)
        nn.init.zeros_(self.output.weight)
        nn.init.constant_(self.output.bias, -5.0)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        e0 = self.enc0(value)
        e1 = self.enc1(F.avg_pool2d(e0, 2))
        e2 = self.enc2(F.avg_pool2d(e1, 2))
        e3 = self.enc3(F.avg_pool2d(e2, 2))
        bottleneck = self.bottleneck(F.avg_pool2d(e3, 2))
        d3 = self.dec3(
            torch.cat(
                [
                    F.interpolate(
                        bottleneck,
                        size=e3.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    ),
                    e3,
                ],
                dim=1,
            )
        )
        d2 = self.dec2(
            torch.cat(
                [
                    F.interpolate(
                        d3,
                        size=e2.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    ),
                    e2,
                ],
                dim=1,
            )
        )
        d1 = self.dec1(
            torch.cat(
                [
                    F.interpolate(
                        d2,
                        size=e1.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    ),
                    e1,
                ],
                dim=1,
            )
        )
        d0 = self.dec0(
            torch.cat(
                [
                    F.interpolate(
                        d1,
                        size=e0.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    ),
                    e0,
                ],
                dim=1,
            )
        )
        return self.maximum_log_gain * torch.sigmoid(self.output(d0))


@dataclass
class SampleArrays:
    clean: np.ndarray
    depth: np.ndarray
    surface: np.ndarray
    caster: np.ndarray


class SyntheticShadowDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(
        self,
        rgb_paths: list[Path],
        depth_paths: list[Path],
        actor_mask_paths: list[Path],
        surface: np.ndarray,
        control_indices: list[int],
        caster_indices: list[int],
        *,
        patch_size: int,
        length: int,
        seed: int,
        deterministic: bool,
    ) -> None:
        self.clean_frames = [
            srgb_to_linear(np.asarray(Image.open(rgb_paths[index]).convert("RGB")))
            for index in control_indices
        ]
        self.depth_frames = [
            normalize_depth(
                np.asarray(Image.open(depth_paths[index]).convert("L"), dtype=np.float32),
                surface,
            )
            for index in control_indices
        ]
        self.caster_masks = [
            (
                np.asarray(Image.open(actor_mask_paths[index]).convert("L"))
                > 0
            ).astype(np.float32)
            for index in caster_indices
        ]
        self.surface = surface.astype(np.float32)
        self.patch_size = patch_size
        self.length = length
        self.seed = seed
        self.deterministic = deterministic

    def __len__(self) -> int:
        return self.length

    def _rng(self, index: int) -> np.random.Generator:
        if self.deterministic:
            return np.random.default_rng(self.seed + index * 7919)
        return np.random.default_rng(
            self.seed
            + index * 7919
            + random.randrange(0, 2**31 - 1)
        )

    def _project_shadow(
        self,
        caster: np.ndarray,
        rng: np.random.Generator,
    ) -> np.ndarray:
        height, width = caster.shape
        center = (width * 0.5, height * 0.5)
        angle = float(rng.uniform(-35.0, 35.0))
        scale = float(rng.uniform(0.65, 1.45))
        matrix = cv2.getRotationMatrix2D(center, angle, scale)
        matrix[0, 2] += float(rng.uniform(-0.30 * width, 0.30 * width))
        matrix[1, 2] += float(rng.uniform(-0.25 * height, 0.35 * height))
        projected = cv2.warpAffine(
            caster,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        sigma = float(rng.uniform(5.0, 32.0))
        projected = cv2.GaussianBlur(
            projected,
            (0, 0),
            sigmaX=sigma,
            sigmaY=sigma,
            borderType=cv2.BORDER_REPLICATE,
        )
        maximum = float(np.max(projected))
        if maximum > 1.0e-5:
            projected /= maximum
        return np.clip(projected * self.surface, 0.0, 1.0)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        rng = self._rng(index)
        clean_index = int(rng.integers(0, len(self.clean_frames)))
        caster_index = int(rng.integers(0, len(self.caster_masks)))
        clean = self.clean_frames[clean_index]
        depth = self.depth_frames[clean_index]
        shadow = self._project_shadow(self.caster_masks[caster_index], rng)
        if rng.random() < 0.30:
            second_index = int(rng.integers(0, len(self.caster_masks)))
            shadow = np.maximum(
                shadow,
                self._project_shadow(self.caster_masks[second_index], rng)
                * float(rng.uniform(0.45, 0.85)),
            )

        opacity = float(rng.uniform(0.22, 0.72))
        true_gain = opacity * shadow
        height, width = shadow.shape
        patch = self.patch_size
        ys, xs = np.nonzero(shadow > 0.08)
        if len(xs):
            pick = int(rng.integers(0, len(xs)))
            center_x, center_y = int(xs[pick]), int(ys[pick])
            x0 = int(
                np.clip(
                    center_x - rng.integers(patch // 4, 3 * patch // 4),
                    0,
                    width - patch,
                )
            )
            y0 = int(
                np.clip(
                    center_y - rng.integers(patch // 4, 3 * patch // 4),
                    0,
                    height - patch,
                )
            )
        else:
            x0 = int(rng.integers(0, width - patch + 1))
            y0 = int(rng.integers(0, height - patch + 1))
        selection = np.s_[y0 : y0 + patch, x0 : x0 + patch]
        clean_patch = clean[selection]
        depth_patch = depth[selection]
        surface_patch = self.surface[selection]
        gain_patch = true_gain[selection] * surface_patch

        color_attenuation = np.asarray(
            [
                rng.uniform(0.90, 1.08),
                rng.uniform(0.96, 1.04),
                rng.uniform(1.00, 1.12),
            ],
            dtype=np.float32,
        )
        shadowed_patch = clean_patch * np.exp(
            -gain_patch[..., None] * color_attenuation[None, None]
        )
        input_tensor = np.concatenate(
            [shadowed_patch, depth_patch[..., None]],
            axis=2,
        ).transpose(2, 0, 1)
        return {
            "input": torch.from_numpy(input_tensor.astype(np.float32)),
            "target": torch.from_numpy(
                clean_patch.transpose(2, 0, 1).astype(np.float32)
            ),
            "gain": torch.from_numpy(gain_patch[None].astype(np.float32)),
            "surface": torch.from_numpy(surface_patch[None].astype(np.float32)),
        }


def spatial_gradient(value: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    dx = value[..., :, 1:] - value[..., :, :-1]
    dy = value[..., 1:, :] - value[..., :-1, :]
    return dx, dy


def compute_loss(
    batch: dict[str, torch.Tensor],
    predicted_gain: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, float]]:
    shadowed = batch["input"][:, :3]
    target = batch["target"]
    true_gain = batch["gain"]
    surface = batch["surface"]
    corrected = torch.clamp(
        shadowed * torch.exp(predicted_gain),
        0.0,
        1.0,
    )
    denominator = torch.clamp(surface.sum() * 3.0, min=1.0)
    reconstruction = torch.sum(torch.abs(corrected - target) * surface) / denominator
    gain_loss = torch.sum(torch.abs(predicted_gain - true_gain) * surface) / torch.clamp(
        surface.sum(),
        min=1.0,
    )
    nonshadow = surface * (true_gain < 0.01).float()
    identity = torch.sum(predicted_gain * nonshadow) / torch.clamp(
        nonshadow.sum(),
        min=1.0,
    )
    corrected_luma = torch.sum(
        corrected * LUMA_WEIGHTS.to(corrected.device),
        dim=1,
        keepdim=True,
    )
    target_luma = torch.sum(
        target * LUMA_WEIGHTS.to(target.device),
        dim=1,
        keepdim=True,
    )
    corrected_dx, corrected_dy = spatial_gradient(corrected_luma)
    target_dx, target_dy = spatial_gradient(target_luma)
    gradient = (
        torch.mean(torch.abs(corrected_dx - target_dx))
        + torch.mean(torch.abs(corrected_dy - target_dy))
    )
    total = reconstruction + 0.55 * gain_loss + 0.25 * identity + 0.10 * gradient
    return total, {
        "loss": float(total.detach()),
        "reconstruction": float(reconstruction.detach()),
        "gain": float(gain_loss.detach()),
        "identity": float(identity.detach()),
        "gradient": float(gradient.detach()),
    }


def validate(
    model: nn.Module,
    loader: DataLoader[dict[str, torch.Tensor]],
    device: str,
) -> dict[str, float]:
    totals = {
        "loss": 0.0,
        "reconstruction": 0.0,
        "gain": 0.0,
        "identity": 0.0,
        "gradient": 0.0,
        "psnr": 0.0,
    }
    count = 0
    model.eval()
    with torch.inference_mode():
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            predicted = model(batch["input"])
            _, metrics = compute_loss(batch, predicted)
            corrected = torch.clamp(
                batch["input"][:, :3] * torch.exp(predicted),
                0.0,
                1.0,
            )
            mse = torch.mean((corrected - batch["target"]) ** 2)
            metrics["psnr"] = float(-10.0 * torch.log10(torch.clamp(mse, 1.0e-8)))
            for key in totals:
                totals[key] += metrics[key]
            count += 1
    return {key: value / max(count, 1) for key, value in totals.items()}


def common_sources(
    args: argparse.Namespace,
) -> tuple[list[Path], list[Path], list[Path], np.ndarray, list[int], list[int], list[int]]:
    rgb_paths = list_images(args.rgb_dir, args.rgb_prefix)
    depth_paths = list_images(args.depth_dir, args.depth_prefix)
    actor_mask_paths = list_images(args.actor_mask_dir)
    if not (len(rgb_paths) == len(depth_paths) == len(actor_mask_paths)):
        raise ValueError(
            f"counts differ rgb={len(rgb_paths)} depth={len(depth_paths)} "
            f"actor={len(actor_mask_paths)}"
        )
    surface = np.asarray(Image.open(args.surface_mask).convert("L")) > 127
    prefix, suffix, casters = derive_controls_and_casters(
        actor_mask_paths,
        surface,
    )
    return (
        rgb_paths,
        depth_paths,
        actor_mask_paths,
        surface,
        prefix,
        suffix,
        casters,
    )


def train(args: argparse.Namespace) -> None:
    (
        rgb_paths,
        depth_paths,
        actor_mask_paths,
        surface,
        prefix,
        suffix,
        casters,
    ) = common_sources(args)
    controls = prefix + suffix
    validation_controls = controls[::5]
    training_controls = [
        index for index in controls if index not in set(validation_controls)
    ]
    training_casters = casters[1::2]
    validation_casters = casters[::2]

    train_dataset = SyntheticShadowDataset(
        rgb_paths,
        depth_paths,
        actor_mask_paths,
        surface,
        training_controls,
        training_casters,
        patch_size=args.patch_size,
        length=args.steps * args.batch_size,
        seed=args.seed,
        deterministic=False,
    )
    validation_dataset = SyntheticShadowDataset(
        rgb_paths,
        depth_paths,
        actor_mask_paths,
        surface,
        validation_controls,
        validation_casters,
        patch_size=args.patch_size,
        length=args.validation_samples,
        seed=args.seed + 1000003,
        deterministic=True,
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.workers,
        pin_memory=True,
        persistent_workers=args.workers > 0,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=max(0, min(args.workers, 2)),
        pin_memory=True,
    )

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    model = GainUNet(
        base_channels=args.base_channels,
        maximum_log_gain=math.log(args.maximum_gain),
    ).to(args.device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        weight_decay=1.0e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=args.steps,
        eta_min=args.learning_rate * 0.05,
    )
    scaler = torch.cuda.amp.GradScaler(enabled=args.amp)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    best_psnr = -float("inf")
    history: list[dict[str, Any]] = []
    started = time.perf_counter()
    model.train()
    for step, batch in enumerate(train_loader, start=1):
        if step > args.steps:
            break
        batch = {key: value.to(args.device, non_blocking=True) for key, value in batch.items()}
        optimizer.zero_grad(set_to_none=True)
        with torch.cuda.amp.autocast(enabled=args.amp):
            predicted = model(batch["input"])
            loss, metrics = compute_loss(batch, predicted)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        if step == 1 or step % args.log_every == 0:
            elapsed = time.perf_counter() - started
            print(
                json.dumps(
                    {
                        "step": step,
                        "steps": args.steps,
                        "elapsedSeconds": elapsed,
                        "stepsPerSecond": step / max(elapsed, 1.0e-6),
                        "learningRate": optimizer.param_groups[0]["lr"],
                        **metrics,
                    }
                ),
                flush=True,
            )
        if step % args.validate_every == 0 or step == args.steps:
            validation = validate(model, validation_loader, args.device)
            record = {"step": step, **validation}
            history.append(record)
            print(json.dumps({"validation": record}), flush=True)
            if validation["psnr"] > best_psnr:
                best_psnr = validation["psnr"]
                torch.save(
                    {
                        "format": "sandstories_rgbd_shadow_gain_unet_v1",
                        "step": step,
                        "model": model.state_dict(),
                        "baseChannels": args.base_channels,
                        "maximumGain": args.maximum_gain,
                        "validation": validation,
                        "automaticControls": {
                            "prefix": prefix,
                            "suffix": suffix,
                            "training": training_controls,
                            "validation": validation_controls,
                        },
                        "casterCount": len(casters),
                        "sources": {
                            "rgbSequenceSha256": sequence_sha256(rgb_paths),
                            "depthSequenceSha256": sequence_sha256(depth_paths),
                            "actorMaskSequenceSha256": sequence_sha256(
                                actor_mask_paths
                            ),
                            "surfaceMaskSha256": file_sha256(args.surface_mask),
                        },
                        "arguments": vars(args),
                        "history": history,
                    },
                    args.output,
                )
                print(
                    json.dumps(
                        {
                            "saved": str(args.output),
                            "bestPsnr": best_psnr,
                            "step": step,
                        }
                    ),
                    flush=True,
                )
            model.train()


def infer(args: argparse.Namespace) -> None:
    (
        rgb_paths,
        depth_paths,
        _actor_mask_paths,
        surface,
        prefix,
        suffix,
        _casters,
    ) = common_sources(args)
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    model = GainUNet(
        base_channels=int(checkpoint["baseChannels"]),
        maximum_log_gain=math.log(float(checkpoint["maximumGain"])),
    )
    model.load_state_dict(checkpoint["model"], strict=True)
    model.to(args.device).eval()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    gain_dir = args.output_dir / "predicted_gain"
    gain_dir.mkdir()
    raw_gain_dir = args.output_dir / "raw_predicted_gain"
    if args.control_baseline:
        raw_gain_dir.mkdir()
    indices = (
        [int(item) for item in args.frames.split(",") if item.strip()]
        if args.frames
        else list(range(len(rgb_paths)))
    )
    surface_float = surface.astype(np.float32)

    def predict_gain(index: int) -> np.ndarray:
        source_u8 = np.asarray(Image.open(rgb_paths[index]).convert("RGB"))
        linear = srgb_to_linear(source_u8)
        depth = np.asarray(
            Image.open(depth_paths[index]).convert("L"),
            dtype=np.float32,
        )
        depth_normalized = normalize_depth(depth, surface)
        input_array = np.concatenate(
            [linear, depth_normalized[..., None]],
            axis=2,
        ).transpose(2, 0, 1)
        tensor = torch.from_numpy(input_array)[None].to(args.device)
        return model(tensor)[0, 0].cpu().numpy() * surface_float

    initial_control_upper: np.ndarray | None = None
    final_control_upper: np.ndarray | None = None
    if args.control_baseline:
        print(
            f"calibrating from automatic actor-free controls "
            f"prefix={prefix[0]}-{prefix[-1]} "
            f"suffix={suffix[0]}-{suffix[-1]}",
            flush=True,
        )
        with torch.inference_mode():
            initial_control_upper = np.percentile(
                np.stack([predict_gain(index) for index in prefix]),
                args.control_percentile,
                axis=0,
            ).astype(np.float32)
            final_control_upper = np.percentile(
                np.stack([predict_gain(index) for index in suffix]),
                args.control_percentile,
                axis=0,
            ).astype(np.float32)

    records = []
    with torch.inference_mode():
        for ordinal, index in enumerate(indices, start=1):
            source_u8 = np.asarray(Image.open(rgb_paths[index]).convert("RGB"))
            linear = srgb_to_linear(source_u8)
            raw_predicted_gain = predict_gain(index)
            predicted_gain = raw_predicted_gain
            if args.control_baseline:
                assert initial_control_upper is not None
                assert final_control_upper is not None
                sequence_alpha = index / max(len(rgb_paths) - 1, 1)
                control_upper = (
                    (1.0 - sequence_alpha) * initial_control_upper
                    + sequence_alpha * final_control_upper
                )
                predicted_gain = np.clip(
                    raw_predicted_gain - control_upper,
                    0.0,
                    None,
                )
                if index in prefix or index in suffix:
                    predicted_gain.fill(0.0)
            corrected = linear * np.exp(
                predicted_gain[..., None] * args.strength
            )
            output_u8 = linear_to_srgb(corrected)
            output_u8[~surface] = source_u8[~surface]
            output_path = args.output_dir / f"clean_rgb_{index + 1:06d}.png"
            Image.fromarray(output_u8, mode="RGB").save(output_path)
            gain_path = gain_dir / f"shadow_gain_{index + 1:06d}.png"
            gain_visual = np.clip(
                predicted_gain / math.log(float(checkpoint["maximumGain"])),
                0.0,
                1.0,
            )
            Image.fromarray(
                np.round(gain_visual * 255.0).astype(np.uint8),
                mode="L",
            ).save(gain_path)
            raw_gain_path: Path | None = None
            if args.control_baseline:
                raw_gain_path = (
                    raw_gain_dir / f"raw_shadow_gain_{index + 1:06d}.png"
                )
                raw_gain_visual = np.clip(
                    raw_predicted_gain
                    / math.log(float(checkpoint["maximumGain"])),
                    0.0,
                    1.0,
                )
                Image.fromarray(
                    np.round(raw_gain_visual * 255.0).astype(np.uint8),
                    mode="L",
                ).save(raw_gain_path)
            changed = np.any(output_u8 != source_u8, axis=2)
            record = {
                "frameIndex": index,
                "input": str(rgb_paths[index]),
                "output": str(output_path),
                "gain": str(gain_path),
                "rawGain": str(raw_gain_path) if raw_gain_path else None,
                "meanGain": float(np.mean(np.exp(predicted_gain[surface]))),
                "p99Gain": float(
                    np.percentile(np.exp(predicted_gain[surface]), 99)
                ),
                "changedPixels": int(np.count_nonzero(changed)),
                "outsideSurfaceChangedPixels": int(
                    np.count_nonzero(changed & ~surface)
                ),
            }
            records.append(record)
            print(
                f"{ordinal}/{len(indices)} {json.dumps(record)}",
                flush=True,
            )
    report = {
        "method": "sand-specific mask-free RGB-D positive illumination-gain U-Net",
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpointSha256": file_sha256(args.checkpoint),
        "checkpointValidation": checkpoint["validation"],
        "strength": args.strength,
        "controlBaseline": args.control_baseline,
        "controlPercentile": (
            args.control_percentile if args.control_baseline else None
        ),
        "automaticControls": (
            {"prefix": prefix, "suffix": suffix}
            if args.control_baseline
            else None
        ),
        "frames": records,
    }
    (args.output_dir / "inference_report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--actor-mask-dir", type=Path, required=True)
    parser.add_argument("--surface-mask", type=Path, required=True)
    parser.add_argument("--rgb-prefix", default="")
    parser.add_argument("--depth-prefix", default="clean_depth_")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train")
    add_common_arguments(train_parser)
    train_parser.add_argument("--output", type=Path, required=True)
    train_parser.add_argument("--device", default="cuda:0")
    train_parser.add_argument("--steps", type=int, default=6000)
    train_parser.add_argument("--batch-size", type=int, default=8)
    train_parser.add_argument("--patch-size", type=int, default=256)
    train_parser.add_argument("--base-channels", type=int, default=32)
    train_parser.add_argument("--maximum-gain", type=float, default=2.5)
    train_parser.add_argument("--learning-rate", type=float, default=2.0e-4)
    train_parser.add_argument("--workers", type=int, default=4)
    train_parser.add_argument("--validation-samples", type=int, default=128)
    train_parser.add_argument("--validate-every", type=int, default=500)
    train_parser.add_argument("--log-every", type=int, default=50)
    train_parser.add_argument("--seed", type=int, default=20260727)
    train_parser.add_argument("--amp", action="store_true")
    train_parser.set_defaults(function=train)

    infer_parser = subparsers.add_parser("infer")
    add_common_arguments(infer_parser)
    infer_parser.add_argument("--checkpoint", type=Path, required=True)
    infer_parser.add_argument("--output-dir", type=Path, required=True)
    infer_parser.add_argument("--device", default="cuda:0")
    infer_parser.add_argument("--frames", default="")
    infer_parser.add_argument("--strength", type=float, default=1.0)
    infer_parser.add_argument("--control-baseline", action="store_true")
    infer_parser.add_argument("--control-percentile", type=float, default=95.0)
    infer_parser.set_defaults(function=infer)

    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
