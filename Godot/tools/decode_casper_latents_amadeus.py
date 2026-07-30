#!/usr/bin/env python3
import argparse
import os
import sys

import torch


def parse_args():
    parser = argparse.ArgumentParser(
        description="Decode a saved CogVideoX-Fun latent tensor with the base VAE."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--latents", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", type=int, default=10)
    return parser.parse_args()


def main():
    args = parse_args()
    sys.path.insert(0, os.path.abspath(args.repo))

    from videox_fun.models import AutoencoderKLCogVideoX
    from videox_fun.utils.utils import save_videos_grid

    device = torch.device("cuda:0")
    vae = AutoencoderKLCogVideoX.from_pretrained(
        args.model,
        subfolder="vae",
    ).to(dtype=torch.float16, device=device)

    latents = torch.load(
        args.latents,
        map_location=device,
        weights_only=True,
    ).to(dtype=torch.float16)
    if latents.ndim != 5:
        raise ValueError(f"Expected a 5D latent tensor, got {tuple(latents.shape)}")

    with torch.inference_mode():
        latents = latents.permute(0, 2, 1, 3, 4)
        latents = latents / vae.config.scaling_factor
        frames = vae.decode(latents).sample
        frames = (frames / 2 + 0.5).clamp(0, 1).cpu().float()

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    save_videos_grid(frames, args.output, fps=args.fps)
    print(
        f"decoded={tuple(frames.shape)} output={args.output} "
        f"bytes={os.path.getsize(args.output)}"
    )


if __name__ == "__main__":
    main()
