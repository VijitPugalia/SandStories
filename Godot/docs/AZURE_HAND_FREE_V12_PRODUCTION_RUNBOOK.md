# Aligned Azure RGB-D to Hand-Free v12: End-to-End Production Runbook

- Status: accepted capture-specific production procedure
- Last verified: 2026-08-20
- Capture: `azure_20260814_173944`
- Input sequence: 2,275 aligned RGB/depth frame pairs
- Selected output range: source frames 520-720 (201 frames)
- Final session: `session_azure_20260814_173944_intrinsic_albedo_v12_0520_0720`

## 1. Purpose and starting point

This runbook starts with **only aligned per-frame RGB and depth** and ends with
the accepted hand-free v12 Godot session. The starting directory contains no
hand masks, no inpainted RGB, no completed depth, no Godot session, and no
normal maps.

The required starting layout is:

```text
<work>/
  rgb/
    frame_000001.jpg
    ...
    frame_002275.jpg
  depth/
    depth_000001.png
    ...
    depth_002275.png
```

For the accepted capture:

- RGB is already registered to depth, BGR/RGB8, `640 x 576`.
- Depth is single-channel `uint16`, in millimetres, `640 x 576`.
- Depth value `0` means invalid.
- Frame numbering is continuous and one-indexed.
- The camera and sand tray are fixed.
- Frame 1 is sufficiently actor-free to define the tray surface band.
- The target clip is 520-720, but frames through 1000 are retained as
  post-roll. The future frames are required by the bidirectional donor pass.

This runbook does not cover MKV decoding or RGB-depth registration. If the
starting RGB and depth are not already spatially aligned, stop and perform
calibrated registration first.

For variable-length MKV ingestion, resumable web submission, queued execution,
and selectable PNG or video-stream artifacts, see
[`RGBD_JOB_GATEWAY.md`](RGBD_JOB_GATEWAY.md). The gateway wraps this production
profile without changing the capture-specific thresholds documented below.

## 2. Final dependency graph

```text
aligned RGB + metric depth
        |
        +--> Grounded-SAM-2 hand/arm masks ------------------+
        |                                                     |
        +--> ProPainter candidate RGB <-----------------------+
        |                                                     |
        +--> quality-filtered Azure metric anchors            |
        |          |                                          |
        |          +--> hand-free conditioning --> Any2Full --+
        |                                                     |
        +--> depth-transience masks ---------------------------+
                                                              |
                                                              v
                                      v3 bidirectional RGB-D reconstruction
                                                              |
                                                              v
                                      v4 robust reconstructed normals
                                                              |
                                                              v
                                      v9 spatial-activation geometry

v4 RGB --> v12 intrinsic/albedo shadow repair ----------------+
                                                              |
                                                              v
                                      final v12 Godot session
```

The branches have deliberately different authority:

- Raw Azure depth is the metric evidence.
- Any2Full supplies a dense, Azure-anchored depth proposal; it is derived, not
  measured ground truth.
- Grounded-SAM-2 and depth transience decide where the current observation is
  not trustworthy.
- ProPainter is only a gated RGB proposal. It never supplies geometry.
- v9 supplies final geometry.
- v12 replaces only RGB appearance and cannot change depth or normals.

## 3. Why the complete source sequence is required

The final session contains 201 frames, but producing it from only those 201
frames is not equivalent to the accepted result.

The v3 reconstruction uses:

- frames before 520 to establish trusted past sand observations;
- frames 520-720 as the delivered clip; and
- frames 721-1000 as future donors after the hand has moved.

The accepted v3 build found approximately 7.40 million masked pixels with both
past and future donors. The median donor gap was 85 frames and P95 was 118
frames. Removing the pre-roll or post-roll changes the reconstruction.

## 4. Software and model provenance

The GPU stages were run on Linux. The CPU reconstruction and final Godot
materialization can run on Linux or Windows.

### 4.1 Accepted external revisions

| Component | Revision |
| --- | --- |
| Grounded-SAM-2 | `b7a9c29f196edff0eb54dbe14588d7ae5e3dde28` |
| ProPainter | `e870e79321c31b733e2031af5aa2fb1fe3ac7eec` |
| Any2Full | `780edf6be2bf9260f1cce8e4ddbcb52d7bcdae9e` |

This repository packages the accepted custom Grounded-SAM-2 driver as
`tools/grounded_sam2_tracking_sandiv.py`. The original production copy, before
the repository provenance comment was added, had SHA-256:

```text
6ae9d6db4bf059ba013c023a1f0d1e8b34398cfb994d469986c8f835cf651a6d
```

Its executable body is unchanged. The driver is part of the accepted
provenance; a clean upstream Grounded-SAM-2 checkout alone is not sufficient.

### 4.2 Accepted runtime versions

