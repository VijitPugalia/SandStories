#!/usr/bin/env python3
"""Fuse a HaMeR MANO mesh with measured Kinect top-surface geometry.

HaMeR supplies the closed hand topology, pose, shape, and metric thickness.
The registered Kinect RGB-D reconstruction supplies the visible top-surface
height. Existing model landmarks may apply one bounded global 2D similarity
alignment, but they never replace or individually move the MANO joints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt

from validate_hamer_against_rgbd import _rasterize_depth


PALM_JOINTS = np.asarray([0, 5, 9, 13, 17], dtype=np.int32)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference-dir", type=Path, required=True)
    parser.add_argument("--rgbd-session", type=Path, required=True)
    parser.add_argument("--processed-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--surface-mask",
        type=Path,
        help=(
            "Static reconstructed-surface support mask. Defaults to "
            "<rgbd-session>/surface_mask.png. MANO vertices outside this "
            "support sample the nearest valid surface point instead of "
            "unmodelled background depth."
        ),
    )
    parser.add_argument("--plane-size", type=float, default=5.5)
    parser.add_argument("--max-lift-meters", type=float, default=0.36)
    parser.add_argument("--world-units-per-meter", type=float, default=3.0)
    parser.add_argument("--hand-clearance", type=float, default=0.006)
    parser.add_argument(
        "--sand-displacement-scale",
        type=float,
        default=1.0,
        help=(
            "Godot sand_depth.gdshader displacement_scale used by the target "
            "session; this must match calibration.height_scale"
        ),
    )
    parser.add_argument("--maximum-nearest-support-pixels", type=float, default=12.0)
    parser.add_argument("--thickness-scale", type=float, default=1.0)
    parser.add_argument("--maximum-thickness-meters", type=float, default=0.065)
    parser.add_argument(
        "--lift-fusion-mode",
        choices=("per_vertex", "mano_rigid_offset"),
        default="per_vertex",
        help=(
            "per_vertex follows each registered RGB-D sample; "
            "mano_rigid_offset uses the dominant visible RGB-D depth mode as "
            "one metric offset and preserves the continuous MANO surface"
        ),
    )
    parser.add_argument("--rgbd-anchor-bin-meters", type=float, default=0.010)
    parser.add_argument("--rgbd-anchor-radius-meters", type=float, default=0.030)
    parser.add_argument("--minimum-alignment-scale", type=float, default=0.70)
    parser.add_argument("--maximum-alignment-scale", type=float, default=1.45)
    parser.add_argument("--maximum-alignment-rotation-degrees", type=float, default=40.0)
    parser.add_argument(
        "--alignment-mode",
        choices=("rgbd_palm_rigid", "bounded_2d", "none"),
        default="rgbd_palm_rigid",
        help=(
            "rgbd_palm_rigid uses measured palm heights to remove monocular "
            "whole-hand tilt while preserving MANO metric scale"
        ),
    )
    parser.add_argument("--no-palm-alignment", action="store_true")
    parser.add_argument(
        "--skip-invalid-frames",
        action="store_true",
        help="Record and skip frames with insufficient RGB-D fusion support",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _dominant_depth_offset(
    offsets: np.ndarray,
    weights: np.ndarray,
    bin_width: float,
    inlier_radius: float,
) -> tuple[float, np.ndarray, dict[str, Any]]:
    if offsets.ndim != 1 or weights.shape != offsets.shape:
        raise ValueError("RGB-D anchor arrays must be matching 1D arrays")
    finite = np.isfinite(offsets) & np.isfinite(weights) & (weights > 0.0)
    if np.count_nonzero(finite) < 20:
        raise ValueError(
            f"Only {np.count_nonzero(finite)} finite RGB-D offset candidates"
        )
    if bin_width <= 0.0 or inlier_radius <= 0.0:
        raise ValueError("RGB-D anchor bin width and radius must be positive")

    valid_offsets = offsets[finite].astype(np.float64)
    valid_weights = weights[finite].astype(np.float64)
    lower = math.floor(float(valid_offsets.min()) / bin_width) * bin_width
    bins = np.floor((valid_offsets - lower) / bin_width).astype(np.int32)
    scores = np.bincount(bins, weights=valid_weights)
    winning_bin = int(np.argmax(scores))
    winning_center = lower + (winning_bin + 0.5) * bin_width
    seeded = np.abs(valid_offsets - winning_center) <= inlier_radius
    if np.count_nonzero(seeded) < 20:
        raise ValueError(
            f"Dominant RGB-D offset mode has only {np.count_nonzero(seeded)} samples"
        )

    center = float(np.median(valid_offsets[seeded]))
    selected_valid = np.abs(valid_offsets - center) <= inlier_radius
    center = float(np.median(valid_offsets[selected_valid]))
    inliers = np.zeros_like(finite)
    inliers[np.flatnonzero(finite)[selected_valid]] = True
    return center, inliers, {
        "candidateCount": int(np.count_nonzero(finite)),
        "inlierCount": int(np.count_nonzero(inliers)),
        "inlierRatio": float(np.count_nonzero(inliers) / np.count_nonzero(finite)),
        "binWidthMeters": float(bin_width),
        "inlierRadiusMeters": float(inlier_radius),
        "winningBinCenterMeters": float(winning_center),
        "cameraSandOffsetMeters": center,
    }


def _sample_bilinear(image: np.ndarray, xy: np.ndarray, border: float) -> np.ndarray:
    map_x = xy[:, 0].astype(np.float32).reshape(-1, 1)
    map_y = xy[:, 1].astype(np.float32).reshape(-1, 1)
    sampled = cv2.remap(
        image.astype(np.float32),
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=float(border),
    )
    return sampled[:, 0]


def _bounded_palm_similarity(
    joints: np.ndarray,
    landmarks: np.ndarray,
    minimum_scale: float,
    maximum_scale: float,
    maximum_rotation_degrees: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    source = joints[PALM_JOINTS].astype(np.float32)
    target = landmarks[PALM_JOINTS].astype(np.float32)
    before = float(np.sqrt(np.mean(np.square(source - target))))
    matrix, inliers = cv2.estimateAffinePartial2D(
        source,
        target,
        method=cv2.LMEDS,
        refineIters=10,
    )
    if matrix is None:
        matrix = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
        accepted = False
        reason = "estimation_failed"
    else:
        scale = float(math.hypot(matrix[0, 0], matrix[1, 0]))
        rotation = float(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
        accepted = (
            minimum_scale <= scale <= maximum_scale
            and abs(rotation) <= maximum_rotation_degrees
        )
        reason = "accepted" if accepted else "outside_bounds"
        if not accepted:
            matrix = np.asarray(
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64
            )
    transformed = cv2.transform(source[None, :, :], matrix)[0]
    after = float(np.sqrt(np.mean(np.square(transformed - target))))
    scale = float(math.hypot(matrix[0, 0], matrix[1, 0]))
    rotation = float(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    return matrix.astype(np.float32), {
        "accepted": accepted,
        "reason": reason,
        "matrix": matrix.tolist(),
        "scale": scale,
        "rotationDegrees": rotation,
        "translationPixels": [float(matrix[0, 2]), float(matrix[1, 2])],
        "palmRmsePixelsBefore": before,
        "palmRmsePixelsAfter": after,
        "inliers": (
            int(np.count_nonzero(inliers)) if inliers is not None else None
        ),
    }


def _unit_scale_palm_rigid_2d(
    joints: np.ndarray,
    landmarks: np.ndarray,
    maximum_rotation_degrees: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Align palm position/orientation in the image without changing hand size."""

    source = joints[PALM_JOINTS].astype(np.float32)
    target = landmarks[PALM_JOINTS].astype(np.float32)
    before = float(np.sqrt(np.mean(np.square(source - target))))
    estimated, inliers = cv2.estimateAffinePartial2D(
        source,
        target,
        method=cv2.LMEDS,
        refineIters=10,
    )
    if estimated is None:
        translation = target.mean(axis=0) - source.mean(axis=0)
        matrix = np.asarray(
            [
                [1.0, 0.0, translation[0]],
                [0.0, 1.0, translation[1]],
            ],
            dtype=np.float64,
        )
        accepted = False
        reason = "estimation_failed_translation_only"
        estimated_scale = 1.0
        rotation = 0.0
    else:
        estimated_scale = float(math.hypot(estimated[0, 0], estimated[1, 0]))
        rotation = float(
            math.degrees(math.atan2(estimated[1, 0], estimated[0, 0]))
        )
        accepted = abs(rotation) <= maximum_rotation_degrees
        reason = "accepted" if accepted else "rotation_outside_bounds"
        if accepted:
            radians = math.radians(rotation)
            rotation_matrix = np.asarray(
                [
                    [math.cos(radians), -math.sin(radians)],
                    [math.sin(radians), math.cos(radians)],
                ],
                dtype=np.float64,
            )
            translation = target.mean(axis=0) - rotation_matrix @ source.mean(axis=0)
            matrix = np.column_stack([rotation_matrix, translation])
        else:
            translation = target.mean(axis=0) - source.mean(axis=0)
            matrix = np.asarray(
                [
                    [1.0, 0.0, translation[0]],
                    [0.0, 1.0, translation[1]],
                ],
                dtype=np.float64,
            )
            reason = "rotation_outside_bounds_translation_only"
    transformed = cv2.transform(source[None, :, :], matrix)[0]
    after = float(np.sqrt(np.mean(np.square(transformed - target))))
    return matrix.astype(np.float32), {
        "accepted": accepted,
        "reason": reason,
        "matrix": matrix.tolist(),
        "scale": 1.0,
        "unconstrainedEstimatedScale": estimated_scale,
        "rotationDegrees": rotation if accepted else 0.0,
        "translationPixels": [float(matrix[0, 2]), float(matrix[1, 2])],
        "palmRmsePixelsBefore": before,
        "palmRmsePixelsAfter": after,
        "inliers": int(np.count_nonzero(inliers)) if inliers is not None else None,
    }


