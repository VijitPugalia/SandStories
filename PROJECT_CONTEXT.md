# SandStories Project Context

This is the durable shared memory for agents and people working in this repository. Read `AGENTS.md` and this file before making product or implementation decisions. Update this file only when repository evidence or an explicit decision changes durable project direction.

## Project Purpose

- SandStories is a research capture and visualization system for sand-based storytelling.
- The primary client is an iOS 17+ Swift app that records synchronized ARKit LiDAR depth, RGB, optional audio, hand-pose/stroke data, location metadata, diagnostics, and a session manifest.
- Azure Kinect DK is a separate Windows capture path for synchronized RGB-D and audio acquisition.
- Captured sessions are evaluated and transformed with Python tools, reviewed in a Godot 4 visualization/experiment application, and can be uploaded to a FastAPI field console.
- The repository supports technical prototyping and controlled pilots. Derived reconstructions are not measured depth ground truth.

## Repository Architecture

### iOS capture app

- Source: `Sources/SandStories/`.
- Build system: Swift Package Manager with Swift tools 6.0; platforms are iOS 17 and macOS 14.
- App configuration: `xtool.yml`, bundle ID `com.vijitpugalia.sandstories`, icon `Resources/AppIcon.png`.
- Linked Apple frameworks include ARKit, RealityKit, CoreLocation, Vision, and AVFoundation. LiveKit Swift SDK is pinned to 2.15.3.
- `RecordingCoordinator` owns the session lifecycle. `SessionFramePipeline` distributes AR frames to depth/RGB, hand tracking, strokes, audio, manifest, export, and upload components.
- Sessions are portable folders/ZIPs centred on `manifest.json`, with synchronized depth/RGB frame metadata and optional audio, strokes, objects, boundaries, diagnostics, and condition sidecars.

### Field console and networking

- `server/` is a FastAPI field console with device/dashboard WebSockets, authenticated device commands, LiveKit token issuance, package upload/validation, downloads, and an optional Any2Full completion worker.
- `deploy/docker-compose.lan.yml` runs the field console on port 8080 and LiveKit on the host network. Runtime tokens and data paths are environment-configured; never commit `deploy/.env` or real credentials.
- The iOS-side networking/upload code is in `ExperimentServerManager.swift`, `LiveKitPreviewManager.swift`, and `SessionUploadManager.swift`.

### Offline processing and evaluation

- `scripts/` contains session validation, visualization, field-validation analysis, object detection, Azure Kinect conversion, export, and recording utilities.
- `tests/` contains Python coverage for package conversion, evaluation, object detection, v2 stream handling, and Any2Full integration/worker behavior.
- Raw captures are the provenance source. Derived evaluations, detections, inpainting, depth completion, and visualizations must remain explicitly labelled as derived.

### Godot visualization and experiment platform

- `Godot/` is the only active Godot project. The older `SandStoriesGodot` sibling path referenced by some historical documentation is deprecated.
- `Godot/scripts/main.gd` implements playback, aligned surface rendering, modality layers, camera controls, logging, and session loading.
- `Godot/scripts/experiment_runner.gd` implements proposal-aligned Stage 1, Stage 2, training, evidence capture, questionnaires, and anonymous submission packaging.
- `Godot/data/session_schema.json` is the processed-session contract; `Godot/data/experiment_protocol.json` defines the experiment protocol.
- `Godot/docs/AGENT_HANDOFF.md` is the authoritative detailed history for Kinect, LiDAR, Any2Full, shadow-removal, virtual-hand, and experiment-platform work.

## Build and Run

### iOS development and IPA

```bash
xtool dev
bash scripts/build_release_ipa.sh release
xtool install xtool/SandStories.ipa
```

- The release script builds the app, merges privacy usage descriptions from `AppSupport/SandStories-App-Info.plist`, and packages `xtool/SandStories.ipa`. Do not package an IPA before the privacy merge.
- Local WSL builds require xtool and an installed Apple/Darwin SDK.
- `.github/workflows/build-ipa.yml` is the source of truth for CI. It currently uses `macos-26`, builds on pushes and pull requests to `main`, supports manual debug/release runs, and publishes a rolling private `latest-ipa` release after successful pushes to `main`.
- Direct private IPA: `https://github.com/VijitPugalia/SandStories/releases/download/latest-ipa/SandStories.ipa`. GitHub authentication is required; installation still requires LiveContainer, SideStore, or another authorised sideloading workflow.
- `docs/CI.md` still mentions `macos-15` in places; prefer the workflow file when the documentation and workflow disagree.

