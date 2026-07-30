#!/usr/bin/env python3
"""Temporally smooth a shared-shape HaMeR MANO sequence in rotation space."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec  # type: ignore[attr-defined]
for _name, _value in {
    "bool": bool,
    "int": int,
    "float": float,
    "complex": complex,
    "object": object,
    "unicode": str,
    "str": str,
}.items():
    if _name not in np.__dict__:
        setattr(np, _name, _value)

import torch
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.spatial.transform import Rotation

from hamer.models.mano_wrapper import MANO


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--mano-model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sigma-frames", type=float, default=1.25)
    parser.add_argument("--maximum-gap-frames", type=int, default=3)
    parser.add_argument(
        "--maximum-rotation-change-degrees", type=float, default=28.0
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _segments(frame_indices: np.ndarray, maximum_gap: int) -> list[slice]:
    starts = [0]
    for index in range(1, len(frame_indices)):
        if int(frame_indices[index] - frame_indices[index - 1]) > maximum_gap:
            starts.append(index)
    starts.append(len(frame_indices))
    return [slice(first, second) for first, second in zip(starts[:-1], starts[1:])]


def _smooth_rotations(
    matrices: np.ndarray,
    segments: list[slice],
    sigma: float,
    maximum_change_degrees: float,
) -> tuple[np.ndarray, np.ndarray]:
    frame_count, joint_count = matrices.shape[:2]
    smoothed = matrices.copy()
    changes = np.zeros((frame_count, joint_count), dtype=np.float64)
    maximum_change = math.radians(maximum_change_degrees)
    for segment in segments:
        if segment.stop - segment.start < 3:
            continue
        for joint in range(joint_count):
            original = Rotation.from_matrix(matrices[segment, joint])
            quaternions = original.as_quat()
            for index in range(1, len(quaternions)):
                if float(np.dot(quaternions[index - 1], quaternions[index])) < 0.0:
                    quaternions[index] *= -1.0
            filtered = gaussian_filter1d(
                quaternions,
                sigma=sigma,
                axis=0,
                mode="nearest",
            )
            filtered /= np.linalg.norm(filtered, axis=1, keepdims=True)
            candidate = Rotation.from_quat(filtered)
            relative = candidate * original.inv()
            rotation_vectors = relative.as_rotvec()
            angles = np.linalg.norm(rotation_vectors, axis=1)
            scale = np.minimum(
                1.0,
                maximum_change / np.maximum(angles, 1.0e-12),
            )
            clamped = Rotation.from_rotvec(rotation_vectors * scale[:, None])
            result = clamped * original
            smoothed[segment, joint] = result.as_matrix().astype(np.float32)
            changes[segment, joint] = np.degrees(
                np.linalg.norm((clamped).as_rotvec(), axis=1)
            )
    return smoothed.astype(np.float32), changes


def _smooth_camera(
    cameras: np.ndarray,
    segments: list[slice],
    sigma: float,
) -> np.ndarray:
    smoothed = cameras.copy()
    for segment in segments:
        if segment.stop - segment.start < 3:
            continue
        robust_camera = median_filter(
            cameras[segment],
            size=(5, 1),
            mode="nearest",
        )
        smoothed[segment] = gaussian_filter1d(
            robust_camera,
            sigma=sigma,
            axis=0,
            mode="nearest",
        )
    return smoothed.astype(np.float32)


def _forward(
    mano: MANO,
    global_orient: np.ndarray,
    hand_pose: np.ndarray,
    betas: np.ndarray,
    is_right: bool,
) -> tuple[np.ndarray, np.ndarray]:
    with torch.no_grad():
        output = mano(
            global_orient=torch.from_numpy(global_orient)[None],
            hand_pose=torch.from_numpy(hand_pose)[None],
            betas=torch.from_numpy(betas)[None],
            pose2rot=False,
        )
    vertices = output.vertices[0].cpu().numpy().astype(np.float32)
    joints = output.joints[0].cpu().numpy().astype(np.float32)
    if not is_right:
        vertices[:, 0] *= -1.0
        joints[:, 0] *= -1.0
    return vertices, joints


def main() -> None:
    args = _parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output_dir}")
    if args.sigma_frames <= 0.0:
        raise ValueError("--sigma-frames must be positive")

    manifest_path = args.input_dir / "hamer_inference_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["frames"]
    arrays = [np.load(args.input_dir / frame["arrays"]) for frame in records]
    frame_indices = np.asarray(
        [int(frame["frameIndex"]) for frame in records], dtype=np.int32
    )
    segments = _segments(frame_indices, args.maximum_gap_frames)
    global_orient = np.stack(
        [array["global_orient"] for array in arrays], axis=0
    )
    hand_pose = np.stack([array["hand_pose"] for array in arrays], axis=0)
    rotations = np.concatenate((global_orient, hand_pose), axis=1)
    smoothed_rotations, rotation_changes = _smooth_rotations(
        rotations,
        segments,
        args.sigma_frames,
        args.maximum_rotation_change_degrees,
    )
    cameras = np.stack([array["cam_full"] for array in arrays], axis=0)
    smoothed_cameras = _smooth_camera(cameras, segments, args.sigma_frames)

    mano = MANO(
        model_path=str(args.mano_model_path),
        is_rhand=True,
        use_pca=False,
        flat_hand_mean=False,
    )
    mano.eval()
    args.output_dir.mkdir(parents=True)
    output_records: list[dict[str, Any]] = []
    width, height = map(float, manifest.get("sourceImageSize", [640, 480]))
    for index, (source_frame, source) in enumerate(zip(records, arrays)):
        frame_index = int(source_frame["frameIndex"])
        smoothed_global = smoothed_rotations[index, :1]
        smoothed_hand = smoothed_rotations[index, 1:]
        betas = source["betas"].astype(np.float32)
        is_right = bool(float(source["is_right"]))
        vertices, joints = _forward(
            mano, smoothed_global, smoothed_hand, betas, is_right
        )
        camera = smoothed_cameras[index]
        vertices_camera = vertices + camera
        joints_camera = joints + camera
        focal_length = float(source["focal_length_px"])
        vertex_uv = np.column_stack(
            (
                focal_length * vertices_camera[:, 0] / vertices_camera[:, 2]
                + width * 0.5,
                focal_length * vertices_camera[:, 1] / vertices_camera[:, 2]
                + height * 0.5,
            )
        ).astype(np.float32)
        joint_uv = np.column_stack(
            (
                focal_length * joints_camera[:, 0] / joints_camera[:, 2]
                + width * 0.5,
                focal_length * joints_camera[:, 1] / joints_camera[:, 2]
                + height * 0.5,
            )
        ).astype(np.float32)

        output_name = f"hamer_{frame_index:06d}.npz"
        output_path = args.output_dir / output_name
        np.savez_compressed(
            output_path,
            vertices_model=vertices,
            vertices_camera=vertices_camera,
            joints_model=joints,
            joints_camera=joints_camera,
            faces=source["faces"],
            vertex_uv=vertex_uv,
            joint_uv=joint_uv,
            cam_crop=source["cam_crop"],
            cam_full=camera,
            focal_length_px=source["focal_length_px"],
            bbox_xyxy=source["bbox_xyxy"],
            crop_landmarks_xy=source["crop_landmarks_xy"],
            global_orient=smoothed_global,
            hand_pose=smoothed_hand,
            betas=betas,
            original_frame_betas=source["original_frame_betas"],
            is_right=source["is_right"],
            unsmoothed_global_orient=source["global_orient"],
            unsmoothed_hand_pose=source["hand_pose"],
            unsmoothed_cam_full=source["cam_full"],
        )
        output_frame = dict(source_frame)
        output_frame["arrays"] = output_name
        output_frame["arraysSha256"] = _sha256(output_path)
        output_frame["temporalRotationChangeDegreesP95"] = float(
            np.percentile(rotation_changes[index], 95)
        )
        output_records.append(output_frame)
        print(f"frame {frame_index}: {output_name}")

    output_manifest = dict(manifest)
    output_manifest["frames"] = output_records
    output_manifest["temporalSmoothing"] = {
        "method": (
            "sign-continuous quaternion Gaussian filtering per MANO joint "
            "within contiguous track segments; camera translation receives "
            "a five-frame median outlier rejection followed by the same "
            "zero-phase Gaussian kernel"
        ),
        "sigmaFrames": args.sigma_frames,
        "maximumGapFrames": args.maximum_gap_frames,
        "maximumRotationChangeDegrees": args.maximum_rotation_change_degrees,
        "segmentCount": len(segments),
        "rotationChangeDegreesP50P90P95Max": [
            float(np.percentile(rotation_changes, percentile))
            for percentile in (50, 90, 95, 100)
        ],
        "cameraChangeP50P90P95Max": [
            float(np.percentile(np.linalg.norm(smoothed_cameras - cameras, axis=1), percentile))
            for percentile in (50, 90, 95, 100)
        ],
    }
    output_manifest["sourceInferenceManifest"] = str(manifest_path.resolve())
    output_manifest["sourceInferenceManifestSha256"] = _sha256(manifest_path)
    output_manifest_path = args.output_dir / "hamer_inference_manifest.json"
    output_manifest_path.write_text(
        json.dumps(output_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_manifest_path}")


if __name__ == "__main__":
    main()
