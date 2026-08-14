# LiDAR reconstruction pipeline

This document is the operational direction for iPhone LiDAR sessions after the
`5532036C-251F-4A20-89DC-A0745E463F87` investigation. It does not replace the
accepted Kinect v20d workflow, and no LiDAR experiment may overwrite either
accepted baseline session.

## What the current experiment established

The source capture contains 1,477 RGB frames and 256x192 ARKit
`smoothedSceneDepth`. `smoothed_depth.f32` is empty, so native unsmoothed
high-frequency LiDAR depth is not available. Detail beyond that sampling and
framework smoothing is inferred detail, not recovered sensor ground truth.

Three independent failures were previously visible as one problem:

1. **Display RGB residue.** ProPainter leaves a large gray hand-shaped blur in
   difficult frames such as 629. Any2Full never modifies display RGB and cannot
   repair this.
2. **Occluder-shaped depth.** Any2Full is conditioned with model-masked RGB, but
   its per-frame prediction is still unconstrained inside the hidden region.
   Across six sampled active-mask frames, its hidden-region deviation from the
   last visible sand state is 8.147 mm RMS on average and reaches 15.597 mm at
   frame 629.
3. **VDA and rendering artifacts.** The retained full-sequence VDA guide was
   run from raw RGB. Frame matching gives 3-4 RGB-level RMSE to raw frames and
   13-42 to repaired RGB, proving that VDA saw the hand. Direct VDA high-frequency
   detail is 2.685 mm RMS in the static probe versus 0.452 mm for Any2Full and
   produces contour bands. The Godot v22a profile bypasses the legacy 3x3
   filter and uses a 639x479-subdivision mesh; it is useful for exposing these
   defects but is not a final reconstruction.

## Required processing stages

### 1. Preserve and decode the capture

- Keep the zip and extracted v2 streams read-only.
- Decode RGB by presentation timestamp and verify frame count, dimensions,
  duration and frame hashes.
- Read `depth.f32` as 256x192 `smoothedSceneDepth`; record explicitly that an
  unsmoothed stream is unavailable.
- Do not compare this session with Kinect as a same-scene accuracy benchmark.

### 2. Produce model masks once

- Track `hand. arm.` with Grounded-SAM-2 across the complete RGB sequence.
- Retain the original binary masks and their model/configuration provenance.
- No hand-authored mask, heuristic shadow mask or sand ROI is allowed.
- Derive `object_dilated` only by the declared fixed dilation required for
  sensor-anchor rejection and state gating.

### 3. Keep display RGB and depth conditioning separate

- Display RGB: official ProPainter with the model masks. A residual hand-shaped
  blur is an RGB limitation until a better video-inpainting branch wins a
  separate temporal audit.
- Any2Full/VDA conditioning RGB: for each frame use the visible-pixel median
  from the local radius-16 window, then Telea-fill only pixels hidden for that
  whole window. Do not show this diagnostic image to participants.
- Do not feed raw RGB to a temporal depth guide. Even with model-masked input,
  depth changes inside `object_dilated` must be ignored because shadows and
  large-fill bands remain visible to a monocular model.

### 4. Reconstruct metric spatial depth

- Build the model-free sand surface from the stable, confidence-2 native LiDAR
  component with the retained range/local-residual/gradient tests.
- Treat only mapped native sample centres as metric evidence. Interpolated
  values are never evaluation ground truth or additional anchors.
- Use grid-4 anchors and Any2Full Large/VIT-L for the dense per-frame spatial
  estimate. Preserve its float NPY output before Godot encoding.

### 5. Maintain an occlusion-gated sand state

For frame `t`, define the visible update support as
`surface AND NOT object_dilated_t`.

1. Initialize `state_1` from Any2Full.
2. Copy `Any2Full_t` into `state_t` only on visible update support.
3. Keep `state_(t-1)` inside `object_dilated_t`. This intentionally delays a
   hidden deformation until the sand becomes visible; it does not borrow a
   future frame.
4. Apply a mild 9-pixel bilateral filter to the state (`sigmaColor=2.5 mm`,
   `sigmaSpace=7 px`).
5. Add at most 55% of clipped Any2Full residual
   `Any2Full - Gaussian(sigma=2)`, clipped to +/-3 mm, and set this residual to
   zero inside the object mask.
6. Re-apply real grid-4 measurements only outside the model-derived
   `object_dilated` mask. Suppress the Gaussian correction inside the mask so
   an otherwise valid nearby anchor cannot bleed object-boundary depth back
   into the held sand state. Never inpaint or fabricate anchor values.

This `causal state + bilateral + bounded Any2Full detail` branch is the current
static winner. On seven representative frames its spatially held-out LiDAR
MAE/p95 are 0.327/0.983 mm. The simpler bilateral branch is 0.302/0.922 mm but
looks slightly softer. These values use spatially correlated measurements from
the same sensor and are selection diagnostics, not independent ground truth.

