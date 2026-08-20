#!/usr/bin/env python3
"""Remove broad cast shadows by reconstructing only low-frequency lighting.

The underlying high-frequency sand texture is retained.  A low-pass Lab
lightness image finds broad dark components; the corresponding low-frequency
linear-RGB illumination field is harmonically filled from the component
boundary; and only the multiplicative illumination ratio is applied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    phase = np.clip((values - edge0) / max(edge1 - edge0, 1.0e-6), 0.0, 1.0)
    return phase * phase * (3.0 - 2.0 * phase)


def srgb_to_linear(image: np.ndarray) -> np.ndarray:
    values = image.astype(np.float32) / 255.0
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


def linear_to_srgb(image: np.ndarray) -> np.ndarray:
    values = np.clip(image, 0.0, 1.0)
    encoded = np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * np.power(values, 1.0 / 2.4) - 0.055,
    )
    return np.uint8(np.clip(np.rint(encoded * 255.0), 0, 255))


def keep_large_components(mask: np.ndarray, minimum: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.uint8(mask) * 255, 8
    )
    output = np.zeros_like(mask, dtype=bool)
    for label_index in range(1, count):
        if int(stats[label_index, cv2.CC_STAT_AREA]) >= minimum:
            output |= labels == label_index
    return output


def label(image: np.ndarray, text: str) -> np.ndarray:
    output = image.copy()
    cv2.rectangle(output, (0, 0), (output.shape[1], 32), (0, 0, 0), -1)
    cv2.putText(
        output,
        text,
        (8, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return output


def correct_frame(
    bgr: np.ndarray,
    surface: np.ndarray,
    *,
    lowpass_sigma: float,
    close_size: int,
    support_threshold: float,
    matte_threshold: float,
    matte_softness: float,
    support_dilation: int,
    inpaint_radius: float,
    maximum_gain: float,
    strength: float,
    neutralize_albedo: bool,
    detail_sigma: float,
    analysis_scale: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = surface.shape
    analysis_width = max(32, int(round(width * analysis_scale)))
    analysis_height = max(32, int(round(height * analysis_scale)))
    analysis_surface = cv2.resize(
        np.uint8(surface) * 255,
        (analysis_width, analysis_height),
        interpolation=cv2.INTER_AREA,
    ) > 127
    yy, xx = np.mgrid[:analysis_height, :analysis_width]
    central = (
        ((xx - analysis_width * 0.50) / (analysis_width * 0.34)) ** 2
        + ((yy - analysis_height * 0.53) / (analysis_height * 0.34)) ** 2
    ) <= 1.0
    central &= analysis_surface

    lightness = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    lightness = cv2.resize(
        lightness,
        (analysis_width, analysis_height),
        interpolation=cv2.INTER_AREA,
    )
    low_lightness = cv2.GaussianBlur(
        lightness, (0, 0), max(lowpass_sigma * analysis_scale, 0.5)
    )
    analysis_close_size = max(3, int(round(close_size * analysis_scale)))
    if analysis_close_size % 2 == 0:
        analysis_close_size += 1
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (analysis_close_size, analysis_close_size)
    )
    expected = cv2.morphologyEx(low_lightness, cv2.MORPH_CLOSE, close_kernel)
    deficit = np.maximum(expected - low_lightness, 0.0)
    support = keep_large_components(
        (deficit >= support_threshold) & central,
        max(64, int(round(500 * analysis_scale * analysis_scale))),
    )
    if support_dilation > 0:
        analysis_dilation = max(1, int(round(support_dilation * analysis_scale)))
        support = cv2.dilate(
            np.uint8(support) * 255,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (analysis_dilation * 2 + 1,) * 2
            ),
        ) > 0
    support &= analysis_surface
    matte = smoothstep(matte_threshold, matte_threshold + matte_softness, deficit)
    matte *= support.astype(np.float32)
    matte = cv2.GaussianBlur(matte, (0, 0), max(5.0 * analysis_scale, 0.5))
    support = cv2.resize(
        np.uint8(support) * 255,
        (width, height),
        interpolation=cv2.INTER_NEAREST,
    ) > 0
    matte = cv2.resize(
        matte,
        (width, height),
        interpolation=cv2.INTER_LINEAR,
    )
    support &= surface
    matte *= surface.astype(np.float32)
    matte = np.clip(matte, 0.0, 1.0)

    linear = srgb_to_linear(bgr[..., ::-1])
    gain = np.ones_like(linear, np.float32)
    corrected_linear = linear.copy()
    if not neutralize_albedo:
        low_linear = cv2.GaussianBlur(linear, (0, 0), lowpass_sigma)
        repaired_low = low_linear.copy()
        full_close_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (close_size, close_size)
        )
        for channel in range(3):
            repaired_low[..., channel] = cv2.morphologyEx(
                low_linear[..., channel],
                cv2.MORPH_CLOSE,
                full_close_kernel,
            )
        gain = repaired_low / np.maximum(low_linear, 1.0e-5)
        gain = np.clip(gain, 1.0, maximum_gain)
        applied_gain = np.exp(np.log(gain) * matte[..., None] * strength)
        corrected_linear = linear * applied_gain
    if neutralize_albedo and support.any():
        wide = cv2.dilate(
            np.uint8(support) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (121, 121)),
        ) > 0
        narrow = cv2.dilate(
            np.uint8(support) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)),
        ) > 0
        ring = wide & ~narrow & surface
        if int(np.count_nonzero(ring)) < 1024:
            ring = surface & ~support
        ring_luma = np.sum(linear[ring] * np.asarray([0.2126, 0.7152, 0.0722]), axis=1)
        lower, upper = np.percentile(ring_luma, [35, 85])
        selected = ring.copy()
        full_luma = np.sum(linear * np.asarray([0.2126, 0.7152, 0.0722]), axis=2)
        selected &= (full_luma >= lower) & (full_luma <= upper)
        target_colour = np.median(linear[selected], axis=0)
        detail_base = cv2.GaussianBlur(linear, (0, 0), detail_sigma)
        detail = np.clip(linear / np.maximum(detail_base, 1.0e-5), 0.82, 1.18)
        rng = np.random.default_rng(173944)
        noise = rng.standard_normal(surface.shape).astype(np.float32)
        noise = cv2.GaussianBlur(noise, (0, 0), 0.75)
        noise /= max(float(np.std(noise[surface])), 1.0e-5)
        synthetic_albedo = (
            target_colour[None, None, :]
            * detail
            * np.exp(noise[..., None] * 0.012)
        )
        corrected_linear = (
            linear * (1.0 - matte[..., None])
            + synthetic_albedo * matte[..., None]
        )
    corrected = linear_to_srgb(corrected_linear)[..., ::-1]
    corrected[~surface] = bgr[~surface]
    return corrected, matte, gain


def parse_frames(value: str) -> list[int]:
    return sorted({int(item) for item in value.split(",") if item.strip()})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=parse_frames)
    parser.add_argument(
        "--review-frames", type=parse_frames,
        default=parse_frames("1,40,80,100,120,140,160,180,201"),
    )
    parser.add_argument("--lowpass-sigma", type=float, default=15.0)
    parser.add_argument("--close-size", type=int, default=121)
    parser.add_argument("--support-threshold", type=float, default=4.0)
    parser.add_argument("--matte-threshold", type=float, default=3.0)
    parser.add_argument("--matte-softness", type=float, default=13.0)
    parser.add_argument("--support-dilation", type=int, default=8)
    parser.add_argument("--inpaint-radius", type=float, default=45.0)
    parser.add_argument("--maximum-gain", type=float, default=3.0)
    parser.add_argument("--strength", type=float, default=1.0)
    parser.add_argument("--neutralize-albedo", action="store_true")
    parser.add_argument("--detail-sigma", type=float, default=5.0)
    parser.add_argument("--analysis-scale", type=float, default=0.5)
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to overwrite {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    matte_dir = args.output / "mattes"
    matte_dir.mkdir()
    manifest = json.loads(
        (args.session / "processed_manifest.json").read_text(encoding="utf-8")
    )
    frame_meta = manifest["frames"]
    surface = cv2.imread(
        str(args.session / manifest["surfaceMask"]), cv2.IMREAD_GRAYSCALE
    ) > 0
    targets = args.frames or list(range(1, len(frame_meta) + 1))
    review_rows: list[np.ndarray] = []
    records: list[dict[str, float | int]] = []
    for number in targets:
        meta = frame_meta[number - 1]
        source = cv2.imread(str(args.session / meta["cleanRgb"]), cv2.IMREAD_COLOR)
        corrected, matte, gain = correct_frame(
            source,
            surface,
            lowpass_sigma=args.lowpass_sigma,
            close_size=args.close_size,
            support_threshold=args.support_threshold,
            matte_threshold=args.matte_threshold,
            matte_softness=args.matte_softness,
            support_dilation=args.support_dilation,
            inpaint_radius=args.inpaint_radius,
            maximum_gain=args.maximum_gain,
            strength=args.strength,
            neutralize_albedo=args.neutralize_albedo,
            detail_sigma=args.detail_sigma,
            analysis_scale=args.analysis_scale,
        )
        stem = f"{number:06d}"
        cv2.imwrite(str(args.output / f"clean_rgb_{stem}.png"), corrected)
        cv2.imwrite(
            str(matte_dir / f"shadow_matte_{stem}.png"),
            np.uint8(np.clip(np.rint(matte * 255.0), 0, 255)),
        )
        changed = np.any(corrected != source, axis=2)
        records.append(
            {
                "frame": number,
                "mattePixels": int(np.count_nonzero(matte > 0.05)),
                "changedPixels": int(np.count_nonzero(changed)),
                "gainP95": float(np.percentile(gain[matte > 0.05], 95))
                if np.any(matte > 0.05)
                else 1.0,
            }
        )
        if number in args.review_frames:
            cells = [
                label(source, f"input {number}"),
                label(cv2.cvtColor(np.uint8(matte * 255), cv2.COLOR_GRAY2BGR), "matte"),
                label(corrected, "spatial intrinsic correction"),
            ]
            review_rows.append(
                np.hstack(
                    [
                        cv2.resize(cell, (320, 288), interpolation=cv2.INTER_AREA)
                        for cell in cells
                    ]
                )
            )
        print(f"wrote {number}/{len(frame_meta)}", flush=True)
    if review_rows:
        cv2.imwrite(str(args.output / "review.png"), np.vstack(review_rows))
    (args.output / "report.json").write_text(
        json.dumps(
            {
                "method": "spatial intrinsic low-frequency illumination repair",
                "parameters": vars(args) | {"session": str(args.session), "output": str(args.output)},
                "frames": records,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
