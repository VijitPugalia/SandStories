# ProPainter → Any2Full Pipeline (consolidated from existing docs)

> This file consolidates the pipeline descriptions already present in the
> project into one overview. It is not a new design. Sources are listed under
> "Document index" at the end; the originals remain authoritative for details.

## Bottom line

**ProPainter's output is not fed directly into Any2Full.** The pipeline follows
one non-negotiable rule — "display RGB, sand depth, and the virtual hand are
three independent products; a generated RGB frame is never recycled as
geometric evidence":

```text
raw RGB ──► Grounded-SAM-2 hand/arm mask ──► ProPainter ──(optional Casper)──► display RGB (display only)
raw RGB + masks ──► separate conditioning RGB (±16-window temporal median + local fill) ──┐
                                                                                          ├─► Any2Full Large ──► dense depth
Kinect/LiDAR raw depth ──► quality filtering + grid4 sparse anchors (~4.37%) ──────────────┘        │
                                                                                                    ▼
                                                          VDA temporal-delta stabilization → frozen sand depth
```

## Stage details

### 1. Display-RGB branch (ProPainter lives here)

- **Grounded-SAM-2** (commit `b7a9c29f…`): detector `grounding-dino-tiny`,
  segmenter SAM 2.1 Hiera Large, prompt `hand. arm.`, detection every 10 frames
  with forward + reverse propagation; masks retained on 665 of 714 frames.
  **No hand-authored masks, spatial rules, or post-processing.**
- **ProPainter** (official commit `e870e793…`): `--save_frames --fp16
  --mask_dilation 4`, one continuous 714-frame run, lossless PNG output. It
  removes the captured hand/forearm but deliberately makes **no shadow-removal
  claim** (residual shadow blur is a known limitation, see the LiDAR doc frame
  629 case).
- **Optional Casper** (CogVideoX-5B clean-background, display only): v21b
  replaced only frames 40–124; v22d ran the full sequence and outputs the full
  predicted background (not a patch composited inside a shadow mask), then
  restored captured high-frequency detail via Laplacian/low-frequency fusion.
  Casper intentionally changes pixels outside the human mask (cast-shadow
  removal); measured mean outside-mask absolute RGB change is 7.858 levels.

### 2. Any2Full conditioning RGB (key: separate from the display branch)

- Built from **raw RGB + the same SAM-2 masks**, **not from ProPainter output**:
  - Window `t−16 … t+16`: visible pixels supply the temporal median; pixels
    masked for the whole window get a local spatial fill; outside-surface
    pixels get the window-local median sand colour.
  - This sequence is **never displayed**, it is model conditioning only.
