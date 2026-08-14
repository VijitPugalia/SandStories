# Kinect full-sequence shadow-cleaned RGB-D workflow (v22d)

## Selected result

The selected review session is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_v22d_casper_lowfreq_any2full_vda_stable
```

Review URL:

```text
http://127.0.0.1:8845/index.html?session=http%3A%2F%2F127.0.0.1%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_v22d_casper_lowfreq_any2full_vda_stable%2Fsession.json&debug=1&autoplay=0&t=casper-full714-v22d-final-20260811
```

The sequence has 714 RGB frames, 714 depth frames and 714 validity masks at
640x480. Its duration is 23.767706 seconds. The display RGB and reconstructed
depth have deliberately separate provenance.

## RGB provenance

1. Grounded-SAM-2 commit `b7a9c29f196edff0eb54dbe14588d7ae5e3dde28`
   supplies the propagated human masks. These are model masks, not hand-drawn
   masks.
2. Official ProPainter commit
   `e870e79321c31b733e2031af5aa2fb1fe3ac7eec` removes the hand/arm from the
   original RGB in one continuous 714-frame run. The exact lossless v45 PNG
   output is the input to Casper.
3. Casper uses `casper_cogvideox5b.safetensors` with the local
   `CogVideoX-Fun-V1.5-5b-InP` base, seed 43, 50 inference steps, FP16,
   temporal window 85, multidiffusion stride 16, three-way Ulysses sequence
   parallelism, and the `bg` output. The output is the full predicted
   background, not a patch composited only inside an authored shadow mask.
4. The latent output is decoded with the native VAE spatial tiling path at
   240x320 tiles and trimmed from the padded 717 frames to the exact original
   714 frames. This lossless PNG decode is the RGB displayed in Godot.

Casper changes pixels outside the original human mask, as intended for cast
shadow removal. The measured mean outside-mask absolute RGB change is 7.858
levels. Static A/B frames 80, 300 and 450 show substantial shadow reduction
while retaining the sand drawing. See
`Godot/diagnostics/casper_full714_v22/casper_full714_ab_contact.png` and its
adjacent JSON report.

## The full-sequence Casper memory bug and its fix

The original distributed runner loaded and decoded the complete 714-frame RGB
and mask sequence independently on all three ranks. Each rank then held large
full-resolution arrays, VAE inputs and conditioning tensors. The three copies
exhausted host RAM before the sequence-parallel transformer became useful. A
windowed workaround would have introduced temporal seams and was therefore not
selected.

The fixed execution path does the following:

- only rank 0 loads full RGB/masks and performs VAE conditioning;
- T5 is released immediately after prompt encoding and VAE hooks are released
  immediately after conditioning;
- full reference noise is generated in-place in eight-frame chunks;
- rank 0 broadcasts only the compact `(1, 180, 17, 60, 80)` FP16 conditioning
  tensor over NCCL;
- ranks 1 and 2 load only the prompt/model state before that broadcast.

A two-step diagnostic first verified the exact latent shape and finite values.
The formal 50-step run then completed in 26 minutes 19 seconds. The final
latent tensor is entirely finite, with min -2.7148, max 2.7793, mean 0.02218
and standard deviation 0.67588. Peak host memory was 69,253 MB and the three
GPU peaks were approximately 21,992/11,942/11,846 MB.

Relevant reproducible tools are:

```text
Godot/tools/prepare_casper_full_sequence_amadeus.sh
Godot/tools/verify_casper_sequence_input.py
Godot/tools/sandiv_casper_cog5b_3gpu_full714.py
Godot/tools/sandiv_casper_cog5b_3gpu_full714_diag2.py
Godot/tools/run_casper_cog5b_3gpu_safe_amadeus.sh
Godot/tools/patch_casper_staged_release.py
Godot/tools/patch_casper_chunked_noise.py
Godot/tools/patch_casper_rank0_vae_conditioning.py
Godot/tools/repair_casper_rank0_inpaint_shape.py
Godot/tools/decode_casper_latents_amadeus.py
```

## Depth provenance

The depth branch never treats Casper or VDA as metric ground truth.

1. The original Kinect depth is converted to metric reference arrays using a
   single fixed range of 0.8128636457--0.9216704175 metres.
2. The propagated Grounded-SAM-2 human mask is unioned with the retained
   model-derived object/tool mask and passed through the existing eight-pixel
   Any2Full mask dilation. Pixels in that union are withheld from sparse depth
   anchors. No shadow mask and no hand-authored mask is used.
3. Quality-filtered Kinect samples on the fixed grid4 pattern are the only
   metric anchors. The mean retained anchor ratio is 4.35912%.
4. Any2Full Large/ViT-L commit
   `780edf6be2bf9260f1cce8e4ddbcb52d7bcdae9e` completes the dense surface.
5. Two RGB-conditioning candidates were evaluated. `v22a` used pure Casper
   RGB. The selected `v22b` used only the bounded low-frequency difference
   between Casper and ProPainter while retaining ProPainter high-frequency
   texture:

   ```text
   ProPainter + surface_alpha * clip(
       Gaussian(Casper, sigma=12) - Gaussian(ProPainter, sigma=12),
       -48, +48
   )
   ```

   This fused image is model conditioning only. Godot still displays the pure
   Casper RGB.

Held-out Kinect agreement is an internal sensor-consistency test, not external
ground truth. The old ProPainter-conditioned baseline has MAE/RMSE/p95 of
1.2538/2.0073/3.3161 mm. Pure Casper conditioning has
1.2681/2.0522/3.3599 mm. The selected conservative fusion has
1.2600/2.0222/3.3306 mm and a maximum absolute per-frame median bias of
0.1491 mm. The differences are small; shadow removal is not claimed to improve
metric geometry.

Relevant tools are:

```text
Godot/tools/prepare_casper_any2full_sources.py
Godot/tools/prepare_any2full_conditioning_rgb_remote.py
Godot/tools/run_any2full_eval_remote.py
Godot/tools/build_kinect_any2full_godot_session.py
```

## Temporal stabilization

Video Depth Anything Small commit
`4f5ae23172ba60fd7bc11ef671cca678842c7072` runs once on the pure Casper RGB.
Its 714x480x640 float32 archive was checked for exact frame count and all-finite
values. One sequence-wide p2--p98 mapping converts it to a temporal guide. VDA
does not set the depth scale and does not replace Any2Full spatial geometry.

The stabilizer applies bidirectional adaptive smoothing. Any2Full proposes the
spatial depth at every frame; VDA contributes only frame-to-frame deltas. A
15-candidate search ranks by full-sequence broad-jump count, sampled Kinect
holdout MAE, maximum absolute frame-median jump, then deviation from Any2Full.
The selected parameters are strength 0.6 and difference threshold 18.

For the selected low-frequency conditioning branch:

- detected broad whole-surface jumps: 2 -> 0;
- mean adjacent encoded-height difference: 1.4748 -> 0.9271;
- p95 adjacent encoded-height difference: 5.0181 -> 2.0136;
- maximum absolute whole-surface frame-median jump: 3.9744 -> 1.0292;
- mean/p95 deviation from the original Any2Full result: 0.7795/2.1611 encoded
  height levels;
- sampled Kinect holdout MAE during tuning: 1.2869 -> 1.3093 mm.

Each output PNG also stores a floating-point `baselineHeightCorrection` in the
manifest so PNG rounding does not reintroduce a uniform surface step.

Relevant tools are:

```text
Godot/tools/run_vda_sandstories.py
Godot/tools/verify_vda_depth_npz.py
Godot/tools/materialize_vda_temporal_guide.py
Godot/tools/stabilize_any2full_with_vda.py
```

## Verification and retained artifacts

The transferred final package is 310,712,517 bytes. Its remote and local
SHA-256 are both:

```text
fe0ffe71947bc05be2b668e2e7768457c92a69d710e7745414a0e1f693e600de
```

Local validation counted 714 RGB, 714 depth and 714 validity-mask PNGs, with
714 manifest frames and `broadJumpCount=0`. Browser QA loaded the declared
v22d session, sought directly to frame 300, played continuously to frame 307,
and reported no browser warnings or errors.

Remote working root:

```text
/home/baleine/rgb-depth-uniform/casper_full714_any2full_v22
```

The unselected pure-Casper Any2Full branch (`v22c`) and all tuning reports are
retained under that root for comparison. The 615 MB raw VDA NPZ and 873 MB
Any2Full float predictions are intentionally not copied into the Godot review
session; the final session contains only the auditable reports and delivery
PNG/JSON assets.

## Known limitation

Casper improves the RGB interpretation of shadows, but this experiment has no
independent laser scan or shadow-free metric ground truth. Kinect holdout tests
show that the depth differences among the old, pure-Casper and fused-Casper
conditioning branches are very small. The defensible claim is therefore:
full-sequence RGB shadow appearance is improved, Any2Full remains constrained
by Kinect metric samples, and VDA reduces non-semantic temporal surface jumps.
It is not defensible to claim that Casper recovers physically correct depth
under every shadow.

## 2026-08-11 no-VDA and SAM-safe corner-lock comparison

Visual review found that the VDA-stabilized v22d surface had less pixelwise
variation but more perceptually salient coherent base-plane motion. The raw
Any2Full `v22b` branch was therefore materialized locally as an explicit
no-VDA comparison. Its RGB/masks are hard links to the same verified Casper
assets as v22d; only depth differs.

The experimental `v22g` candidate adds an offset-only reference lock after raw
Any2Full. Four corner candidate patches are generated automatically from the
eroded surface mask. Per-frame Grounded-SAM-2 hand/arm masks are dilated by 31
pixels and excluded. Within each corner, only the lowest 50% temporal-MAD
pixels that are unmasked for at least 75% of the sequence are eligible. The
available corner medians are combined robustly, and a 21-frame median filter
is applied only to the resulting scalar correction coefficient. No depth
pixel, drawing residual or RGB frame is temporally blurred.

A four-corner affine-plane candidate was also generated but rejected before
delivery: the right-side corner patches contain real local sand/tool changes,
so fitting tilt converted local activity into a false global plane rotation.
The retained v22g variant locks height only. Relative to raw no-VDA v22b, the
measured global offset standard deviation falls from 0.5933 to 0.3214 encoded
height units while mean absolute adjacent offset remains essentially unchanged
(0.1057 versus 0.1050). It remains a review candidate rather than a selected
production version until visual comparison is accepted.

Relevant tool and diagnostic:

```text
Godot/tools/lock_depth_to_sam_safe_corners.py
Godot/diagnostics/casper_full714_v22/base_plane_motion_v22g_corner_height_r10.json
```

## 2026-08-11 selected no-VDA temporal de-jitter candidate

Visual review of v22g still showed small non-semantic flicker. Two stronger
metric-reference alternatives were measured before changing the depth:

- sparse corner grid4 anchors were rejected as the sole correction source
  because those pixels are already supplied to Any2Full and therefore do not
  observe interpolation motion between anchors;
- a robust affine error plane fitted to quality-filtered Kinect hold-out pixels
  improved metric tilt agreement, but explained only a small part of the
  perceptual residual jitter and was not applied globally.

The retained `v22h` candidate therefore starts from v22g and applies a
five-frame symmetric median independently to every pixel along the time axis.
There is no spatial filtering and no mixing between neighbouring pixels. An
odd temporal median preserves persistent monotonic surface changes such as a
new groove, while rejecting reconstruction impulses that exist for fewer than
half of the window. The source PNG plus its floating baseline correction is
filtered as a float; the result is baked back into the PNG and every output
`baselineHeightCorrection` is fixed to zero so the shader cannot reintroduce a
coherent fractional whole-surface step.

Candidate windows of 3, 5, 7 and 11 frames were measured. Five frames was
selected as the conservative trade-off. Sampled full-surface mean adjacent
depth change fell from 1.477 encoded height units for v22g to 0.428; the result
is 0.199 on the lowest-temporal-MAD 35% of the surface. The full-resolution
mean is 0.426, and the median per-pixel modification from v22g is only 0.0425
height units (p95 2.97). The
independent plane analysis reports adjacent offset/tiltX/tiltY changes of
0.0490/0.0981/0.0548, compared with 0.1050/about 0.27/about 0.15 before the
temporal median.

Godot Web QA loaded frames 1, 143, 256, 510 and 686, continuously played the
143--256 interval, preserved the visible groove geometry at the matched v22g
frame, and produced no browser warnings or errors. This is the current review
candidate; v22g remains available as the unfiltered comparison.

Relevant tools and diagnostics:

```text
Godot/tools/measure_any2full_metric_corner_lock.py
Godot/tools/measure_any2full_metric_plane_lock.py
Godot/tools/temporal_median_stabilize_depth.py
Godot/diagnostics/casper_full714_v22/metric_corner_anchor_lock_candidates.json
Godot/diagnostics/casper_full714_v22/metric_heldout_plane_lock_candidates.json
Godot/diagnostics/casper_full714_v22/base_plane_motion_v22h_temporal_median_r2.json
```

## 2026-08-11 stable-plane and high-precision depth candidate

Visual review of v22h found a small amount of residual coherent motion even
after the five-frame temporal median. The next candidate, `v22k`, keeps that
median unchanged and adds a separate low-frequency stabilization stage. It
does not increase the per-pixel temporal window.

Stable reference pixels are selected across the sand surface rather than from
one corner. The selector starts from the eroded sand mask, excludes the
dilated Grounded-SAM-2 hand/tool region, divides the surface into spatial
tiles, and retains the lowest-temporal-MAD pixels in each usable tile. A robust
affine plane (height offset plus x/y tilt) is fitted to those references for
each frame. Only this global plane is removed; the local depth residual that
contains grooves, mounds and drawing detail is not spatially filtered.

The raw fitted plane coefficients occasionally react to a real large-area
change as if it were camera motion. To prevent that estimate from creating a
new jump, v22k applies a zero-phase Gaussian filter with sigma 6 frames to the
three correction coefficients before materialization. This reduced the
maximum adjacent correction step from 0.519 to 0.055 height units for offset,
from 1.639 to 0.189 for x tilt, and from 0.192 to 0.029 for y tilt. The filter
is symmetric/offline, so it does not introduce a time delay.

The previous 8-bit grayscale depth PNG also caused sub-level corrections to
round differently from frame to frame. v22k therefore stores the normalized
depth as a packed 16-bit value in an RGB8 PNG: red is the high byte and green
is the low byte. Godot decodes it in the sand and virtual-hand shaders when
`data_sources.depth_value_encoding` is `rg16_unorm`. Sessions without that
field remain on the legacy red-channel path. The maximum measured packing
error is 0.001953 height units, versus up to 0.5 height units for 8-bit
rounding.

The resulting 714-frame candidate has 714 RGB PNGs, 714 packed depth PNGs and
714 validity masks. Browser QA loaded the first frame, sought through the
large change around frame 365, played continuously through frames 374--609,
and reported no warnings or errors. Local grooves remained visible. An
independent stable-region analyzer still reports an event near frame 365;
inspection shows that the analyzer's reference set is responding to a real
large-area sand change, so that statistic is not used as evidence of a render
jump. v22k remains a review candidate until visual comparison is accepted.

Relevant implementation and diagnostics:

```text
Godot/tools/lock_depth_to_stable_surface_plane.py
Godot/tools/materialize_rg16_stable_depth.py
Godot/tools/analyze_depth_base_plane_motion.py
Godot/diagnostics/casper_full714_v22/base_plane_motion_v22k_stable_plane_gauss6_rg16.json
Godot/assets/shaders/sand_depth.gdshader
Godot/scripts/main.gd
```

## 2026-08-12 Any2Full temporal metric-anchor candidate

Visual review of v22k localized the remaining motion to pixels that were
masked in consecutive frames and therefore had no current Kinect observation.
Any2Full is frame-independent, so the RGB and outside-mask grid4 anchors alone
did not require the model to choose the same hidden sand surface in adjacent
frames.

Three bounded input ablations were run before the full sequence. Increasing
the outside-mask lattice density from grid4 to grid2 improved Kinect holdout
MAE but did not improve hidden-region stability. Supplying the direct
ProPainter RGB instead of the existing conditioning patch also had negligible
effect. The selected change retains the original grid4 and RGB inputs and adds
only conservative bidirectional metric anchors inside the model mask:

- the nearest quality-filtered Kinect observation before and after the current
  frame must both exist within 60 frames;
- the two observed depths must agree within 1.5 mm;
- accepted values are distance-weighted between the two real observations;
- disagreement is treated as possible real sand change and receives no
  temporal anchor.

The complete input contains 625,489 accepted anchors across 709 of 714 frames,
with a mean of 876.04 anchors per frame and 42.23% acceptance among masked
grid4 candidates. Any2Full Large/ViT-L was rerun as three independent 238-frame
GPU shards and merged only after each shard produced all expected float and
Godot-height outputs.

The full raw metric comparison against the previous low-frequency-conditioned
grid4 result shows:

- persistent completion-region mean frame change: 0.6779 -> 0.1819 mm
  (73.17% reduction);
- mask entry/exit mean frame change: 1.2380 -> 0.4563 mm;
- far visible-surface mean frame change: 0.86064 -> 0.86059 mm;
- Kinect holdout MAE: 1.2600 -> 1.2522 mm;
- Kinect holdout RMSE: 2.0222 -> 2.0107 mm.

These are sensor-consistency and temporal-consistency measurements, not
external geometric ground truth. The temporal anchors change the predicted
surface inside the current model mask by 2.33 mm on average relative to the
old unconstrained completion; that change is expected because the candidate
is now prompted by real before/after Kinect observations.

The raw candidate is retained as `v22l`. The review candidate `v22p` applies
the same display-side stages already validated for v22k: SAM-safe scalar
corner lock, five-frame symmetric per-pixel median, distributed stable-plane
correction with sigma-6 zero-phase coefficient smoothing, and RG16 depth.
Under the same encoded-height region analyzer, v22k -> v22p changes are:

- persistent completion region: 0.5761 -> 0.1330 height unit;
- mask entry/exit region: 1.1064 -> 0.3243 height unit;
- near visible ring: 0.2324 -> 0.1959 height unit;
- far visible surface: 0.3900 -> 0.3861 height unit.

The maximum RG16 quantization error remains 0.001953 height unit. Browser QA
cold-loaded v22p, played frames 1--204 continuously, sought to frame 402, and
played continuously through frame 566. The drawing and concentric grooves
remained visible and the browser reported no warnings or errors.

Selected local session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_v22p_temporal_anchor_stable_plane_gauss6_rg16
```

Review URL:

```text
http://127.0.0.1:8845/index.html?session=http%3A%2F%2F127.0.0.1%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_v22p_temporal_anchor_stable_plane_gauss6_rg16%2Fsession.json&debug=1&autoplay=0&t=temporal-anchor-v22p-20260812
```

Relevant tools and diagnostics:

```text
Godot/tools/prepare_any2full_hand_temporal_probe.py
Godot/tools/evaluate_any2full_hand_probe.py
Godot/tools/prepare_any2full_temporal_anchor_full.py
Godot/tools/evaluate_any2full_temporal_anchor_full.py
Godot/tools/aggregate_any2full_evaluations.py
Godot/diagnostics/casper_full714_v22/any2full_hand_input_probe_v1.json
Godot/diagnostics/casper_full714_v22/any2full_temporal_anchor_v22p_hand_region.json
```
