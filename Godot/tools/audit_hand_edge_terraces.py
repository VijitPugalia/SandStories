#!/usr/bin/env python3
"""Measure hand-contour-shaped depth terraces in reconstructed RGB-D sessions.

The ordinary whole-frame gradient score used by earlier reconstruction passes
can improve while a visually obvious hand-shaped depression remains.  This
audit instead samples depth profiles along the outward normal of the original
per-frame hand mask.  It reports repeated local troughs, their prominence, and
the contour-aligned (coherent) residual as a function of distance from the
hand edge.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.signal import find_peaks, savgol_filter


def parse_frames(value: str) -> list[int]:
    frames = sorted({int(item) for item in value.split(",") if item.strip()})
    if not frames or min(frames) < 1:
        raise argparse.ArgumentTypeError("frames must be one-indexed positive integers")
    return frames


def read_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(path)
    return image


def decode_rg16_metric(path: Path, metric_low: float, metric_high: float) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] < 3:
        raise FileNotFoundError(path)
    packed = (image[..., 2].astype(np.uint16) << 8) | image[..., 1].astype(np.uint16)
    normalized_height = packed.astype(np.float32) / 65535.0
    return metric_high - normalized_height * (metric_high - metric_low)


def load_session(session_dir: Path) -> tuple[dict[str, Any], np.ndarray, tuple[float, float]]:
    manifest = json.loads((session_dir / "processed_manifest.json").read_text("utf-8"))
    surface = read_gray(session_dir / manifest["surfaceMask"]) > 0
    metric_range = tuple(float(value) for value in manifest["metricDepthRange"])
    return manifest, surface, metric_range  # type: ignore[return-value]


def contour_samples(mask: np.ndarray, maximum: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mask_u8 = np.uint8(mask) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return (
            np.empty(0, np.float32),
            np.empty(0, np.float32),
            np.empty((0, 2), np.float32),
        )
    points = np.concatenate([contour[:, 0, :] for contour in contours], axis=0).astype(np.float32)
    if len(points) > maximum:
        selection = np.linspace(0, len(points) - 1, maximum, dtype=np.int32)
        points = points[selection]

    blurred = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2.2)
    grad_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    px = np.clip(np.rint(points[:, 0]).astype(np.int32), 0, mask.shape[1] - 1)
    py = np.clip(np.rint(points[:, 1]).astype(np.int32), 0, mask.shape[0] - 1)
    # The mask is one inside the hand, so the negative gradient points outward.
    normals = -np.column_stack((grad_x[py, px], grad_y[py, px]))
    magnitude = np.linalg.norm(normals, axis=1)
    valid = magnitude > 1e-4
    points = points[valid]
    normals = normals[valid] / magnitude[valid, None]
    return points[:, 0], points[:, 1], normals.astype(np.float32)


def sample_profiles(
    depth: np.ndarray,
    surface: np.ndarray,
    mask: np.ndarray,
    excluded: np.ndarray,
    radius: int,
    maximum_profiles: int,
) -> np.ndarray:
    x, y, normals = contour_samples(mask, maximum_profiles)
    if len(x) == 0:
        return np.empty((0, radius + 1), np.float32)
    distance = np.arange(radius + 1, dtype=np.float32)
    map_x = x[:, None] + normals[:, 0, None] * distance[None, :]
    map_y = y[:, None] + normals[:, 1, None] * distance[None, :]
    profiles = cv2.remap(
        depth,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=np.nan,
    )
    support = cv2.remap(
        np.uint8(surface & ~excluded),
        map_x,
        map_y,
        interpolation=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    ) > 0
    # Start two pixels outside the segmentation edge.  The exact edge is often
    # antialiased and is not the terrace ring the user is evaluating.
    valid = np.all(support[:, 2:], axis=1) & np.all(np.isfinite(profiles[:, 2:]), axis=1)
    return profiles[valid, 2:].astype(np.float32)


def persistent_change_support(
    session_dir: Path,
    manifest: dict[str, Any],
    metric_range: tuple[float, float],
    threshold_mm: float,
    margin: int,
    atlas_frames: int = 15,
) -> np.ndarray:
    """Find the intentional, persistent drawing so it is not scored as a terrace."""
    frame_count = len(manifest["frames"])
    atlas_frames = min(atlas_frames, max(frame_count // 3, 1))

    def atlas(indices: range) -> np.ndarray:
        samples = [
            decode_rg16_metric(
                session_dir / manifest["frames"][index]["cleanDepth"],
                metric_range[0],
                metric_range[1],
            )
            for index in indices
        ]
        return np.median(np.stack(samples), axis=0).astype(np.float32)

    before = atlas(range(atlas_frames))
    after = atlas(range(frame_count - atlas_frames, frame_count))
    changed = np.abs(after - before) * 1000.0 >= threshold_mm
    changed = cv2.morphologyEx(
        np.uint8(changed) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
    )
    if margin > 0:
        changed = cv2.dilate(
            changed,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (margin * 2 + 1, margin * 2 + 1)
            ),
        )
    return changed > 0


def profile_metrics(profiles: np.ndarray, prominence_mm: float) -> dict[str, Any]:
    if profiles.shape[0] == 0:
        return {
            "profileCount": 0,
            "multiTroughFraction": None,
            "prominenceP50Mm": None,
            "prominenceP95Mm": None,
            "peakToPeakP50Mm": None,
            "peakToPeakP95Mm": None,
            "coherentRingPeakMm": None,
            "normalGradientRmsMmPerPixel": None,
            "medianResidualMm": [],
        }

    width = profiles.shape[1]
    fine_window = min(width if width % 2 else width - 1, 9)
    broad_window = min(width if width % 2 else width - 1, 31)
    fine_window = max(fine_window, 5)
    broad_window = max(broad_window, fine_window + 2 + (fine_window % 2))
    if broad_window >= width:
        broad_window = width if width % 2 else width - 1
    fine = savgol_filter(profiles, fine_window, 2, axis=1, mode="interp")
    broad = savgol_filter(fine, broad_window, 2, axis=1, mode="interp")
    residual_mm = (fine - broad) * 1000.0

    trough_counts: list[int] = []
    maximum_prominence: list[float] = []
    for residual in residual_mm:
        _, properties = find_peaks(
            -residual,
            prominence=prominence_mm,
            distance=3,
        )
        prominences = properties.get("prominences", np.empty(0, np.float32))
        trough_counts.append(int(len(prominences)))
        maximum_prominence.append(float(np.max(prominences)) if len(prominences) else 0.0)

    maximum_prominence_array = np.asarray(maximum_prominence, np.float32)
    peak_to_peak = np.ptp(residual_mm, axis=1)
    median_residual = np.median(residual_mm, axis=0)
    normal_gradient = np.diff(fine * 1000.0, axis=1)
    return {
        "profileCount": int(len(profiles)),
        "multiTroughFraction": float(np.mean(np.asarray(trough_counts) >= 2)),
        "prominenceP50Mm": float(np.percentile(maximum_prominence_array, 50)),
        "prominenceP95Mm": float(np.percentile(maximum_prominence_array, 95)),
        "peakToPeakP50Mm": float(np.percentile(peak_to_peak, 50)),
        "peakToPeakP95Mm": float(np.percentile(peak_to_peak, 95)),
        "coherentRingPeakMm": float(np.max(np.abs(median_residual))),
        "normalGradientRmsMmPerPixel": float(np.sqrt(np.mean(normal_gradient**2))),
        "medianResidualMm": [round(float(value), 5) for value in median_residual],
    }


def aggregate(frame_reports: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_keys = [
        "multiTroughFraction",
        "prominenceP50Mm",
        "prominenceP95Mm",
        "peakToPeakP50Mm",
        "peakToPeakP95Mm",
        "coherentRingPeakMm",
        "normalGradientRmsMmPerPixel",
    ]
    output: dict[str, Any] = {
        "frameCount": len(frame_reports),
        "profileCount": int(sum(item["profileCount"] for item in frame_reports)),
    }
    for key in numeric_keys:
        values = [float(item[key]) for item in frame_reports if item[key] is not None]
        output[key + "MedianAcrossFrames"] = float(np.median(values)) if values else None
        output[key + "WorstFrame"] = float(np.max(values)) if values else None
    return output


def audit_session(
    session_dir: Path,
    manifest: dict[str, Any],
    metric_range: tuple[float, float],
    masks: dict[int, np.ndarray],
    surfaces: dict[int, np.ndarray],
    excluded: np.ndarray,
    profile_selection: dict[int, np.ndarray],
    frames: list[int],
    radius: int,
    maximum_profiles: int,
    prominence_mm: float,
) -> dict[str, Any]:
    frame_reports: list[dict[str, Any]] = []
    for frame_number in frames:
        frame_meta = manifest["frames"][frame_number - 1]
        depth = decode_rg16_metric(
            session_dir / frame_meta["cleanDepth"], metric_range[0], metric_range[1]
        )
        profiles = sample_profiles(
            depth,
            surfaces[frame_number],
            masks[frame_number],
            excluded,
            radius,
            maximum_profiles,
        )
        selection = profile_selection[frame_number]
        if len(profiles) != len(selection):
            raise ValueError(
                f"profile sampling differs at frame {frame_number}: "
                f"{len(profiles)} != {len(selection)}"
            )
        profiles = profiles[selection]
        metrics = profile_metrics(profiles, prominence_mm)
        metrics["frame"] = frame_number
        frame_reports.append(metrics)
    return {
        "session": str(session_dir.resolve()),
        "frames": frame_reports,
        "aggregate": aggregate(frame_reports),
    }


def ratio(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or abs(baseline) < 1e-8:
        return None
    return float(candidate / baseline)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_session", type=Path)
    parser.add_argument("candidate_sessions", type=Path, nargs="+")
    parser.add_argument("--frames", type=parse_frames, default=parse_frames("81,101,103,121,141,161,181,201"))
    parser.add_argument("--profile-radius", type=int, default=48)
    parser.add_argument("--maximum-profiles", type=int, default=900)
    parser.add_argument("--prominence-mm", type=float, default=0.20)
    parser.add_argument("--maximum-profile-range-mm", type=float, default=12.0)
    parser.add_argument(
        "--change-reference",
        type=Path,
        help="session whose persistent first/last change defines the intentional drawing; defaults to the last candidate",
    )
    parser.add_argument("--change-threshold-mm", type=float, default=2.0)
    parser.add_argument("--change-margin", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baseline_manifest, baseline_surface, baseline_range = load_session(args.baseline_session)
    frame_count = len(baseline_manifest["frames"])
    if max(args.frames) > frame_count:
        parser.error(f"frame selection exceeds baseline frame count {frame_count}")

    masks: dict[int, np.ndarray] = {}
    surfaces: dict[int, np.ndarray] = {}
    for frame_number in args.frames:
        frame_meta = baseline_manifest["frames"][frame_number - 1]
        masks[frame_number] = read_gray(
            args.baseline_session / frame_meta["persistenceMask"]
        ) > 0
        surfaces[frame_number] = baseline_surface

    change_reference_dir = args.change_reference or args.candidate_sessions[-1]
    change_manifest, _, change_range = load_session(change_reference_dir)
    if len(change_manifest["frames"]) != frame_count:
        raise ValueError(f"change reference frame count differs: {change_reference_dir}")
    excluded = persistent_change_support(
        change_reference_dir,
        change_manifest,
        change_range,
        args.change_threshold_mm,
        args.change_margin,
    )
    # Planarity is selected once from the change-reference geometry and then
    # reused for every session.  This keeps every comparison on the exact same
    # contour normals; a candidate cannot improve its score by filtering out a
    # different subset of difficult profiles.
    profile_selection: dict[int, np.ndarray] = {}
    for frame_number in args.frames:
        frame_meta = change_manifest["frames"][frame_number - 1]
        change_depth = decode_rg16_metric(
            change_reference_dir / frame_meta["cleanDepth"],
            change_range[0],
            change_range[1],
        )
        reference_profiles = sample_profiles(
            change_depth,
            baseline_surface,
            masks[frame_number],
            excluded,
            args.profile_radius,
            args.maximum_profiles,
        )
        profile_selection[frame_number] = (
            np.ptp(reference_profiles, axis=1) * 1000.0
            <= args.maximum_profile_range_mm
        )

    reports = [
        audit_session(
            args.baseline_session,
            baseline_manifest,
            baseline_range,
            masks,
            surfaces,
            excluded,
            profile_selection,
            args.frames,
            args.profile_radius,
            args.maximum_profiles,
            args.prominence_mm,
        )
    ]
    for candidate_dir in args.candidate_sessions:
        manifest, surface, metric_range = load_session(candidate_dir)
        if len(manifest["frames"]) != frame_count:
            raise ValueError(f"frame count differs: {candidate_dir}")
        candidate_surfaces = {frame: surface for frame in args.frames}
        reports.append(
            audit_session(
                candidate_dir,
                manifest,
                metric_range,
                masks,
                candidate_surfaces,
                excluded,
                profile_selection,
                args.frames,
                args.profile_radius,
                args.maximum_profiles,
                args.prominence_mm,
            )
        )

    baseline_aggregate = reports[0]["aggregate"]
    comparisons: list[dict[str, Any]] = []
    for report in reports[1:]:
        candidate_aggregate = report["aggregate"]
        comparisons.append(
            {
                "session": report["session"],
                "multiTroughFractionRatio": ratio(
                    candidate_aggregate["multiTroughFractionMedianAcrossFrames"],
                    baseline_aggregate["multiTroughFractionMedianAcrossFrames"],
                ),
                "prominenceP95Ratio": ratio(
                    candidate_aggregate["prominenceP95MmMedianAcrossFrames"],
                    baseline_aggregate["prominenceP95MmMedianAcrossFrames"],
                ),
                "coherentRingPeakRatio": ratio(
                    candidate_aggregate["coherentRingPeakMmMedianAcrossFrames"],
                    baseline_aggregate["coherentRingPeakMmMedianAcrossFrames"],
                ),
                "normalGradientRmsRatio": ratio(
                    candidate_aggregate["normalGradientRmsMmPerPixelMedianAcrossFrames"],
                    baseline_aggregate["normalGradientRmsMmPerPixelMedianAcrossFrames"],
                ),
            }
        )

    result = {
        "schemaVersion": 1,
        "method": "outward hand-contour normal depth profiles",
        "parameters": {
            "frames": args.frames,
            "profileRadiusPixels": args.profile_radius,
            "maximumProfilesPerFrame": args.maximum_profiles,
            "troughProminenceThresholdMm": args.prominence_mm,
            "maximumProfileRangeMm": args.maximum_profile_range_mm,
            "changeReference": str(change_reference_dir.resolve()),
            "changeThresholdMm": args.change_threshold_mm,
            "changeMarginPixels": args.change_margin,
            "excludedPersistentChangePixels": int(excluded.sum()),
        },
        "reports": reports,
        "comparisonsToBaseline": comparisons,
    }
    serialized = json.dumps(result, indent=2)
    print(serialized)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