Do not use linear anchor interpolation as the output even though it scores
0.307/0.928 mm: sparse-grid triangulation creates visible planar fans. Do not
add VDA high-frequency residual: it scores 0.498/1.306 mm and creates contour
stripes.

### 6. Treat VDA as optional low-frequency timing only

The local raw/conditioned RGB A/B uses official VDA Small at input size 384 on
three 64-frame windows centred at frames 269, 629 and 806. Removing the modelled
hand changes the predicted relief materially, but large inpaint bands and
unmasked illumination/shadows still become apparent geometry. Therefore:

- high-pass VDA contribution is always zero;
- VDA deltas are permitted only after Gaussian low-pass filtering;
- deltas are zero inside `object_dilated` and are not allowed to update the
  causal sand state there;
- compare strengths 0, 0.15 and 0.30 on the full sequence; retain VDA only if it
  reduces broad jumps and temporal flicker without worsening held-out p95 by
  more than 0.15 mm or increasing the hand-imprint score;
- if no setting passes, ship the causal Any2Full branch without VDA. VDA is not
  a required stage.

### 7. Encode and render without inventing detail

- Generate Godot depth PNGs from float metric depth with one fixed range and
  retain per-frame quantization residual correction.
- Use the explicit surface mask to remove the tray/outside region.
- A 639x479-subdivision mesh may be enabled per LiDAR session. Keep legacy
  256x256 as the default so Kinect v20d is unchanged.
- Do not enable unfiltered `preserve_masked_depth_detail` for a final session.
  First materialize the selected filtered float candidate, then tune a bounded
  raw/3x3 shader blend if needed. High mesh density cannot restore absent
  256x192 sensor information.

## Acceptance checks

Every final LiDAR branch must publish all of the following:

- exact input/model/checkpoint/commit provenance and no-manual-mask assertion;
- complete frame-count, duplicate, gap, dimensions and hash audit;
- held-out LiDAR MAE, RMSE and p95 outside `object_dilated`;
- hidden-region deviation from the causal sand state (hand-imprint score);
- high- and medium-frequency RMS, with static relief and detrended pages;
- broad-jump count and adjacent-frame temporal difference;
- a no-future-leak test for the causal state;
- start/middle/late/end Godot Web screenshots and a full playback console audit.

Static diagnostic outputs for this investigation are stored under:

```text
tmp/opencode/lidar_static_depth_method_probe_v1
tmp/opencode/lidar_vda_local_probe/comparison
```

Reusable scripts are:

```text
tools/analyze_lidar_depth_detail_candidates.py
tools/prepare_lidar_vda_probe_inputs.py
tools/compare_vda_raw_conditioned_probe.py
tools/materialize_lidar_causal_depth_candidates.py
tools/build_lidar_causal_godot_session.py
```

The local VDA probe environment is deliberately outside the repository:

```text
tmp/opencode/venv_vda_local
tmp/opencode/Video-Depth-Anything-local
```

It uses the official `video_depth_anything_vits.pth` checkpoint. The official
upstream repository is `https://github.com/DepthAnything/Video-Depth-Anything`.

## Rejected full-sequence diagnostic: v23b

The complete 1,477-frame materialization produced
`causal_any2full_detail_v23b`. It is forward-only and uses no future frame and
no hand-authored mask. Its exact depth sequence SHA-256 is
`231e80ddfbf5469bf2e43a439473c83d75e932f8b8dd176fc39c6c2db1eadd92`.
It is retained only as an audit artifact and must not be presented as the
selected LiDAR reconstruction.

The first v23a diagnostic allowed the Gaussian anchor correction to enter the
masked hidden region. The grid-4 anchor set itself already excluded object
pixels, but correction support near the object boundary still produced an
unnecessary 0.779 mm hidden-region RMS deviation. v23b explicitly zeros that
correction inside `object_dilated`; hidden-region deviation falls to
0.367 mm without a broad surface jump.

Full-sequence v23b metrics are:

| Candidate | held-out MAE | held-out RMSE | approx. p95 | high-frequency RMS | mean adjacent difference | broad jumps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| causal bilateral | 0.306 mm | 0.582 mm | 0.956 mm | 0.678 mm | 0.853 mm | 0 |
| causal + 55% Any2Full detail | 0.331 mm | 0.623 mm | 1.020 mm | 0.744 mm | 0.856 mm | 0 |

The aggregate metrics originally made the detail branch look preferable, but
they did not measure semantic shape leakage. Direct review at capture time
19.63 seconds (manifest frame 458) shows a clear hand and finger outline
embedded in the depth-only sand relief. The moving model-mask boundary allowed
contaminated Any2Full values to enter the causal state; zero broad jumps and
low held-out error therefore did not imply a correct hidden surface. The
maximum absolute frame-median delta is 0.635 mm and the approximate p95
adjacent difference is 1.885 mm, but these numbers do not rescue the rejected
geometry.