### Python tools

```bash
python -m pip install -r requirements.txt
python scripts/visualize_sandstories_session.py <session-folder>
python scripts/evaluate_session.py --batch <sessions-root> --output-dir <derived-root> --csv <derived-root>/field_validation.csv
```

- Use the session directory containing `manifest.json`.
- Keep generated evaluation and detection outputs outside the immutable raw package where practical.

### Field console

```bash
docker compose -f deploy/docker-compose.lan.yml up
```

- The compose configuration starts LiveKit and runs `uvicorn server.app:app --host 0.0.0.0 --port 8080`.
- Development defaults in the compose file are not production credentials or a production security configuration.

### Godot

- Open `Godot/project.godot` with Godot 4.x and run the project.
- From `Godot/`, `tools/build_web.ps1` builds the Web export and `tools/start_review_server.ps1` serves it at `http://localhost:8845` by default.
- Generated Godot sessions, models, Web builds, export templates, and local experiment data are intentionally ignored.

### Azure Kinect DK

```powershell
py -3.12 -m pip install -r .\scripts\requirements-azure-kinect.txt
powershell -ExecutionPolicy Bypass -File .\scripts\azure_kinect_preflight.ps1 -ListAudioDevices
powershell -ExecutionPolicy Bypass -File .\scripts\record_azure_kinect.ps1 <parameters>
```

- Follow `docs/AZURE_KINECT_RECORDING.md`; both `readyToRecord` and `readyToConvert` must be true before capture.
- The official MKV is immutable source data. Conversion produces the common `v2_streams` package without replacing the MKV.

## Device Requirements and Constraints

### iPhone / ARKit

- Requires a LiDAR-capable iPhone running iOS 17 or later for the intended depth workflow.
- Controlled capture uses a fixed, normal-to-tray mount; record the measured sensor height and keep framing stable within a condition.
- ARKit raw/smoothed depth can miss shallow sand traces. If RGB shows a trace but raw depth does not, treat LiDAR as coarse geometry/alignment and RGB/vision as the fine-trace channel.
- Unsupported zoom/lens controls remain removed. Cropping an RGB preview or switching to an RGB lens that is not registered with the depth stream is misleading.
- Prefer stable frame capture and low thermal load over expensive real-time visual effects.

### Azure Kinect DK

- Azure Kinect DK is a time-of-flight depth camera, not an iPhone LiDAR sensor. Record `captureDeviceFamily: azure_kinect_dk`.
- Requires the Kinect power supply, a direct USB 3 connection, Azure Kinect Sensor SDK 1.4.2 on Windows, and Python 3.12 for the current `pyk4a` adapter.
- The documented default is 30 fps, `NFOV_UNBINNED` depth, and 1080p colour. Keep device mode fixed within a controlled matrix.
- Azure MKV does not contain the required microphone audio; the recorder captures separate 48 kHz mono audio and records timing offsets. A visible/audible clap is required for synchronization review.
- Direct sunlight can degrade active-infrared depth. Treat direct sun as a labelled stress condition, not evidence for indoor/shade performance.
- Azure capture supplies RGB-D, calibration, timing, and audio. Gesture strokes, boundary confidence, and object detections require offline processing or manual evidence.

## Product and UI Decisions

- The capture UI should remain quiet, native-feeling, and close to Apple's Camera app: visible top bar, native tab bar, and an obvious bottom Record control.
- Pause must actually pause depth/RGB, strokes, and audio; it must not be a blocking overlay while capture continues.
- Bottom controls must remain legible over the camera feed. Prefer stable APIs to decorative effects that reduce capture reliability.
- The LiDAR mesh overlay is intentional. A picture-in-picture depth preview is not the selected design.
- Regression to check whenever export UI changes: Export Session previously showed a blank grey screen on first open but worked after reopening.

## Research Constraints

