# SandStories controlled pilot protocol

## Purpose and scope

This pilot tests whether the selected capture package is reliable enough to start the full 36-session study. Record the device family in every manifest and do not mix iPhone ARKit and Azure Kinect measurements within one matrix unless device is an explicit condition. It uses only simulated geometric marks and generic props. Do not use authentic cultural material. Godot screenshots are development evidence only. v24b and Any2Full outputs are derived reconstructions, not measured depth ground truth.

Target: nine 90-second sessions. Minimum: six complete, valid packages.

## Equipment and setup

- LiDAR-capable iPhone with the corrected IPA.
- Or Azure Kinect DK with power supply, direct USB 3, Sensor SDK 1.4.2 and the Windows recording wrapper in `docs/AZURE_KINECT_RECORDING.md`.
- Fixed tripod and tape measure.
- Sand tray with dry loose and wet compacted preparations.
- Physical 5 mm and 10 mm reference tools or gauge blocks.
- Four saturated corner markers that are visible in RGB.
- One generic stone and one generic stick.
- Printed run sheet and session matrix.
- Stable shade for the primary matrix; direct sun only for the stress session.

Keep the phone normal to the tray, record the measured sensor height from the sand surface, and keep framing constant within each height.

## 90-second script

Keep one sensor family and one depth mode fixed throughout the controlled matrix. If Azure Kinect is selected, use shade/indoor conditions for the primary matrix and retain direct sun only as the explicitly labelled stress run.

| Time | Action | Required evidence |
|---|---|---|
| 00-10 s | Hold on an untouched, flat surface. Say the session name and conditions. | Flat-surface noise baseline; audible conditions. |
| 10-12 s | Make one sharp clap or tap in view of the RGB camera. | Common RGB, depth and audio synchronization marker. |
| 12-25 s | Make a measured 5 mm groove/reference and say "five millimetres". | Depth recovery relative to flat noise. |
| 25-38 s | Make a measured 10 mm groove/reference and say "ten millimetres". | Depth recovery relative to flat noise. |
| 38-58 s | Perform five neutral actions: straight stroke, circle, zigzag, point/tap, broad sweep. Count one to five aloud. | Five hand trajectories and spoken labels. |
| 58-75 s | Place, move and remove the stone; place, move and remove the stick. Name each action aloud. | Object detections and temporally aligned speech. |
| 75-85 s | Hold the completed surface steady and describe the visible geometry in one sentence. | Stable final depth/RGB evidence and audio. |
| 85-90 s | Keep hands and props out of frame; end capture. | Clean tail for stream coverage. |

Do not pause between actions. If the app stops, timestamps regress, or any required stream is empty, rerun immediately with a new replicate number.

## Pilot matrix

| Run | Height | Lighting | Surface | Replicate | Purpose |
|---|---:|---|---|---:|---|
| P01 | 60 cm | shade | dry | 1 | Matrix |
| P02 | 60 cm | shade | wet | 1 | Matrix |
| P03 | 80 cm | shade | dry | 1 | Matrix |
| P04 | 80 cm | shade | wet | 1 | Matrix |
| P05 | 100 cm | shade | dry | 1 | Matrix |
| P06 | 100 cm | shade | wet | 1 | Matrix |
| P07 | 80 cm | direct_sun | dry | 1 | Stress |
| P08 | 80 cm | shade | dry | 2 | Repeatability |
| P09 | 80 cm | shade | wet | 2 | Repeatability |

Use: `pilot_<height>cm_<lighting>_<surface>_r<replicate>_<YYYYMMDD-HHMMSS>`.

## Sidecars

Create `conditions.json` before acceptance:

```json
{
  "sensorHeightCm": 80,
  "lighting": "shade",
  "surfaceType": "dry",
  "replicate": 1
}
```

After locating the clap/tap in each modality, create `sync_check.json`:

```json
{
  "marker": "clap",
  "rgbTimeSeconds": 10.12,
  "depthTimeSeconds": 10.18,
  "audioTimeSeconds": 10.08,
  "evidenceNotes": "First visible hand impact and audio transient."
}
```

After manual review, create `completeness_rating.json` with a 1-5 rating and evidence notes. Schemas are in `docs/pilot_schemas/`.

## Acceptance gate

An accepted package must have:

- Non-empty `streams/depth.f32`, RGB video and audio.
- Readable frame metadata with monotonic timestamps and offsets within stream bounds.
- Complete conditions metadata.
- A measured clap/tap span of 250 ms or less across RGB, depth and audio.
- Non-zero evidence for depth, gestures, objects, boundaries and audio, or an explicit documented failure.
- A manual completeness rating with evidence notes.

A failed 5 mm or 10 mm recovery is a valid result. Compare each reference with flat-surface noise and do not use RGB-derived reconstruction to conceal LiDAR failure.

## Processing commands

```bash
python scripts/evaluate_session.py --batch <sessions-root> --output-dir <derived-root> --csv <derived-root>/field_validation.csv
python scripts/detect_objects_yolo_world.py --batch <sessions-root> --sample-fps 2 --classes "stone,stick,coloured marker,hand"
python scripts/analyze_field_validation.py --csv <derived-root>/field_validation.csv --sessions-dir <sessions-root> --descriptive-only --out <derived-root>/pilot_descriptive_results.md
```

Keep all generated detections and evaluation artifacts outside the raw package where possible. When detections must sit beside a package for evaluator discovery, use only `derived/objects_yolo_world.jsonl`.