The local review session is:

```text
tmp/opencode/session_lidar_5532036C_251F_4A20_89DC_A0745E463F87_causal_any2full_detail_v23b
```

It opts into a 639x479 mesh and direct sampling of the already filtered v23b
depth PNGs. This does not expose unfiltered raw LiDAR/Any2Full depth, and the
renderer defaults remain unchanged for every earlier session. The Godot 4.5.1
Web build loaded and played without a browser error, but that software check
did not validate the reconstructed semantics. Frame 458 is now a mandatory
visual gate for every successor.

Raw RGB at frame 626 confirms that some circular and long-line structures are
real story grooves, but this does not explain the explicit finger contour at
frame 458. The separate ProPainter display RGB still contains a gray
hand-shaped inpainting residue in that interval. v23b changes depth only and
does not fix either failure.

## Selected hand-imprint repair: v24b temporal LiDAR anchors

`temporal_anchor_surface_v24b` is the selected successor to rejected v23b. It
is an offline reconstruction and deliberately uses both past and future
frames. The manifest records `futureFramesUsed: true`; this branch must not be
described as causal. It introduces no hand-authored ROI, shadow mask or other
manual mask. Grounded-SAM-2's retained `object_dilated` sequence is the only
semantic exclusion signal.

The selected algorithm is:

1. Mark a metric grid-4 LiDAR anchor observation unsafe if any
   `object_dilated` mask touches it within +/-15 frames.
2. For every lattice cell, take the centred median of safe observations within
   +/-60 frames. Use a +/-180-frame median only when the short window has no
   safe observation. Spatially inpaint remaining missing lattice cells, clamp
   to the frame's 1st-99th anchor percentiles, apply Gaussian sigma 2.0 in
   lattice space and linearly upsample to the 640x480 anchor bounds.
3. Use that metric LiDAR surface inside the temporal object envelope. Blend it
   to the current Any2Full low-frequency surface over 48 pixels with
   smoothstep, rather than drawing a hard object-shaped replacement edge or
   flattening the whole sand ROI.
4. Add only 55% of Any2Full's high-pass residual, clipped to +/-3 mm. The
   residual is zero through 16 pixels from the temporal envelope and ramps to
   full weight at 32 pixels, so the model cannot redraw a finger edge.

The first full temporal-anchor attempt, v24a, applied the temporal LiDAR
surface to the whole lattice ROI. It removed the hand but is rejected because
it over-smoothed legitimate story detail and raised held-out MAE to 2.627 mm.
The 48-pixel spatial blend in v24b restores evidence outside the occluded
region. Full-sequence v24b metrics are:

| held-out MAE | held-out RMSE | approx. p95 | high-frequency RMS | mean adjacent difference | broad jumps |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.921 mm | 1.735 mm | 3.081 mm | 0.303 mm | 0.307 mm | 0 |

The maximum absolute frame-median delta is 0.467 mm. The temporal-object-
envelope high-frequency RMS falls from 1.193 mm in source Any2Full to 0.972 mm
in v24b. Those aggregate values are diagnostics only; mandatory visual gates
269, 458, 629 and 806 were also reviewed. Most importantly, the explicit hand
and finger outline visible in v23b at 19.63 seconds/frame 458 is absent from
the fully materialized v24b frame and from the high-density Godot mesh.

The selected local review session is:

```text
tmp/opencode/session_lidar_5532036C_251F_4A20_89DC_A0745E463F87_temporal_anchor_surface_v24b
```

It contains 1,477 RGB, depth and valid-mask frames. The session depth-sequence
SHA-256 is
`067741e629cedc55e76ff4422d73577b9a11a9b5948b05873aad6ead044a4f7c`.
The lossless return archive SHA-256 is
`54fd1cffb2c9251ea93b88b45cce8d8568b9c9eee0d6a8a4fc9c7fa2f3271fa5`.
It travelled Amadeus -> acode -> jp -> Windows with the same hash at every
hop. No package was installed on acode; both staging directories and both
temporary authorized keys were removed after local verification.

Godot 4.5.1 Web directly samples the already filtered v24b PNGs on a 639x479
mesh. Review at 19.67 seconds displayed frame 459 without the v23b hand
outline. A complete 0.00-57.27-second playback ended on frame 1477 with no
browser warning or error and no broad surface jump. The remaining honest
limitation is local loss of high-frequency sand detail while the hand covers a
region: sparse LiDAR does not contain that information, and copying Any2Full
detail there would reintroduce the rejected hand-shaped artifact.

Reusable implementation and probe tools are:

```text
tools/probe_lidar_bidirectional_surface_completion.py
tools/materialize_lidar_temporal_anchor_surface.py
tools/build_lidar_causal_godot_session.py
```