def _transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return cv2.transform(points.astype(np.float32)[None, :, :], matrix)[0]


def _rgbd_palm_rigid_refit(
    vertices_camera: np.ndarray,
    joints_camera: np.ndarray,
    landmarks: np.ndarray,
    measured_lift: np.ndarray,
    confidence: np.ndarray,
    support_distance: np.ndarray,
    support_nearest_indices: np.ndarray,
    maximum_support_distance: float,
    focal_length: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Fit one metric rigid transform from MANO palm joints to RGB-D palm points."""

    height, width = measured_lift.shape
    palm_xy = landmarks[PALM_JOINTS]
    rounded_x = np.rint(palm_xy[:, 0]).astype(np.int32)
    rounded_y = np.rint(palm_xy[:, 1]).astype(np.int32)
    inside = (
        (rounded_x >= 0)
        & (rounded_x < width)
        & (rounded_y >= 0)
        & (rounded_y < height)
    )
    clipped_x = np.clip(rounded_x, 0, width - 1)
    clipped_y = np.clip(rounded_y, 0, height - 1)
    distance = support_distance[clipped_y, clipped_x]
    nearest_y = support_nearest_indices[0, clipped_y, clipped_x]
    nearest_x = support_nearest_indices[1, clipped_y, clipped_x]
    valid = inside & (distance <= maximum_support_distance)
    if np.count_nonzero(valid) < 4:
        return vertices_camera, joints_camera, {
            "mode": "rgbd_palm_rigid",
            "accepted": False,
            "reason": "fewer_than_four_rgbd_supported_palm_points",
            "supportedPalmPoints": int(np.count_nonzero(valid)),
        }

    source = joints_camera[PALM_JOINTS][valid].astype(np.float64)
    valid_xy = palm_xy[valid].astype(np.float64)
    palm_lift = measured_lift[nearest_y[valid], nearest_x[valid]].astype(np.float64)
    weights = confidence[nearest_y[valid], nearest_x[valid]].astype(np.float64)
    weights = np.maximum(weights, 1e-3)
    weights /= weights.sum()

    # The camera's absolute sand distance is not measured, but the combination
    # joint_camera_z + surface_lift provides a robust per-frame estimate. The
    # resulting target points use the original HaMeR perspective calibration
    # and the Kinect lift only for relative metric depth.
    sand_camera_z = float(np.sum(weights * (source[:, 2] + palm_lift)))
    target_z = sand_camera_z - palm_lift
    target = np.column_stack(
        [
            (valid_xy[:, 0] - width * 0.5) * target_z / focal_length,
            (valid_xy[:, 1] - height * 0.5) * target_z / focal_length,
            target_z,
        ]
    )

    source_center = np.sum(source * weights[:, None], axis=0)
    target_center = np.sum(target * weights[:, None], axis=0)
    source_centered = source - source_center
    target_centered = target - target_center

    # Five palm points are close to planar, so an unconstrained Kabsch fit has
    # two nearly equivalent solutions and can flip the hand by ~180 degrees.
    # Estimate the two palm-plane normals and use only their minimum rotation.
    # This corrects the monocular out-of-plane tilt while retaining HaMeR's
    # in-plane articulation and its official MANO metric scale.
    source_covariance = (source_centered * weights[:, None]).T @ source_centered
    target_covariance = (target_centered * weights[:, None]).T @ target_centered
    _, source_vectors = np.linalg.eigh(source_covariance)
    _, target_vectors = np.linalg.eigh(target_covariance)
    source_normal = source_vectors[:, 0]
    target_normal = target_vectors[:, 0]
    if source_normal[2] < 0.0:
        source_normal *= -1.0
    if target_normal[2] < 0.0:
        target_normal *= -1.0
    if np.dot(source_normal, target_normal) < 0.0:
        target_normal *= -1.0

    axis = np.cross(source_normal, target_normal)
    sine = float(np.linalg.norm(axis))
    cosine = float(np.clip(np.dot(source_normal, target_normal), -1.0, 1.0))
    if sine < 1e-10:
        rotation_column = np.eye(3, dtype=np.float64)
    else:
        skew = np.asarray(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ],
            dtype=np.float64,
        )
        rotation_column = (
            np.eye(3, dtype=np.float64)
            + skew
            + skew @ skew * ((1.0 - cosine) / (sine * sine))
        )
    rotation = rotation_column.T
    translation = target_center - source_center @ rotation

    transformed_vertices = (
        vertices_camera.astype(np.float64) @ rotation + translation
    ).astype(np.float32)
    transformed_joints = (
        joints_camera.astype(np.float64) @ rotation + translation
    ).astype(np.float32)
    fitted = source @ rotation + translation
    before = np.sqrt(np.sum(np.square(source - target), axis=1))
    after = np.sqrt(np.sum(np.square(fitted - target), axis=1))
    rotation_angle = math.degrees(
        math.acos(np.clip((np.trace(rotation) - 1.0) * 0.5, -1.0, 1.0))
    )
    return transformed_vertices, transformed_joints, {
        "mode": "rgbd_palm_rigid",
        "accepted": True,
        "reason": "accepted",
        "supportedPalmPoints": int(np.count_nonzero(valid)),
        "rotationMatrix": rotation.tolist(),
        "rotationAngleDegrees": float(rotation_angle),
        "sourcePalmNormal": source_normal.tolist(),
        "targetPalmNormal": target_normal.tolist(),
        "translationMeters": translation.tolist(),
        "sandCameraDepthMeters": sand_camera_z,
        "palmRgbdLiftMeters": palm_lift.tolist(),
        "palmRmseMillimetersBefore": float(
            np.sqrt(np.sum(weights * np.square(before))) * 1000.0
        ),
        "palmRmseMillimetersAfter": float(
            np.sqrt(np.sum(weights * np.square(after))) * 1000.0
        ),
    }


def _manifest_by_clean_depth(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(frame["cleanDepth"]): frame for frame in payload["frames"]}


def _sand_surface_world_y(
    depth_path: Path,
    xy: np.ndarray,
    baseline_height_correction: float,
    displacement_scale: float = 1.0,
) -> np.ndarray:
    depth = cv2.imread(str(depth_path), cv2.IMREAD_GRAYSCALE)
    if depth is None:
        raise FileNotFoundError(depth_path)
    normalized = depth.astype(np.float32) / 255.0
    blurred = cv2.boxFilter(
        normalized,
        ddepth=-1,
        ksize=(3, 3),
        normalize=True,
        borderType=cv2.BORDER_REFLECT_101,
    )
    background = 1.0
    eps_0 = 0.08
    eps_1 = 0.415
    amount = np.clip(
        (np.abs(blurred - background) - eps_0) / (eps_1 - eps_0), 0.0, 1.0
    )
    amount = amount * amount * (3.0 - 2.0 * amount)
    checked = background * (1.0 - amount) + blurred * amount
    baseline_offset = float(baseline_height_correction) / 255.0
    surface = (
        -(checked + baseline_offset)
        / 11.625
        * float(displacement_scale)
    )
    return _sample_bilinear(surface, xy, border=-1.0 / 11.625)


def _nearest_valid_surface_coordinates(
    xy: np.ndarray,
    valid_surface: np.ndarray,
    nearest_indices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = valid_surface.shape
    rounded_x = np.rint(xy[:, 0]).astype(np.int32)
    rounded_y = np.rint(xy[:, 1]).astype(np.int32)
    inside = (
        (rounded_x >= 0)
        & (rounded_x < width)
        & (rounded_y >= 0)
        & (rounded_y < height)
    )
    clipped_x = np.clip(rounded_x, 0, width - 1)
    clipped_y = np.clip(rounded_y, 0, height - 1)
    direct = inside & valid_surface[clipped_y, clipped_x]
    sample_xy = xy.astype(np.float32).copy()
    invalid = ~direct
    sample_xy[invalid, 0] = nearest_indices[
        1,
        clipped_y[invalid],
        clipped_x[invalid],
    ]
    sample_xy[invalid, 1] = nearest_indices[
        0,
        clipped_y[invalid],
        clipped_x[invalid],
    ]
    distance = np.linalg.norm(sample_xy - xy, axis=1)
    return sample_xy, direct, distance.astype(np.float32)


def _vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices, dtype=np.float64)
    edges_a = vertices[faces[:, 1]] - vertices[faces[:, 0]]
    edges_b = vertices[faces[:, 2]] - vertices[faces[:, 0]]
    face_normals = np.cross(edges_a, edges_b)
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals /= np.maximum(lengths, 1e-12)
    return normals.astype(np.float32)


def _write_obj(
    path: Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    image_uv: np.ndarray,
    normals: np.ndarray,
    width: int,
    height: int,
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("mtllib hamer_rgbd_fused.mtl\n")
        stream.write(f"o {path.stem}\n")
        for vertex in vertices:
            stream.write(f"v {vertex[0]:.8f} {vertex[1]:.8f} {vertex[2]:.8f}\n")
        for uv in image_uv:
            stream.write(f"vt {uv[0] / width:.8f} {1.0 - uv[1] / height:.8f}\n")
        for normal in normals:
            stream.write(f"vn {normal[0]:.8f} {normal[1]:.8f} {normal[2]:.8f}\n")
        stream.write("usemtl HamerRgbdHand\n")
        for face in faces + 1:
            stream.write(
                "f "
                + " ".join(f"{index}/{index}/{index}" for index in face)
                + "\n"
            )


def _percentiles(values: np.ndarray, q: tuple[float, ...]) -> list[float]:
    if values.size == 0:
        return [float("nan")] * len(q)
    return [float(value) for value in np.percentile(values, q)]


def main() -> None:
    args = _parse_args()
    args.rgbd_session = args.rgbd_session.resolve()
    args.processed_manifest = args.processed_manifest.resolve()
    args.output_dir = args.output_dir.resolve()
    surface_mask_path = (
        args.surface_mask.resolve()
        if args.surface_mask is not None
        else args.rgbd_session / "surface_mask.png"
    )
    surface_mask_image = cv2.imread(
        str(surface_mask_path),
        cv2.IMREAD_GRAYSCALE,
    )
    if surface_mask_image is None:
        raise FileNotFoundError(surface_mask_path)
    valid_surface = surface_mask_image >= 128
    if not np.any(valid_surface):
        raise ValueError(f"Surface mask is empty: {surface_mask_path}")
    _, surface_nearest_indices = distance_transform_edt(
        ~valid_surface,
        return_indices=True,
    )
    inference_manifest_path = args.inference_dir / "hamer_inference_manifest.json"
    inference_manifest = json.loads(
        inference_manifest_path.read_text(encoding="utf-8")
    )
    processed_by_depth = _manifest_by_clean_depth(args.processed_manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "hamer_rgbd_fused.mtl").write_text(
        "newmtl HamerRgbdHand\n"
        "Ka 0.08 0.10 0.12\n"
        "Kd 0.34 0.72 0.86\n"
        "Ks 0.18 0.22 0.24\n"
        "Ns 48.0\n"
        "d 1.0\n",
        encoding="utf-8",
    )

    records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    for frame in inference_manifest["frames"]:
        frame_index = int(frame["frameIndex"])
        arrays_path = args.inference_dir / frame["arrays"]
        arrays = np.load(arrays_path)
        faces = arrays["faces"].astype(np.int32)
        landmarks = arrays["crop_landmarks_xy"].astype(np.float32)
        vertices_camera = arrays["vertices_camera"].astype(np.float32)
        joints_camera = arrays["joints_camera"].astype(np.float32)
        focal_length = float(arrays["focal_length_px"])
        geometry_path = (
            args.rgbd_session / f"virtual_hand_geometry_{frame_index:06d}.png"
        )
        geometry = cv2.imread(str(geometry_path), cv2.IMREAD_UNCHANGED)
        if geometry is None or geometry.ndim != 3 or geometry.shape[2] < 3:
            raise FileNotFoundError(geometry_path)
        height, width = geometry.shape[:2]
        measured_lift = (
            geometry[:, :, 2].astype(np.float32) / 255.0 * args.max_lift_meters
        )
        confidence = geometry[:, :, 1].astype(np.float32) / 255.0
        direct = geometry[:, :, 0] >= 128
        support = confidence > 0.0
        distance, nearest_indices = distance_transform_edt(
            ~support, return_indices=True
        )

        alignment_mode = "none" if args.no_palm_alignment else args.alignment_mode
        alignment = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32
        )
        if alignment_mode == "rgbd_palm_rigid":
            refit_vertices_camera, refit_joints_camera, alignment_report = (
                _rgbd_palm_rigid_refit(
                    vertices_camera,
                    joints_camera,
                    landmarks,
                    measured_lift,
                    confidence,
                    distance,
                    nearest_indices,
                    args.maximum_nearest_support_pixels,
                    focal_length,
                )
            )
            # Keep HaMeR's top-down XY silhouette. The RGB-D palm plane is used
            # only to replace the monocular camera-depth component; reprojecting
            # all three rigidly transformed coordinates can throw an otherwise
            # good outline out of the measured hand support.
            vertices_camera[:, 2] = refit_vertices_camera[:, 2]
            joints_camera[:, 2] = refit_joints_camera[:, 2]
            image_uv = arrays["vertex_uv"].astype(np.float32)
            joint_uv_aligned = arrays["joint_uv"].astype(np.float32)
            alignment, image_alignment_report = _unit_scale_palm_rigid_2d(
                joint_uv_aligned,
                landmarks,
                args.maximum_alignment_rotation_degrees,
            )
            image_uv = _transform_points(image_uv, alignment)
            joint_uv_aligned = _transform_points(
                joint_uv_aligned, alignment
            )
            alignment_report["imagePlaneAlignment"] = image_alignment_report
            alignment_report["projectionPolicy"] = (
                "HaMeR XY silhouette retained; RGB-D palm rigid fit contributes "
                "camera-depth only"
            )
        else:
            image_uv = arrays["vertex_uv"].astype(np.float32)
            joint_uv = arrays["joint_uv"].astype(np.float32)
            if alignment_mode == "bounded_2d":
                alignment, alignment_report = _bounded_palm_similarity(
                    joint_uv,
                    landmarks,
                    args.minimum_alignment_scale,
                    args.maximum_alignment_scale,
                    args.maximum_alignment_rotation_degrees,
                )
                alignment_report["mode"] = "bounded_2d"
            else:
                alignment_report = {
                    "mode": "none",
                    "accepted": False,
                    "reason": "disabled",
                    "matrix": alignment.tolist(),
                    "scale": 1.0,
                    "rotationDegrees": 0.0,
                    "translationPixels": [0.0, 0.0],
                    "palmRmsePixelsBefore": float(
                        np.sqrt(
                            np.mean(
                                np.square(
                                    joint_uv[PALM_JOINTS]
                                    - landmarks[PALM_JOINTS]
                                )
                            )
                        )
                    ),
                    "palmRmsePixelsAfter": None,
                    "inliers": None,
                }
            image_uv = _transform_points(image_uv, alignment)
            joint_uv_aligned = _transform_points(joint_uv, alignment)

        rounded_x = np.rint(image_uv[:, 0]).astype(np.int32)
        rounded_y = np.rint(image_uv[:, 1]).astype(np.int32)
        inside = (
            (rounded_x >= 0)
            & (rounded_x < width)
            & (rounded_y >= 0)
            & (rounded_y < height)
        )
        clipped_x = np.clip(rounded_x, 0, width - 1)
        clipped_y = np.clip(rounded_y, 0, height - 1)
        vertex_distance = distance[clipped_y, clipped_x]
        nearest_y = nearest_indices[0, clipped_y, clipped_x]
        nearest_x = nearest_indices[1, clipped_y, clipped_x]
        supported = (
            inside & (vertex_distance <= args.maximum_nearest_support_pixels)
        )
        observed_lift = measured_lift[nearest_y, nearest_x]
        observed_confidence = confidence[nearest_y, nearest_x]
        observed_direct = direct[nearest_y, nearest_x]

        zbuffer = _rasterize_depth(
            image_uv,
            vertices_camera[:, 2],
            faces,
            width,
            height,
        )
        # A projected vertex often lies exactly on a triangle edge, while the
        # z-buffer is sampled at pixel centres. Find the spatially nearest valid
        # z-buffer sample, but preserve that sample's depth. A min-filter/erode
        # is incorrect here: on a sloped hand it selects a physically closer
        # neighbour and invents tens of millimetres of back-surface thickness.
        zbuffer_valid = np.isfinite(zbuffer)
        zbuffer_distance, zbuffer_nearest = distance_transform_edt(
            ~zbuffer_valid, return_indices=True
        )
        visible_depth = zbuffer[
            zbuffer_nearest[0, clipped_y, clipped_x],
            zbuffer_nearest[1, clipped_y, clipped_x],
        ]
        finite_visible = (
            inside & (zbuffer_distance[clipped_y, clipped_x] <= 2.5)
        )
        thickness = np.maximum(vertices_camera[:, 2] - visible_depth, 0.0)
        thickness[~finite_visible] = 0.0
        thickness = np.minimum(thickness, args.maximum_thickness_meters)

        anchor = supported & finite_visible
        if np.count_nonzero(anchor) < 20:
            if args.skip_invalid_frames:
                skipped_records.append(
                    {
                        "frameIndex": frame_index,
                        "reason": "fewer_than_20_fusion_anchors",
                        "fusionAnchors": int(np.count_nonzero(anchor)),
                        "supportedVertexRatio": float(np.mean(supported)),
                    }
                )
                print(
                    f"frame {frame_index}: skipped, only "
                    f"{np.count_nonzero(anchor)} fusion anchors"
                )
                continue
            raise ValueError(
                f"Frame {frame_index} has only {np.count_nonzero(anchor)} fusion anchors"
            )
        lift_fusion_report: dict[str, Any]
        visible_inliers = anchor.copy()
        if args.lift_fusion_mode == "mano_rigid_offset":
            visible_candidates = (
                anchor & observed_direct & (thickness <= 0.0015)
            )
            if np.count_nonzero(visible_candidates) < 20:
                if args.skip_invalid_frames:
                    skipped_records.append(
                        {
                            "frameIndex": frame_index,
                            "reason": "fewer_than_20_visible_rgbd_candidates",
                            "visibleCandidates": int(
                                np.count_nonzero(visible_candidates)
                            ),
                            "fusionAnchors": int(np.count_nonzero(anchor)),
                            "supportedVertexRatio": float(np.mean(supported)),
                        }
                    )
                    print(
                        f"frame {frame_index}: skipped, only "
                        f"{np.count_nonzero(visible_candidates)} visible candidates"
                    )
                    continue
                raise ValueError(
                    f"Frame {frame_index} has only "
                    f"{np.count_nonzero(visible_candidates)} visible RGB-D candidates"
                )
            try:
                camera_sand_offset, visible_inliers, lift_fusion_report = (
                    _dominant_depth_offset(
                        (observed_lift + visible_depth)[visible_candidates],
                        observed_confidence[visible_candidates],
                        args.rgbd_anchor_bin_meters,
                        args.rgbd_anchor_radius_meters,
                    )
                )
            except ValueError as error:
                if not args.skip_invalid_frames:
                    raise
                skipped_records.append(
                    {
                        "frameIndex": frame_index,
                        "reason": "dominant_depth_offset_failed",
                        "detail": str(error),
                        "visibleCandidates": int(
                            np.count_nonzero(visible_candidates)
                        ),
                        "fusionAnchors": int(np.count_nonzero(anchor)),
                        "supportedVertexRatio": float(np.mean(supported)),
                    }
                )
                print(f"frame {frame_index}: skipped, {error}")
                continue
            expanded_inliers = np.zeros_like(anchor)
            expanded_inliers[np.flatnonzero(visible_candidates)] = visible_inliers
            visible_inliers = expanded_inliers
            lift_fusion_report["mode"] = "mano_rigid_offset"
        else:
            camera_sand_offset = float(
                np.median(observed_lift[anchor] + visible_depth[anchor])
            )
            lift_fusion_report = {
                "mode": "per_vertex",
                "candidateCount": int(np.count_nonzero(anchor)),
                "inlierCount": int(np.count_nonzero(anchor)),
                "inlierRatio": 1.0,
                "cameraSandOffsetMeters": camera_sand_offset,
            }
        fallback_lift = camera_sand_offset - vertices_camera[:, 2]
        if args.lift_fusion_mode == "mano_rigid_offset":
            fused_lift = fallback_lift
        else:
            fused_lift = fallback_lift.copy()
            fused_lift[supported] = (
                observed_lift[supported]
                - args.thickness_scale * thickness[supported]
            )
        fused_lift = np.clip(fused_lift, 0.0, args.max_lift_meters)

        clean_depth_name = f"clean_depth_{frame_index:06d}.png"
        if clean_depth_name not in processed_by_depth:
            raise KeyError(clean_depth_name)
        processed_frame = processed_by_depth[clean_depth_name]
        depth_path = args.rgbd_session / clean_depth_name
        surface_sample_xy, surface_sample_direct, surface_sample_distance = (
            _nearest_valid_surface_coordinates(
                image_uv,
                valid_surface,
                surface_nearest_indices,
            )
        )
        sampled_sand_y = _sand_surface_world_y(
            depth_path,
            surface_sample_xy,
            float(processed_frame.get("baselineHeightCorrection", 0.0)),
            args.sand_displacement_scale,
        )
        if args.lift_fusion_mode == "mano_rigid_offset":
            surface_anchor_vertices = visible_inliers
            if np.count_nonzero(surface_anchor_vertices) == 0:
                surface_anchor_vertices = anchor
            surface_anchor_y = float(
                np.median(sampled_sand_y[surface_anchor_vertices])
            )
            sand_y = np.full_like(sampled_sand_y, surface_anchor_y)
            surface_height_policy = "one_median_visible_inlier_anchor"
        else:
            surface_anchor_y = None
            sand_y = sampled_sand_y
            surface_height_policy = "per_vertex"
        vertices_world = np.column_stack(
            [
                (image_uv[:, 0] / width - 0.5) * args.plane_size,
                sand_y
                + fused_lift * args.world_units_per_meter
                + args.hand_clearance,
                (image_uv[:, 1] / height - 0.5) * args.plane_size,
            ]
        ).astype(np.float32)
        normals = _vertex_normals(vertices_world, faces)

        stem = f"hamer_rgbd_fused_{frame_index:06d}"
        npz_path = args.output_dir / f"{stem}.npz"
        np.savez_compressed(
            npz_path,
            vertices_world=vertices_world,
            faces=faces,
            normals=normals,
            image_uv=image_uv,
            joint_uv=joint_uv_aligned,
            fused_lift_meters=fused_lift.astype(np.float32),
            measured_lift_meters=observed_lift.astype(np.float32),
            measured_confidence=observed_confidence.astype(np.float32),
            measured_direct=observed_direct,
            supported=supported,
            mano_thickness_meters=thickness.astype(np.float32),
            vertices_camera_refit=vertices_camera,
            joints_camera_refit=joints_camera,
            alignment_matrix=alignment,
        )
        obj_path = args.output_dir / f"{stem}.obj"
        _write_obj(
            obj_path,
            vertices_world,
            faces,
            image_uv,
            normals,
            width,
            height,
        )

        visible = supported & finite_visible & (thickness <= 0.0015)
        if args.lift_fusion_mode == "mano_rigid_offset":
            visible = visible_inliers
            visible_residual_mm = (
                camera_sand_offset
                - visible_depth[visible]
                - observed_lift[visible]
            ) * 1000.0
        else:
            visible_residual_mm = (
                fused_lift[visible] - observed_lift[visible]
            ) * 1000.0
        records.append(
            {
                "frameIndex": frame_index,
                "sourceArrays": str(arrays_path.resolve()),
                "sourceArraysSha256": _sha256(arrays_path),
                "sourceGeometry": str(geometry_path.resolve()),
                "sourceGeometrySha256": _sha256(geometry_path),
                "sourceDepth": str(depth_path.resolve()),
                "sourceDepthSha256": _sha256(depth_path),
                "alignment": alignment_report,
                "liftFusion": lift_fusion_report,
                "vertices": int(vertices_world.shape[0]),
                "faces": int(faces.shape[0]),
                "supportedVertexRatio": float(np.mean(supported)),
                "directMeasuredVertexRatio": float(np.mean(supported & observed_direct)),
                "visibleSupportedVertices": int(np.count_nonzero(visible)),
                "visibleLiftResidualMillimeters": {
                    "rmse": float(
                        np.sqrt(np.mean(np.square(visible_residual_mm)))
                    ),
                    "absoluteP50P90P95": _percentiles(
                        np.abs(visible_residual_mm), (50, 90, 95)
                    ),
                },
                "manoThicknessMillimetersP50P90P95": _percentiles(
                    thickness * 1000.0, (50, 90, 95)
                ),
                "surfaceMaskDirectVertexRatio": float(
                    np.mean(surface_sample_direct)
                ),
                "surfaceMaskNearestDistancePixelsP50P90P95": _percentiles(
                    surface_sample_distance,
                    (50, 90, 95),
                ),
                "surfaceHeightPolicy": surface_height_policy,
                "surfaceAnchorWorldY": surface_anchor_y,
                "sampledSurfaceWorldYP50P90P95": _percentiles(
                    sampled_sand_y,
                    (50, 90, 95),
                ),
                "worldBoundsMinimum": vertices_world.min(axis=0).tolist(),
                "worldBoundsMaximum": vertices_world.max(axis=0).tolist(),
                "npz": npz_path.name,
                "npzSha256": _sha256(npz_path),
                "obj": obj_path.name,
                "objSha256": _sha256(obj_path),
            }
        )
        print(
            f"frame {frame_index}: support {np.mean(supported):.3f}, "
            f"visible RGB-D RMSE "
            f"{records[-1]['visibleLiftResidualMillimeters']['rmse']:.3f} mm"
        )

    report = {
        "schemaVersion": 1,
        "method": (
            "HaMeR MANO topology/pose plus registered RGB-D metric height; "
            + (
                "the dominant visible RGB-D depth mode anchors one rigid "
                "camera-depth offset while MANO preserves a continuous closed surface"
                if args.lift_fusion_mode == "mano_rigid_offset"
                else "per-vertex RGB-D lift drives the visible surface while "
                "MANO camera depth preserves closed back-surface thickness"
            )
        ),
        "handAuthoredMasks": False,
        "palmAlignmentPolicy": (
            "default: one fixed-scale 3D rigid transform from five semantic "
            "palm joints and measured RGB-D lift; no per-joint correction"
        ),
        "alignmentMode": (
            "none" if args.no_palm_alignment else args.alignment_mode
        ),
        "inferenceManifest": str(inference_manifest_path.resolve()),
        "inferenceManifestSha256": _sha256(inference_manifest_path),
        "processedManifest": str(args.processed_manifest.resolve()),
        "processedManifestSha256": _sha256(args.processed_manifest),
        "planeSize": args.plane_size,
        "maxLiftMeters": args.max_lift_meters,
        "worldUnitsPerMeter": args.world_units_per_meter,
        "handClearance": args.hand_clearance,
        "sandDisplacementScale": args.sand_displacement_scale,
        "surfaceMask": str(surface_mask_path),
        "surfaceMaskSha256": _sha256(surface_mask_path),
        "surfaceSamplingPolicy": (
            "bilinear clean-depth sampling inside the existing static "
            "reconstructed-surface mask; nearest valid surface sampling "
            "outside it; rigid-offset fusion uses one median visible-inlier "
            "surface anchor for the whole closed MANO mesh; no mask synthesis "
            "or dilation"
        ),
        "maximumNearestSupportPixels": args.maximum_nearest_support_pixels,
        "thicknessScale": args.thickness_scale,
        "maximumThicknessMeters": args.maximum_thickness_meters,
        "liftFusionMode": args.lift_fusion_mode,
        "rgbdAnchorBinMeters": args.rgbd_anchor_bin_meters,
        "rgbdAnchorRadiusMeters": args.rgbd_anchor_radius_meters,
        "sourceFrameCount": len(inference_manifest["frames"]),
        "frameCount": len(records),
        "skippedFrameCount": len(skipped_records),
        "skippedFrames": skipped_records,
        "frames": records,
    }
    report_path = args.output_dir / "hamer_rgbd_fusion_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