| Environment | Versions |
| --- | --- |
| CPU tools | Python 3.11.9, OpenCV 4.12.0, NumPy 1.26.4, SciPy 1.14.1 |
| ProPainter | Python 3.11.2, PyTorch 2.5.1 + CUDA 12.1 |
| Any2Full | Python 3.11.2, PyTorch 2.1.1 + CUDA 12.1 |

Accepted checkpoints:

- `sam2.1_hiera_large.pt` (898,083,611 bytes);
- Grounding DINO `IDEA-Research/grounding-dino-tiny`; and
- `Any2Full_vitl.pth.tar` (2,069,029,116 bytes).

### 4.3 Production helper scripts

The RGB/depth-to-v3 stages use these repository tools:

- `tools/azure_sam2_prep.py`
- `tools/grounded_sam2_tracking_sandiv.py`
- `tools/run_sam2_arm_pass.sh`
- `tools/merge_sam2_masks.py`
- `tools/run_propainter_fullres.py`
- `tools/azure_prepare_input.py`
- `tools/azure_clean_rgb_handfree.py`
- `tools/azure_depth_actor_mask.py`
- `tools/azure_bidirectional_filter.py`
- `tools/run_any2full_eval_remote.py`

The v4-to-v12 stages use these repository tools:

- `tools/build_robust_normal_sidecar.py`
- `tools/build_persistent_substrate_v5.py`
- `tools/remove_spatial_shadow_intrinsic_v12.py`
- `tools/materialize_intrinsic_albedo_session_v12.py`
- `tools/audit_hand_edge_terraces.py`
- `tools/test_audit_hand_edge_terraces.py`
- `tools/start_review_server.ps1`

## 5. Safety and capacity rules

- Never run a generation stage into an accepted or non-empty output directory.
- Use a fresh work copy for derived SAM, ProPainter, and Any2Full directories.
- Do not modify the starting RGB/depth pairs.
- Do not start a full sequence stage with less than 25 GiB free.
- With less than 20 GiB free, perform diagnosis or explicit cleanup only.
- Keep raw RGB/depth, the final v3/v4/v9/v12 receipts, and model provenance.
- Do not commit raw captures, generated sessions, checkpoints, or participant
  data to Git.
- Prefer hard links for unchanged Godot assets.

The commands below use explicit output names and refuse existing final session
directories. Some historical GPU helper scripts recreate their own derived
scratch directories, so run them only inside a dedicated work copy.

## 6. Linux GPU workspace setup

Set paths for the machine that contains the models and the starting RGB/depth.
Keep machine-specific installation paths in the shell environment rather than
committing them into this runbook.

```bash
set -euo pipefail

export PIPELINE_ROOT="${PIPELINE_ROOT:?set PIPELINE_ROOT to the repository Godot/tools directory}"
export WORK="${WORK:?set WORK to the directory containing rgb/ and depth/}"
export GPU_ID="${GPU_ID:-0}"

export CPU_PY="${CPU_PY:?set CPU_PY to the production Python 3.11 executable}"
export SAM2_ROOT="${SAM2_ROOT:?set SAM2_ROOT to the Grounded-SAM-2 checkout}"
export SAM2_PY="${SAM2_PY:-$CPU_PY}"
export PROPAINTER_ROOT="${PROPAINTER_ROOT:?set PROPAINTER_ROOT to the ProPainter checkout}"
export PROPAINTER_PY="${PROPAINTER_PY:?set PROPAINTER_PY to the ProPainter Python executable}"
export ANY2FULL_ROOT="${ANY2FULL_ROOT:?set ANY2FULL_ROOT to the Any2Full checkout}"
export ANY2FULL_PY="${ANY2FULL_PY:?set ANY2FULL_PY to the Any2Full Python executable}"
export ANY2FULL_CKPT="${ANY2FULL_CKPT:-$ANY2FULL_ROOT/checkpoints/Any2Full_vitl.pth.tar}"

export FRAME_COUNT=2275
export CLIP_START=520
export CLIP_END=720
export POST_END=1000
export METRIC_LOW=0.400
export METRIC_HIGH=0.630

test -d "$WORK/rgb"
test -d "$WORK/depth"
test -f "$PIPELINE_ROOT/azure_bidirectional_filter.py"
test -f "$PIPELINE_ROOT/grounded_sam2_tracking_sandiv.py"
test -f "$ANY2FULL_CKPT"

df -h "$WORK"
```

Fail the local capacity gate programmatically:

```bash
"$CPU_PY" - "$WORK" <<'PY'
from pathlib import Path
import shutil
import sys

work = Path(sys.argv[1])
free_gib = shutil.disk_usage(work).free / 1024**3
print(f"free space: {free_gib:.2f} GiB")
if free_gib < 25:
    raise SystemExit("free-space gate failed: at least 25 GiB is required")
PY
```