- Do not pool iPhone ARKit and Azure Kinect measurements unless device family is an explicit experimental factor.
- The controlled pilot uses simulated geometric marks and generic props only. Do not use authentic cultural material as test content.
- The current pilot target is nine 90-second sessions, with at least six complete valid packages. Follow `docs/PILOT_PROTOCOL_2026-08.md` for the matrix, sidecars, script, and acceptance gate.
- An accepted pilot package requires non-empty depth, RGB, and audio; monotonic in-bounds timing; complete conditions; RGB/depth/audio synchronization within 250 ms; evidence for required modalities or a documented failure; and a manual completeness rating.
- A failed 5 mm or 10 mm depth recovery is a valid result. Never use RGB-derived reconstruction to conceal measured-depth failure.
- v24b LiDAR and v22-series Kinect/Any2Full outputs are derived reconstructions, not measured ground truth. Preserve provenance and disclose future-frame use, model masks, temporal completion, and metric anchors.
- Experiment data collection must remain fail-closed until the configured protocol has approved participant information/consent, ethics approval, real validated stimuli, creator-authored questions/rubrics, approved retention/access/backup policy, and production allocation/storage.
- Avoid recording identifiable people, audio, or culturally sensitive content outside the approved consent, ethics, privacy, and data-management scope.

## Completed Work

- iOS multimodal capture, manifest/session packaging, diagnostics, depth benchmark, hand/stroke capture, gesture controls, export/share, remote control, LiveKit preview, and server upload paths are implemented in the repository.
- Gesture controls include open-palm pause/resume, open-hand wave stop, and triple-pinch segment marking; drawing strokes and UI-control gestures remain separate data paths.
- Azure Kinect preflight, MKV/audio recording, calibrated RGB-D conversion, package validation, and evaluator/Godot adapters are implemented.
- The FastAPI field console implements device management, WebSockets, upload validation, package download, LiveKit token generation, and optional queued Any2Full completion.
- The active Godot project supports aligned RGB-D surface playback, hand/object/annotation layers, modality ablations, experiment phases, evidence marking, questionnaires, Web export, and local review serving.
- Experiment-platform readiness was hardened to prevent formal runs from silently using unready sessions or client-only allocation.
- Selected research artifacts are documented rather than treated as universal production pipelines: iPhone LiDAR temporal-anchor repair v24b and Kinect full-sequence/temporal-anchor work through v22p. See `Godot/docs/LIDAR_RECONSTRUCTION_PIPELINE.md` and `Godot/docs/KINECT_CASPER_ANY2FULL_V22_WORKFLOW.md`.
- The capture-specific Azure hand-free v12 workflow is documented from aligned RGB/depth pairs through automatic actor masks, metric completion, bidirectional reconstruction, progressive v9 geometry, and RGB-only intrinsic/albedo repair. It is a derived reconstruction with explicit sensor/model provenance; see `Godot/docs/AZURE_HAND_FREE_V12_PRODUCTION_RUNBOOK.md`.
- GitHub Actions produces a rolling private IPA on successful `main` builds.

## Known Limitations and Deferred Work

- Current checked-in/sample Godot sessions are not automatically valid research stimuli. Real narration, complete object/tool observations, creator validation, approved study text, and production data governance remain prerequisites for recruitment.
- Godot's fixed top/front panes are currently reconstructed-scene camera proxies where real top/front video sources are absent.
- Fine sand relief can be below ARKit depth resolution/noise; RGB evidence and measured reference tools remain necessary.
- Active occlusion contains no trustworthy high-frequency surface evidence. Temporal/model completion can produce a locally smoother surface and must not invent claimed measured detail.
- Video inpainting and shadow removal may alter appearance inside model-derived masks. They must not modify measured depth provenance or be presented as original RGB.
- Simultaneous or cross-device results are not interchangeable without an explicit device comparison design and calibration.
- Azure Kinect direct-sun performance, separate audio synchronization, and offline gesture/object derivation require explicit validation per session.
- Local WSL USB device installation may be unreliable; the supported distribution path is the private GitHub IPA followed by manual iPhone import/install.
- Optional Any2Full and large reconstruction workflows require separately installed model checkpoints and suitable GPU/runtime environments; large generated artifacts are not stored in Git.
- The repository contains historical documentation with machine-specific paths and older project names. Use current repository-relative paths and `Godot/ACTIVE_PROJECT.md` as authoritative.

