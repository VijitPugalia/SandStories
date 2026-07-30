#!/usr/bin/env python3
"""Validate projected HaMeR meshes against measured Kinect RGB-D hand geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference-dir", type=Path, required=True)
    parser.add_argument("--rgbd-session", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-lift-meters", type=float, default=0.36)
    parser.add_argument("--minimum-lift-meters", type=float, default=0.005)
    return parser.parse_args()


def _rasterize_depth(
    uv: np.ndarray, depth: np.ndarray, faces: np.ndarray, width: int, height: int
) -> np.ndarray:
    """Rasterize the nearest triangle surface in camera-depth coordinates."""

    zbuffer = np.full((height, width), np.inf, dtype=np.float32)
    for face in faces:
        triangle = uv[face].astype(np.float32)
        triangle_depth = depth[face].astype(np.float32)
        if not np.isfinite(triangle).all() or not np.isfinite(triangle_depth).all():
            continue
        if np.any(triangle_depth <= 0.0):
            continue

        x0 = max(0, int(np.floor(triangle[:, 0].min())))
        x1 = min(width - 1, int(np.ceil(triangle[:, 0].max())))
        y0 = max(0, int(np.floor(triangle[:, 1].min())))
        y1 = min(height - 1, int(np.ceil(triangle[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue

        ax, ay = triangle[0]
        bx, by = triangle[1]
        cx, cy = triangle[2]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(float(denominator)) < 1e-6:
            continue

        grid_y, grid_x = np.mgrid[y0 : y1 + 1, x0 : x1 + 1]
        grid_x = grid_x.astype(np.float32) + 0.5
        grid_y = grid_y.astype(np.float32) + 0.5
        weight_a = (
            (by - cy) * (grid_x - cx) + (cx - bx) * (grid_y - cy)
        ) / denominator
        weight_b = (
            (cy - ay) * (grid_x - cx) + (ax - cx) * (grid_y - cy)
        ) / denominator
        weight_c = 1.0 - weight_a - weight_b
        inside = (
            (weight_a >= -1e-4)
            & (weight_b >= -1e-4)
            & (weight_c >= -1e-4)
        )
        if not inside.any():
            continue
        interpolated = (
            weight_a * triangle_depth[0]
            + weight_b * triangle_depth[1]
            + weight_c * triangle_depth[2]
        )
        target = zbuffer[y0 : y1 + 1, x0 : x1 + 1]
        update = inside & (interpolated < target)
        target[update] = interpolated[update]
    return zbuffer


def _percentiles(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {"p50": float("nan"), "p90": float("nan"), "p95": float("nan")}
    result = np.percentile(values, [50, 90, 95])
    return {"p50": float(result[0]), "p90": float(result[1]), "p95": float(result[2])}


def _fit_depth(
    mesh_depth: np.ndarray, measured_lift: np.ndarray, fit_mask: np.ndarray
) -> dict[str, Any]:
    z = mesh_depth[fit_mask].astype(np.float64)
    lift = measured_lift[fit_mask].astype(np.float64)
    if z.size < 50:
        raise ValueError(f"Only {z.size} RGB-D-supported mesh pixels")

    # MANO and HaMeR use metric model coordinates. Under a top-down camera,
    # closer mesh points have smaller camera Z and greater lift above the sand.
    fixed_offset = float(np.median(lift + z))
    fixed_prediction = fixed_offset - z
    fixed_residual_mm = (fixed_prediction - lift) * 1000.0

    design = np.column_stack([np.ones_like(z), z])
    affine_offset, affine_slope = np.linalg.lstsq(design, lift, rcond=None)[0]
    affine_prediction = affine_offset + affine_slope * z
    affine_residual_mm = (affine_prediction - lift) * 1000.0
    centered = lift - lift.mean()
    denominator = float(np.square(centered).sum())
    r_squared = (
        1.0 - float(np.square(affine_prediction - lift).sum()) / denominator
        if denominator > 1e-12
        else float("nan")
    )

    return {
        "samplePixels": int(z.size),
        "fixedMetric": {
            "model": "lift = offset - camera_z (MANO metric scale fixed at 1)",
            "offsetMeters": fixed_offset,
            "meanResidualMillimeters": float(fixed_residual_mm.mean()),
            "rmseMillimeters": float(np.sqrt(np.mean(np.square(fixed_residual_mm)))),
            "absoluteResidualMillimeters": _percentiles(
                np.abs(fixed_residual_mm)
            ),
        },
        "affineDiagnostic": {
            "model": "lift = offset + slope * camera_z",
            "offsetMeters": float(affine_offset),
            "slope": float(affine_slope),
            "impliedMetricScale": float(-affine_slope),
            "rSquared": r_squared,
            "rmseMillimeters": float(np.sqrt(np.mean(np.square(affine_residual_mm)))),
            "absoluteResidualMillimeters": _percentiles(
                np.abs(affine_residual_mm)
            ),
        },
    }


def _colorize(
    values: np.ndarray, mask: np.ndarray, maximum: float, colormap: int
) -> np.ndarray:
    normalized = np.zeros(values.shape, dtype=np.uint8)
    normalized[mask] = np.clip(
        np.rint(values[mask] / maximum * 255.0), 0, 255
    ).astype(np.uint8)
    color = cv2.applyColorMap(normalized, colormap)
    color[~mask] = 0
    return color


def _visualize(
    measured_lift: np.ndarray,
    direct_mask: np.ndarray,
    mesh_depth: np.ndarray,
    mesh_mask: np.ndarray,
    fit_mask: np.ndarray,
    fixed_offset: float,
    maximum_lift: float,
) -> np.ndarray:
    predicted_lift = fixed_offset - mesh_depth
    measured_panel = _colorize(
        measured_lift, direct_mask, maximum_lift, cv2.COLORMAP_TURBO
    )
    predicted_panel = _colorize(
        np.clip(predicted_lift, 0.0, maximum_lift),
        mesh_mask,
        maximum_lift,
        cv2.COLORMAP_TURBO,
    )
    residual = np.zeros_like(measured_lift)
    residual[fit_mask] = np.abs(predicted_lift[fit_mask] - measured_lift[fit_mask])
    residual_panel = _colorize(residual, fit_mask, 0.08, cv2.COLORMAP_INFERNO)

    mesh_contours, _ = cv2.findContours(
        mesh_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    for panel in (measured_panel, predicted_panel, residual_panel):
        cv2.drawContours(panel, mesh_contours, -1, (255, 255, 255), 1)
    return np.concatenate([measured_panel, predicted_panel, residual_panel], axis=1)


def _median(records: list[dict[str, Any]], path: tuple[str, ...]) -> float:
    values = []
    for record in records:
        value: Any = record
        for key in path:
            value = value[key]
        if np.isfinite(value):
            values.append(float(value))
    return float(np.median(values)) if values else float("nan")


def main() -> None:
    args = _parse_args()
    manifest_path = args.inference_dir / "hamer_inference_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for frame in manifest["frames"]:
        frame_index = int(frame["frameIndex"])
        arrays = np.load(args.inference_dir / frame["arrays"])
        geometry_path = (
            args.rgbd_session / f"virtual_hand_geometry_{frame_index:06d}.png"
        )
        geometry = cv2.imread(str(geometry_path), cv2.IMREAD_UNCHANGED)
        if geometry is None or geometry.ndim != 3 or geometry.shape[2] < 3:
            raise FileNotFoundError(f"Missing or invalid geometry image: {geometry_path}")
        height, width = geometry.shape[:2]

        measured_lift = (
            geometry[:, :, 2].astype(np.float32) / 255.0 * args.max_lift_meters
        )
        confidence = geometry[:, :, 1].astype(np.float32) / 255.0
        direct_mask = geometry[:, :, 0] >= 128
        support_mask = confidence > 0.0

        mesh_depth = _rasterize_depth(
            arrays["vertex_uv"],
            arrays["vertices_camera"][:, 2],
            arrays["faces"],
            width,
            height,
        )
        mesh_mask = np.isfinite(mesh_depth)
        fit_mask = (
            mesh_mask
            & direct_mask
            & (measured_lift >= args.minimum_lift_meters)
        )
        fit = _fit_depth(mesh_depth, measured_lift, fit_mask)
        fixed_offset = fit["fixedMetric"]["offsetMeters"]

        intersection_support = int(np.count_nonzero(mesh_mask & support_mask))
        intersection_direct = int(np.count_nonzero(mesh_mask & direct_mask))
        mesh_pixels = int(np.count_nonzero(mesh_mask))
        support_pixels = int(np.count_nonzero(support_mask))
        direct_pixels = int(np.count_nonzero(direct_mask))
        record = {
            "frameIndex": frame_index,
            "meshPixels": mesh_pixels,
            "rgbdSupportPixels": support_pixels,
            "directMeasuredPixels": direct_pixels,
            "meshCoveredByRgbdSupport": (
                intersection_support / mesh_pixels if mesh_pixels else 0.0
            ),
            "meshCoveredByDirectMeasurement": (
                intersection_direct / mesh_pixels if mesh_pixels else 0.0
            ),
            "rgbdSupportCoveredByMesh": (
                intersection_support / support_pixels if support_pixels else 0.0
            ),
            "depthFit": fit,
        }
        records.append(record)

        visualization = _visualize(
            measured_lift,
            direct_mask,
            mesh_depth,
            mesh_mask,
            fit_mask,
            fixed_offset,
            args.max_lift_meters,
        )
        output_image = args.output_dir / f"hamer_rgbd_validation_{frame_index:06d}.png"
        if not cv2.imwrite(str(output_image), visualization):
            raise RuntimeError(f"Failed to write {output_image}")
        print(
            f"frame {frame_index}: direct coverage "
            f"{record['meshCoveredByDirectMeasurement']:.3f}, "
            f"fixed RMSE {fit['fixedMetric']['rmseMillimeters']:.1f} mm"
        )

    report = {
        "schemaVersion": 1,
        "method": (
            "Z-buffer the projected HaMeR MANO surface, compare visible camera-Z "
            "against official registered Kinect lift on directly measured pixels"
        ),
        "inferenceManifest": str(manifest_path.resolve()),
        "rgbdSession": str(args.rgbd_session.resolve()),
        "maxLiftMeters": args.max_lift_meters,
        "minimumLiftMeters": args.minimum_lift_meters,
        "frameCount": len(records),
        "summaryMedian": {
            "meshCoveredByRgbdSupport": _median(
                records, ("meshCoveredByRgbdSupport",)
            ),
            "meshCoveredByDirectMeasurement": _median(
                records, ("meshCoveredByDirectMeasurement",)
            ),
            "fixedMetricRmseMillimeters": _median(
                records, ("depthFit", "fixedMetric", "rmseMillimeters")
            ),
            "fixedMetricP90AbsoluteResidualMillimeters": _median(
                records,
                (
                    "depthFit",
                    "fixedMetric",
                    "absoluteResidualMillimeters",
                    "p90",
                ),
            ),
            "affineImpliedMetricScale": _median(
                records, ("depthFit", "affineDiagnostic", "impliedMetricScale")
            ),
            "affineRmseMillimeters": _median(
                records, ("depthFit", "affineDiagnostic", "rmseMillimeters")
            ),
            "affineRSquared": _median(
                records, ("depthFit", "affineDiagnostic", "rSquared")
            ),
        },
        "frames": records,
    }
    report_path = args.output_dir / "hamer_rgbd_validation_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