## 7. Validate the RGB/depth-only input

This validation checks continuity, dimensions, and depth encoding without
creating derived files.

```bash
"$CPU_PY" - "$WORK" "$FRAME_COUNT" <<'PY'
from pathlib import Path
import cv2
import sys

work = Path(sys.argv[1])
count = int(sys.argv[2])

for index in range(1, count + 1):
    rgb = work / "rgb" / f"frame_{index:06d}.jpg"
    depth = work / "depth" / f"depth_{index:06d}.png"
    if not rgb.is_file() or not depth.is_file():
        raise SystemExit(f"missing pair at frame {index}: {rgb}, {depth}")

for index in (1, 520, 720, 1000, count):
    rgb = cv2.imread(str(work / "rgb" / f"frame_{index:06d}.jpg"), cv2.IMREAD_COLOR)
    depth = cv2.imread(
        str(work / "depth" / f"depth_{index:06d}.png"),
        cv2.IMREAD_UNCHANGED,
    )
    if rgb is None or rgb.shape != (576, 640, 3):
        raise SystemExit(f"unexpected RGB frame {index}: {None if rgb is None else rgb.shape}")
    if depth is None or depth.shape != (576, 640) or depth.dtype.name != "uint16":
        raise SystemExit(
            f"unexpected depth frame {index}: "
            f"{None if depth is None else (depth.shape, depth.dtype)}"
        )

print({"pairs": count, "shape": [576, 640], "depth": "uint16 millimetres"})
PY
```

For the accepted capture, the first depth frame had valid-depth percentiles of
approximately 403, 461, and 627 mm at P1/P50/P99. A materially different tray
distance requires recalibrating the `400 630` surface band instead of copying
the accepted values blindly.

## 8. Build automatic hand/arm masks

### 8.1 Prepare model inputs

Grounded-SAM-2 was run at `320 x 288` to fit the complete sequence into GPU
memory. ProPainter retained the full `640 x 576` RGB.

```bash
"$SAM2_PY" "$PIPELINE_ROOT/azure_sam2_prep.py" "$WORK"
```

Expected results:

- 2,275 JPEGs under `sam2_input`;
- 2,275 full-resolution links under `propainter_input`.

### 8.2 Split SAM input into bounded segments

```bash
"$CPU_PY" - "$WORK" <<'PY'
from pathlib import Path
import sys

work = Path(sys.argv[1])
frames = sorted((work / "sam2_input").glob("*.jpg"))
if list(work.glob("sam2_seg_*")):
    raise SystemExit("refusing to reuse existing sam2_seg_* directories")

segment_length = 550
for segment_index, start in enumerate(range(0, len(frames), segment_length), 1):
    destination = work / f"sam2_seg_{segment_index}"
    destination.mkdir()
    for frame in frames[start : start + segment_length]:
        (destination / frame.name).symlink_to(frame)

print({"frames": len(frames), "segments": len(list(work.glob('sam2_seg_*')))})
PY
```

### 8.3 Grounded-SAM-2 pass 1: `hand. arm.`

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

for segment in "$WORK"/sam2_seg_*; do
    name="$(basename "$segment")"
    output="$WORK/sam2_output_$name"
    test ! -e "$output"
    (
        cd "$SAM2_ROOT"
        CUDA_VISIBLE_DEVICES="$GPU_ID" "$SAM2_PY" \
            "$PIPELINE_ROOT/grounded_sam2_tracking_sandiv.py" \
            --video-dir "$segment" \
            --output-dir "$output" \
            --text "hand. arm." \
            --step 10 \
            --box-threshold 0.35 \
            --text-threshold 0.20 \
            --sam2-checkpoint checkpoints/sam2.1_hiera_large.pt \
            --sam2-config configs/sam2.1/sam2.1_hiera_l.yaml \
            --grounding-model IDEA-Research/grounding-dino-tiny
    )
done

