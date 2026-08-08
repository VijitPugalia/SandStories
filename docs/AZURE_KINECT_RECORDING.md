# Record a SandStories session with Azure Kinect DK

This is the Windows capture path for Azure Kinect DK. It records the official
Kinect MKV as the immutable source, records microphone audio separately, and
converts the synchronized RGB-D frames into the same `v2_streams` package used
by the evaluator and Godot adapter.

Azure Kinect DK is a time-of-flight depth camera, not an iPhone LiDAR sensor.
Keep `captureDeviceFamily: azure_kinect_dk` in the manifest and do not pool its
measurements with ARKit results unless device is an explicit experimental
factor.

## 1. Connect and verify the camera

Use the Kinect power supply and a direct USB 3 connection. Install Azure Kinect
Sensor SDK 1.4.2 for Windows; this provides `k4arecorder.exe`, `k4aviewer.exe`,
the playback library, and the device drivers. Then install the Python adapter:

```powershell
py -3.12 -m pip install -r .\scripts\requirements-azure-kinect.txt
```
Use Python 3.12 for `pyk4a`; pass its full executable path to the recorder if `python` selects a newer interpreter.

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\azure_kinect_preflight.ps1 -ListAudioDevices
```

The JSON result must show both `readyToRecord: true` and
`readyToConvert: true`. If the default microphone name is not listed, copy its
exact DirectShow name for `-AudioDevice` below. Open `k4aviewer` once before the
field session to confirm that RGB and depth are live, then close it so the
recorder can claim the camera.

## 2. Record a 90-second session

This example records the 80 cm, shade, dry-sand, replicate-one condition:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\record_azure_kinect.ps1 `
  -DurationSeconds 90 `
  -SensorHeightCm 80 `
  -Lighting shade `
  -SurfaceType dry `
  -Replicate 1 `
  -AudioDevice "Microphone Array (Azure Kinect Microphone Array)" `
  -Python "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" `
  -PrepareGodot
```

The default sensor configuration is 30 fps, `NFOV_UNBINNED` depth and 1080p
colour. Keep those settings fixed throughout one controlled matrix. The script
prints a reminder to make one sharp, visible and audible clap near the start.
Follow the actions and timings in `docs/PILOT_PROTOCOL_2026-08.md`.

By default, sessions are written to:

```text
%USERPROFILE%\Documents\SandStories\AzureKinectSessions\session_<id>
```

Use `-OutputRoot D:\SandStoriesSessions` when a different storage location is
required. Do not reuse `-SessionId`; the script refuses to silently replace a
successful source recording.

## 3. What the script produces

```text
session_<id>/
  source/azure_kinect.mkv      official raw RGB-D source recording
  recording_metadata.json     recorder/audio UTC starts and configuration
  conditions.json             height, lighting, surface and replicate
  audio.wav                    separate 48 kHz mono microphone recording
  streams/depth.f32            native DEPTH16 mm converted to Float32 metres
  streams/rgb.mp4              colour transformed into depth-camera geometry
  v2_frames.jsonl              sensor timestamps, offsets and calibration
  manifest.json                device-aware SandStories package manifest
  derived/evaluation/          package validation and descriptive metrics
```

Azure `DEPTH16` is the primary measured surface data. The RGB video is
calibration-transformed into depth geometry for pixel correspondence. The
converter refuses a plain image resize unless `--allow-resized-color` is
explicitly requested for diagnostics. The source MKV is never replaced by the
derived files.

Azure Kinect recordings do not contain microphone audio, so the wrapper starts
FFmpeg beside `k4arecorder` and stores the exact UTC start offset. The clap is
still required: annotate its RGB, depth and audio times in `sync_check.json`
and verify that the span is at most 250 ms before accepting the session.

## 4. Recovery and troubleshooting

- If preflight reports no camera, verify the power LED, use a direct USB 3 port,
  and test in `k4aviewer`.
- If audio fails, rerun preflight with `-ListAudioDevices` and pass the exact
  microphone name. `-SkipAudio` is diagnostic only and does not meet pilot
  acceptance criteria.
- If conversion fails, the raw MKV remains under `source/`. Install the SDK and
  Python requirements, then rerun the converter manually:

```powershell
python .\scripts\convert_azure_kinect_mkv.py `
  C:\path\to\session_id\source\azure_kinect.mkv `
  --session-dir C:\path\to\session_id `
  --audio C:\path\to\session_id\audio.wav `
  --recording-metadata C:\path\to\session_id\recording_metadata.json `
  --no-copy-source
```

- `-SkipConversion` records MKV/audio only. Use it only when conversion must be
  deferred to another Windows environment.
- Direct sunlight can degrade active-infrared depth. Treat `direct_sun` as a
  documented stress condition, not as evidence that indoor/shade capture works.
- Azure capture supplies RGB-D/audio, calibration and timing. Gesture strokes,
  boundary confidence and object detections still require the repository's
  offline processing or manual evidence workflow.
