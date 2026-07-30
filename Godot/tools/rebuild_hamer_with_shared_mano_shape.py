#!/usr/bin/env python3
"""Rebuild HaMeR outputs with one robust MANO shape shared across frames."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import shutil
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

from hamer.models.mano_wrapper import MANO


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--mano-model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--maximum-reconstruction-error-millimeters",
        type=float,
        default=0.5,
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _forward(
    mano: MANO,
    arrays: Any,
    betas: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    with torch.no_grad():
        output = mano(
            global_orient=torch.from_numpy(
                arrays["global_orient"].astype(np.float32)
            )[None],
            hand_pose=torch.from_numpy(arrays["hand_pose"].astype(np.float32))[
                None
            ],
            betas=torch.from_numpy(betas.astype(np.float32))[None],
            pose2rot=False,
        )
    vertices = output.vertices[0].cpu().numpy().astype(np.float32)
    joints = output.joints[0].cpu().numpy().astype(np.float32)
    if not bool(float(arrays["is_right"])):
        vertices[:, 0] *= -1.0
        joints[:, 0] *= -1.0
    return vertices, joints


def main() -> None:
    args = _parse_args()
    source_manifest_path = args.input_dir / "hamer_inference_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    frame_arrays = [
        np.load(args.input_dir / frame["arrays"])
        for frame in source_manifest["frames"]
    ]
    shared_betas = np.median(
        np.stack([arrays["betas"] for arrays in frame_arrays], axis=0),
        axis=0,
    ).astype(np.float32)

    mano = MANO(
        model_path=str(args.mano_model_path),
        is_rhand=True,
        use_pca=False,
        flat_hand_mean=False,
    )
    mano.eval()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for source_frame, arrays in zip(source_manifest["frames"], frame_arrays):
        frame_index = int(source_frame["frameIndex"])
        reproduced_vertices, reproduced_joints = _forward(
            mano, arrays, arrays["betas"]
        )
        vertex_error_mm = np.linalg.norm(
            reproduced_vertices - arrays["vertices_model"], axis=1
        ) * 1000.0
        joint_error_mm = np.linalg.norm(
            reproduced_joints - arrays["joints_model"], axis=1
        ) * 1000.0
        maximum_error_mm = float(vertex_error_mm.max())
        if maximum_error_mm > args.maximum_reconstruction_error_millimeters:
            raise RuntimeError(
                f"Frame {frame_index} MANO self-check failed: maximum vertex "
                f"error {maximum_error_mm:.4f} mm"
            )

        vertices, joints = _forward(mano, arrays, shared_betas)
        camera = arrays["cam_full"].astype(np.float32)
        vertices_camera = vertices + camera
        joints_camera = joints + camera
        focal_length = float(arrays["focal_length_px"])
        source_image_size = source_manifest.get("sourceImageSize", [640, 480])
        width, height = map(float, source_image_size)
        vertex_uv = np.column_stack(
            [
                focal_length * vertices_camera[:, 0] / vertices_camera[:, 2]
                + width * 0.5,
                focal_length * vertices_camera[:, 1] / vertices_camera[:, 2]
                + height * 0.5,
            ]
        ).astype(np.float32)
        joint_uv = np.column_stack(
            [
                focal_length * joints_camera[:, 0] / joints_camera[:, 2]
                + width * 0.5,
                focal_length * joints_camera[:, 1] / joints_camera[:, 2]
                + height * 0.5,
            ]
        ).astype(np.float32)

        output_name = f"hamer_{frame_index:06d}.npz"
        output_path = args.output_dir / output_name
        np.savez_compressed(
            output_path,
            vertices_model=vertices,
            vertices_camera=vertices_camera,
            joints_model=joints,
            joints_camera=joints_camera,
            faces=arrays["faces"],
            vertex_uv=vertex_uv,
            joint_uv=joint_uv,
            cam_crop=arrays["cam_crop"],
            cam_full=camera,
            focal_length_px=arrays["focal_length_px"],
            bbox_xyxy=arrays["bbox_xyxy"],
            crop_landmarks_xy=arrays["crop_landmarks_xy"],
            global_orient=arrays["global_orient"],
            hand_pose=arrays["hand_pose"],
            betas=shared_betas,
            original_frame_betas=arrays["betas"],
            is_right=arrays["is_right"],
        )
        overlay_name = source_frame.get("overlay")
        if overlay_name:
            source_overlay = args.input_dir / overlay_name
            if source_overlay.exists():
                shutil.copy2(source_overlay, args.output_dir / overlay_name)
        output_frame = dict(source_frame)
        output_frame["arrays"] = output_name
        output_frame["arraysSha256"] = _sha256(output_path)
        output_frame["manoSelfCheckMaximumVertexErrorMillimeters"] = (
            maximum_error_mm
        )
        output_frame["manoSelfCheckMaximumJointErrorMillimeters"] = float(
            joint_error_mm.max()
        )
        records.append(output_frame)
        print(
            f"frame {frame_index}: self-check max vertex "
            f"{maximum_error_mm:.6f} mm"
        )

    output_manifest = dict(source_manifest)
    output_manifest["frames"] = records
    output_manifest["shapePolicy"] = (
        "component-wise median MANO betas shared by every frame"
    )
    output_manifest["sharedBetas"] = shared_betas.tolist()
    output_manifest["sourceInferenceManifest"] = str(
        source_manifest_path.resolve()
    )
    output_manifest["sourceInferenceManifestSha256"] = _sha256(
        source_manifest_path
    )
    output_manifest_path = args.output_dir / "hamer_inference_manifest.json"
    output_manifest_path.write_text(
        json.dumps(output_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_manifest_path}")


if __name__ == "__main__":
    main()
