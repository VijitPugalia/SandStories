# SandStories

Capture sand storytelling sessions as synchronized LiDAR depth, RGB video frames, audio, and 3D stroke data.

SandStories is an iOS AR capture app for research-style recording of sand tray storytelling sessions. It uses ARKit, LiDAR scene depth, camera frames, hand pose input, microphone audio, and location metadata to produce a portable session folder that can be shared, analyzed offline, or automatically uploaded to a receiver service.

```text
iPhone ARKit + LiDAR  ──▶  Session Writer  ──▶  manifest.json + depth/RGB/audio/strokes
  scene depth frames          timestamp sync        Python / MATLAB / Fiji analysis
  RGB camera frames           manifest index        ZIP export for sharing
  hand stroke points          storage/upload        benchmark data for format tests
```

## What Works Today

The app runs on a physical LiDAR-capable iPhone/iPad and records packaged sessions into app storage or an external Files/USB-C destination. The current v2 package format stores one RGB video stream, one contiguous high-fidelity Float32 depth stream, one optional confidence stream, frame metadata, optional AAC audio, 3D stroke data, location metadata, and placeholder object-detection/tray-boundary hooks.

There is also a **Benchmark** button that runs a 15-second depth-only capture test and reports AR frame rate, saved frame rate, motion skips, no-depth frames, stream encode/write time, and total depth/RGB size.

```mermaid
flowchart LR
  phone["LiDAR iPhone"]
  capture["SandStories Capture"]
  session["session_UUID"]
  analysis["Offline Analysis"]

  phone -->|"ARKit frames"| capture
  capture -->|"manifest + media files"| session
  session -->|"Python, MATLAB, Fiji"| analysis
```

## What Does Not Work Yet

- Object detection is currently a stubbed pipeline hook rather than a trained/story-specific detector.
- Tray boundary detection is heuristic and may remain `pending` for difficult scenes.
- v2 depth is stored as a contiguous Float32 stream rather than one file per frame; lossless compression for the stream is still future work.
- The Python visualization script shows one selected frame at a time; full session reports/contact sheets are future tooling.
- Simulator support is not a goal for real capture because ARKit scene depth requires physical hardware.

## Hardware

| Component | Notes |
| --- | --- |
| LiDAR-capable iPhone/iPad | Required for ARKit scene depth capture |
| iOS 17+ device | Physical device only for real capture |
| Sand tray / storytelling surface | Subject being captured |
| Optional external SSD or Files folder | Used for longer sessions or easier transfer |
| Mac/Linux/Windows machine | Used for Python visualization and offline analysis |

## Build And Run

This project is a Swift Package Manager app packaged with `xtool`.

```bash
./scripts/build_release_ipa.sh
```

The build script:

1. Runs `xtool dev build -c release`.
2. Merges iOS privacy usage descriptions from `AppSupport/SandStories-App-Info.plist`.
3. Packages `xtool/SandStories.ipa`.

The privacy merge step matters. iOS will terminate an app that accesses camera, LiDAR/world sensing, location, or microphone without the corresponding `Info.plist` usage descriptions.

See [`docs/INSTALL_IPA.md`](docs/INSTALL_IPA.md) if the app crashes on launch after manual packaging.

### CI (no Mac)

GitHub Actions builds a downloadable IPA on macOS runners (no local Mac or SDK secrets required). See [`docs/CI.md`](docs/CI.md) for details and how to install the artifact on your iPhone.

## Architecture

SandStories is intentionally organized around the session lifecycle: AR frames enter through a delegate multiplexer, modality-specific components write their data, and `CaptureSessionController` keeps the manifest consistent.

```mermaid
sequenceDiagram
  participant ARView
  participant Multiplexer
  participant DepthManager
  participant HandManager
  participant Coordinator
  participant SessionController
  participant Disk

  ARView->>Multiplexer: ARFrame didUpdate
  Multiplexer->>DepthManager: sceneDepth + capturedImage
  DepthManager->>Disk: streams/depth.f32
  DepthManager->>Disk: streams/confidence.bin
  DepthManager->>Disk: streams/rgb.mp4
  DepthManager->>SessionController: v2 frame offsets + timestamps
  Multiplexer->>HandManager: hand pose / stroke point
  HandManager->>Disk: strokes.json
  Multiplexer->>Coordinator: tray, object, location hooks
  Coordinator->>SessionController: session metadata
  SessionController->>Disk: manifest.json
```