## Repository Hygiene

- Use code-review-graph tools before normal code searching, as required by `AGENTS.md`.
- Never commit secrets, `deploy/.env`, raw participant data, generated sessions, model weights, build outputs, or large research artifacts.
- Important ignored paths include `artifacts/`, `tmp/`, `weights/`, `*.pt`, `test_sessions/`, `server_data/`, `xtool/`, `Godot/build/`, and Godot session/experiment asset directories.
- Do not overwrite immutable raw captures. Create separately named derived sessions and retain manifests, provenance, hashes, and limitations.

## Maintenance Rule

Update this file when a task changes durable product direction, architecture, build/distribution, research readiness, device behavior, or a verified limitation. Do not turn it into a chronological chat transcript; detailed experiment history belongs in the linked documentation.

## LiDAR Accuracy Direction (2026 — from depth/LiDAR work)

- The perceived "gap" vs Azure Kinect is **density, retention, and smoothing**, not raw sensor noise.
  On stable static frames the iPhone LiDAR per-pixel temporal sigma is ~0.36 mm (median) / 0.79 mm (p95) —
  already sub-millimetre and below a 2 mm sand groove. See Godot/docs/AGENT_HANDOFF.md (2026-08-03 LiDAR section).
- The iOS app already captures **raw `sceneDepth` as the primary stream** (`streams/depth.f32`), with
  `smoothedSceneDepth` only as an optional sidecar (`streams/smoothed_depth.f32`) and `confidence` in
  `streams/confidence.bin`. Do NOT "add raw capture" — it exists. The earlier note that all frames used
  `smoothedSceneDepth` was an older capture/device state, not the current code.
- The motion gate (`deltaMeanAbsThresholdU16`, mean-abs delta on the 32x32 downsampled UInt16/8 m depth)
  is **OFF by default** (`depthDeltaThresholdMeanU16 = 0`). The low `depthRetention` (~2%) seen in early
  pilot stats is NOT caused by a hard-coded 400; the real causes are unverified (30 fps frame cap vs ARKit
  ~15 Hz sceneDepth cadence, warmup/valid-ratio/in-flight skips, or sensor/environment). Instrument before asserting.
- There is **no autofocus/exposure lock API** on `ARWorldTrackingConfiguration`. `configuration.isAutofocusEnabled`
  does not exist. ARKit manages the camera; focus/exposure locking would require lower-level AVCaptureDevice access
  that an active ARSession generally overrides. Do not plan a "one-line autofocus lock". Control lighting instead.
- **Motion-gate auto-calibration was implemented, then REVERTED (2026-08-18).** A Settings toggle
  *"Auto-calibrate motion gate from baseline"* measured a median of adjacent 32x32 mean-abs-delta over the
  first 30 saved frames and set `threshold = floor * 4`. On-device depth-diagnostic testing proved it
  **harmful**: with the toggle ON, retention collapsed to 5.3% (32/600 frames; 545 motion-gate skips) because
  the baseline window caught ARKit settling/early motion and inflated the floor to ~40 UInt16 units
  (threshold 160 ≈ 19.5 mm mean surface change per frame). With the gate OFF (the default), the SAME rig
  retained **95.5%** (573/600), losing only 23 warmup frames.
- **Verified retention fact:** normal capture with the motion gate off already retains ~95.5% of AR depth
  frames; the earlier ~2% `depthRetention` figure from old pilot stats is NOT reproducible and was wrong.
  There is no retention problem to solve. Do not re-add a motion gate unless it is gated on true stillness
  and a low-percentile physical-mm threshold; the naive version was reverted from source.
- Post-processing strengths to use: temporal median+outlier aggregation, per-device bias-field subtraction,
  RANSAC/corner-marker plane leveling, gauge-block (5 mm / 10 mm) recovery as the acceptance metric.
  Constrain any RGB-guided upsampling to edge-preserving interpolation between measured pixels (never snap
  depth to drawing edges / shadows) and label output as derived.