test ! -e "$WORK/sam2_output/binary_masks"
mkdir -p "$WORK/sam2_output/binary_masks"
for segment in "$WORK"/sam2_seg_*; do
    name="$(basename "$segment")"
    cp "$WORK/sam2_output_$name"/binary_masks/*.png \
        "$WORK/sam2_output/binary_masks/"
done
```

### 8.4 Grounded-SAM-2 pass 2: `arm.`

The second pass used the custom maximum-box-area filter to reject tray-sized
false arm detections.

```bash
bash "$PIPELINE_ROOT/run_sam2_arm_pass.sh" "$WORK" "$GPU_ID"
```

### 8.5 Merge and upscale the two passes

```bash
"$SAM2_PY" "$PIPELINE_ROOT/merge_sam2_masks.py" "$WORK"

test "$(find "$WORK/propainter_masks" -maxdepth 1 -type f | wc -l)" -eq "$FRAME_COUNT"
```

The accepted merge included a 17-pixel vertical extension at the `320 x 288`
mask scale before upscaling. This was intended to include fingertips and the
arm continuation entering from the top of the fixed view. It is a
capture-specific rule and must be visually revalidated for a different camera
orientation.

Review at least frames 520, 580, 620, 633, 700, and 720. Reject masks that miss
either hand or cover a tray-sized region.

## 9. Generate full-resolution ProPainter candidate RGB

Run the segmented, resume-aware wrapper:

```bash
"$PROPAINTER_PY" "$PIPELINE_ROOT/run_propainter_fullres.py" \
    "$WORK" \
    "$GPU_ID" \
    --seg-len 500 \
    --overlap 16

test "$(find "$WORK/display_rgb_full" -maxdepth 1 -type f -name 'frame_*.png' | wc -l)" \
    -eq "$FRAME_COUNT"
```

The wrapper uses official ProPainter with:

- `--mask_dilation 4`;
- `--ref_stride 35`;
- `--subvideo_length 40`;
- `--fp16`; and
- full `640 x 576` output.

Important: this output is a candidate, not the final texture. Large occlusions
can become blurred. The v3 builder accepts ProPainter only where its colour is
consistent with temporal donors and its local sharpness does not decrease.

## 10. Build metric Any2Full depth proposals

### 10.1 Prepare sparse Azure anchors

```bash
test ! -e "$WORK/any2full_input"

"$CPU_PY" "$PIPELINE_ROOT/azure_prepare_input.py" \
    --rgb-dir "$WORK/rgb" \
    --depth-dir "$WORK/depth" \
    --object-mask-dir "$WORK/propainter_masks" \
    --output-root "$WORK/any2full_input" \
    --band-mm 400 630 \
    --object-dilate 8 \
    --local-residual-mm 8 \
    --gradient-mm 30 \
    --frames "$FRAME_COUNT"

test ! -e "$WORK/surface_mask.png"
cp "$WORK/any2full_input/surface_mask.png" "$WORK/surface_mask.png"
```

This stage:

1. defines `surface_mask.png` from the first depth frame and the 400-630 mm
   tray band;
2. rejects invalid, hand-masked, locally inconsistent, and high-gradient Azure
   samples;
3. writes metric depth in metres; and
4. retains quality samples on grid-4 and grid-6 lattices.

The accepted `surface_mask.png` covered 80.9% of the image. The grid-4 anchor
count was commonly around 13,000-17,000 pixels per frame.

### 10.2 Produce model-conditioning RGB

```bash
test ! -e "$WORK/rgb_clean_handfree"

"$CPU_PY" "$PIPELINE_ROOT/azure_clean_rgb_handfree.py" \
    --session "$WORK" \
    --mask-dir "$WORK/propainter_masks" \
    --rgb-dir "$WORK/display_rgb_full" \
    --out-dir "$WORK/rgb_clean_handfree" \
    --dilate 8 \
    --radius 5 \
    --mode inpaint \
    --frames "$FRAME_COUNT"
```

This Telea pass is **conditioning only**. It is intentionally not used as the
final visible RGB because it can create grey or pink blurred patches inside a
large hand mask.

### 10.3 Run Any2Full

```bash
test ! -e "$WORK/predictions_handfree"

(
    cd "$ANY2FULL_ROOT"
    CUDA_VISIBLE_DEVICES="$GPU_ID" "$ANY2FULL_PY" \
        "$PIPELINE_ROOT/run_any2full_eval_remote.py" \
        --any2full-root "$ANY2FULL_ROOT" \
        --input-root "$WORK/any2full_input" \
        --rgb-dir "$WORK/rgb_clean_handfree" \
        --output-root "$WORK/predictions_handfree" \
        --encoder vitl \
        --checkpoint "$ANY2FULL_CKPT" \
        --frame-start 1 \
        --frame-end "$FRAME_COUNT" \
        --densities 4 \
        --metric-low "$METRIC_LOW" \
        --metric-high "$METRIC_HIGH" \
        --device cuda
)

test "$(find "$WORK/predictions_handfree/grid4" -maxdepth 1 -type f -name 'frame_*.npy' | wc -l)" \
    -eq "$FRAME_COUNT"
```

Any2Full output remains a derived dense proposal. Unmasked Azure samples and
the later temporal reconstruction retain metric authority.

## 11. Build conservative raw-depth actor masks

The bidirectional builder computes its own depth-transience masks for the
delivered range. This additional sequence is used conservatively in the
post-roll to prevent future donor selection from landing on a hand pixel.

```bash
test ! -e "$WORK/depth_actor_masks"

"$CPU_PY" "$PIPELINE_ROOT/azure_depth_actor_mask.py" \
    --session "$WORK" \
    --depth-dir "$WORK/depth" \
    --out-dir "$WORK/depth_actor_masks" \
    --threshold-mm 420 \
    --min-area 100 \
    --frames "$FRAME_COUNT"
```

## 12. Build v3 bidirectional RGB-D reconstruction

The v3 mask is the union of:

- depth transience relative to a robust q75 sand reference;
- the Grounded-SAM-2/ProPainter mask; and
- a `+/-3` frame temporal propagation.

For masked pixels, the builder finds the closest trusted observations before
and after the occlusion and blends them by temporal distance. ProPainter may
contribute at most 25% and only passes where colour consistency and sharpness
support it.

```bash
export DERIVED_ROOT="$WORK/persistence_test_B_0520_0720"
export V3_REMOTE="$DERIVED_ROOT/session_azure_20260814_173944_bidirectional_v3_0520_0720"

test ! -e "$V3_REMOTE"
mkdir -p "$DERIVED_ROOT"

"$CPU_PY" "$PIPELINE_ROOT/azure_bidirectional_filter.py" \
    "$WORK" \
    --start "$CLIP_START" \
    --end "$CLIP_END" \
    --post-end "$POST_END" \
    --output-session "$V3_REMOTE" \
    --session-id session_azure_20260814_173944_bidirectional_v3_0520_0720 \
    --title "Azure bidirectional v3 temporal donors / gated ProPainter" \
    --fps 30 \
    --sample-stride 10 \
    --margin-mm 15 \
    --large-margin-mm 30 \
    --short-horizon 45 \
    --long-horizon 120 \
    --support-threshold 0.55 \
    --tolerance-mm 3 \
    --min-component-area 120 \
    --dilation 11 \
    --temporal-radius 3 \
    --inner-feather 4 \
    --outer-feather 12 \
    --propainter-max-weight 0.25 \
    --metric-low "$METRIC_LOW" \
    --metric-high "$METRIC_HIGH" \
    --review-frames 520,560,580,600,620,633,650,680,700,720
```

Accepted v3 receipt values:

| Field | Accepted value |
| --- | ---: |
| Processed frames | 201 |
| Median mask pixels | 25,784 |
| Maximum mask pixels | 95,535 |
| Bidirectional donor samples | 7,397,762 |
| Median donor gap | 85 frames |
| P95 donor gap | 118 frames |
| Mean accepted ProPainter weight | 0.1177 |
| P95 accepted ProPainter weight | 0.2322 |

Reject the build if the trench is still absent at source frames 700/720, or if
hand-shaped depth is visible in the review sheet.

## 13. Build v4 robust reconstructed normals

This stage preserves v3 depth and RGB. It derives temporally stable,
mask-aware object-space normals from a separate regularized height stack.

The command can run in the GPU workspace or after v3 is transferred to the
Godot workstation.

```bash
export V4_REMOTE="$DERIVED_ROOT/session_azure_20260814_173944_bidirectional_v4_robust_normals_0520_0720"

test ! -e "$V4_REMOTE"

"$CPU_PY" "$PIPELINE_ROOT/build_robust_normal_sidecar.py" \
    "$V3_REMOTE" \
    "$V4_REMOTE" \
    --session-id session_azure_20260814_173944_bidirectional_v4_robust_normals_0520_0720 \
    --title "Azure bidirectional v4 / robust temporal normals" \
    --temporal-radius 2 \
    --fine-diameter 7 \
    --fine-sigma-mm 1.5 \
    --coarse-diameter 15 \
    --coarse-sigma-mm 4.0 \
    --coarse-spatial-sigma 5.0 \
    --masked-normal-confidence 0.68 \
    --plane-width 5.5 \
    --plane-depth 5.5 \
    --shader-arg-1 11.625 \
    --displacement -5.0 \
    --metric-range-mm 230 \
    --review-frames 1,100,112,131,160,181,201
```

Accepted masked temporal normal jump:

- median: `0.0791 degrees`;
- P95: `1.8820 degrees`.

## 14. Transfer v3/v4 into the active Godot project

On Windows PowerShell, start in the active `Godot` directory. Set the remote
host through an environment variable rather than embedding a personal SSH
alias in the document.

```powershell
$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path ".").Path
if (-not (Test-Path -LiteralPath (Join-Path $Repo "project.godot"))) {
    throw "Run this block from the active Godot project directory"
}

$Sessions = Join-Path $Repo "assets\processed_sessions"
$RemoteHost = $env:SANDSTORIES_GPU_HOST
$RemoteDerivedRoot = $env:SANDSTORIES_AZURE_DERIVED_ROOT
if (-not $RemoteHost -or -not $RemoteDerivedRoot) {
    throw "Set SANDSTORIES_GPU_HOST and SANDSTORIES_AZURE_DERIVED_ROOT"
}

$V3Name = "session_azure_20260814_173944_bidirectional_v3_0520_0720"
$V4Name = "session_azure_20260814_173944_bidirectional_v4_robust_normals_0520_0720"
$V3 = Join-Path $Sessions $V3Name
$V4 = Join-Path $Sessions $V4Name

foreach ($target in @($V3, $V4)) {
    if (Test-Path -LiteralPath $target) {
        throw "Refusing to overwrite existing session: $target"
    }
}

scp -r "${RemoteHost}:$RemoteDerivedRoot/$V3Name" $Sessions
scp -r "${RemoteHost}:$RemoteDerivedRoot/$V4Name" $Sessions
```

If the accepted v3/v4 already exist locally, do not copy or rebuild over them.

## 15. Windows Python and output setup

```powershell
$ScratchRoot = Join-Path ([System.IO.Path]::GetTempPath()) "sandstories_v12_rebuild"
$EnvDir = Join-Path $ScratchRoot "venv"
$Python = Join-Path $EnvDir "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    New-Item -ItemType Directory -Force -Path $ScratchRoot | Out-Null
    py -3.11 -m venv $EnvDir
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Repo "requirements.txt")
}

& $Python -c "import cv2, numpy, scipy; print(cv2.__version__, numpy.__version__, scipy.__version__)"

$RunSuffix = "_rebuild_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
$V9 = Join-Path $Sessions ("session_azure_20260814_173944_spatial_activation_v9_0520_0720" + $RunSuffix)
$V12 = Join-Path $Sessions ("session_azure_20260814_173944_intrinsic_albedo_v12_0520_0720" + $RunSuffix)
$V12Rgb = Join-Path $ScratchRoot ("v12_full_rgb" + $RunSuffix)

$localFreeGiB = (Get-PSDrive -Name C).Free / 1GB
if ($localFreeGiB -lt 25) {
    throw "Local free-space gate failed: $([math]::Round($localFreeGiB, 2)) GiB"
}
```

## 16. Build v9 progressive geometry

v9 replaces the per-pixel donor mosaic with a coherent substrate model:

1. robust before/after atlases from unoccluded depth;
2. a fixed temporal-union geometry guard over the hand path;
3. per-pixel first-activation times inferred from persistent observations;
4. a three-frame activation ramp; and
5. normals regenerated from the same depth trajectory.

The historical development path produced a v5 DiffuEraser candidate before
v9. That candidate is not required for the final v12 dependency chain: v9 uses
its RGB only as a placeholder, and v12 replaces every RGB frame. For a clean
rebuild, reuse v4 RGB while producing the accepted v9 geometry.

```powershell
if (Test-Path -LiteralPath $V9) {
    throw "Refusing to overwrite existing v9 output: $V9"
}

& $Python (Join-Path $Repo "tools\build_persistent_substrate_v5.py") `
    $V4 `
    $V9 `
    --reuse-rgb-session $V4 `
    --minimum-free-gb 25 `
    --session-id (Split-Path $V9 -Leaf) `
    --title "Azure spatial-activation substrate v9 / progressive trench geometry" `
    --revision-version 9 `
    --geometry-guard-radius 24 `
    --geometry-residual-support-radius 60 `
    --geometry-residual-threshold-mm 3.0 `
    --geometry-temporal-union `
    --geometry-temporal-union-margin 14 `
    --spatial-activation `
    --activation-exclusion-radius 22 `
    --activation-vote-window 5 `
    --activation-vote-minimum 2 `
    --activation-ramp-frames 3 `
    --boundary-expansion-radius 18 `
    --boundary-inpaint-radius 20 `
    --boundary-bias-sigma 9 `
    --transition-radius 30

if ($LASTEXITCODE -ne 0) {
    throw "v9 geometry build failed"
}
```

Expected v9 output:

- 201 `clean_depth` frames;
- 201 `normal_map` frames;
- 201 `normal_confidence` frames;
- 201 placeholder RGB frames;
- `latent_substrate_v9_review.png`;
- `latent_substrate_v9_stats.json`; and
- `latent_substrate_v9_receipt.json`.

Accepted v9 values include masked-normal temporal jump P95 of approximately
`0.386 degrees` and substrate progress from approximately `0.0067` to `1.0`.

### 16.1 Historical v5 provenance

The original investigation also ran:

```text
v4 + DiffuEraser RGB candidate -> latent substrate v5 -> v9 reused v5 RGB
```

v5 helped establish the coherent-atlas direction, but its generated RGB was
not accepted as final appearance. The final v12 materializer discards that RGB
branch. Preserve v5 receipts when auditing the historical experiment; do not
make DiffuEraser a mandatory dependency of a clean v12 rebuild.

## 17. Generate v12 intrinsic/albedo RGB

The dark T-shaped region exists before ProPainter and is primarily broad cast
illumination. The accepted v12 operation preserves high-frequency RGB detail
and reconstructs only the low-frequency illumination/albedo component.

Use v4 RGB as the source because it retains the temporally gated hand-removal
result without depending on rejected v5/v11 generated appearance.

```powershell
if (Test-Path -LiteralPath $V12Rgb) {
    throw "Refusing to overwrite existing v12 RGB scratch output: $V12Rgb"
}

& $Python (Join-Path $Repo "tools\remove_spatial_shadow_intrinsic_v12.py") `
    --session $V4 `
    --output $V12Rgb `
    --close-size 251 `
    --maximum-gain 6 `
    --matte-threshold 2 `
    --matte-softness 12 `
    --neutralize-albedo `
    --detail-sigma 5 `
    --analysis-scale 0.5

if ($LASTEXITCODE -ne 0) {
    throw "v12 intrinsic/albedo RGB generation failed"
}
```

Expected output:

- 201 `clean_rgb_XXXXXX.png` frames;
- 201 mattes;
- `review.png`; and
- `report.json`.

Review frames 1, 40, 80, 100, 120, 140, 160, 180, and 201. Reject broad blur,
checkerboard texture, missing trench texture, or incomplete shadow removal.

## 18. Materialize final v12 without changing geometry

```powershell
if (Test-Path -LiteralPath $V12) {
    throw "Refusing to overwrite existing v12 output: $V12"
}

& $Python (Join-Path $Repo "tools\materialize_intrinsic_albedo_session_v12.py") `
    --source-session $V9 `
    --rgb-dir $V12Rgb `
    --output-session $V12 `
    --min-free-gib 25

if ($LASTEXITCODE -ne 0) {
    throw "v12 materialization failed"
}
```

On the accepted NTFS build, the receipt recorded 2,419 hard links and zero
copies. A different filesystem may copy instead; re-check capacity first.

## 19. Run the hand-edge terrace audit

The audit samples depth profiles along outward normals from the original v3
hand contour. It excludes the intentional trench and pre-existing large
discontinuities.

```powershell
$Audit = Join-Path $V12 "hand_edge_terrace_audit.json"

& $Python (Join-Path $Repo "tools\audit_hand_edge_terraces.py") `
    $V3 `
    $V9 `
    $V12 `
    --change-reference $V12 `
    --frames "81,101,103,121,141,161,181,201" `
    --profile-radius 48 `
    --maximum-profiles 900 `
    --prominence-mm 0.20 `
    --maximum-profile-range-mm 12 `
    --change-threshold-mm 2.0 `
    --change-margin 10 `
    --output $Audit

if ($LASTEXITCODE -ne 0) {
    throw "hand-edge terrace audit failed"
}
```

Run the synthetic regression test:

```powershell
Push-Location (Join-Path $Repo "tools")
try {
    & $Python -m unittest -v test_audit_hand_edge_terraces.py
    if ($LASTEXITCODE -ne 0) {
        throw "synthetic terrace regression test failed"
    }
}
finally {
    Pop-Location
}
```

Accepted v12 reductions relative to v3, using the same 735 stable contour
profiles:

| Metric | Reduction |
| --- | ---: |
| Profiles with multiple troughs | 51.1% |
| P95 trough prominence | 58.1% |
| Coherent hand-contour residual | 57.4% |
| Normal-direction gradient RMS | 23.6% |

All four metrics must improve. A scalar improvement does not override a visual
failure at frames 101, 103, or 121.

## 20. Verify geometry identity and frame completeness

The final v12 must contain 201 RGB frames and 603 geometry files that are
byte-identical to v9: 201 depth, 201 normal, and 201 normal-confidence files.

```powershell
& $Python -c @"
from pathlib import Path
import hashlib

v9 = Path(r'$V9')
v12 = Path(r'$V12')
groups = (
    ('clean_depth', 'clean_depth'),
    ('normal_map', 'normal'),
    ('normal_confidence', 'normal_confidence'),
)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

checked = 0
for directory, stem in groups:
    for index in range(1, 202):
        name = f'{stem}_{index:06d}.png'
        source = v9 / directory / name
        candidate = v12 / directory / name
        if digest(source) != digest(candidate):
            raise SystemExit(f'geometry mismatch: {candidate}')
        checked += 1

rgb_count = len(list((v12 / 'clean_rgb').glob('clean_rgb_*.png')))
if checked != 603 or rgb_count != 201:
    raise SystemExit(f'incomplete v12: geometry={checked}, rgb={rgb_count}')
print({'geometry_files_verified': checked, 'rgb_frames': rgb_count})
"@

if ($LASTEXITCODE -ne 0) {
    throw "v12 integrity verification failed"
}
```

## 21. Godot visual acceptance

```powershell
& (Join-Path $Repo "tools\start_review_server.ps1") `
    -Port 8845 `
    -BindAddress "127.0.0.1" `
    -SessionName (Split-Path $V12 -Leaf) `
    -Background

$SessionName = Split-Path $V12 -Leaf
$SessionUrl = "http://127.0.0.1:8845/assets/processed_sessions/$SessionName/session.json"
$ReviewUrl = "http://127.0.0.1:8845/index.html?session=$([Uri]::EscapeDataString($SessionUrl))&debug=1&autoplay=0"
Start-Process $ReviewUrl
```

Camera shortcuts:

- `1`: top view;
- `2`: front/low-angle view;
- `3`: orbit/oblique view.

Review frames 80, 100, 101, 103, 121, 140, 160, 180, and 201.

Accept only when:

- the trench is absent before it is drawn;
- the trench appears progressively around frames 140, 160, and 180;
- the complete trench does not globally fade in;
- no repeated hand/finger-shaped terraced depression remains;
- the T-shaped cast shadow is no longer dominant;
- sand grain and trench RGB detail are preserved;
- depth and reconstructed normals agree in oblique light; and
- Godot reports no loading or WebGL error.

Some isolated local transitions may remain around frames 101-121. Do not apply
global smoothing merely to reduce a metric; that can erase the real trench.

## 22. Rejected branches and what was learned

### One-sided persistence filtering

Freezing the last trusted surface removed hand depth but delayed the trench and
retained old terrain. The accepted v3 uses both past and future donors.

### Direct ProPainter as final RGB

Large hand/arm holes became grey or pink blurred patches, and incomplete masks
left visible hand pixels. ProPainter remains a low-weight, gated proposal.

### ProPainter followed by Telea as final RGB

The second single-frame inpaint degraded temporal ProPainter output further.
Telea is retained only as Any2Full conditioning.

### v5 global substrate progress

It reduced donor noise but moving hand boundaries still influenced geometry.

### v7 expanded per-frame geometry mask

It moved the seam outward rather than eliminating the actor-shaped boundary.

### v8 temporal-union mask with one global progress value

It removed much of the hand outline but made the complete final trench fade in
at once. v9 replaces global progress with per-pixel spatial activation.

### Metric Video Depth Anything

The tested metric model had approximately 943 mm median direct error against
trusted Azure pixels. Affine alignment still left approximately 39.4 mm median
error and reversed depth direction. It is not metric geometry truth here.

### Expanded shadow-mask ProPainter v11c

It reduced the shadow but introduced checkerboard/blurred regions and erased
trench texture near frame 140. It was not merged.

### Temporal RGB median atlas

The hand/shadow occupied the centre for too much of the window, so the median
learned the shadow instead of removing it.

## 23. Final end-to-end checklist

- [ ] Input contains 2,275 continuous aligned RGB/depth pairs.
- [ ] RGB is `640 x 576`; depth is aligned `uint16` millimetres.
- [ ] Full pre-roll and post-roll through frame 1000 are retained.
- [ ] Free space is at least 25 GiB before every full stage.
- [ ] Grounded-SAM-2 revisions, custom driver hash, and checkpoints match.
- [ ] Both SAM passes and merged masks contain 2,275 frames.
- [ ] Frames 520/580/620/633/700/720 pass mask review.
- [ ] ProPainter candidate RGB contains 2,275 frames.
- [ ] Any2Full input report records the 400-630 mm band and 2,275 frames.
- [ ] Any2Full grid-4 output contains 2,275 metric `.npy` files.
- [ ] Conservative post-roll depth actor masks contain 2,275 frames.
- [ ] v3 contains 201 RGB/depth/mask frames and its receipt is retained.
- [ ] v4 contains 201 reconstructed normals and confidence maps.
- [ ] v9 contains 201 depth, normal, confidence, and placeholder RGB frames.
- [ ] v12 intrinsic/albedo RGB contains 201 reviewed frames.
- [ ] v12 was materialized without overwriting v9.
- [ ] All 603 final geometry files match v9.
- [ ] The synthetic terrace test passes.
- [ ] The real contour audit improves all four accepted metrics.
- [ ] Frames 101/103 pass low-angle hand-edge review.
- [ ] Frames 140/160/180 show progressive trench growth.
- [ ] Godot loads the final session without errors.
- [ ] Raw inputs, manifests, receipts, revisions, and limitations are retained.

## 24. Provenance statement for research use

The final v12 session is a **derived reconstruction**. Azure Kinect provides
the aligned RGB, metric depth samples, and temporal evidence. Grounded-SAM-2,
ProPainter, Any2Full, bidirectional temporal donors, substrate reconstruction,
normal regularization, and intrinsic/albedo repair are offline derived stages.
The output must not be presented as untouched sensor RGB or measured depth in
regions that were occluded by the hand.