Key source files:

- `SandStoriesApp.swift` — SwiftUI app entry point.
- `ContentView.swift` — main AR UI, capture controls, benchmark button, export sheet.
- `ARSessionDelegateMultiplexer.swift` — fans ARKit delegate callbacks out to capture subsystems.
- `RecordingCoordinator.swift` — owns start/stop flow, storage destination, audio, location, tray/object hooks, and benchmark mode.
- `DepthCaptureManager.swift` — writes v2 RGB/depth/confidence streams and records throughput metrics.
- `CaptureSessionController.swift` — creates session folders, writes `manifest.json`, and appends `objects.jsonl`.
- `HandPoseCaptureManager.swift` and `StrokeRecorder.swift` — convert hand pose events into 3D stroke polylines.
- `SessionManifestModels.swift` — canonical schema for exported sessions.
- `SessionUploadManager.swift` — optional automatic session ZIP upload after recording.
- `ShareExportManager.swift` and `SimpleZipWriter.swift` — package sessions for sharing/upload.

## Data Format

Each recording is a self-contained folder named `session_<UUID>`. The canonical entry point is `manifest.json`; all other files are referenced relative to the session root.

```mermaid
flowchart TB
  subgraph sessionFolder["session_UUID"]
    manifest["manifest.json"]
    streams["streams/rgb.mp4 + depth.f32 + confidence.bin"]
    frames["v2_frames.jsonl"]
    audioFile["audio.m4a"]
    strokesFile["strokes.json"]
    objectsFile["objects.jsonl"]
  end

  manifest --> streams
  manifest --> frames
  frames --> streams
  manifest --> audioFile
  manifest --> strokesFile
  manifest --> objectsFile
```

`manifest.json` contains:

- Session ID, device model, app version, and OS version.
- Wall-clock start/end time.
- Monotonic elapsed session time for cross-modality alignment.
- ARKit timestamp reference.
- Storage destination metadata.
- `captureFormat = v2_streams` and `v2Streams` paths.
- `v2_frames.jsonl` frame entries with timestamps, byte offsets, byte counts, dimensions, camera transform, and intrinsics.
- Optional audio metadata.
- Stroke, object-detection, tray-boundary, and location metadata.

Current v2 stream format:

```text
streams/rgb.mp4              H.264 MP4 preview/reference video
streams/depth.f32            contiguous little-endian Float32 meters
streams/confidence.bin       contiguous raw ARKit confidence bytes when available
v2_frames.jsonl              per-frame offsets, sizes, timestamps, camera transform, intrinsics
```

For each row in `v2_frames.jsonl`, read `depthByteCount` bytes from `streams/depth.f32` starting at `depthByteOffset`, then interpret the bytes as `width * height` little-endian `Float32` depth values in meters. Confidence data uses the same offset/count pattern when ARKit provides a confidence map. Frames are motion-gated, so the stream contains retained frames only.

## Automatic Upload

Run the standalone receiver on a computer on the same network:

```bash
python scripts/sandstories_upload_server.py --host 0.0.0.0 --port 8080 --dir uploads --extract
```

On the iPhone, tap **Upload**, enable **Auto-upload after recording**, and set the endpoint to your computer's LAN address, for example:

```text
http://192.168.1.20:8080/upload
```

When a recording stops, the app zips the completed session folder and posts it to the server. For a simple shared secret, start the server with `--token mytoken` and use `http://192.168.1.20:8080/upload?token=mytoken` as the endpoint.

## Field Console (LAN)

For experiment debugging, the repo includes a LAN field console with a high-contrast outdoor UI, package validation, download links, remote-control WebSockets, and self-hosted LiveKit preview.

1. Find the computer's LAN IP, for example `192.168.1.20`.
2. Start LiveKit and the console:

```bash
cd deploy
LAN_IP=192.168.1.20 docker compose -f docker-compose.lan.yml up
```

3. Open the dashboard:

```text
http://192.168.1.20:8080/?token=field-console
```

4. In the iPhone app, open **Upload** and set:

