#!/usr/bin/env python3
"""Run WiLoR on RGB frames using an existing model-produced hand track crop.

The track sidecar supplies only a stable image crop and handedness. WiLoR
predicts MANO pose, shape, camera, joints, and vertices from the RGB crop.
No mask or hand-authored pose correction is used.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
os.environ.setdefault("PYGLET_HEADLESS", "true")
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

import cv2
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

import torch


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wilor-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--track-json", type=Path, required=True)
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
        help="Python format string resolved below --rgb-dir.",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--rescale-factor", type=float, default=2.5)
    parser.add_argument(
        "--handedness",
        choices=("track", "right", "left"),
        default="track",
    )
    parser.add_argument("--no-overlay", action="store_true")
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


def _load_track(path: Path) -> tuple[dict[int, dict[str, Any]], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tracks = payload.get("hand_tracks", [])
    if len(tracks) != 1:
        raise ValueError(f"Expected exactly one hand track, found {len(tracks)}")
    track = tracks[0]
    samples = {int(sample["frameIndex"]): sample for sample in track["samples"]}
    return samples, str(track.get("handedness", "right")).lower()


def _bbox_from_landmarks(sample: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    landmarks = np.asarray(sample["pixelLandmarks"], dtype=np.float32)
    if landmarks.shape != (21, 2) or not np.isfinite(landmarks).all():
        raise ValueError(
            f"Frame {sample.get('frameIndex')} has invalid pixelLandmarks shape/data"
        )
    bbox = np.concatenate([landmarks.min(axis=0), landmarks.max(axis=0)])
    if np.any(bbox[2:] - bbox[:2] < 8.0):
        raise ValueError(f"Frame {sample.get('frameIndex')} has a degenerate crop")
    return bbox, landmarks


def _to_device(value: Any, device: torch.device) -> Any:
    if isinstance(value, torch.Tensor):
        return value.to(device)
    if isinstance(value, dict):
        return {key: _to_device(item, device) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_device(item, device) for item in value]
    return value


def _diagnostic_overlay(
    image_bgr: np.ndarray,
    projected_vertices: np.ndarray,
    projected_joints: np.ndarray,
    faces: np.ndarray,
    landmarks: np.ndarray,
    bbox: np.ndarray,
) -> np.ndarray:
    height, width = image_bgr.shape[:2]
    finite = np.isfinite(projected_vertices).all(axis=1)
    inside = (
        finite
        & (projected_vertices[:, 0] >= -width)
        & (projected_vertices[:, 0] < 2 * width)
        & (projected_vertices[:, 1] >= -height)
        & (projected_vertices[:, 1] < 2 * height)
    )
    valid_faces = faces[np.all(inside[faces], axis=1)]
    silhouette = np.zeros((height, width), dtype=np.uint8)
    projected_int = np.rint(projected_vertices).astype(np.int32)
    for face in valid_faces:
        cv2.fillConvexPoly(silhouette, projected_int[face], 255, lineType=cv2.LINE_AA)

    result = image_bgr.copy()
    color = np.zeros_like(result)
    color[:, :] = (190, 120, 245)
    alpha = (silhouette.astype(np.float32) / 255.0 * 0.52)[..., None]
    result = np.rint(result * (1.0 - alpha) + color * alpha).astype(np.uint8)

    x0, y0, x1, y1 = np.rint(bbox).astype(int)
    cv2.rectangle(result, (x0, y0), (x1, y1), (50, 220, 255), 1)
    for point in np.rint(landmarks).astype(int):
        cv2.circle(result, tuple(point), 2, (70, 255, 90), -1, cv2.LINE_AA)

    skeleton_edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (0, 5),
        (5, 6),
        (6, 7),
        (7, 8),
        (0, 9),
        (9, 10),
        (10, 11),
        (11, 12),
        (0, 13),
        (13, 14),
        (14, 15),
        (15, 16),
        (0, 17),
        (17, 18),
        (18, 19),
        (19, 20),
    ]
    joint_pixels = np.rint(projected_joints).astype(np.int32)
    joint_valid = np.isfinite(projected_joints).all(axis=1)
    for start, end in skeleton_edges:
        if joint_valid[start] and joint_valid[end]:
            cv2.line(
                result,
                tuple(joint_pixels[start]),
                tuple(joint_pixels[end]),
                (255, 95, 45),
                2,
                cv2.LINE_AA,
            )
    for point, valid in zip(joint_pixels, joint_valid):
        if valid:
            cv2.circle(result, tuple(point), 2, (255, 245, 220), -1, cv2.LINE_AA)
    return result


def main() -> None:
    args = _parse_args()
    frames = _frame_indices(args.frames)
    args.wilor_root = args.wilor_root.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.config = args.config.resolve()
    args.track_json = args.track_json.resolve()
    args.rgb_dir = args.rgb_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    for path in (
        args.wilor_root,
        args.checkpoint,
        args.config,
        args.track_json,
        args.rgb_dir,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    sys.path.insert(0, str(args.wilor_root))
    os.chdir(args.wilor_root)
    from wilor.datasets.vitdet_dataset import ViTDetDataset
    from wilor.models import load_wilor
    from wilor.utils.renderer import cam_crop_to_full

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA device requested but unavailable: {device}")

    samples, track_handedness = _load_track(args.track_json)
    handedness = (
        track_handedness if args.handedness == "track" else args.handedness
    )
    if handedness not in {"right", "left"}:
        raise ValueError(f"Unsupported handedness: {handedness}")
    is_right = np.float32(handedness == "right")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model, model_cfg = load_wilor(
        checkpoint_path=str(args.checkpoint),
        cfg_path=str(args.config),
    )
    model = model.to(device).eval()
    faces = np.asarray(model.mano.faces, dtype=np.int32)

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "method": "WiLoR MANO inference from raw RGB; track landmarks used for crop only",
        "wilorRoot": str(args.wilor_root),
        "checkpoint": str(args.checkpoint),
        "checkpointSha256": _sha256(args.checkpoint),
        "config": str(args.config),
        "configSha256": _sha256(args.config),
        "trackJson": str(args.track_json),
        "trackJsonSha256": _sha256(args.track_json),
        "rgbDir": str(args.rgb_dir),
        "framesRequested": frames,
        "handedness": handedness,
        "rescaleFactor": args.rescale_factor,
        "device": str(device),
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cudaRuntime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
        "frames": [],
    }

    for frame_index in frames:
        if frame_index not in samples:
            raise KeyError(f"No exact track sample for frame {frame_index}")
        sample = samples[frame_index]
        bbox, landmarks = _bbox_from_landmarks(sample)
        image_path = args.rgb_dir / args.image_pattern.format(frame=frame_index)
        image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise FileNotFoundError(image_path)

        dataset = ViTDetDataset(
            model_cfg,
            image_bgr,
            bbox[None, :],
            np.asarray([is_right], dtype=np.float32),
            rescale_factor=args.rescale_factor,
        )
        batch = torch.utils.data.default_collate([dataset[0]])
        batch = _to_device(batch, device)
        with torch.inference_mode():
            output = model(batch)

        multiplier = 2.0 * batch["right"] - 1.0
        pred_cam = output["pred_cam"].clone()
        pred_cam[:, 1] *= multiplier
        box_center = batch["box_center"].float()
        box_size = batch["box_size"].float()
        image_size = batch["img_size"].float()
        focal_length = (
            model_cfg.EXTRA.FOCAL_LENGTH
            / model_cfg.MODEL.IMAGE_SIZE
            * image_size.max()
        )
        camera_full = cam_crop_to_full(
            pred_cam, box_center, box_size, image_size, focal_length
        )[0]

        vertices = output["pred_vertices"][0].detach().cpu().numpy()
        joints = output["pred_keypoints_3d"][0].detach().cpu().numpy()
        if not bool(is_right):
            vertices[:, 0] *= -1.0
            joints[:, 0] *= -1.0
        camera_full_np = camera_full.detach().cpu().numpy()
        vertices_camera = vertices + camera_full_np
        joints_camera = joints + camera_full_np
        width, height = image_size[0].detach().cpu().numpy()
        projected_vertices = np.column_stack(
            [
                focal_length.item() * vertices_camera[:, 0] / vertices_camera[:, 2]
                + width / 2.0,
                focal_length.item() * vertices_camera[:, 1] / vertices_camera[:, 2]
                + height / 2.0,
            ]
        )
        projected_joints = np.column_stack(
            [
                focal_length.item() * joints_camera[:, 0] / joints_camera[:, 2]
                + width / 2.0,
                focal_length.item() * joints_camera[:, 1] / joints_camera[:, 2]
                + height / 2.0,
            ]
        )
        params = {
            key: value[0].detach().cpu().numpy()
            for key, value in output["pred_mano_params"].items()
        }
        stem = f"wilor_{frame_index:06d}"
        array_path = args.output_dir / f"{stem}.npz"
        np.savez_compressed(
            array_path,
            vertices_model=vertices,
            vertices_camera=vertices_camera,
            joints_model=joints,
            joints_camera=joints_camera,
            faces=faces,
            vertex_uv=projected_vertices,
            joint_uv=projected_joints,
            cam_crop=pred_cam[0].detach().cpu().numpy(),
            cam_full=camera_full_np,
            focal_length_px=np.float32(focal_length.item()),
            bbox_xyxy=bbox,
            crop_landmarks_xy=landmarks,
            global_orient=params["global_orient"],
            hand_pose=params["hand_pose"],
            betas=params["betas"],
            is_right=is_right,
        )

        overlay_name = None
        if not args.no_overlay:
            overlay = _diagnostic_overlay(
                image_bgr,
                projected_vertices,
                projected_joints,
                faces,
                landmarks,
                bbox,
            )
            overlay_path = args.output_dir / f"{stem}_overlay.png"
            if not cv2.imwrite(str(overlay_path), overlay):
                raise RuntimeError(f"Failed to write {overlay_path}")
            overlay_name = overlay_path.name

        manifest["frames"].append(
            {
                "frameIndex": frame_index,
                "sourceImage": str(image_path),
                "sourceImageSha256": _sha256(image_path),
                "trackConfidence": sample.get("confidence"),
                "trackIntent": sample.get("intent"),
                "bboxXyxy": bbox.tolist(),
                "cropBoxSize": float(box_size[0].item()),
                "cameraFull": camera_full_np.tolist(),
                "focalLengthPx": float(focal_length.item()),
                "arrays": array_path.name,
                "arraysSha256": _sha256(array_path),
                "overlay": overlay_name,
            }
        )
        print(f"frame {frame_index}: {array_path.name}", flush=True)

    manifest_path = args.output_dir / "wilor_inference_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
