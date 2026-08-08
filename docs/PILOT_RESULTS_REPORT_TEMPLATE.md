# SandStories pilot results report

**Study window:** 7-12 August 2026
**Prepared for:** Supervisor review
**Scope:** Controlled pilot only; no inferential claims

## Executive summary

State how many sessions were attempted, accepted and rerun. State whether the capture pipeline is ready, conditionally ready, or not ready for the full 36-session study.

## Research question for this pilot

Can the selected RGB-D/audio package preserve surface deformation, gestures, generic objects, tray boundaries, audio and cross-modal timing well enough to justify the full study?

## Methods

### Capture matrix

List the completed height, lighting, surface and replicate combinations. Explain deviations from the planned nine sessions.

### Script and equipment

Reference `docs/PILOT_PROTOCOL_2026-08.md`. Record sensor model, capture build/configuration, tripod setup, marker design, sand preparation and reference-tool method.

### Data provenance

The primary measurement is the declared native depth source stored as Float32 metres in `streams/depth.f32`: ARKit `sceneDepth` for iPhone sessions or Azure Kinect `DEPTH16` millimetres for Azure sessions. Each frame's `selectedDepthSource` and the manifest's `captureDeviceFamily` are authoritative. Report devices separately unless device is an explicit experimental factor. v24b and Any2Full are derived visual reconstructions and are not depth ground truth. Godot screenshots document development inspection only.

### Metrics

- Depth retention and dropout intervals.
- 5 mm and 10 mm reference separation from flat-surface noise.
- Offline object count and mean confidence for stone/stick actions.
- Gesture continuity; empty or invalid strokes score zero.
- Mean tray-boundary confidence.
- Audio coverage using probed media duration when manifest duration is unavailable.
- RGB/depth/audio sync-marker span, with 250 ms as the acceptance threshold.
- Manual completeness rating from 1 to 5.

## Results

### Package validity

| Session | Conditions | Valid | Rerun | Validation errors |
|---|---|---:|---:|---|

### Descriptive metrics

| Session | Depth retention | 5 mm recoverable | 10 mm recoverable | Gesture continuity | Object confidence | Boundary confidence | Audio continuity | Sync ms | Completeness |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|

Report means, ranges and counts only. Do not claim Kruskal-Wallis significance from this pilot.

### Best and worst cases

Include one best and one worst session with depth diagnostic contact sheets. Add Godot screenshots only where they explain a development issue.

## Findings against the proposal

### Surface deformation

State whether 5 mm and 10 mm marks were distinguishable from flat-surface noise for each condition.

### Gesture, object and speech evidence

State what was recorded continuously, what required offline processing, and which failures remain.

### Synchronization

Report each measured marker span and whether it met 250 ms.

## Limitations

Include the small incomplete matrix, simulated content, device-specific ARKit behavior, offline object detection, heuristic marker detection, manual ratings, and the derived nature of visual reconstructions.

## Decision before the full study

Choose one:

- Proceed without changes.
- Proceed after listed P0/P1 fixes and a new smoke capture.
- Do not proceed; redesign and repeat the pilot.

List the exact gate for beginning the 18-condition x two-replicate study.

## Full-study schedule

Provide the capture, quality-control, descriptive analysis, inferential analysis, FAIR/CARE documentation, deployment guidance and thesis-writing sequence. Keep community-facing playback or interpretation tools outside the current primary deliverable unless separately approved.

## Evidence index

Link `field_validation.csv`, per-session `evaluation_report.json`, `dropouts.jsonl`, object detections, contact sheets, completeness ratings, sync annotations and selected screenshots.
