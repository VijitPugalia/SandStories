#!/usr/bin/env python3
"""Remove hands/tools from Kinect processed sessions before reconstruction.

This is an offline preprocessing step for fixed-camera SandStories captures. It
uses open-vocabulary YOLO/YOLO-World boxes for things like hands, arms, pens and
pencils, optionally refines those boxes with SAM, then inpaints the affected
RGB/depth/detail maps so downstream Godot playback and temporal fusion only see
the sand surface.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


DEFAULT_CLASSES = ["hand", "arm", "human hand", "pen", "pencil", "stylus", "tool"]


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _read_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8)


def _write_rgb(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), "RGB").save(path)


def _write_gray(path: Path, image: np.ndarray) -> None:
    Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), "L").save(path)


def _dilate(mask: np.ndarray, pixels: int) -> np.ndarray:
    if pixels <= 0 or not np.any(mask):
        return mask.astype(bool)
    size = pixels * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    return cv2.dilate(mask.astype(np.uint8), kernel, iterations=1).astype(bool)


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    if min_area <= 1 or not np.any(mask):
        return mask.astype(bool)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    kept = np.zeros(mask.shape, dtype=bool)
    for component in range(1, component_count):
        if int(stats[component, cv2.CC_STAT_AREA]) >= min_area:
            kept |= labels == component
    return kept


def _largest_component(mask: np.ndarray) -> np.ndarray:
    if not np.any(mask):
        return mask.astype(bool)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if component_count <= 2:
        return mask.astype(bool)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == largest


def _trim_surface_mask_to_body(mask: np.ndarray, col_projection_ratio: float, row_projection_ratio: float) -> np.ndarray:
    if (col_projection_ratio <= 0 and row_projection_ratio <= 0) or not np.any(mask):
        return mask.astype(bool)

    h, w = mask.shape
    if col_projection_ratio > 0:
        col_threshold = max(1, int(round(h * col_projection_ratio)))
        cols = np.where(mask.sum(axis=0) >= col_threshold)[0]
    else:
        cols = np.arange(w)
    if row_projection_ratio > 0:
        row_threshold = max(1, int(round(w * row_projection_ratio)))
        rows = np.where(mask.sum(axis=1) >= row_threshold)[0]
    else:
        rows = np.arange(h)
    if len(cols) == 0 or len(rows) == 0:
        return mask.astype(bool)

    body = np.zeros(mask.shape, dtype=bool)
    body[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1] = True
    return mask & body


def _box_mask(shape: tuple[int, int], box: tuple[int, int, int, int]) -> np.ndarray:
    h, w = shape
    x1, y1, x2, y2 = box
    x1 = max(0, min(w - 1, x1))
    x2 = max(0, min(w, x2))
    y1 = max(0, min(h - 1, y1))
    y2 = max(0, min(h, y2))
    mask = np.zeros((h, w), dtype=bool)
    if x2 > x1 and y2 > y1:
        mask[y1:y2, x1:x2] = True
    return mask


def _filter_detections_by_surface_overlap(
    detections: list[Detection],
    surface_mask: np.ndarray,
    max_surface_overlap_ratio: float,
) -> tuple[list[Detection], list[Detection]]:
    if max_surface_overlap_ratio <= 0:
        return detections, []

    surface_pixels = int(surface_mask.sum())
    if surface_pixels <= 0:
        return detections, []

    kept: list[Detection] = []
    skipped: list[Detection] = []
    for detection in detections:
        overlap = _box_mask(surface_mask.shape, detection.box) & surface_mask
        overlap_ratio = float(overlap.sum()) / float(surface_pixels)
        if overlap_ratio > max_surface_overlap_ratio:
            skipped.append(detection)
        else:
            kept.append(detection)
    return kept, skipped


def _inpaint_gray(image: np.ndarray, mask: np.ndarray, radius: float) -> np.ndarray:
    if not np.any(mask):
        return image.copy()
    return cv2.inpaint(image.astype(np.uint8), mask.astype(np.uint8) * 255, radius, cv2.INPAINT_TELEA)


def _inpaint_rgb(image: np.ndarray, mask: np.ndarray, radius: float) -> np.ndarray:
    if not np.any(mask):
        return image.copy()
    bgr = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2BGR)
    repaired = cv2.inpaint(bgr, mask.astype(np.uint8) * 255, radius, cv2.INPAINT_TELEA)
    return cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB)


def _repair_rgb_with_reference(
    image: np.ndarray,
    mask: np.ndarray,
    reference: np.ndarray | None,
    radius: float,
    feather: int,
) -> np.ndarray:
    if not np.any(mask):
        return image.copy()
    if reference is None:
        return _inpaint_rgb(image, mask, radius)

    repaired = image.copy()
    repaired[mask] = reference[mask]
    if feather <= 0:
        return repaired

    kernel = feather * 2 + 1
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (kernel, kernel), 0)
    alpha = np.maximum(alpha, mask.astype(np.float32))[:, :, None]
    blended = image.astype(np.float32) * (1.0 - alpha) + repaired.astype(np.float32) * alpha
    return np.clip(blended, 0, 255).astype(np.uint8)


def _repair_gray_with_reference(
    image: np.ndarray,
    mask: np.ndarray,
    reference: np.ndarray | None,
    radius: float,
) -> np.ndarray:
    if reference is None:
        return _inpaint_gray(image, mask, radius)
    repaired = image.copy()
    if np.any(mask):
        repaired[mask] = reference[mask]
    return _inpaint_gray(repaired, mask & (reference == 0), radius)


def _reference_foreground_mask(
    clean_depth: np.ndarray,
    detail_depth: np.ndarray,
    clean_reference: np.ndarray | None,
    detail_reference: np.ndarray | None,
    surface_mask: np.ndarray,
    threshold: int,
    min_area: int,
    dilate_pixels: int,
) -> np.ndarray:
    if threshold <= 0 or clean_reference is None or detail_reference is None:
        return np.zeros(clean_depth.shape, dtype=bool)

    clean_delta = clean_depth.astype(np.int16) - clean_reference.astype(np.int16)
    detail_delta = detail_depth.astype(np.int16) - detail_reference.astype(np.int16)
    foreground = ((clean_delta >= threshold) | (detail_delta >= threshold)) & surface_mask
    foreground = _remove_small_components(foreground, min_area)
    foreground = _dilate(foreground, dilate_pixels)
    return foreground & surface_mask


def _load_yolo(model_name: str, classes: list[str]):
    from ultralytics import YOLO

    model = YOLO(model_name)
    if hasattr(model, "set_classes"):
        model.set_classes(classes)
    return model


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _detect_yolo(model, rgb: np.ndarray, confidence: float, classes: list[str], device: str) -> list[Detection]:
    results = model.predict(rgb, conf=confidence, verbose=False, device=device)
    detections: list[Detection] = []
    wanted = {c.lower() for c in classes}
    for result in results:
        names = getattr(result, "names", None) or getattr(model, "names", {})
        for box in result.boxes:
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            cls_id = int(box.cls[0]) if box.cls is not None else -1
            label = str(names.get(cls_id, cls_id)).lower() if isinstance(names, dict) else str(cls_id)
            if wanted and not any(token in label for token in wanted):
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].tolist()]
            detections.append(Detection(label=label, confidence=conf, box=(x1, y1, x2, y2)))
    return detections


def _load_sam(checkpoint: str, model_type: str, device: str):
    import torch
    from segment_anything import SamPredictor, sam_model_registry

    sam = sam_model_registry[model_type](checkpoint=checkpoint)
    sam.to(device=device)
    return SamPredictor(sam)


def _sam_refine(predictor, rgb: np.ndarray, detections: list[Detection]) -> np.ndarray:
    h, w = rgb.shape[:2]
    if not detections:
        return np.zeros((h, w), dtype=bool)
    predictor.set_image(rgb)
    union = np.zeros((h, w), dtype=bool)
    for detection in detections:
        box = np.array(detection.box, dtype=np.float32)
        masks, scores, _ = predictor.predict(box=box, multimask_output=True)
        if len(masks) == 0:
            union |= _box_mask((h, w), detection.box)
            continue
        best = int(np.argmax(scores)) if len(scores) else 0
        union |= masks[best].astype(bool)
    return union


def _draw_overlay(rgb: np.ndarray, mask: np.ndarray, detections: list[Detection]) -> np.ndarray:
    overlay = rgb.copy()
    if np.any(mask):
        red = np.zeros_like(overlay)
        red[:, :, 0] = 255
        overlay[mask] = (overlay[mask].astype(np.float32) * 0.45 + red[mask].astype(np.float32) * 0.55).astype(np.uint8)
    image = Image.fromarray(overlay, "RGB")
    draw = ImageDraw.Draw(image)
    for det in detections:
        draw.rectangle(det.box, outline=(255, 255, 0), width=2)
        draw.text((det.box[0] + 3, det.box[1] + 3), f"{det.label} {det.confidence:.2f}", fill=(255, 255, 0))
    return np.asarray(image, dtype=np.uint8)


def _detection_boxes_mask(shape: tuple[int, int], detections: list[Detection]) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    for detection in detections:
        mask |= _box_mask(shape, detection.box)
    return mask


def process_session(
    session_dir: Path,
    output_dir: Path,
    *,
    yolo_model: str,
    classes: list[str],
    confidence: float,
    sam_checkpoint: str | None,
    sam_model_type: str,
    device: str,
    mask_dilate: int,
    depth_mask_dilate: int,
    depth_include_boxes: bool,
    depth_temporal_radius: int,
    depth_reference_repair: bool,
    depth_reference_threshold: int,
    depth_reference_min_area: int,
    depth_reference_dilate: int,
    rgb_reference_repair: bool,
    rgb_mask_dilate: int,
    rgb_temporal_radius: int,
    rgb_include_depth_mask: bool,
    rgb_reference_alpha: float,
    rgb_feather: int,
    inpaint_radius: float,
    max_surface_overlap_ratio: float,
    start_frame: int,
    frame_step: int,
    max_frames: int | None,
    write_overlays: bool,
    surface_trim_col_ratio: float,
    surface_trim_row_ratio: float,
) -> Path:
    manifest = _load_json(session_dir / "processed_manifest.json")
    session_json = _load_json(session_dir / "session.json")
    frames: list[dict[str, Any]] = list(manifest.get("frames", []))
    if start_frame > 0 or frame_step > 1:
        frames = frames[max(0, start_frame)::max(1, frame_step)]
    if max_frames is not None:
        frames = frames[:max_frames]

    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("*.png"):
        old.unlink()
    for old in output_dir.glob("*.json"):
        old.unlink()

    if (session_dir / "frame_contact_sheet.png").exists():
        shutil.copy2(session_dir / "frame_contact_sheet.png", output_dir / "source_frame_contact_sheet.png")

    yolo = _load_yolo(yolo_model, classes)
    resolved_device = _resolve_device(device)
    sam_predictor = _load_sam(sam_checkpoint, sam_model_type, resolved_device) if sam_checkpoint else None
    surface_mask = _largest_component(_read_gray(session_dir / "surface_mask.png") > 0)
    surface_mask = _trim_surface_mask_to_body(surface_mask, surface_trim_col_ratio, surface_trim_row_ratio)
    _write_gray(output_dir / "surface_mask.png", surface_mask.astype(np.uint8) * 255)

    records: list[dict[str, Any]] = []
    mask_pixels_total = 0
    for output_index, frame in enumerate(frames, start=1):
        rgb = _read_rgb(session_dir / frame["cleanRgb"])
        candidate_detections = _detect_yolo(yolo, rgb, confidence, classes, resolved_device)
        detections, skipped_detections = _filter_detections_by_surface_overlap(
            candidate_detections,
            surface_mask,
            max_surface_overlap_ratio,
        )
        if sam_predictor is not None:
            object_mask = _sam_refine(sam_predictor, rgb, detections)
        else:
            object_mask = np.zeros(rgb.shape[:2], dtype=bool)
            for detection in detections:
                object_mask |= _box_mask(rgb.shape[:2], detection.box)

        object_mask &= surface_mask
        object_mask = _dilate(object_mask, mask_dilate)
        object_mask &= surface_mask
        mask_pixels_total += int(object_mask.sum())

        depth_object_mask = object_mask.copy()
        if depth_include_boxes:
            depth_object_mask |= _detection_boxes_mask(rgb.shape[:2], detections) & surface_mask
        depth_object_mask = _dilate(depth_object_mask, depth_mask_dilate)
        depth_object_mask &= surface_mask
        records.append({
            "outputIndex": output_index,
            "frame": frame,
            "detections": detections,
            "skippedDetections": skipped_detections,
            "objectMask": object_mask,
            "depthObjectMask": depth_object_mask,
        })

    output_frames: list[dict[str, Any]] = []
    detections_jsonl = output_dir / "object_detections.jsonl"
    rgb_reference: np.ndarray | None = None
    clean_depth_reference: np.ndarray | None = None
    detail_depth_reference: np.ndarray | None = None
    shaded_depth_reference: np.ndarray | None = None
    with detections_jsonl.open("w", encoding="utf-8") as detections_file:
        for index, record in enumerate(records):
            output_index = int(record["outputIndex"])
            frame = record["frame"]
            detections = record["detections"]
            skipped_detections = record["skippedDetections"]
            object_mask = record["objectMask"]
            depth_object_mask = record["depthObjectMask"].copy()
            if depth_temporal_radius > 0:
                start = max(0, index - depth_temporal_radius)
                end = min(len(records), index + depth_temporal_radius + 1)
                for neighbor in records[start:end]:
                    depth_object_mask |= neighbor["depthObjectMask"]
                depth_object_mask &= surface_mask

            raw_depth = _read_gray(session_dir / frame["cleanDepth"])
            raw_detail = _read_gray(session_dir / frame["detailDepth"])
            raw_shaded = _read_gray(session_dir / frame["shadedDepth"])
            reference_mask = np.zeros(depth_object_mask.shape, dtype=bool)
            if depth_reference_repair:
                reference_mask = _reference_foreground_mask(
                    raw_depth,
                    raw_detail,
                    clean_depth_reference,
                    detail_depth_reference,
                    surface_mask,
                    depth_reference_threshold,
                    depth_reference_min_area,
                    depth_reference_dilate,
                )
                depth_object_mask |= reference_mask
                depth_object_mask &= surface_mask

            rgb_repair_mask = object_mask.copy()
            if rgb_temporal_radius > 0:
                start = max(0, index - rgb_temporal_radius)
                end = min(len(records), index + rgb_temporal_radius + 1)
                for neighbor in records[start:end]:
                    rgb_repair_mask |= neighbor["objectMask"]
            rgb_repair_mask = _dilate(rgb_repair_mask, rgb_mask_dilate)
            if rgb_include_depth_mask:
                rgb_repair_mask |= depth_object_mask
            rgb_repair_mask &= surface_mask

            stem = f"{output_index:06d}"
            clean_rgb_name = f"clean_rgb_{stem}.png"
            clean_depth_name = f"clean_depth_{stem}.png"
            detail_name = f"detail_depth_{stem}.png"
            shaded_name = f"shaded_depth_{stem}.png"
            valid_name = f"valid_mask_{stem}.png"
            object_mask_name = f"object_mask_{stem}.png"
            depth_object_mask_name = f"depth_object_mask_{stem}.png"

            rgb = _read_rgb(session_dir / frame["cleanRgb"])
            if rgb_reference_repair:
                repaired_rgb = _repair_rgb_with_reference(rgb, rgb_repair_mask, rgb_reference, inpaint_radius, rgb_feather)
            else:
                repaired_rgb = _inpaint_rgb(rgb, object_mask, inpaint_radius)
            repaired_depth = _repair_gray_with_reference(raw_depth, depth_object_mask, clean_depth_reference, inpaint_radius)
            repaired_detail = _repair_gray_with_reference(raw_detail, depth_object_mask, detail_depth_reference, inpaint_radius)
            repaired_shaded = _repair_gray_with_reference(raw_shaded, depth_object_mask, shaded_depth_reference, inpaint_radius)
            valid = _read_gray(session_dir / frame["occlusionMask"])

            if rgb_reference_repair:
                if rgb_reference is None:
                    rgb_reference = repaired_rgb.copy()
                else:
                    safe_rgb_update = surface_mask & ~rgb_repair_mask & ~depth_object_mask
                    if np.any(safe_rgb_update):
                        updated = (
                            rgb_reference[safe_rgb_update].astype(np.float32) * (1.0 - rgb_reference_alpha)
                            + rgb[safe_rgb_update].astype(np.float32) * rgb_reference_alpha
                        )
                        rgb_reference[safe_rgb_update] = np.clip(updated, 0, 255).astype(np.uint8)
            clean_depth_reference = repaired_depth.copy()
            detail_depth_reference = repaired_detail.copy()
            shaded_depth_reference = repaired_shaded.copy()

            _write_rgb(output_dir / clean_rgb_name, repaired_rgb)
            _write_gray(output_dir / clean_depth_name, repaired_depth)
            _write_gray(output_dir / detail_name, repaired_detail)
            _write_gray(output_dir / shaded_name, repaired_shaded)
            _write_gray(output_dir / valid_name, valid)
            _write_gray(output_dir / object_mask_name, object_mask.astype(np.uint8) * 255)
            _write_gray(output_dir / depth_object_mask_name, depth_object_mask.astype(np.uint8) * 255)
            if write_overlays:
                _write_rgb(output_dir / f"object_overlay_{stem}.png", _draw_overlay(rgb, object_mask, detections))
                _write_rgb(output_dir / f"depth_object_overlay_{stem}.png", _draw_overlay(rgb, depth_object_mask, detections))

            next_frame = dict(frame)
            next_frame.update({
                "cleanRgb": clean_rgb_name,
                "cleanDepth": clean_depth_name,
                "detailDepth": detail_name,
                "shadedDepth": shaded_name,
                "occlusionMask": valid_name,
                "maskOverlay": f"object_overlay_{stem}.png" if write_overlays else shaded_name,
                "objectMask": object_mask_name,
                "depthObjectMask": depth_object_mask_name,
                "removedObjectPixels": int(object_mask.sum()),
                "repairedRgbPixels": int(rgb_repair_mask.sum()),
                "removedDepthObjectPixels": int(depth_object_mask.sum()),
                "referenceForegroundPixels": int(reference_mask.sum()),
            })
            output_frames.append(next_frame)

            detections_file.write(json.dumps({
                "frameIndex": frame.get("frameIndex", output_index - 1),
                "time": frame.get("time", 0.0),
                "detections": [det.__dict__ | {"box": list(det.box)} for det in detections],
                "skippedDetections": [det.__dict__ | {"box": list(det.box)} for det in skipped_detections],
                "objectMask": object_mask_name,
                "depthObjectMask": depth_object_mask_name,
                "removedObjectPixels": int(object_mask.sum()),
                "repairedRgbPixels": int(rgb_repair_mask.sum()),
                "removedDepthObjectPixels": int(depth_object_mask.sum()),
                "referenceForegroundPixels": int(reference_mask.sum()),
            }, ensure_ascii=False) + "\n")

    next_manifest = dict(manifest)
    next_manifest["sourceSession"] = str(session_dir)
    next_manifest["processedFrameCount"] = len(output_frames)
    next_manifest["frames"] = output_frames
    next_manifest["objectRemoval"] = {
        "method": "yolo_world_boxes_plus_optional_sam_masks_then_inpaint",
        "classes": classes,
        "yoloModel": yolo_model,
        "samCheckpoint": sam_checkpoint or "disabled_box_masks_only",
        "device": resolved_device,
        "maskDilatePixels": mask_dilate,
        "depthMaskDilatePixels": depth_mask_dilate,
        "depthIncludeDetectionBoxes": depth_include_boxes,
        "depthTemporalRadius": depth_temporal_radius,
        "depthReferenceRepair": depth_reference_repair,
        "depthReferenceThreshold": depth_reference_threshold,
        "depthReferenceMinArea": depth_reference_min_area,
        "depthReferenceDilatePixels": depth_reference_dilate,
        "rgbReferenceRepair": rgb_reference_repair,
        "rgbMaskDilatePixels": rgb_mask_dilate,
        "rgbTemporalRadius": rgb_temporal_radius,
        "rgbIncludeDepthMask": rgb_include_depth_mask,
        "rgbReferenceAlpha": rgb_reference_alpha,
        "rgbFeatherPixels": rgb_feather,
        "inpaintRadius": inpaint_radius,
        "maxSurfaceOverlapRatio": max_surface_overlap_ratio,
        "surfaceTrimColRatio": surface_trim_col_ratio,
        "surfaceTrimRowRatio": surface_trim_row_ratio,
        "startFrame": start_frame,
        "frameStep": frame_step,
        "totalRemovedObjectPixels": mask_pixels_total,
        "note": "Masks are applied only inside the detected sand surface and inpainted before downstream reconstruction.",
    }
    _save_json(output_dir / "processed_manifest.json", next_manifest)

    final = output_frames[-1]
    rel_output = f"res://assets/processed_sessions/{output_dir.name}"
    next_session = dict(session_json)
    next_session["id"] = f"{session_json.get('id', output_dir.name)}_object_removed"
    next_session["title"] = f"{session_json.get('title', output_dir.name)} - object removed"
    next_session["duration"] = float(final.get("time", next_session.get("duration", 0.0)))
    data_sources = dict(next_session.get("data_sources", {}))
    data_sources.update({
        "depth_map": f"{rel_output}/{final['cleanDepth']}",
        "detail_depth_map": f"{rel_output}/{final['detailDepth']}",
        "texture_map": f"{rel_output}/{final['cleanRgb']}",
        "surface_mask": f"{rel_output}/surface_mask.png",
        "occlusion_mask": f"{rel_output}/{final['occlusionMask']}",
        "processed_manifest": f"{rel_output}/processed_manifest.json",
    })
    next_session["data_sources"] = data_sources
    production = dict(next_session.get("production_session", {}))
    production["objectRemoval"] = next_manifest["objectRemoval"]
    next_session["production_session"] = production
    _save_json(output_dir / "session.json", next_session)
    return output_dir / "session.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove hands/tools from a processed Kinect Godot session.")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--yolo-model", default="yolov8s-world.pt")
    parser.add_argument("--classes", nargs="+", default=DEFAULT_CLASSES)
    parser.add_argument("--confidence", type=float, default=0.08)
    parser.add_argument("--sam-checkpoint", default=None, help="SAM checkpoint path. If omitted, filled YOLO boxes are used.")
    parser.add_argument("--sam-model-type", default="vit_b", choices=["vit_b", "vit_l", "vit_h"])
    parser.add_argument("--device", default="auto")
    parser.add_argument("--mask-dilate", type=int, default=9)
    parser.add_argument("--depth-mask-dilate", type=int, default=18, help="Extra dilation used only for depth/detail/shaded inpainting.")
    parser.add_argument("--depth-include-boxes", action="store_true", help="Also include kept YOLO boxes in the depth-only mask.")
    parser.add_argument(
        "--depth-temporal-radius",
        type=int,
        default=0,
        help="OR depth-only masks with this many neighboring frames on each side before depth/detail/shaded inpainting.",
    )
    parser.add_argument(
        "--depth-reference-repair",
        action="store_true",
        help="Use the last repaired clean depth/detail/shaded maps as a long-term reference for depth-only foreground repair.",
    )
    parser.add_argument(
        "--depth-reference-threshold",
        type=int,
        default=22,
        help="Minimum positive grayscale depth/detail difference from the clean reference before adding a depth-only mask.",
    )
    parser.add_argument(
        "--depth-reference-min-area",
        type=int,
        default=120,
        help="Minimum connected-component area for reference-derived depth foreground masks.",
    )
    parser.add_argument(
        "--depth-reference-dilate",
        type=int,
        default=8,
        help="Dilation applied to reference-derived depth foreground masks.",
    )
    parser.add_argument(
        "--rgb-reference-repair",
        action="store_true",
        help="Use a rolling clean RGB reference to repair RGB object masks instead of relying only on spatial inpaint.",
    )
    parser.add_argument("--rgb-mask-dilate", type=int, default=4, help="Extra dilation used only for RGB reference repair masks.")
    parser.add_argument(
        "--rgb-temporal-radius",
        type=int,
        default=0,
        help="OR RGB repair masks with this many neighboring frames on each side before RGB reference repair.",
    )
    parser.add_argument(
        "--rgb-include-depth-mask",
        action="store_true",
        help="Also include the final depth/reference foreground mask in the RGB repair mask.",
    )
    parser.add_argument(
        "--rgb-reference-alpha",
        type=float,
        default=0.12,
        help="EMA update rate for clean RGB reference on safe unmasked pixels.",
    )
    parser.add_argument("--rgb-feather", type=int, default=8, help="Feather radius for RGB reference repair edges.")
    parser.add_argument("--inpaint-radius", type=float, default=5.0)
    parser.add_argument(
        "--max-surface-overlap-ratio",
        type=float,
        default=0.18,
        help="Skip any detection box that overlaps more than this fraction of the sand surface; use <=0 to disable.",
    )
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--write-overlays", action="store_true")
    parser.add_argument(
        "--surface-trim-col-ratio",
        type=float,
        default=0.7,
        help="Trim working/output surface mask columns to the main tray body using vertical projection density; use <=0 to disable.",
    )
    parser.add_argument(
        "--surface-trim-row-ratio",
        type=float,
        default=0.22,
        help="Trim working/output surface mask rows to the main tray body using horizontal projection density; use <=0 to disable.",
    )
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = session_dir.with_name(f"{session_dir.name}_object_removed")
    print(process_session(
        session_dir,
        output_dir.resolve(),
        yolo_model=args.yolo_model,
        classes=args.classes,
        confidence=args.confidence,
        sam_checkpoint=args.sam_checkpoint,
        sam_model_type=args.sam_model_type,
        device=args.device,
        mask_dilate=args.mask_dilate,
        depth_mask_dilate=args.depth_mask_dilate,
        depth_include_boxes=args.depth_include_boxes,
        depth_temporal_radius=args.depth_temporal_radius,
        depth_reference_repair=args.depth_reference_repair,
        depth_reference_threshold=args.depth_reference_threshold,
        depth_reference_min_area=args.depth_reference_min_area,
        depth_reference_dilate=args.depth_reference_dilate,
        rgb_reference_repair=args.rgb_reference_repair,
        rgb_mask_dilate=args.rgb_mask_dilate,
        rgb_temporal_radius=args.rgb_temporal_radius,
        rgb_include_depth_mask=args.rgb_include_depth_mask,
        rgb_reference_alpha=args.rgb_reference_alpha,
        rgb_feather=args.rgb_feather,
        inpaint_radius=args.inpaint_radius,
        max_surface_overlap_ratio=args.max_surface_overlap_ratio,
        start_frame=args.start_frame,
        frame_step=args.frame_step,
        max_frames=args.max_frames,
        write_overlays=args.write_overlays,
        surface_trim_col_ratio=args.surface_trim_col_ratio,
        surface_trim_row_ratio=args.surface_trim_row_ratio,
    ))


if __name__ == "__main__":
    main()
