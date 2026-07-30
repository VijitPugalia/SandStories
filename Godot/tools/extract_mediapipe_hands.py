#!/usr/bin/env python3
"""Extract MediaPipe hand tracks from Kinect RGB frames for Godot playback.

The output is a small JSON sidecar containing Godot-space hand landmarks. It is
intended to run on an uncleaned RGB-D session, then be attached to a cleaned
session for visualization.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


DEFAULT_COLORS = {
    "left": "#f1a85b",
    "right": "#5ec8d8",
}
PALM_ANCHOR_INDICES = [0, 5, 9, 13, 17]
FINGERTIP_INDICES = [4, 8, 12, 16, 20]
DEFAULT_HAND_LANDMARKER_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
DEFAULT_HAND_LANDMARKER_PATH = Path("/tmp/opencode/hand_landmarker.task")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _session_path(path: Path) -> Path:
    return path / "session.json" if path.is_dir() else path


def _resolve_asset(base_dir: Path, value: str) -> Path:
    if value.startswith("res://assets/processed_sessions/"):
        return base_dir / Path(value).name
    if value.startswith("res://"):
        raise ValueError(f"Cannot resolve project resource outside this session: {value}")
    return base_dir / value


def _manifest_path(session_path: Path, session: dict[str, Any]) -> Path:
    data_sources = session.get("data_sources", {})
    manifest = str(data_sources.get("processed_manifest", ""))
    if not manifest:
        raise ValueError("Session has no data_sources.processed_manifest")
    return _resolve_asset(session_path.parent, manifest)


def _calibration(session: dict[str, Any]) -> dict[str, Any]:
    data_sources = session.get("data_sources", {})
    calibration = data_sources.get("calibration", {})
    return calibration if isinstance(calibration, dict) else {}


def _depth_profile_arg1(depth_name: str) -> float:
    if depth_name.startswith("detail_depth_fused_"):
        return 3.4
    if depth_name.startswith("detail_depth_"):
        return 3.0
    return 11.625


def _depth_profile_background(depth_name: str) -> float:
    return 0.5 if depth_name.startswith("detail_depth") else 1.0


def _read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _read_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def _sample_depth(depth: np.ndarray, x: float, y: float, radius: int) -> float:
    h, w = depth.shape
    px = int(round(x))
    py = int(round(y))
    x1 = max(0, px - radius)
    x2 = min(w, px + radius + 1)
    y1 = max(0, py - radius)
    y2 = min(h, py + radius + 1)
    patch = depth[y1:y2, x1:x2]
    if patch.size == 0:
        return 0.0
    return float(np.mean(patch))


def _height_from_depth_value(value: float, height_scale: float, arg1: float, background: float) -> float:
    # Mirrors sand_depth.gdshader's vertex displacement closely enough for overlay.
    h = value if abs(value - background) > 0.004 else background
    return -(h / arg1) * height_scale


def _landmark_to_world(
    landmark: Any,
    width: int,
    height: int,
    depth: np.ndarray | None,
    plane_size: float,
    height_scale: float,
    arg1: float,
    background: float,
    sample_radius: int,
    hand_lift: float,
    mediapipe_z_scale: float,
) -> tuple[list[float], dict[str, float]]:
    px = float(landmark.x) * float(width - 1)
    py = float(landmark.y) * float(height - 1)
    depth_value = _sample_depth(depth, px, py, sample_radius) if depth is not None else background
    world_x = (float(landmark.x) - 0.5) * plane_size
    world_z = (float(landmark.y) - 0.5) * plane_size
    world_y = _height_from_depth_value(depth_value, height_scale, arg1, background)
    surface_y = world_y
    world_y += hand_lift + (-float(landmark.z) * mediapipe_z_scale)
    return [round(world_x, 5), round(world_y, 5), round(world_z, 5)], {
        "x": round(px, 3),
        "y": round(py, 3),
        "z": round(float(landmark.z), 6),
        "depth": round(depth_value, 6),
        "surfaceY": round(surface_y, 6),
    }


def _median(values: list[float], fallback: float = 0.0) -> float:
    if not values:
        return fallback
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) * 0.5


def _adjust_hand_height(
    world_landmarks: list[list[float]],
    debug_landmarks: list[dict[str, float]],
    args: argparse.Namespace,
) -> list[list[float]]:
    if args.height_mode == "surface":
        return world_landmarks
    if len(world_landmarks) < 21 or len(debug_landmarks) < 21:
        return world_landmarks

    surface_ys = [float(item.get("surfaceY", world_landmarks[index][1])) for index, item in enumerate(debug_landmarks)]
    palm_surface = _median([surface_ys[index] for index in PALM_ANCHOR_INDICES], surface_ys[0])
    adjusted = [point[:] for point in world_landmarks]

    # Keep the hand mostly rigid in Y. This prevents each joint from inheriting a
    # different sand height, while preserving a small MediaPipe relative-Z shape.
    for index, point in enumerate(adjusted):
        mp_z = float(debug_landmarks[index].get("z", 0.0))
        point[1] = palm_surface + args.hand_hover + (-mp_z * args.mediapipe_z_scale)

    contact_indices = [index for index in args.contact_indices if 0 <= index < len(adjusted)]
    if contact_indices:
        if args.contact_shift_hand:
            gaps = [adjusted[index][1] - surface_ys[index] for index in contact_indices]
            closest_gap = min(gaps)
            shift = args.contact_lift - closest_gap
            for point in adjusted:
                point[1] += shift

        strength = max(0.0, min(1.0, args.contact_snap_strength))
        for index in contact_indices:
            target_y = surface_ys[index] + args.contact_lift
            adjusted[index][1] = adjusted[index][1] * (1.0 - strength) + target_y * strength

    return [[round(point[0], 5), round(point[1], 5), round(point[2], 5)] for point in adjusted]


def _track_id(handedness: str, occurrence: int, handedness_count: int) -> str:
    label = handedness.lower() if handedness else "hand"
    if handedness_count <= 1:
        return f"{label}_hand"
    return f"{label}_hand_{occurrence + 1}"


def _best_hand_index(handedness_items: list[dict[str, Any]], count: int) -> int:
    best_index = 0
    best_score = -1.0
    for hand_index in range(count):
        score = 0.0
        if hand_index < len(handedness_items):
            score = float(handedness_items[hand_index].get("score", 0.0))
        if score > best_score:
            best_score = score
            best_index = hand_index
    return best_index


def _ensure_landmarker_model(path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading MediaPipe hand landmarker model to {path}")
    urllib.request.urlretrieve(DEFAULT_HAND_LANDMARKER_URL, path)
    return path


def _create_hand_landmarker(args: argparse.Namespace):
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = _ensure_landmarker_model(args.model_asset)
    base_options = python.BaseOptions(model_asset_path=str(model_path))
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        num_hands=args.max_num_hands,
        min_hand_detection_confidence=args.min_detection_confidence,
        min_hand_presence_confidence=args.min_tracking_confidence,
        min_tracking_confidence=args.min_tracking_confidence,
    )
    return vision.HandLandmarker.create_from_options(options)


def _detect_hands(landmarker: Any, rgb: np.ndarray) -> tuple[list[Any], list[dict[str, Any]]]:
    import mediapipe as mp

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect(mp_image)
    landmarks = list(result.hand_landmarks or [])
    handedness: list[dict[str, Any]] = []
    for item in result.handedness or []:
        if len(item) == 0:
            handedness.append({"label": "hand", "score": 0.0})
            continue
        category = item[0]
        handedness.append({"label": str(category.category_name).lower(), "score": float(category.score)})
    return landmarks, handedness


def extract_hands(args: argparse.Namespace) -> dict[str, Any]:
    session_path = _session_path(args.source_session)
    session = _load_json(session_path)
    manifest_path = _manifest_path(session_path, session)
    manifest = _load_json(manifest_path)
    frames = manifest.get("frames", [])
    calibration = _calibration(session)
    height_scale = args.height_scale
    if height_scale is None:
        height_scale = float(calibration.get("height_scale", -1.9))

    tracks: dict[str, dict[str, Any]] = {}
    debug_frames: list[dict[str, Any]] = []
    detected_frame_count = 0
    processed_frame_count = 0

    with _create_hand_landmarker(args) as landmarker:
        for source_index, frame in enumerate(frames):
            if source_index < args.start_frame:
                continue
            if args.max_frames is not None and processed_frame_count >= args.max_frames:
                break
            if (source_index - args.start_frame) % args.frame_step != 0:
                continue
            if not isinstance(frame, dict):
                continue

            rgb_name = str(frame.get(args.rgb_key, ""))
            if not rgb_name:
                continue
            rgb_path = _resolve_asset(manifest_path.parent, rgb_name)
            if not rgb_path.exists():
                continue

            depth_name = str(frame.get(args.depth_key, ""))
            if not depth_name and args.depth_key != "cleanDepth":
                depth_name = str(frame.get("cleanDepth", ""))
            depth_path = _resolve_asset(manifest_path.parent, depth_name) if depth_name else None
            depth = _read_gray(depth_path) if depth_path is not None and depth_path.exists() else None
            arg1 = args.arg1 if args.arg1 is not None else _depth_profile_arg1(depth_path.name if depth_path else "")
            background = args.background if args.background is not None else _depth_profile_background(depth_path.name if depth_path else "")

            rgb = _read_rgb(rgb_path)
            height, width = rgb.shape[:2]
            landmark_items, handedness_items = _detect_hands(landmarker, rgb)
            if args.merge_handedness_duplicates and len(landmark_items) > 1:
                selected: dict[str, tuple[float, Any, dict[str, Any]]] = {}
                for hand_index, landmarks in enumerate(landmark_items):
                    handedness_item = handedness_items[hand_index] if hand_index < len(handedness_items) else {"label": "hand", "score": 0.0}
                    label = str(handedness_item.get("label", "hand")).lower()
                    score = float(handedness_item.get("score", 0.0))
                    if label not in selected or score > selected[label][0]:
                        selected[label] = (score, landmarks, handedness_item)
                landmark_items = [item[1] for item in selected.values()]
                handedness_items = [item[2] for item in selected.values()]
            if args.single_hand_track and len(landmark_items) > 1:
                best_index = _best_hand_index(handedness_items, len(landmark_items))
                landmark_items = [landmark_items[best_index]]
                handedness_items = [handedness_items[best_index] if best_index < len(handedness_items) else {"label": "hand", "score": 0.0}]
            hand_entries: list[dict[str, Any]] = []
            if landmark_items:
                detected_frame_count += 1

            handedness_counts: dict[str, int] = {}
            for handedness_item in handedness_items:
                label = str(handedness_item.get("label", "hand")).lower()
                handedness_counts[label] = handedness_counts.get(label, 0) + 1
            handedness_seen: dict[str, int] = {}

            for hand_index, landmarks in enumerate(landmark_items):
                handedness = "hand"
                score = 0.0
                if hand_index < len(handedness_items):
                    handedness = str(handedness_items[hand_index].get("label", "hand")).lower()
                    score = float(handedness_items[hand_index].get("score", 0.0))
                occurrence = handedness_seen.get(handedness, 0)
                handedness_seen[handedness] = occurrence + 1
                if args.single_hand_track:
                    track_id = args.single_track_id
                    track_label = args.single_track_label
                    track_handedness = "primary"
                    color = args.single_track_color
                else:
                    track_id = _track_id(handedness, occurrence, handedness_counts.get(handedness, 1))
                    track_label = f"{handedness.capitalize()} hand"
                    track_handedness = handedness
                    color = DEFAULT_COLORS.get(handedness, "#5ec8d8")
                if track_id not in tracks:
                    tracks[track_id] = {
                        "id": track_id,
                        "label": track_label,
                        "handedness": track_handedness,
                        "color": color,
                        "joint_count": 21,
                        "virtual_hand": True,
                        "show_landmarks": args.show_landmarks,
                        "show_skeleton": args.show_skeleton,
                        "interpolation": args.interpolation,
                        "samples": [],
                    }
                world_landmarks: list[list[float]] = []
                debug_landmarks: list[dict[str, float]] = []
                for landmark in landmarks:
                    world, debug = _landmark_to_world(
                        landmark,
                        width,
                        height,
                        depth,
                        args.plane_size,
                        height_scale,
                        arg1,
                        background,
                        args.depth_sample_radius,
                        args.hand_lift,
                        args.mediapipe_z_scale,
                    )
                    world_landmarks.append(world)
                    debug_landmarks.append(debug)
                world_landmarks = _adjust_hand_height(world_landmarks, debug_landmarks, args)
                sample = {
                    "time": float(frame.get("time", 0.0)),
                    "frameIndex": int(frame.get("frameIndex", source_index)),
                    "landmarks": world_landmarks,
                    "confidence": round(score, 6),
                }
                tracks[track_id]["samples"].append(sample)
                hand_entries.append({
                    "id": track_id,
                    "handedness": handedness,
                    "confidence": round(score, 6),
                    "landmarks": world_landmarks,
                    "pixels": debug_landmarks,
                })

            debug_frames.append({
                "frameIndex": int(frame.get("frameIndex", source_index)),
                "time": float(frame.get("time", 0.0)),
                "rgb": rgb_name,
                "depth": depth_name,
                "hands": hand_entries,
            })
            processed_frame_count += 1

    track_list = list(tracks.values())
    return {
        "schemaVersion": 1,
        "sourceSession": str(session_path),
        "sourceManifest": str(manifest_path),
        "method": "mediapipe.tasks.hand_landmarker + Godot heightmap depth sampling + %s height" % args.height_mode,
        "frameCount": processed_frame_count,
        "detectedFrameCount": detected_frame_count,
        "planeSize": args.plane_size,
        "heightScale": height_scale,
        "handLift": args.hand_lift,
        "mediapipeZScale": args.mediapipe_z_scale,
        "heightMode": args.height_mode,
        "handHover": args.hand_hover,
        "contactLift": args.contact_lift,
        "contactSnapStrength": args.contact_snap_strength,
        "contactIndices": args.contact_indices,
        "contactShiftHand": args.contact_shift_hand,
        "hand_tracks": track_list,
        "mediapipe_hands": debug_frames,
    }


def attach_hand_tracks(session_path: Path, hand_tracks_path: Path, output_path: Path | None) -> None:
    session_path = _session_path(session_path)
    session = _load_json(session_path)
    data_sources = session.setdefault("data_sources", {})
    relative = hand_tracks_path.name if hand_tracks_path.parent == session_path.parent else str(hand_tracks_path)
    data_sources["hand_tracks"] = relative
    production = session.setdefault("production_session", {})
    production["handTracking"] = {
        "method": "mediapipe_hands_depth_heightmap_sidecar",
        "path": relative,
        "note": "Hand tracks are extracted from RGB and lifted into Godot space using per-frame depth maps.",
    }
    _save_json(output_path or session_path, session)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_session", type=Path, help="Session JSON or session directory to read RGB-D frames from.")
    parser.add_argument("--output", type=Path, default=None, help="Output hand track JSON. Defaults to <session>/hand_tracks_mediapipe.json.")
    parser.add_argument("--attach-session", type=Path, default=None, help="Session JSON or directory to update with data_sources.hand_tracks.")
    parser.add_argument("--attach-output", type=Path, default=None, help="Optional output path for the attached session JSON.")
    parser.add_argument("--rgb-key", default="cleanRgb", help="Frame manifest key for RGB images.")
    parser.add_argument("--depth-key", default="detailDepth", help="Frame manifest key for depth/height images.")
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--max-num-hands", type=int, default=2)
    parser.add_argument("--model-complexity", type=int, default=1)
    parser.add_argument("--model-asset", type=Path, default=DEFAULT_HAND_LANDMARKER_PATH)
    parser.add_argument("--min-detection-confidence", type=float, default=0.45)
    parser.add_argument("--min-tracking-confidence", type=float, default=0.45)
    parser.add_argument("--plane-size", type=float, default=5.5)
    parser.add_argument("--height-scale", type=float, default=None)
    parser.add_argument("--arg1", type=float, default=None, help="Override shader arg_1 used for height mapping.")
    parser.add_argument("--background", type=float, default=None, help="Override shader background value used for height mapping.")
    parser.add_argument("--depth-sample-radius", type=int, default=2)
    parser.add_argument("--hand-lift", type=float, default=0.06, help="Small lift above sampled depth to avoid z-fighting.")
    parser.add_argument("--mediapipe-z-scale", type=float, default=0.0, help="Optional extra vertical shaping from MediaPipe relative z.")
    parser.add_argument("--height-mode", choices=["surface", "rigid-contact"], default="surface", help="surface follows sand per joint; rigid-contact keeps hand height stable and snaps fingertips to sand.")
    parser.add_argument("--hand-hover", type=float, default=0.14, help="Base rigid hand height above the palm surface in rigid-contact mode.")
    parser.add_argument("--contact-lift", type=float, default=0.025, help="Target gap between snapped fingertips and sampled sand surface.")
    parser.add_argument("--contact-snap-strength", type=float, default=0.85, help="Blend strength for fingertip contact snapping in rigid-contact mode.")
    parser.add_argument("--contact-indices", type=int, nargs="+", default=FINGERTIP_INDICES, help="MediaPipe landmark indices to snap toward sand contact.")
    parser.add_argument("--no-contact-shift-hand", dest="contact_shift_hand", action="store_false", help="Do not translate the whole hand to enforce contact; snap only selected contact landmarks.")
    parser.set_defaults(contact_shift_hand=True)
    parser.add_argument("--interpolation", choices=["nearest", "linear", "cubic"], default="cubic", help="Godot playback interpolation mode for generated tracks.")
    parser.add_argument("--single-hand-track", action="store_true", help="Force all detections into one primary track; useful when MediaPipe flips handedness for one visible hand.")
    parser.add_argument("--single-track-id", default="primary_hand")
    parser.add_argument("--single-track-label", default="Primary hand")
    parser.add_argument("--single-track-color", default="#5ec8d8")
    parser.add_argument("--keep-handedness-duplicates", dest="merge_handedness_duplicates", action="store_false", help="Keep multiple same-handedness detections in a frame instead of merging by confidence.")
    parser.set_defaults(merge_handedness_duplicates=True)
    parser.add_argument("--show-landmarks", action="store_true")
    parser.add_argument("--show-skeleton", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.frame_step <= 0:
        raise ValueError("--frame-step must be >= 1")
    output = args.output
    if output is None:
        output = _session_path(args.source_session).parent / "hand_tracks_mediapipe.json"
    payload = extract_hands(args)
    _save_json(output, payload)
    if args.attach_session is not None:
        attach_hand_tracks(args.attach_session, output, args.attach_output)
    print(
        "Wrote %s with %d tracks, %d/%d detected frames"
        % (output, len(payload["hand_tracks"]), payload["detectedFrameCount"], payload["frameCount"])
    )


if __name__ == "__main__":
    main()
