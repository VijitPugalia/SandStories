#!/usr/bin/env python3
"""Build an RGB-aligned Kinect 2.5D hand surface on top of a v6b session.

The Grounded-SAM-2 actor pixels remain the authoritative visible silhouette.
Official libfreenect FREENECT_DEPTH_REGISTERED frames supply the observed hand
height above the stabilized sand reconstruction. The source RGB, stabilized
sand depth, and v6b RGBA overlays are linked byte-for-byte into a new session.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from materialize_topdown_virtual_hand_session import (
    PRESERVATION_MARKER,
    file_sha256,
    link_or_copy,
    load_binary_mask,
    load_json,
    rewrite_resource_paths,
    save_json,
    select_surface_actor,
    sequence_sha256,
)


DEFAULT_CONTACT_FRAMES = [82, 120, 177, 231, 297, 356, 400, 526, 604]


def read_registered_depth_mm(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        depth = np.asarray(image, dtype=np.uint16)
    # libfreenect's record/replay PGM payload is little-endian even though PGM
    # readers conventionally interpret 16-bit samples as big-endian.
    return depth.byteswap().astype(np.float32)


def godot_height_to_meters(
    height: np.ndarray,
    metric_low: float,
    metric_high: float,
) -> np.ndarray:
    normalized_height = np.clip(
        (height.astype(np.float32) / 255.0 - 0.14) / 0.78,
        0.0,
        1.0,
    )
    return metric_high - normalized_height * (metric_high - metric_low)


def finite_percentiles(
    values: np.ndarray,
    percentiles: list[float],
) -> list[float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return [0.0 for _ in percentiles]
    return [
        float(value)
        for value in np.percentile(finite, percentiles)
    ]


def robust_sand_bias_meters(
    stable_depth_m: np.ndarray,
    registered_depth_m: np.ndarray,
    registered_valid: np.ndarray,
    surface_mask: np.ndarray,
    selected_actor: np.ndarray,
    exclusion_radius: int,
) -> tuple[float, int]:
    excluded = ndimage.binary_dilation(
        selected_actor,
        iterations=max(0, exclusion_radius),
    )
    calibration = surface_mask & registered_valid & ~excluded
    if int(np.count_nonzero(calibration)) < 4096:
        calibration = surface_mask & registered_valid & ~selected_actor
    if not np.any(calibration):
        return 0.0, 0
    residual = stable_depth_m - registered_depth_m
    return float(np.median(residual[calibration])), int(
        np.count_nonzero(calibration)
    )


def reconstruct_lift(
    direct_lift_m: np.ndarray,
    direct_valid: np.ndarray,
    selected_actor: np.ndarray,
    fill_radius_pixels: float,
    smoothing_sigma: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lift = np.zeros(direct_lift_m.shape, dtype=np.float32)
    confidence = np.zeros(direct_lift_m.shape, dtype=np.float32)
    direct_flag = direct_valid.astype(np.float32)
    lift[direct_valid] = direct_lift_m[direct_valid]
    confidence[direct_valid] = 1.0

    if np.any(direct_valid) and fill_radius_pixels > 0.0:
        distance, indices = ndimage.distance_transform_edt(
            ~direct_valid,
            return_indices=True,
        )
        fill = (
            selected_actor
            & ~direct_valid
            & (distance <= fill_radius_pixels)
        )
        nearest_lift = direct_lift_m[
            indices[0],
            indices[1],
        ]
        lift[fill] = nearest_lift[fill]
        decay_scale = max(1.0, fill_radius_pixels * 0.5)
        confidence[fill] = (
            0.65 * np.exp(-distance[fill] / decay_scale)
        ).astype(np.float32)

    if smoothing_sigma > 0.0 and np.any(confidence > 0.0):
        numerator = ndimage.gaussian_filter(
            lift * confidence,
            sigma=smoothing_sigma,
            mode="nearest",
        )
        denominator = ndimage.gaussian_filter(
            confidence,
            sigma=smoothing_sigma,
            mode="nearest",
        )
        smoothed = np.divide(
            numerator,
            denominator,
            out=np.zeros_like(numerator),
            where=denominator > 1e-5,
        )
        lift[confidence > 0.0] = smoothed[confidence > 0.0]

    lift[~selected_actor] = 0.0
    confidence[~selected_actor] = 0.0
    direct_flag[~selected_actor] = 0.0
    return lift, confidence, direct_flag


def encode_geometry(
    lift_m: np.ndarray,
    confidence: np.ndarray,
    direct_flag: np.ndarray,
    max_lift_m: float,
) -> np.ndarray:
    geometry = np.zeros((*lift_m.shape, 3), dtype=np.uint8)
    geometry[:, :, 0] = np.round(
        np.clip(lift_m / max_lift_m, 0.0, 1.0) * 255.0
    ).astype(np.uint8)
    geometry[:, :, 1] = np.round(
        np.clip(confidence, 0.0, 1.0) * 255.0
    ).astype(np.uint8)
    geometry[:, :, 2] = np.round(
        np.clip(direct_flag, 0.0, 1.0) * 255.0
    ).astype(np.uint8)
    return geometry


def heatmap(values: np.ndarray, maximum: float) -> np.ndarray:
    normalized = np.clip(values / max(maximum, 1e-6), 0.0, 1.0)
    red = np.clip(normalized * 2.2, 0.0, 1.0)
    green = np.clip(1.7 - np.abs(normalized - 0.55) * 3.2, 0.0, 1.0)
    blue = np.clip(1.25 - normalized * 2.1, 0.0, 1.0)
    return np.round(
        np.dstack([red, green, blue]) * 255.0
    ).astype(np.uint8)


def make_contact_sheet(
    output_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    tiles: list[Image.Image] = []
    labels = ["raw RGB", "model actor", "registered depth", "measured lift"]
    for row in rows:
        images = [
            Image.fromarray(row["rgb"]).convert("RGB"),
            Image.fromarray(row["actor"]).convert("RGB"),
            Image.fromarray(row["registered"]).convert("RGB"),
            Image.fromarray(row["lift"]).convert("RGB"),
        ]
        width, height = images[0].size
        tile = Image.new(
            "RGB",
            (width * len(images), height + 48),
            (18, 18, 18),
        )
        draw = ImageDraw.Draw(tile)
        for column, (label, image) in enumerate(zip(labels, images)):
            x = column * width
            tile.paste(image, (x, 24))
            draw.text((x + 6, 6), label, fill=(245, 245, 245))
        draw.text((6, height + 29), row["caption"], fill=(245, 245, 245))
        tiles.append(tile)
    if not tiles:
        return
    sheet = Image.new(
        "RGB",
        (tiles[0].width, tiles[0].height * len(tiles)),
        (0, 0, 0),
    )
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (0, index * tile.height))
    sheet.save(output_path, format="PNG", optimize=True)


def parse_contact_frames(value: str) -> set[int]:
    if not value.strip():
        return set()
    return {
        int(item.strip())
        for item in value.split(",")
        if item.strip()
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-session", type=Path, required=True)
    parser.add_argument("--source-masks", type=Path, required=True)
    parser.add_argument("--registered-depth", type=Path, required=True)
    parser.add_argument("--source-appearance-session", type=Path)
    parser.add_argument("--output-session", type=Path, required=True)
    parser.add_argument(
        "--association-max-gap-pixels",
        type=float,
        default=26.0,
    )
    parser.add_argument(
        "--valid-depth-min-mm",
        type=float,
        default=250.0,
    )
    parser.add_argument(
        "--valid-depth-max-mm",
        type=float,
        default=1500.0,
    )
    parser.add_argument(
        "--sand-calibration-exclusion-pixels",
        type=int,
        default=24,
    )
    parser.add_argument(
        "--fill-radius-pixels",
        type=float,
        default=8.0,
    )
    parser.add_argument(
        "--smoothing-sigma",
        type=float,
        default=0.85,
    )
    parser.add_argument(
        "--max-lift-meters",
        type=float,
        default=0.36,
    )
    parser.add_argument(
        "--contact-frames",
        default=",".join(str(value) for value in DEFAULT_CONTACT_FRAMES),
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_session = args.source_session.resolve()
    source_masks = args.source_masks.resolve()
    registered_dir = args.registered_depth.resolve()
    appearance_session = (
        args.source_appearance_session.resolve()
        if args.source_appearance_session
        else None
    )
    output_session = args.output_session.resolve()
    if (output_session / PRESERVATION_MARKER).is_file():
        raise FileExistsError(
            "refusing to modify a preserved baseline; choose a new "
            f"--output-session instead: {output_session}"
        )
    if (
        output_session.exists()
        and any(output_session.iterdir())
        and not args.resume
    ):
        raise FileExistsError(
            f"refusing to overwrite non-empty output: {output_session}"
        )

    manifest = load_json(source_session / "processed_manifest.json")
    session = load_json(source_session / "session.json")
    frames = manifest.get("frames", [])
    if not isinstance(frames, list) or not frames:
        raise ValueError("source processed manifest has no frames")
    masks = sorted(source_masks.glob("*.png"))
    if len(masks) != len(frames):
        raise ValueError(
            f"mask/frame count mismatch: {len(masks)} vs {len(frames)}"
        )
    registered = sorted(
        registered_dir.glob("official_depth_registered_*.pgm")
    )
    if len(registered) not in {len(frames), len(frames) - 1}:
        raise ValueError(
            "registered-depth/frame count mismatch: "
            f"{len(registered)} vs {len(frames)}"
        )

    frame_size = manifest.get("frameSize", {})
    expected_size = (
        int(frame_size.get("width", 640)),
        int(frame_size.get("height", 480)),
    )
    with Image.open(source_session / str(manifest["surfaceMask"])) as image:
        if image.size != expected_size:
            raise ValueError("surface-mask dimensions do not match manifest")
        surface_mask = np.asarray(
            image.convert("L"),
            dtype=np.uint8,
        ) > 127

    completion = manifest.get("any2FullDepthCompletion", {})
    metric_range = completion.get(
        "metricDepthRange",
        [0.8128636457361647, 0.9216704175465102],
    )
    metric_low = float(metric_range[0])
    metric_high = float(metric_range[1])
    height_units_per_meter = (
        0.78 * 255.0 / (metric_high - metric_low)
    )
    max_lift_m = max(0.01, float(args.max_lift_meters))

    appearance_frames: list[dict[str, Any]] = []
    if appearance_session is not None:
        appearance_manifest = load_json(
            appearance_session / "processed_manifest.json"
        )
        appearance_frames = appearance_manifest.get("frames", [])
        if len(appearance_frames) != len(frames):
            raise ValueError(
                "appearance/source frame counts do not match: "
                f"{len(appearance_frames)} vs {len(frames)}"
            )

    output_session.mkdir(parents=True, exist_ok=True)
    source_name = source_session.name
    output_name = output_session.name
    skip = {
        PRESERVATION_MARKER,
        "session.json",
        "processed_manifest.json",
        "rgbd_virtual_hand_report.json",
        "rgbd_virtual_hand_contact_sheet.png",
    }
    for source in source_session.iterdir():
        if source.is_file() and source.name not in skip:
            destination = output_session / source.name
            if not destination.exists():
                link_or_copy(source, destination)

    output_frames = rewrite_resource_paths(
        frames,
        source_name,
        output_name,
    )
    geometry_paths: list[Path] = []
    frame_reports: list[dict[str, Any]] = []
    contact_rows: list[dict[str, Any]] = []
    contact_frames = parse_contact_frames(args.contact_frames)
    repeated_registered_frames: list[int] = []

    for index, (frame, mask_path) in enumerate(
        zip(output_frames, masks),
        start=1,
    ):
        registered_index = min(index, len(registered))
        if registered_index != index:
            repeated_registered_frames.append(index)
        registered_path = registered[registered_index - 1]
        registered_mm = read_registered_depth_mm(registered_path)
        if registered_mm.shape[::-1] != expected_size:
            raise ValueError(
                f"{registered_path} is {registered_mm.shape[::-1]}, "
                f"expected {expected_size}"
            )
        registered_m = registered_mm / 1000.0
        registered_valid = (
            (registered_mm > float(args.valid_depth_min_mm))
            & (registered_mm < float(args.valid_depth_max_mm))
        )

        union_mask = load_binary_mask(mask_path, expected_size)
        selected_actor, _, _, selected_area, _ = select_surface_actor(
            union_mask,
            surface_mask,
            float(args.association_max_gap_pixels),
        )
        depth_name = str(frame["cleanDepth"])
        with Image.open(output_session / depth_name) as image:
            stable_height = np.asarray(
                image.convert("L"),
                dtype=np.uint8,
            )
        stable_depth_m = godot_height_to_meters(
            stable_height,
            metric_low,
            metric_high,
        )
        correction_units = float(
            frame.get("baselineHeightCorrection", 0.0)
        )
        stable_depth_m -= correction_units / height_units_per_meter
        bias_m, calibration_pixels = robust_sand_bias_meters(
            stable_depth_m,
            registered_m,
            registered_valid,
            surface_mask,
            selected_actor,
            int(args.sand_calibration_exclusion_pixels),
        )
        residual_m = stable_depth_m - registered_m - bias_m
        direct_valid = selected_actor & registered_valid
        direct_lift_m = np.zeros(residual_m.shape, dtype=np.float32)
        direct_lift_m[direct_valid] = np.clip(
            residual_m[direct_valid],
            0.0,
            max_lift_m,
        )
        lift_m, confidence, direct_flag = reconstruct_lift(
            direct_lift_m,
            direct_valid,
            selected_actor,
            float(args.fill_radius_pixels),
            float(args.smoothing_sigma),
        )
        lift_m = np.clip(lift_m, 0.0, max_lift_m)
        geometry = encode_geometry(
            lift_m,
            confidence,
            direct_flag,
            max_lift_m,
        )
        geometry_name = f"virtual_hand_geometry_{index:06d}.png"
        geometry_path = output_session / geometry_name
        if not (args.resume and geometry_path.is_file()):
            Image.fromarray(geometry).save(
                geometry_path,
                format="PNG",
                optimize=True,
            )
        geometry_paths.append(geometry_path)
        frame["virtualHandGeometry"] = geometry_name

        selected_count = max(1, selected_area)
        direct_count = int(np.count_nonzero(direct_valid))
        reconstructed_count = int(
            np.count_nonzero(selected_actor & (confidence > 0.0))
        )
        positive = direct_lift_m[direct_valid]
        report_row = {
            "frame": index,
            "sourceRegisteredDepth": registered_path.name,
            "registeredDepthRepeated": registered_index != index,
            "selectedActorPixels": selected_area,
            "directMeasuredPixels": direct_count,
            "directMeasuredCoverage": direct_count / selected_count,
            "shortGapReconstructedPixels": (
                reconstructed_count - direct_count
            ),
            "geometryCoverage": reconstructed_count / selected_count,
            "sandBiasMillimeters": bias_m * 1000.0,
            "sandCalibrationPixels": calibration_pixels,
            "directLiftPercentilesMillimeters": [
                value * 1000.0
                for value in finite_percentiles(
                    positive,
                    [5.0, 25.0, 50.0, 75.0, 95.0],
                )
            ],
            "directPositiveLiftRatio": (
                float(np.mean(positive > 0.012))
                if positive.size
                else 0.0
            ),
        }
        frame_reports.append(report_row)

        if index in contact_frames:
            if appearance_frames:
                rgb_path = appearance_session / str(
                    appearance_frames[index - 1]["cleanRgb"]
                )
            else:
                rgb_path = output_session / str(frame["cleanRgb"])
            with Image.open(rgb_path) as image:
                rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
            actor = rgb.copy()
            actor[~selected_actor] = np.round(
                actor[~selected_actor].astype(np.float32) * 0.22
            ).astype(np.uint8)
            actor[selected_actor] = np.clip(
                actor[selected_actor].astype(np.float32) * 0.45
                + np.asarray([50.0, 225.0, 198.0]) * 0.55,
                0.0,
                255.0,
            ).astype(np.uint8)
            registered_view = heatmap(
                np.clip(1.0 - registered_m, 0.0, 0.5),
                0.5,
            )
            registered_view[~registered_valid] = 0
            lift_view = heatmap(lift_m, max_lift_m)
            lift_view[~selected_actor] = np.round(
                rgb[~selected_actor].astype(np.float32) * 0.18
            ).astype(np.uint8)
            contact_rows.append({
                "rgb": rgb,
                "actor": actor,
                "registered": registered_view,
                "lift": lift_view,
                "caption": (
                    f"frame {index}: direct "
                    f"{report_row['directMeasuredCoverage']:.1%}, "
                    f"geometry {report_row['geometryCoverage']:.1%}, "
                    f"median lift "
                    f"{report_row['directLiftPercentilesMillimeters'][2]:.0f} mm, "
                    f"sand bias {report_row['sandBiasMillimeters']:.1f} mm"
                ),
            })

    make_contact_sheet(
        output_session / "rgbd_virtual_hand_contact_sheet.png",
        contact_rows,
    )

    active_rows = [
        row for row in frame_reports
        if row["selectedActorPixels"] > 0
    ]
    coverage = np.asarray(
        [row["directMeasuredCoverage"] for row in active_rows],
        dtype=np.float64,
    )
    geometry_coverage = np.asarray(
        [row["geometryCoverage"] for row in active_rows],
        dtype=np.float64,
    )
    biases_mm = np.asarray(
        [row["sandBiasMillimeters"] for row in frame_reports],
        dtype=np.float64,
    )

    source_rgb = [
        source_session / str(frame["cleanRgb"])
        for frame in frames
    ]
    output_rgb = [
        output_session / str(frame["cleanRgb"])
        for frame in output_frames
    ]
    source_depth = [
        source_session / str(frame["cleanDepth"])
        for frame in frames
    ]
    output_depth = [
        output_session / str(frame["cleanDepth"])
        for frame in output_frames
    ]
    source_overlays = [
        source_session / str(frame["virtualHandOverlay"])
        for frame in frames
    ]
    output_overlays = [
        output_session / str(frame["virtualHandOverlay"])
        for frame in output_frames
    ]
    report = {
        "schemaVersion": 1,
        "method": (
            "official_libfreenect_registered_rgbd_measured_top_surface"
        ),
        "interpretation": (
            "RGB-aligned measured 2.5D top surface; not a closed or inferred "
            "full hand mesh"
        ),
        "sourceSession": str(source_session),
        "sourceMasks": str(source_masks),
        "registeredDepthSource": str(registered_dir),
        "frameCount": len(output_frames),
        "registeredDepthFrameCount": len(registered),
        "repeatedRegisteredDepthFrames": repeated_registered_frames,
        "activeActorFrameCount": len(active_rows),
        "maskPolicy": (
            "reuse the v6b Grounded-SAM-2 surface-associated actor pixels; "
            "no hand-authored mask and no image-position rule"
        ),
        "handAuthoredMasks": False,
        "imagePositionRules": False,
        "registeredDepthEncoding": {
            "source": "libfreenect FREENECT_DEPTH_REGISTERED PGM",
            "byteswapApplied": True,
            "units": "millimeters",
            "validRangeMillimeters": [
                float(args.valid_depth_min_mm),
                float(args.valid_depth_max_mm),
            ],
        },
        "sandReference": {
            "source": "stabilized Any2Full depth retained by v6b",
            "metricDepthRangeMeters": [metric_low, metric_high],
            "heightUnitsPerMeter": height_units_per_meter,
            "perFrameBiasMethod": (
                "median stable-minus-registered metric depth on visible sand "
                "outside a dilated actor exclusion"
            ),
            "actorExclusionPixels": int(
                args.sand_calibration_exclusion_pixels
            ),
            "biasMillimeters": {
                "median": float(np.median(biases_mm)),
                "p05": float(np.percentile(biases_mm, 5.0)),
                "p95": float(np.percentile(biases_mm, 95.0)),
            },
        },
        "geometryEncoding": {
            "filePattern": "virtual_hand_geometry_%06d.png",
            "red": f"reconstructed lift normalized to 0..{max_lift_m} meters",
            "green": (
                "measurement confidence: 1 direct, decayed for short-gap fill"
            ),
            "blue": "direct registered-depth measurement flag",
            "maxLiftMeters": max_lift_m,
            "shortGapFillRadiusPixels": float(args.fill_radius_pixels),
            "smoothingSigmaPixels": float(args.smoothing_sigma),
            "fallback": (
                "zero lift on stabilized sand where registered depth and "
                "short-gap support are unavailable"
            ),
        },
        "directMeasuredCoverageActiveFrames": {
            "median": float(np.median(coverage)) if coverage.size else 0.0,
            "p10": float(np.percentile(coverage, 10.0))
            if coverage.size else 0.0,
            "p90": float(np.percentile(coverage, 90.0))
            if coverage.size else 0.0,
        },
        "geometryCoverageActiveFrames": {
            "median": float(np.median(geometry_coverage))
            if geometry_coverage.size else 0.0,
            "p10": float(np.percentile(geometry_coverage, 10.0))
            if geometry_coverage.size else 0.0,
            "p90": float(np.percentile(geometry_coverage, 90.0))
            if geometry_coverage.size else 0.0,
        },
        "registeredDepthArchiveSha256": (
            "57c36a94034dc93f9601a98c243347b7beed687a338f50fe5a713aeafa4d4b8c"
        ),
        "geometrySequenceSha256": sequence_sha256(geometry_paths),
        "sourceRgbSequenceSha256": sequence_sha256(source_rgb),
        "outputRgbSequenceSha256": sequence_sha256(output_rgb),
        "sourceDepthSequenceSha256": sequence_sha256(source_depth),
        "outputDepthSequenceSha256": sequence_sha256(output_depth),
        "sourceOverlaySequenceSha256": sequence_sha256(source_overlays),
        "outputOverlaySequenceSha256": sequence_sha256(output_overlays),
        "frameReports": frame_reports,
    }
    report["rgbUnchanged"] = (
        report["sourceRgbSequenceSha256"]
        == report["outputRgbSequenceSha256"]
    )
    report["depthUnchanged"] = (
        report["sourceDepthSequenceSha256"]
        == report["outputDepthSequenceSha256"]
    )
    report["overlayUnchanged"] = (
        report["sourceOverlaySequenceSha256"]
        == report["outputOverlaySequenceSha256"]
    )
    if not (
        report["rgbUnchanged"]
        and report["depthUnchanged"]
        and report["overlayUnchanged"]
    ):
        raise RuntimeError("v6b RGB/depth/overlay identity gate failed")

    output_manifest = rewrite_resource_paths(
        manifest,
        source_name,
        output_name,
    )
    output_manifest["sessionId"] = output_name
    output_manifest["frames"] = output_frames
    output_manifest["rgbdVirtualHand"] = report
    save_json(output_session / "processed_manifest.json", output_manifest)

    output_session_json = rewrite_resource_paths(
        session,
        source_name,
        output_name,
    )
    output_session_json["id"] = output_name
    output_session_json["title"] = (
        str(session.get("title", "Kinect session"))
        + " + registered RGB-D measured hand surface"
    )
    data_sources = output_session_json.setdefault("data_sources", {})
    data_sources["virtual_hand_geometry"] = (
        "virtual_hand_geometry_000001.png"
    )
    data_sources["virtual_hand_max_lift_meters"] = max_lift_m
    data_sources["virtual_hand_world_units_per_meter"] = (
        0.78
        / (metric_high - metric_low)
        * abs(
            float(
                data_sources.get("calibration", {}).get(
                    "height_scale",
                    -5.0,
                )
            )
        )
        / 11.625
    )
    output_session_json.setdefault("production_session", {})[
        "rgbdVirtualHand"
    ] = report
    save_json(output_session / "session.json", output_session_json)
    save_json(
        output_session / "rgbd_virtual_hand_report.json",
        report,
    )
    print(json.dumps({
        "outputSession": str(output_session),
        "frameCount": len(output_frames),
        "activeActorFrameCount": len(active_rows),
        "directMeasuredCoverage": report[
            "directMeasuredCoverageActiveFrames"
        ],
        "geometryCoverage": report["geometryCoverageActiveFrames"],
        "sandBiasMillimeters": report["sandReference"][
            "biasMillimeters"
        ],
        "geometrySequenceSha256": report["geometrySequenceSha256"],
        "rgbUnchanged": report["rgbUnchanged"],
        "depthUnchanged": report["depthUnchanged"],
        "overlayUnchanged": report["overlayUnchanged"],
    }, indent=2))


if __name__ == "__main__":
    main()
