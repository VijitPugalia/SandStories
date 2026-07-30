#!/usr/bin/env python3
"""Fit anatomically constrained MANO poses to model-produced 2D hand tracks.

This is a hand-only diagnostic. It deliberately does not use tool geometry,
intent-specific pose rules, or hand-authored masks. A low-dimensional MANO PCA
pose and one perspective camera translation are optimized against the 21
model-produced image landmarks. One robust median MANO shape is shared by
every requested frame.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import pickle
import platform
from typing import Any

import numpy as np


def _install_legacy_compatibility() -> None:
    if not hasattr(inspect, "getargspec"):
        inspect.getargspec = inspect.getfullargspec  # type: ignore[attr-defined]
    aliases = {
        "bool": bool,
        "int": int,
        "float": float,
        "complex": complex,
        "object": object,
        "unicode": str,
        "str": str,
    }
    for name, value in aliases.items():
        if name not in np.__dict__:
            setattr(np, name, value)


_install_legacy_compatibility()

import cv2
from scipy.spatial.transform import Rotation
import torch
import torch.nn.functional as functional

import smplx
from smplx.lbs import batch_rodrigues, vertices2joints
from smplx.utils import MANOOutput, to_tensor
from smplx.vertex_ids import vertex_ids


class MANO(smplx.MANOLayer):
    """MANO layer with the standard 21-joint OpenPose/MediaPipe ordering."""

    def __init__(
        self,
        *args: Any,
        joint_regressor_extra: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        mano_to_openpose = [
            0,
            13,
            14,
            15,
            16,
            1,
            2,
            3,
            17,
            4,
            5,
            6,
            18,
            10,
            11,
            12,
            19,
            7,
            8,
            9,
            20,
        ]
        if joint_regressor_extra is not None:
            with Path(joint_regressor_extra).open("rb") as stream:
                regressor = pickle.load(stream, encoding="latin1")
            self.register_buffer(
                "joint_regressor_extra",
                torch.tensor(regressor, dtype=torch.float32),
            )
        self.register_buffer(
            "extra_joints_idxs",
            to_tensor(list(vertex_ids["mano"].values()), dtype=torch.long),
        )
        self.register_buffer(
            "joint_map",
            torch.tensor(mano_to_openpose, dtype=torch.long),
        )

    def forward(self, *args: Any, **kwargs: Any) -> MANOOutput:
        mano_output = super().forward(*args, **kwargs)
        extra_joints = torch.index_select(
            mano_output.vertices,
            1,
            self.extra_joints_idxs,
        )
        joints = torch.cat([mano_output.joints, extra_joints], dim=1)
        mano_output.joints = joints[:, self.joint_map, :]
        if hasattr(self, "joint_regressor_extra"):
            regressed_joints = vertices2joints(
                self.joint_regressor_extra,
                mano_output.vertices,
            )
            mano_output.joints = torch.cat(
                [mano_output.joints, regressed_joints],
                dim=1,
            )
        return mano_output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--track-json", type=Path, required=True)
    parser.add_argument("--mano-model-path", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--frames",
        required=True,
        help="Comma-separated zero-based frame indices.",
    )
    parser.add_argument(
        "--image-pattern",
        default="clean_rgb_{frame:06d}.png",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--iterations", type=int, default=1800)
    parser.add_argument("--learning-rate", type=float, default=0.025)
    parser.add_argument("--pca-components", type=int, default=15)
    parser.add_argument("--pose-prior-weight", type=float, default=0.0025)
    parser.add_argument("--camera-prior-weight", type=float, default=0.001)
    parser.add_argument("--orientation-prior-weight", type=float, default=0.001)
    parser.add_argument("--maximum-camera-scale-change", type=float, default=0.18)
    parser.add_argument(
        "--camera-depth-policy",
        choices=("independent_bounded", "shared_fixed"),
        default="independent_bounded",
        help=(
            "shared_fixed uses one median perspective depth for every frame, "
            "preventing monocular per-frame hand-size pumping"
        ),
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_indices(value: str) -> list[int]:
    frames = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    if not frames or frames[0] < 0:
        raise ValueError("--frames must contain non-negative frame indices")
    return frames


def _load_track(path: Path) -> dict[int, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tracks = payload.get("hand_tracks", [])
    if len(tracks) != 1:
        raise ValueError(f"Expected exactly one hand track, found {len(tracks)}")
    return {
        int(sample["frameIndex"]): sample for sample in tracks[0]["samples"]
    }


def _rotation_matrix_to_axis_angle(value: np.ndarray) -> np.ndarray:
    matrices = np.asarray(value, dtype=np.float64).reshape(-1, 3, 3)
    return Rotation.from_matrix(matrices).as_rotvec().astype(np.float32)


def _axis_angle_to_rotation_matrix(value: np.ndarray) -> np.ndarray:
    vectors = np.asarray(value, dtype=np.float64).reshape(-1, 3)
    return Rotation.from_rotvec(vectors).as_matrix().astype(np.float32)


def _project(
    points: torch.Tensor,
    camera_xy: torch.Tensor,
    camera_log_z: torch.Tensor,
    focal_length: torch.Tensor,
    image_size: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    camera = torch.cat((camera_xy, camera_log_z.exp().reshape(1)), dim=0)
    camera_points = points + camera.reshape(1, 3)
    uv = torch.stack(
        (
            focal_length * camera_points[:, 0] / camera_points[:, 2]
            + image_size[0] * 0.5,
            focal_length * camera_points[:, 1] / camera_points[:, 2]
            + image_size[1] * 0.5,
        ),
        dim=1,
    )
    return uv, camera


def _forward_mano(
    mano: MANO,
    global_axis_angle: torch.Tensor,
    pose_coefficients: torch.Tensor,
    hand_components: torch.Tensor,
    hand_mean: torch.Tensor,
    betas: torch.Tensor,
) -> tuple[Any, torch.Tensor]:
    """Run the rotation-matrix MANO layer from differentiable PCA parameters."""
    hand_axis_angle = (
        pose_coefficients @ hand_components + hand_mean
    ).reshape(15, 3)
    rotations = batch_rodrigues(
        torch.cat((global_axis_angle.reshape(1, 3), hand_axis_angle), dim=0)
    ).reshape(1, 16, 3, 3)
    output = mano(
        global_orient=rotations[:, :1],
        hand_pose=rotations[:, 1:],
        betas=betas,
    )
    return output, hand_axis_angle


def _draw_overlay(
    image_bgr: np.ndarray,
    vertex_uv: np.ndarray,
    joint_uv: np.ndarray,
    target_uv: np.ndarray,
    faces: np.ndarray,
) -> np.ndarray:
    height, width = image_bgr.shape[:2]
    valid_vertices = (
        np.isfinite(vertex_uv).all(axis=1)
        & (vertex_uv[:, 0] >= -width)
        & (vertex_uv[:, 0] < width * 2)
        & (vertex_uv[:, 1] >= -height)
        & (vertex_uv[:, 1] < height * 2)
    )
    valid_faces = faces[np.all(valid_vertices[faces], axis=1)]
    silhouette = np.zeros((height, width), dtype=np.uint8)
    vertices_int = np.rint(vertex_uv).astype(np.int32)
    for face in valid_faces:
        cv2.fillConvexPoly(
            silhouette,
            vertices_int[face],
            255,
            lineType=cv2.LINE_AA,
        )

    result = image_bgr.copy()
    tint = np.zeros_like(result)
    tint[:, :] = (185, 105, 238)
    alpha = (silhouette.astype(np.float32) / 255.0 * 0.48)[..., None]
    result = np.rint(result * (1.0 - alpha) + tint * alpha).astype(np.uint8)

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
    ]
    fitted_int = np.rint(joint_uv).astype(np.int32)
    target_int = np.rint(target_uv).astype(np.int32)
    for start, end in edges:
        cv2.line(
            result,
            tuple(fitted_int[start]),
            tuple(fitted_int[end]),
            (255, 100, 35),
            2,
            cv2.LINE_AA,
        )
    for point in target_int:
        cv2.circle(result, tuple(point), 3, (55, 245, 75), -1, cv2.LINE_AA)
    for point in fitted_int:
        cv2.circle(result, tuple(point), 2, (255, 245, 225), -1, cv2.LINE_AA)
    return result


def main() -> None:
    args = _parse_args()
    frames = _frame_indices(args.frames)
    for attribute in (
        "input_dir",
        "track_json",
        "mano_model_path",
        "rgb_dir",
        "output_dir",
    ):
        setattr(args, attribute, getattr(args, attribute).resolve())
    for path in (
        args.input_dir,
        args.track_json,
        args.mano_model_path,
        args.rgb_dir,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    if not 1 <= args.pca_components <= 45:
        raise ValueError("--pca-components must be between 1 and 45")
    if args.iterations <= 0:
        raise ValueError("--iterations must be positive")
    if not 0.0 <= args.maximum_camera_scale_change < 1.0:
        raise ValueError("--maximum-camera-scale-change must be in [0, 1)")

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA device requested but unavailable: {device}")
    samples = _load_track(args.track_json)
    missing_samples = [frame for frame in frames if frame not in samples]
    if missing_samples:
        raise KeyError(f"Track samples missing for frames {missing_samples}")

    source_arrays: dict[int, Any] = {}
    for frame in frames:
        path = args.input_dir / f"wilor_{frame:06d}.npz"
        if not path.exists():
            raise FileNotFoundError(path)
        source_arrays[frame] = np.load(path)

    shared_betas = np.median(
        np.stack([source_arrays[frame]["betas"] for frame in frames], axis=0),
        axis=0,
    ).astype(np.float32)
    shared_camera_z = float(
        np.median(
            [
                float(source_arrays[frame]["cam_full"][2])
                for frame in frames
            ]
        )
    )
    mano = MANO(
        model_path=str(args.mano_model_path),
        is_rhand=True,
        use_pca=True,
        num_pca_comps=args.pca_components,
        flat_hand_mean=False,
    ).to(device)
    mano.eval()
    for parameter in mano.parameters():
        parameter.requires_grad_(False)
    faces = np.asarray(mano.faces, dtype=np.int32)
    hand_components = mano.hand_components.detach()
    hand_mean = mano.hand_mean.detach()
    betas_tensor = torch.from_numpy(shared_betas).to(device).reshape(1, -1)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "method": (
            "hand-only low-dimensional MANO inverse kinematics against "
            "model-produced 21-point image landmarks"
        ),
        "constraintsExcluded": [
            "tool geometry",
            "tool contact",
            "intent-specific pose rules",
            "hand-authored masks",
        ],
        "inputDir": str(args.input_dir),
        "trackJson": str(args.track_json),
        "trackJsonSha256": _sha256(args.track_json),
        "manoModelPath": str(args.mano_model_path),
        "manoModelSha256": _sha256(args.mano_model_path),
        "rgbDir": str(args.rgb_dir),
        "framesRequested": frames,
        "sharedBetas": shared_betas.tolist(),
        "pcaComponents": args.pca_components,
        "iterations": args.iterations,
        "learningRate": args.learning_rate,
        "posePriorWeight": args.pose_prior_weight,
        "cameraPriorWeight": args.camera_prior_weight,
        "orientationPriorWeight": args.orientation_prior_weight,
        "maximumCameraScaleChange": args.maximum_camera_scale_change,
        "cameraDepthPolicy": args.camera_depth_policy,
        "sharedCameraZ": shared_camera_z,
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cudaRuntime": torch.version.cuda,
            "gpu": (
                torch.cuda.get_device_name(device)
                if device.type == "cuda"
                else None
            ),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
        "frames": [],
    }

    for frame in frames:
        arrays = source_arrays[frame]
        target = np.asarray(samples[frame]["pixelLandmarks"], dtype=np.float32)
        if target.shape != (21, 2) or not np.isfinite(target).all():
            raise ValueError(f"Invalid track landmarks for frame {frame}")
        image_path = args.rgb_dir / args.image_pattern.format(frame=frame)
        image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise FileNotFoundError(image_path)
        height, width = image_bgr.shape[:2]
        image_size = torch.tensor(
            [float(width), float(height)],
            dtype=torch.float32,
            device=device,
        )
        focal_length = torch.tensor(
            float(arrays["focal_length_px"]),
            dtype=torch.float32,
            device=device,
        )
        target_tensor = torch.from_numpy(target).to(device)
        target_scale = max(
            float(np.linalg.norm(target.max(axis=0) - target.min(axis=0))),
            24.0,
        )

        initial_global_aa = _rotation_matrix_to_axis_angle(
            arrays["global_orient"]
        ).reshape(3)
        initial_hand_aa = _rotation_matrix_to_axis_angle(
            arrays["hand_pose"]
        ).reshape(45)
        initial_hand_tensor = torch.from_numpy(initial_hand_aa).to(device)
        initial_coefficients = (
            (initial_hand_tensor - hand_mean)
            @ hand_components.transpose(0, 1)
        )[: args.pca_components]
        pose_coefficients = torch.nn.Parameter(
            initial_coefficients.detach().clone()
        )
        global_axis_angle = torch.nn.Parameter(
            torch.from_numpy(initial_global_aa).to(device)
        )
        initial_camera = torch.from_numpy(
            arrays["cam_full"].astype(np.float32)
        ).to(device)
        camera_xy = torch.nn.Parameter(initial_camera[:2].detach().clone())
        if args.camera_depth_policy == "shared_fixed":
            camera_log_z: torch.Tensor = torch.tensor(
                shared_camera_z,
                dtype=torch.float32,
                device=device,
            ).log()
        else:
            camera_log_z = torch.nn.Parameter(initial_camera[2].log())

        parameter_groups = [
            {"params": [pose_coefficients], "lr": args.learning_rate},
            {"params": [global_axis_angle], "lr": args.learning_rate * 0.35},
            {"params": [camera_xy], "lr": args.learning_rate * 0.08},
        ]
        if args.camera_depth_policy == "independent_bounded":
            parameter_groups.append(
                {
                    "params": [camera_log_z],
                    "lr": args.learning_rate * 0.025,
                }
            )
        optimizer = torch.optim.Adam(parameter_groups)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=args.iterations,
            eta_min=args.learning_rate * 0.02,
        )

        with torch.no_grad():
            initial_output, _ = _forward_mano(
                mano,
                global_axis_angle,
                pose_coefficients,
                hand_components,
                hand_mean,
                betas_tensor,
            )
            initial_uv, _ = _project(
                initial_output.joints[0],
                camera_xy,
                camera_log_z,
                focal_length,
                image_size,
            )
            initial_error = torch.linalg.vector_norm(
                initial_uv - target_tensor, dim=1
            )

        for iteration in range(args.iterations):
            optimizer.zero_grad(set_to_none=True)
            output, _ = _forward_mano(
                mano,
                global_axis_angle,
                pose_coefficients,
                hand_components,
                hand_mean,
                betas_tensor,
            )
            joint_uv, camera = _project(
                output.joints[0],
                camera_xy,
                camera_log_z,
                focal_length,
                image_size,
            )
            normalized_delta = (joint_uv - target_tensor) / target_scale
            landmark_loss = functional.smooth_l1_loss(
                normalized_delta,
                torch.zeros_like(normalized_delta),
                beta=0.025,
            )
            pose_prior = pose_coefficients.square().mean()
            orientation_prior = (
                global_axis_angle
                - torch.from_numpy(initial_global_aa).to(device)
            ).square().mean()
            camera_scale_reference = (
                torch.tensor(
                    shared_camera_z,
                    dtype=torch.float32,
                    device=device,
                )
                if args.camera_depth_policy == "shared_fixed"
                else initial_camera[2]
            )
            camera_scale_delta = (
                camera[2].log() - camera_scale_reference.log()
            )
            camera_center_delta = (
                (camera[:2] - initial_camera[:2])
                / initial_camera[2].clamp_min(0.1)
            )
            camera_prior = (
                camera_center_delta.square().mean()
                + camera_scale_delta.square()
            )
            loss = (
                landmark_loss
                + args.pose_prior_weight * pose_prior
                + args.orientation_prior_weight * orientation_prior
                + args.camera_prior_weight * camera_prior
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [pose_coefficients, global_axis_angle, camera_xy]
                + (
                    [camera_log_z]
                    if args.camera_depth_policy == "independent_bounded"
                    else []
                ),
                max_norm=8.0,
            )
            optimizer.step()
            if args.camera_depth_policy == "independent_bounded":
                with torch.no_grad():
                    lower = initial_camera[2] * (
                        1.0 - args.maximum_camera_scale_change
                    )
                    upper = initial_camera[2] * (
                        1.0 + args.maximum_camera_scale_change
                    )
                    camera_log_z.clamp_(lower.log(), upper.log())
            scheduler.step()

        with torch.no_grad():
            output, hand_axis_angle = _forward_mano(
                mano,
                global_axis_angle,
                pose_coefficients,
                hand_components,
                hand_mean,
                betas_tensor,
            )
            vertices_model = output.vertices[0]
            joints_model = output.joints[0]
            vertex_uv, camera = _project(
                vertices_model,
                camera_xy,
                camera_log_z,
                focal_length,
                image_size,
            )
            joint_uv, _ = _project(
                joints_model,
                camera_xy,
                camera_log_z,
                focal_length,
                image_size,
            )
            final_error = torch.linalg.vector_norm(
                joint_uv - target_tensor, dim=1
            )

        vertices_np = vertices_model.cpu().numpy().astype(np.float32)
        joints_np = joints_model.cpu().numpy().astype(np.float32)
        camera_np = camera.cpu().numpy().astype(np.float32)
        vertex_uv_np = vertex_uv.cpu().numpy().astype(np.float32)
        joint_uv_np = joint_uv.cpu().numpy().astype(np.float32)
        hand_axis_angle_np = hand_axis_angle.cpu().numpy().astype(np.float32)
        global_axis_angle_np = (
            global_axis_angle.detach().cpu().numpy().astype(np.float32)
        )
        vertices_camera = vertices_np + camera_np
        joints_camera = joints_np + camera_np
        array_path = args.output_dir / f"mano_hand_only_{frame:06d}.npz"
        np.savez_compressed(
            array_path,
            vertices_model=vertices_np,
            vertices_camera=vertices_camera,
            joints_model=joints_np,
            joints_camera=joints_camera,
            faces=faces,
            vertex_uv=vertex_uv_np,
            joint_uv=joint_uv_np,
            cam_full=camera_np,
            focal_length_px=np.float32(focal_length.item()),
            crop_landmarks_xy=target,
            global_orient=_axis_angle_to_rotation_matrix(
                global_axis_angle_np
            ).reshape(1, 3, 3),
            hand_pose=_axis_angle_to_rotation_matrix(hand_axis_angle_np),
            hand_pose_axis_angle=hand_axis_angle_np,
            mano_pca_coefficients=(
                pose_coefficients.detach().cpu().numpy().astype(np.float32)
            ),
            betas=shared_betas,
            is_right=np.float32(1.0),
        )
        overlay = _draw_overlay(
            image_bgr,
            vertex_uv_np,
            joint_uv_np,
            target,
            faces,
        )
        overlay_path = args.output_dir / f"mano_hand_only_{frame:06d}_overlay.png"
        if not cv2.imwrite(str(overlay_path), overlay):
            raise RuntimeError(f"Failed to write {overlay_path}")

        initial_error_np = initial_error.cpu().numpy()
        final_error_np = final_error.cpu().numpy()
        record = {
            "frameIndex": frame,
            "intent": samples[frame].get("intent"),
            "trackConfidence": samples[frame].get("confidence"),
            "sourceArrays": str(
                (args.input_dir / f"wilor_{frame:06d}.npz").resolve()
            ),
            "sourceImage": str(image_path),
            "arrays": array_path.name,
            "arraysSha256": _sha256(array_path),
            "overlay": overlay_path.name,
            "overlaySha256": _sha256(overlay_path),
            "initialMeanLandmarkErrorPixels": float(initial_error_np.mean()),
            "initialP95LandmarkErrorPixels": float(
                np.percentile(initial_error_np, 95)
            ),
            "finalMeanLandmarkErrorPixels": float(final_error_np.mean()),
            "finalP95LandmarkErrorPixels": float(
                np.percentile(final_error_np, 95)
            ),
            "cameraFullInitial": initial_camera.cpu().numpy().tolist(),
            "cameraFullFinal": camera_np.tolist(),
        }
        report["frames"].append(record)
        print(
            f"frame {frame}: mean landmark error "
            f"{record['initialMeanLandmarkErrorPixels']:.2f}px -> "
            f"{record['finalMeanLandmarkErrorPixels']:.2f}px",
            flush=True,
        )

    report_path = args.output_dir / "mano_hand_only_fit_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {report_path}", flush=True)


if __name__ == "__main__":
    main()