- The exception in the v22 series (the only direct "ProPainter/Casper →
  Any2Full" connection): conditioning uses a **bounded low-frequency fusion**
  instead of the plain median image —
  `ProPainter + surface_alpha * clip(Gaussian(Casper,σ=12) − Gaussian(ProPainter,σ=12), −48, +48)`
  i.e. keep ProPainter high-frequency texture and add only the bounded
  low-frequency Casper−ProPainter difference (v22b selected; pure-Casper v22a
  rejected).

### 3. Depth branch (Any2Full is here; anchors are the geometric evidence)

- Raw depth (Kinect v1 PGM, or iPhone LiDAR 256×192) → **quality filtering**:
  surface mask required, Kinect-valid required, object-region mask dilated 8 px
  and excluded, encoded height limited to 40–230, 9×9 median consistency ≤ 8
  levels, Sobel gradient ≤ 48, fixed **grid4** sampling.
- Mean retained anchor density ≈ **4.37%**; calibration range
  0.81286–0.92167 m (Kinect path).
- **Any2Full Large / ViT-L** (commit `780edf6b…`, checkpoint
  `Any2Full_vitl.pth.tar`): inputs = grid4 quality-filtered anchors + the
  conditioning RGB from stage 2 → output = 714 dense metric-depth frames.
- Predictions clamped to the calibrated range; per-frame float
  `baselineHeightCorrection` preserves the held-out Kinect median after PNG
  quantization.
- **VDA (Video Depth Anything Small) is only a temporal-delta guide**:
  bidirectional adaptive smoothing, strength 0.92 / difference threshold 18; it
  contributes only frame-to-frame deltas, **never replaces Any2Full spatial
  geometry nor sets the metric scale**; reduces broad coherent jumps from 2 to
  0. Held-out Kinect agreement: MAE 1.319 / RMSE 2.040 / p95 3.465 mm
  (sensor consistency, not hidden-surface ground truth).

## Version history (what each branch changed)

| Version | Change | Status |
|---|---|---|
| v20d | Accepted geometry/hand baseline | baseline |
| v21b | Frames 40–124 display RGB swapped to Casper low-frequency; depth frozen | review |
| v22d | Full-sequence Casper; conditioning uses Casper−ProPainter low-frequency fusion; VDA stabilization | earlier selected |
| v22g/h/k | SAM-safe corner lock → 5-frame per-pixel temporal median → stable-plane (offset+tilt, σ6 Gaussian-smoothed coefficients) + **RG16 packed depth** (quantization error 0.001953 vs 0.5 for 8-bit) | review candidates |
| **v22p** | = v22k + **bidirectional metric temporal anchors inside the mask** (±60-frame before/after observations, accepted only when they agree within 1.5 mm, distance-weighted; 625,489 anchors over 709 frames, 42.23% acceptance) + corner lock + 5-frame median + stable plane + RG16 | **selected on the Kinect path** (`session_…_v22p_…`) |
| LiDAR v24b | iPhone LiDAR path: grid4 anchors ±60-frame median → metric LiDAR surface inside the temporal object envelope blended 48 px smoothstep into Any2Full low frequency → add only 55% high-pass residual (±3 mm, zeroed inside the envelope); mandatory visual gate fixing the frame-458 hand/finger outline | selected on the LiDAR path |

## Key numbers

- Kinect v22p vs v22k: persistent completion-region frame change 0.5761 →
  0.1330 (encoded height units); mask entry/exit region 1.1064 → 0.3243.
- Any2Full anchor consistency (Kinect holdout): MAE ≈ 1.25–1.26 mm /
  RMSE ≈ 2.01–2.02 mm / p95 ≈ 3.32–3.36 mm (differences between conditioning
  branches are tiny).
- LiDAR v24b: holdout MAE 0.921 / RMSE 1.735 / p95 3.081 mm; high-frequency
  detail under the occluded hand is intentionally smooth (no evidence, no
  fabricated detail).
- Any2Full environment: Python 3.9 + torch 2.1 + torchvision 0.16 + numpy<2;
  checkpoints `vits/vitb/vitl` from HF `zhiyuandaily/Any2Full`.

## Document index (sources)

| Document | Covers |
|---|---|
| `SandStories/Godot/docs/RGBD_RECONSTRUCTION_WORKFLOW.md` | v20d baseline + v21b, layer provenance table, dependency direction |
| `SandStories/Godot/docs/KINECT_CASPER_ANY2FULL_V22_WORKFLOW.md` | v22d→v22p end-to-end (Casper memory fix, low-frequency fusion, VDA, corner lock / stable plane / RG16, temporal anchors), commits and numbers |
| `SandStories/Godot/docs/AGENT_HANDOFF.md` | authoritative v21b end-to-end production flow (9 steps: freeze depth → masks → QA gates → ProPainter → packaging → playback gate) |
| `SandStories/Godot/docs/LIDAR_RECONSTRUCTION_PIPELINE.md` | iPhone LiDAR path, v23b failure lessons, v24b temporal anchors |
| `.codex_worktrees/experiment-platform-pr/docs/ANY2FULL.md`, `AUTOMATIC_ANY2FULL.md` | Any2Full as an optional offline derived-data step + automatic field-console queueing (Docker / native runs) |

> Honest boundary: all accuracy numbers are holdout consistency against the
> **same quality-filtered sensor**, not independent external ground truth;
> Casper shadow removal improves RGB appearance only and does not claim to
> recover physically correct depth under every shadow.