```text
Auto-upload after recording: on
Server upload URL: http://192.168.1.20:8080/upload?token=field-device
Enable remote console: on
Publish LiveKit preview: on
Console server URL: http://192.168.1.20:8080
Device token: field-device
```

The dashboard can send start/stop/pause/resume/mark commands to a connected device. Uploaded ZIP packages are validated server-side before being marked valid. The package table lets you download any uploaded session ZIP and inspect its validation report.

Default LAN tokens are intentionally simple. Change these in `deploy/env.lan.example` before exposing anything beyond a trusted local network.

## Timing Model

The app stores multiple time bases because different analysis tasks need different alignment guarantees.

```mermaid
flowchart TB
  wall["Wall clock Unix seconds"]
  mono["Monotonic elapsed seconds"]
  arkit["ARFrame.timestamp"]
  frames["Depth and RGB frames"]
  strokes["Stroke points"]
  audio["Audio start and duration"]
  objects["Object detections"]

  wall --> frames
  mono --> frames
  mono --> audio
  arkit --> frames
  arkit --> strokes
  arkit --> objects
```

Use `monotonicElapsedSeconds` for session-local alignment across modalities. Use `arTimestamp` when correlating directly with ARKit frames.

## Visualize Session Data

The repository includes a Python script for opening a recorded session and viewing a selected depth/RGB frame.

```bash
pip install numpy pillow matplotlib
python scripts/visualize_sandstories_session.py "/path/to/session_UUID" --frame 0
```

Save the visualization to disk:

```bash
python scripts/visualize_sandstories_session.py "/path/to/session_UUID" --frame 0 --save frame_0.png
```

See [`docs/VISUALIZE_SESSION.md`](docs/VISUALIZE_SESSION.md) for ImageJ/Fiji, MATLAB, and OpenCV workflows.

## Project Structure

```text
SandStories/
  AppSupport/
    SandStories-App-Info.plist          iOS privacy usage descriptions
  Sources/SandStories/
    SandStoriesApp.swift                App entry point
    ContentView.swift                   Main SwiftUI capture UI
    RecordingCoordinator.swift          Session lifecycle orchestration
    DepthCaptureManager.swift           LiDAR/RGB persistence and benchmark metrics
    CaptureSessionController.swift      manifest.json and objects.jsonl writer
    SessionUploadManager.swift          Auto-upload settings and ZIP upload client
    HandPoseCaptureManager.swift        Hand pose integration
    StrokeRecorder.swift                3D stroke persistence
    SessionManifestModels.swift         Exported data schema
    ShareExportManager.swift            Session export helpers
  docs/
    INSTALL_IPA.md                      IPA/privacy troubleshooting
    VISUALIZE_SESSION.md                Offline visualization guide
  scripts/
    build_release_ipa.sh                Release app + IPA build
    merge_privacy_into_app.sh           Info.plist privacy merge
    visualize_sandstories_session.py    Depth/RGB visualization tool
    sandstories_upload_server.py        Standalone upload receiver
  Package.swift                         Swift package definition
  xtool.yml                             iOS bundle identifier config
```

## Roadmap

- Phase 1: Stable packaged session capture with PNG depth, RGB, audio, strokes, and manifest metadata.
- Phase 2: Session analysis tooling: summaries, contact sheets, depth quality metrics, and stroke timelines.
- Phase 3: Storage benchmark: compare PNG depth against lossless depth video and compressed 16-bit depth chunks.
- Phase 4: Stronger tray detection and story-object detection.
- Phase 5: Dataset viewer/dashboard for reviewing many sessions side by side.

The biggest open technical question is the best storage format for high-rate, exact 16-bit depth. PNG is simple and reliable, but may be too slow or file-heavy for longer sessions. The next candidates are lossless depth video or an indexed compressed depth chunk stream.

## Dependencies

### iOS

Apple frameworks only:

- ARKit
- RealityKit
- SwiftUI
- CoreLocation
- Vision
- AVFoundation

### Tooling

- Swift 6.0 toolchain.
- `xtool` for packaging the iOS app.
- Python 3 with `numpy`, `pillow`, and `matplotlib` for visualization.

## Repository Hygiene

Build products and local scratch files are intentionally ignored:

- `.build/`
- `xtool/`
- `DerivedData/`
- `.venv*/`
- local transcription scratch files

The repository should contain source, scripts, docs, and lightweight configuration only.
