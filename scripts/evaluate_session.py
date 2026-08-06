#!/usr/bin/env python3
"""
Evaluate SandStories captured session folder against the 5 research proposal metrics:
1. Depth retention
2. Object detection confidence
3. Gesture continuity
4. Boundary detection
5. Audio continuity

Also outputs a dropouts.jsonl file logging gaps >= 2 seconds.

Usage:
  python scripts/evaluate_session.py /path/to/session_folder
  python scripts/evaluate_session.py --batch /path/to/sessions_root/ --csv field_validation.csv
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate SandStories session metrics")
    parser.add_argument("session_dir", type=Path, nargs="?", help="Session folder to evaluate")
    parser.add_argument("--batch", type=Path, help="Directory containing multiple session folders")
    parser.add_argument("--csv", type=Path, help="Output summary CSV file (requires --batch)")
    return parser.parse_args()

def load_json_lines(path: Path) -> list:
    if not path.is_file():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records

def load_strokes(path: Path) -> list:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

def get_media_duration(media_path: Path) -> float:
    """Return container duration without treating intentional silence as data loss."""
    if not media_path.is_file():
        return 0.0

    executable = os.environ.get("SANDSTORIES_FFPROBE", "ffprobe")
    cmd = [
        executable,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15,
        )
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0


def object_confidences(records: list) -> list[float]:
    """Accept both legacy one-detection records and frame-grouped detections."""
    confidences = []
    for record in records:
        detections = record.get("detections")
        if isinstance(detections, list):
            for detection in detections:
                if isinstance(detection, dict):
                    confidences.append(float(detection.get("confidence", 0.0)))
        elif "confidence" in record:
            confidences.append(float(record.get("confidence", 0.0)))
    return confidences

def evaluate_session(session_dir: Path) -> dict:
    session_dir = session_dir.resolve()
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json not found in {session_dir}")
        
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    # Get session duration
    duration = manifest.get("monotonicSessionEndElapsedSeconds")
    if duration is None:
        start_unix = manifest.get("wallClockStartUnix", 0)
        end_unix = manifest.get("wallClockEndUnix")
        if end_unix is not None:
            duration = end_unix - start_unix
        else:
            duration = 0.0
            
    dropouts = []
    
    # 1. Depth Retention
    depth_frames = manifest.get("depthFrames", [])
    v2_streams = manifest.get("v2Streams") or {}
    v2_frames_path = session_dir / v2_streams.get("frameMetadataFile", "v2_frames.jsonl")
    if not depth_frames and v2_frames_path.is_file():
        depth_frames = load_json_lines(v2_frames_path)
    expected_depth = duration * 15.0
    actual_depth = len(depth_frames)
    depth_retention = min(1.0, actual_depth / expected_depth) if expected_depth > 0 else 0.0
    
    # Find depth dropouts (gaps >= 2s)
    last_t = 0.0
    for idx, frame in enumerate(depth_frames):
        t = frame.get("monotonicElapsedSeconds", 0.0)
        if idx > 0 and (t - last_t) >= 2.0:
            dropouts.append({
                "stream": "depth",
                "start": last_t,
                "end": t,
                "duration": t - last_t
            })
        last_t = t
        
    # 2. Object Detection Confidence
    obj_file = manifest.get("objectDetectionsFile", "objects.jsonl")
    obj_path = session_dir / obj_file
    obj_records = load_json_lines(obj_path)
    object_detection_source = obj_file
    derived_obj_path = session_dir / "derived" / "objects_yolo_world.jsonl"
    if not obj_records and derived_obj_path.is_file():
        obj_records = load_json_lines(derived_obj_path)
        object_detection_source = "derived/objects_yolo_world.jsonl"
    obj_confidences = object_confidences(obj_records)
    obj_conf = sum(obj_confidences) / len(obj_confidences) if obj_confidences else 0.0
        
    # 3. Gesture Continuity
    strokes_file = manifest.get("strokesFile", "strokes.json")
    strokes_path = session_dir / strokes_file
    strokes = load_strokes(strokes_path)
    
    total_stroke_dur = 0.0
    valid_stroke_dur = 0.0
    for s in strokes:
        started = s.get("startedAt", 0.0)
        finished = s.get("finishedAt", 0.0)
        points = s.get("points", [])
        sdur = finished - started
        if sdur <= 0:
            continue
            
        total_stroke_dur += sdur
        # Filter fragmented: < 3 points or < 0.1s
        if len(points) >= 3 and sdur >= 0.1:
            valid_stroke_dur += sdur
            
        # Check gaps >= 2s within a single stroke
        last_pt_t = started
        for pt in points:
            pt_t = pt.get("timestamp", started)
            if (pt_t - last_pt_t) >= 2.0:
                dropouts.append({
                    "stream": "gesture",
                    "start": last_pt_t,
                    "end": pt_t,
                    "duration": pt_t - last_pt_t
                })
            last_pt_t = pt_t
            
    gesture_continuity = (valid_stroke_dur / total_stroke_dur) if total_stroke_dur > 0 else 1.0
    
    # 4. Boundary Detection Confidence
    boundary_file = manifest.get("boundarySamplesFile", "boundary_samples.jsonl")
    boundary_path = session_dir / boundary_file
    boundary_records = load_json_lines(boundary_path)
    if boundary_records:
        boundary_conf = sum(r.get("confidence", 0.0) for r in boundary_records) / len(boundary_records)
        
        # Find boundary dropouts (gaps >= 2s between checks)
        last_b_t = 0.0
        for idx, r in enumerate(boundary_records):
            b_t = r.get("monotonicElapsedSeconds", 0.0)
            if idx > 0 and (b_t - last_b_t) >= 2.0:
                dropouts.append({
                    "stream": "boundary",
                    "start": last_b_t,
                    "end": b_t,
                    "duration": b_t - last_b_t
                })
            last_b_t = b_t
    else:
        # Fall back to manifest static trayBoundary confidence
        tb = manifest.get("trayBoundary", {})
        if tb.get("status") == "detected":
            boundary_conf = 1.0  # Heuristic fallback if file is missing
        else:
            boundary_conf = 0.0
            
    # 5. Audio Continuity
    audio_info = manifest.get("audio")
    audio_continuity = 0.0
    audio_observed_duration = 0.0
    audio_expected_duration = 0.0
    if audio_info:
        audio_rel = audio_info.get("relativePath", "audio.m4a")
        audio_path = session_dir / audio_rel
        audio_start = max(0.0, float(audio_info.get("startMonotonicElapsedSeconds", 0.0)))
        audio_expected_duration = max(0.0, duration - audio_start)
        manifest_audio_duration = max(0.0, float(audio_info.get("durationSeconds", 0.0)))
        probed_audio_duration = get_media_duration(audio_path)
        audio_observed_duration = probed_audio_duration or manifest_audio_duration
        if audio_expected_duration > 0:
            audio_continuity = min(1.0, audio_observed_duration / audio_expected_duration)

        missing_tail = max(0.0, audio_expected_duration - audio_observed_duration)
        if missing_tail >= 2.0:
            dropouts.append({
                "stream": "audio",
                "start": audio_start + audio_observed_duration,
                "end": audio_start + audio_expected_duration,
                "duration": missing_tail,
            })
            
    # Write dropouts.jsonl
    dropouts_path = session_dir / "dropouts.jsonl"
    with dropouts_path.open("w", encoding="utf-8") as df:
        for d in dropouts:
            df.write(json.dumps(d) + "\n")
            
    # Write evaluation_report.json
    report = {
        "sessionId": manifest.get("sessionId"),
        "durationSeconds": duration,
        "metrics": {
            "depthRetention": depth_retention,
            "objectDetectionConfidence": obj_conf,
            "gestureContinuity": gesture_continuity,
            "boundaryDetection": boundary_conf,
            "audioContinuity": audio_continuity
        },
        "observations": {
            "depthFrameCount": actual_depth,
            "expectedDepthFrameCountAt15Hz": expected_depth,
            "objectDetectionCount": len(obj_confidences),
            "objectDetectionSource": object_detection_source,
            "strokeCount": len(strokes),
            "boundarySampleCount": len(boundary_records),
            "audioObservedDurationSeconds": audio_observed_duration,
            "audioExpectedDurationSeconds": audio_expected_duration,
        },
        "dropoutCount": len(dropouts)
    }
    
    report_path = session_dir / "evaluation_report.json"
    with report_path.open("w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2)
        
    return report

def main():
    args = parse_args()
    
    if args.batch:
        if not args.batch.is_dir():
            print(f"Error: {args.batch} is not a directory", file=sys.stderr)
            return 1
            
        sessions = []
        for root, dirs, files in os.walk(args.batch):
            if "manifest.json" in files:
                sessions.append(Path(root))
                
        if not sessions:
            print(f"No session folders (with manifest.json) found under {args.batch}")
            return 0
            
        print(f"Evaluating {len(sessions)} sessions...")
        
        results = []
        for s_dir in sessions:
            try:
                rep = evaluate_session(s_dir)
                results.append((s_dir, rep))
                print(f"  Passed: {s_dir.name}")
            except Exception as e:
                print(f"  Failed {s_dir.name}: {e}", file=sys.stderr)
                
        if args.csv and results:
            with args.csv.open("w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([
                    "sessionName",
                    "sessionId",
                    "durationSeconds",
                    "depthRetention",
                    "objectDetectionConfidence",
                    "gestureContinuity",
                    "boundaryDetection",
                    "audioContinuity",
                    "dropoutCount"
                ])
                for s_dir, rep in results:
                    metrics = rep["metrics"]
                    writer.writerow([
                        s_dir.name,
                        rep["sessionId"],
                        rep["durationSeconds"],
                        metrics["depthRetention"],
                        metrics["objectDetectionConfidence"],
                        metrics["gestureContinuity"],
                        metrics["boundaryDetection"],
                        metrics["audioContinuity"],
                        rep["dropoutCount"]
                    ])
            print(f"Wrote summary CSV to {args.csv}")
            
    elif args.session_dir:
        try:
            rep = evaluate_session(args.session_dir)
            print(json.dumps(rep, indent=2))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        print("Error: Specify a session folder or use --batch", file=sys.stderr)
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
