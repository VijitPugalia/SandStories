#!/usr/bin/env python3
"""Evaluate OmniHands video inference with a model-produced right-hand track.

This is an isolated research benchmark for temporal hand-pose recovery. The
right-hand track supplies crop boxes only. A constant off-image crop represents
the absent left hand; no mask, pose edit, or gesture rule is used.
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

import einops
import torch


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omnihands-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--track-json", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-frame", type=int, required=True)
    parser.add_argument("--end-frame", type=int, required=True)
    parser.add_argument(
        "--review-frames",
        default="",
        help="Comma-separated global frame indices that receive PNG overlays.",
    )
    parser.add_argument(
        "--image-pattern",
        default="clean_rgb_{frame:06d}.png",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--rescale-factor", type=float, default=2.0)
    parser.add_argument("--sequence-gap", type=int, default=10)
    parser.add_argument("--token-batch-size", type=int, default=8)
    parser.add_argument("--temporal-batch-size", type=int, default=4)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_frame_set(value: str) -> set[int]:
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def _track_samples(path: Path) -> dict[int, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tracks = payload.get("hand_tracks", [])
    if len(tracks) != 1:
        raise ValueError(f"Expected exactly one hand track, found {len(tracks)}")
    return {
        int(sample["frameIndex"]): sample for sample in tracks[0]["samples"]
    }


def _bbox(sample: dict[str, Any]) -> np.ndarray:
    landmarks = np.asarray(sample["pixelLandmarks"], dtype=np.float32)
    if landmarks.shape != (21, 2) or not np.isfinite(landmarks).all():
        raise ValueError(
            f"Frame {sample.get('frameIndex')} has invalid pixel landmarks"
        )
    result = np.concatenate([landmarks.min(axis=0), landmarks.max(axis=0)])
    if np.any(result[2:] - result[:2] < 8.0):
        raise ValueError(f"Frame {sample.get('frameIndex')} has a degenerate crop")
    return result


def _smooth_box_sizes(boxes: list[np.ndarray], window: int = 30) -> list[np.ndarray]:
    widths = np.asarray([box[2:] - box[:2] for box in boxes], dtype=np.float64)
    half = window // 2
    result: list[np.ndarray] = []
    for index, box in enumerate(boxes):
        start = max(0, index - half)
        end = min(len(boxes), index + half + 1)
        size = widths[start:end].mean(axis=0)
        center = (box[:2] + box[2:]) * 0.5
        result.append(
            np.concatenate([center - size * 0.5, center + size * 0.5]).astype(
                np.float32
            )
        )
    return result


def _sequences(frame_count: int, sequence_length: int, gap: int) -> np.ndarray:
    rows: list[list[int]] = []
    for frame in range(frame_count):
        start = frame - (sequence_length // 2) * gap
        rows.append(
            [
                min(max(start + step * gap, 0), frame_count - 1)
                for step in range(sequence_length)
            ]
        )
    return np.asarray(rows, dtype=np.int64)


def _project(
    points: np.ndarray,
    camera: np.ndarray,
    focal_length: float,
    width: int,
    height: int,
) -> np.ndarray:
    camera_points = points + camera[None, :]
    return np.column_stack(
        [
            focal_length * camera_points[:, 0] / camera_points[:, 2] + width / 2,
            focal_length * camera_points[:, 1] / camera_points[:, 2] + height / 2,
        ]
    )


def _overlay(
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
    vertices_int = np.rint(projected_vertices).astype(np.int32)
    for face in valid_faces:
        cv2.fillConvexPoly(silhouette, vertices_int[face], 255, cv2.LINE_AA)

    result = image_bgr.copy()
    color = np.zeros_like(result)
    color[:] = (120, 215, 245)
    alpha = (silhouette.astype(np.float32) / 255.0 * 0.55)[..., None]
    result = np.rint(result * (1.0 - alpha) + color * alpha).astype(np.uint8)

    x0, y0, x1, y1 = np.rint(bbox).astype(int)
    cv2.rectangle(result, (x0, y0), (x1, y1), (50, 220, 255), 1)
    for point in np.rint(landmarks).astype(int):
        cv2.circle(result, tuple(point), 2, (70, 255, 90), -1, cv2.LINE_AA)

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
    ]
    joints_int = np.rint(projected_joints).astype(np.int32)
    joints_valid = np.isfinite(projected_joints).all(axis=1)
    for start, end in edges:
        if joints_valid[start] and joints_valid[end]:
            cv2.line(
                result,
                tuple(joints_int[start]),
                tuple(joints_int[end]),
                (255, 95, 45),
                2,
                cv2.LINE_AA,
            )
    for point, valid in zip(joints_int, joints_valid):
        if valid:
            cv2.circle(result, tuple(point), 2, (255, 245, 220), -1, cv2.LINE_AA)
    return result


def main() -> None:
    args = _parse_args()
    if args.start_frame < 0 or args.end_frame < args.start_frame:
        raise ValueError("Invalid start/end frame range")
    review_frames = _parse_frame_set(args.review_frames)
    args.omnihands_root = args.omnihands_root.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.config = args.config.resolve()
    args.track_json = args.track_json.resolve()
    args.rgb_dir = args.rgb_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    for path in (
        args.omnihands_root,
        args.checkpoint,
        args.config,
        args.track_json,
        args.rgb_dir,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    sys.path.insert(0, str(args.omnihands_root))
    os.chdir(args.omnihands_root)
    from hands_4d.datasets.vitdet_dataset import (
        HandToken_Sequence,
        ViTDetInterDataset_Batch,
        ViTDetInterDataset_Sequence,
    )
    from hands_4d.models import load_from_ckpt
    from hands_4d.utils import recursive_to

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CUDA device unavailable: {device}")

    samples = _track_samples(args.track_json)
    frame_indices = list(range(args.start_frame, args.end_frame + 1))
    images: list[torch.Tensor] = []
    boxes: list[np.ndarray] = []
    landmarks_by_frame: dict[int, np.ndarray] = {}
    image_paths: list[Path] = []
    for frame_index in frame_indices:
        if frame_index not in samples:
            raise KeyError(f"No exact track sample for frame {frame_index}")
        sample = samples[frame_index]
        image_path = args.rgb_dir / args.image_pattern.format(frame=frame_index)
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(image_path)
        images.append(torch.from_numpy(image))
        boxes.append(_bbox(sample))
        landmarks_by_frame[frame_index] = np.asarray(
            sample["pixelLandmarks"], dtype=np.float32
        )
        image_paths.append(image_path)

    boxes = _smooth_box_sizes(boxes)
    bbox_payload = {
        "right": {str(index): box.tolist() for index, box in enumerate(boxes)},
        # The official model requires paired hand crops. This constant crop is
        # fully outside the image and explicitly represents a missing left hand.
        "left": {
            str(index): [-64.0, -64.0, -32.0, -32.0]
            for index in range(len(frame_indices))
        },
    }

    model, model_cfg = load_from_ckpt(str(args.checkpoint), str(args.config))
    model = model.to(device).eval()
    faces = np.asarray(model.mano.faces, dtype=np.int32)
    sequences = _sequences(
        len(frame_indices),
        int(model_cfg.MODEL.SEQ_LEN),
        args.sequence_gap,
    )
    single_dataset = ViTDetInterDataset_Batch(
        model_cfg,
        images,
        bbox_payload,
        rescale_factor=args.rescale_factor,
    )
    sequence_dataset = ViTDetInterDataset_Sequence(
        model_cfg,
        images,
        bbox_payload,
        sequences,
        rescale_factor=args.rescale_factor,
    )

    single_loader = torch.utils.data.DataLoader(
        single_dataset,
        batch_size=args.token_batch_size,
        shuffle=False,
        num_workers=0,
    )
    tokens: list[torch.Tensor] = []
    with torch.inference_mode():
        for batch in single_loader:
            batch = recursive_to(batch, device)
            value = model.inference_token_forward(batch)
            value = einops.rearrange(value, "(b s) c -> b s c", s=2)
            tokens.append(value.detach().cpu())
    all_tokens = torch.cat(tokens, dim=0)

    token_dataset = HandToken_Sequence(all_tokens, sequences)
    token_loader = torch.utils.data.DataLoader(
        token_dataset,
        batch_size=args.temporal_batch_size,
        shuffle=False,
        num_workers=0,
    )
    sequence_loader = torch.utils.data.DataLoader(
        sequence_dataset,
        batch_size=args.temporal_batch_size,
        shuffle=False,
        num_workers=0,
    )

    output_chunks: dict[str, list[np.ndarray]] = {}
    with torch.inference_mode():
        for token_batch, sequence_batch in zip(token_loader, sequence_loader):
            sequence_batch = recursive_to(sequence_batch, device)
            token_batch = token_batch.to(device)
            token_batch = einops.rearrange(
                token_batch, "b t s c -> (b t s) c"
            )
            output = model.inference_temp_forward(token_batch, sequence_batch)
            for key, value in output.items():
                if isinstance(value, torch.Tensor):
                    output_chunks.setdefault(key, []).append(
                        value.detach().cpu().numpy()
                    )
    outputs = {
        key: np.concatenate(values, axis=0)
        for key, values in output_chunks.items()
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    height, width = images[0].shape[:2]
    focal_length = (
        model_cfg.EXTRA.FOCAL_LENGTH
        / model_cfg.MODEL.IMAGE_SIZE
        * max(width, height)
    )
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "method": (
            "OmniHands official video checkpoint; true RGB; model track used "
            "for right crop only; constant off-image missing-left sentinel"
        ),
        "omnihandsRoot": str(args.omnihands_root),
        "checkpoint": str(args.checkpoint),
        "checkpointSha256": _sha256(args.checkpoint),
        "config": str(args.config),
        "configSha256": _sha256(args.config),
        "trackJson": str(args.track_json),
        "trackJsonSha256": _sha256(args.track_json),
        "rgbDir": str(args.rgb_dir),
        "startFrame": args.start_frame,
        "endFrame": args.end_frame,
        "reviewFrames": sorted(review_frames),
        "rescaleFactor": args.rescale_factor,
        "sequenceLength": int(model_cfg.MODEL.SEQ_LEN),
        "sequenceGap": args.sequence_gap,
        "postInferenceVertexSmoothing": False,
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cudaRuntime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(device),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
        },
        "frames": [],
    }

    for local_index, frame_index in enumerate(frame_indices):
        vertices = outputs["verts3d_world_right"][local_index]
        joints = outputs["joints3d_world_right"][local_index]
        camera = outputs["cam_aligned_right"][local_index]
        projected_vertices = _project(
            vertices, camera, float(focal_length), width, height
        )
        projected_joints = _project(
            joints, camera, float(focal_length), width, height
        )
        array_path = args.output_dir / f"omnihands_{frame_index:06d}.npz"
        np.savez_compressed(
            array_path,
            vertices_model=vertices,
            vertices_camera=vertices + camera[None, :],
            joints_model=joints,
            joints_camera=joints + camera[None, :],
            faces=faces,
            vertex_uv=projected_vertices,
            joint_uv=projected_joints,
            cam_full=camera,
            focal_length_px=np.float32(focal_length),
            bbox_xyxy=boxes[local_index],
            crop_landmarks_xy=landmarks_by_frame[frame_index],
            mano_pose=outputs["mano_pose_right"][local_index],
            betas=outputs["mano_shape_right"][local_index],
            is_right=np.float32(1.0),
        )

        overlay_name = None
        if frame_index in review_frames:
            image_bgr = images[local_index].numpy()
            overlay = _overlay(
                image_bgr,
                projected_vertices,
                projected_joints,
                faces,
                landmarks_by_frame[frame_index],
                boxes[local_index],
            )
            overlay_path = args.output_dir / (
                f"omnihands_{frame_index:06d}_overlay.png"
            )
            if not cv2.imwrite(str(overlay_path), overlay):
                raise RuntimeError(f"Failed to write {overlay_path}")
            overlay_name = overlay_path.name

        manifest["frames"].append(
            {
                "frameIndex": frame_index,
                "sourceImage": str(image_paths[local_index]),
                "sourceImageSha256": _sha256(image_paths[local_index]),
                "arrays": array_path.name,
                "arraysSha256": _sha256(array_path),
                "overlay": overlay_name,
            }
        )
        print(f"frame {frame_index}: {array_path.name}", flush=True)

    manifest_path = args.output_dir / "omnihands_inference_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
