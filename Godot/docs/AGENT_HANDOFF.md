# Agent Handoff: SandStories Kinect Depth Completion

Updated: 2026-07-28 (canonical final v21b RGB/depth provenance recorded)

This is the authoritative handoff for the current SandStories work. Do not use
older project paths or the early RGB/LiDAR fusion plan from previous versions
of this file.

`docs/posterior_repair_handoff.md` is a historical archive. It contains useful
provenance for v42-v44 and posterior-repair experiments, but it is not the
current execution plan.

## Read This First: Current State

- The selected 714-frame Any2Full result is complete. Do not rerun Any2Full by
  default.
- The v44 ProPainter RGB is no longer the selected display prior. User review
  found a hand ghost and rejected the assumption that v44 was authoritative.
  v44 remains preserved as historical input and was not overwritten.
- A separately named displayed-RGB candidate was rebuilt from the exact 714 raw
  Kinect RGB frames on Amadeus using standard Grounded-SAM-2 model output and
  the official ProPainter inference path.
- No hand-authored masks, heuristic mask extension, or surface clipping were
  used in the selected RGB rebuild. Do not reintroduce those shortcuts.
- The rebuilt RGB removes the skin-colored hand/forearm covered by the model
  masks. Dark hand-shaped shadows remain in immutable v20d. Shadow removal is
  now a separate research branch; its current full-Casper probe uses the same
  automatic actor masks and existing registered surface mask, not a painted
  shadow region. The thin tool/pencil remains outside the `hand. arm.` prompt.
- A later full-sequence audit found two separate causes of visible whole-surface
  jumps: Kinect raw-depth quantization steps copied through sparse anchors, and
  the Web runtime advancing the playhead before the requested PNG textures were
  ready. See "Depth Correctness and Height-Jump Resolution (2026-07-23)".
- A separate VDA-guided temporal candidate now preserves the Any2Full spatial
  reconstruction while rejecting broad Kinect quantization steps. The original
  Any2Full session remains unchanged as the spatial-reference baseline.
- The Web runtime now prefetches a bounded frame window, switches depth/RGB
  atomically, advances processed sessions sequentially, and stalls instead of
  silently skipping unavailable frames.
- The Windows-native review server on port `8845` served all `714/714` depth and
  `714/714` rebuilt RGB frames during a complete browser playback of the new
  combined session. Browser console status was `0` errors and `0` warnings.
- `build_any2full_godot_preview.py` now requires `--rgb-dir`. Always pass the
  displayed ProPainter directory separately from object-masked conditioning RGB.
- Virtual-hand v3 exposed two track-to-rig errors during review: its rig scale
  followed the noisy per-frame MediaPipe palm span, and its contact correction
  locally overwrote only the index fingertip. Frame 604 therefore collapsed to
  a dot, and every non-positioning state was incorrectly treated as fingertip
  contact.
- Virtual-hand v4 fixed scale and added intent-aware contact/tool drawing, but
  review exposed three remaining interacting defects: unreliable occluded
  MediaPipe landmarks could flip or over-bend the rig, unconstrained joints
  could penetrate the reconstructed sand, and transparent hand/sand depth
  prepasses could hide most of the hand.
- Virtual-hand v5c is the retained pose-constrained 3D-rig candidate. It adds
  palm-orientation continuity and finger swing/length gates, enforces
  per-intent clearance for all 21 landmarks, makes the masked sand body an
  opaque depth-writing cutout, and gives the translucent hand a stable alpha
  scissor depth prepass. It changes no RGB or depth image.
- The virtual-hand v5c Web run completed `714/714` with zero browser errors and
  zero warnings, but user review still found anatomical deformation. The core
  limitation is not another alpha/depth bug: a single top-down view and noisy
  21-point MediaPipe landmarks do not constrain the occluded 3D finger pose.
- The separately named v6b top-down 2.5D prototype therefore does not retarget
  those landmarks into a hand skeleton. It renders the accepted standard-model
  actor silhouette with raw-RGB luminance on the exact stabilized surface.
  This removes bone twisting and scale breathing without changing RGB/depth.
- The v6b Web run completed `714/714`, its layer toggle passed, and the browser
  reported zero errors and zero warnings. It is the current top-down review
  prototype, not a general free-camera 3D hand. Preserve v3, v4, v5c, and v6b.
- The later v10/v11 HaMeR, WiLoR, and OmniHands MANO branches are preserved only
  as rejected diagnostics. All three predict an open/fanned hand at frame 231,
  where true RGB shows a compact grip around the drawing tool. Do not present
  any of those branches as corrected hand motion or extend them to a new full
  production run. They remain useful negative controls beside v6b (top-down
  appearance) and v7 (early measured RGB-D surface).
- The later MANO hand-only path recovered the correct generic-hand semantics,
  and v18e fixed the tray-ROI tracking and jitter over `82-299`. The separately
  named v19i result is the retained geometry/motion baseline: it stabilizes the
  accepted pose over `300-621`, rejects low-support tray-edge surface anchor
  mode switches, preserves all RGB/depth assets and genuine source gaps, and
  does not add tool interaction or hand-authored masks.
- v20a is the retained soft-peach appearance candidate. v20d is the current
  requested cerulean-blue variant. Both use every v19i RGB, depth, and MANO
  mesh unchanged, replacing only the muddy fixed PBR hand color with the same
  opaque, normal-sign-stable session-colored shader. They continue to write
  depth and remain double-sided, so no alpha/depth workaround was reintroduced.
- v20d remains the immutable accepted visual/session baseline. The active Web
  runtime has now advanced separately to v21a, which adds the proposal-aligned
  Stage 1/Stage 2 experiment runner without changing any v20d RGB, depth, MANO
  mesh, or palette asset.
- A full 85-frame Generative Omnimatte/Casper CogVideoX-5B shadow-removal probe
  has now completed at 480x640, 50 steps, across all three Amadeus GPUs. It
  removes the hard frame-82 actor-associated shadow and keeps the circular
  groove on the correct timeline. A measured-detail fusion preserves 97.4% of
  source sand high-frequency energy and changes zero pixels outside the
  registered surface.
- The separately named v21b review session uses that fused result only as the
  displayed RGB for frames `40-124`. It hard-links every v20d depth frame,
  MANO mesh, and RGB frame outside that window; it does not rerun or feed the
  generated RGB into Any2Full, temporal depth stabilization, MANO fitting, or
  RGB-D fusion. It is marked `production_session=false` and remains a review
  probe rather than a ground-truth or production claim.
- v21a implements consent, anonymous profile covariates, common full-modality
  training, five Stage 1 ablations, Stage 2 annotation tasks, interpretation
  and evidence responses, Likert/raw NASA-TLX measures, phase timing,
  interaction capture, and anonymous JSON export. A browser-discovered timing
  leak was fixed: Stage 1 no longer reveals/applies its ablation until the
  participant finishes the common training and begins the main task.
- The runner is infrastructure-complete but the current sample and v20d
  content are intentionally marked `readyForDataCollection=false`. Do not use
  them for recruitment until real narration, object/tool observations,
  creator-validated interpretations/questions, final ethics/consent text,
  approved production submission storage/retention, and Stage 2 ordering are
  supplied. Local balanced allocation and durable pilot persistence now exist.

Current full session:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714
```

Current temporally stabilized review candidate:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18
```

Current rebuilt-RGB plus stabilized-depth review candidate:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18
```

Previous rebuilt-RGB/stable-depth plus rigged virtual-hand v3 candidate:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v3
```

Previous stable-scale/contact-aware virtual-hand v4 candidate:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v4
```

Previous pose-constrained/depth-correct virtual-hand v5c candidate:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v5c
```

Previous top-down 2.5D virtual-hand v6b review prototype:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_virtual_hand_v6b_topdown
```

Retained generic-hand v19i geometry/motion baseline:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v19i_reference_surface_stable
```

Retained soft-peach v20a appearance session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v20a_soft_peach
```

Current cerulean-blue v20d appearance session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final
```

Current RGB-only Casper v21b review session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124
```

Current shadow-removal playback probe:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\shadow_analysis\casper_results\cog5b_3gpu_safe50_f040_124\fused_hard_surface_radius_01.mp4
```

Current review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final%2Fsession.json&debug=1&t=mano-cerulean-blue-v20d-final-20260725&autoplay=0
```

Current RGB-only shadow-removal review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124%2Fsession.json&debug=1&t=casper5b-rgb-only-v21b-f040-124-20260727&autoplay=0
```

Current proposal-runner QA URL:

```text
http://localhost:8845/index.html?study=pilot&participant=qa001&debug=1&t=proposal-v21a-pilot-20260725
```

Amadeus access from WSL:

```bash
ssh -J root@192.168.28.1 baleine@192.168.91.98
```

## Canonical Final v21b RGB / Depth Provenance (2026-07-28)

This is the short authoritative answer to “where do RGB and depth in the final
review version come from?”. The version covered here is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\
session_kinect_20260623_154953_virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124
```

It has `714` frames over `23.767706155776978` seconds. It is deliberately
marked `production_session=false` and `review_candidate=true` because the
Casper shadow-removal interval is still a generative review result.

The final composition contains three independent layers:

| Layer | Final source | Important boundary |
|---|---|---|
| Sand colour / displayed RGB | Grounded-SAM-2 + ProPainter, with Casper replacement on frames `40-124` | Display only; never used to recompute depth or the hand |
| Sand geometry / depth | Kinect sparse metric evidence + Any2Full Large, followed by VDA-delta temporal stabilization | Frozen before the final RGB rebuild and Casper pass |
| Blue virtual hand | The retained v19i MANO mesh sequence rendered with the v20d cerulean shader | Separate 3D overlay; not baked into either RGB or sand depth |

### Final displayed RGB

The base displayed-RGB sequence was produced from the exact `714` raw Kinect
RGB frames, not from v44 and not from Any2Full conditioning images.

Automatic hand/arm mask generation:

```text
Detector/tracker repository:
Grounded-SAM-2

Grounded-SAM-2 commit:
b7a9c29f196edff0eb54dbe14588d7ae5e3dde28

Detection model:
IDEA-Research/grounding-dino-tiny

Segmentation model:
SAM 2.1 Hiera Large

SAM checkpoint:
sam2.1_hiera_large.pt

Prompt:
hand. arm.

Prompt interval:
every 10 frames

Grounding DINO thresholds:
box 0.35, text 0.20

Temporal mask propagation:
continuous object ID forward tracking plus reverse propagation

Selected mask count:
665 active frames out of 714

Mask postprocessing:
none

Hand-authored masks / surface clipping:
none
```

The rejected `boxThreshold=0.20` run produced false whole-tray masks late in
the recording. The retained `0.35` threshold was selected from the actual
Grounding DINO score separation between real hand/arm detections and those
false responses; it was not an image-position rule.

The model-derived masks were passed to the official ProPainter video-inpainting
implementation:

```text
ProPainter commit:
e870e79321c31b733e2031af5aa2fb1fe3ac7eec

Arguments:
--save_frames --fp16 --mask_dilation 4

Other parameters:
official defaults

Output:
714 lossless PNG frames, 640 x 480
```

This removed the visible captured hand/forearm body while retaining the sand
appearance reconstructed by ProPainter. The sequence used by v20d has SHA-256:

```text
713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30
```

v21b then changes only displayed RGB frames `40-124`, inclusive. These `85`
frames use the full Generative Omnimatte/Casper CogVideoX-5B model:

```text
Model:
Casper CogVideoX-5B

Mode:
clean background

Input:
global frames 40-124, 480 x 640, 10 fps

Sampling:
50 DDIM steps, seed 43

Actor support:
the standard Grounded-SAM-2 masks, Casper internal dilation width 11

Hardware:
three RTX 2080 Ti GPUs with three-way Ulysses sequence parallelism
```

Casper supplies the counterfactual low-frequency, shadow-reduced appearance.
To avoid replacing valid captured sand detail with a fully regenerated image,
the retained result restores one-level source detail:

```text
fused = source + blur(Casper, radius=1) - blur(source, radius=1)
```

That correction is applied only inside the unchanged registered
`surface_mask.png`. Pixels outside the hard surface boundary are byte
unchanged. The retained fusion preserves about `97.4%` of source sand
high-frequency energy.

Therefore the final v21b RGB sequence is:

```text
frames 1-39:    original Grounded-SAM-2 + ProPainter RGB from v20d
frames 40-124:  Casper CogVideoX-5B low-frequency result + source detail fusion
frames 125-714: original Grounded-SAM-2 + ProPainter RGB from v20d
```

Its complete ordered sequence SHA-256 is:

```text
ade1ed99ce153bb4d7244136855094b8952ccbbeaa0cfa54fb91149009dbb3bd
```

The Casper output is only a texture replacement. It is not passed into
Any2Full, Video Depth Anything, MANO fitting, MANO RGB-D fusion, surface-anchor
stabilization, or mesh packing.

### Final sand depth

The sand-depth branch starts from the Kinect v1/libfreenect capture. The
original source representation is raw Kinect depth PGM; the selected Any2Full
run uses only quality-filtered sparse metric evidence derived from that
capture, rather than treating the entire Kinect depth image as reliable.

Sparse-anchor preparation:

```text
surface mask required
Kinect valid mask required
object-region depth mask dilated by 8 px and excluded
encoded height restricted to 40-230
9 x 9 local median consistency check
maximum local residual 8 grayscale levels
maximum Sobel gradient 48
fixed grid4 positions
mean retained surface density approximately 4.37%
```

The metric range represented by the retained capture calibration is:

```text
0.8128636457361647 to 0.9216704175465102 metres
```

A separate object-masked RGB sequence was built strictly as model
conditioning. It is not the displayed RGB and it is not the later Casper
output. For each frame it uses a local temporal window of `t-16` through
`t+16`; visible pixels supply the temporal median, pixels masked throughout the
window receive a local spatial fill, and outside-surface pixels receive the
window-local median sand colour.

Dense spatial completion:

```text
Model:
Any2Full Large

Repository commit:
780edf6be2bf9260f1cce8e4ddbcb52d7bcdae9e

Encoder / variant:
vitl / vitl_object_masked_rgb

Checkpoint:
Any2Full_vitl.pth.tar

Inputs:
quality-filtered grid4 Kinect anchors
+ the separate window-16 object-masked conditioning RGB

Output:
714 dense metric-depth frames
```

Any2Full is the spatial and metric source. Predictions are clamped to the
calibrated Kinect metric range during Godot height encoding. A small per-frame
floating-point baseline correction retains the held-out Kinect median metric
bias after PNG quantization.

The observed whole-surface jumps came from broad Kinect quantization steps
copied through the sparse anchors, especially at transitions `147->148` and
`222->223`. The selected temporal pass therefore uses a separate Video Depth
Anything result only as a temporal-delta guide:

```text
Temporal guide model:
Video Depth Anything Small

Checkpoint:
video_depth_anything_vits.pth

Method:
bidirectional VDA-delta-guided adaptive smoothing

Strength:
0.92

Encoded-difference threshold:
18
```

Video Depth Anything does not replace the Any2Full surface and does not set
its absolute metric scale. It contributes only the expected direction and
relative magnitude of temporal changes; Any2Full remains the spatial source
and Kinect evidence remains the metric anchor.

The stabilized sequence reduces the audited broad coherent jump count from
`2` to `0`. Its post-encoding held-out Kinect error is approximately:

```text
mean MAE:   1.3190 mm
mean RMSE:  2.0395 mm
mean P95:   3.4645 mm
```

This is agreement with quality-filtered captured Kinect evidence, not
independent hidden-surface ground truth.

The final ordered `clean_depth_*.png` sequence SHA-256 is:

```text
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8
```

Every later virtual-hand, appearance, experiment-runner, and Casper branch
keeps those `714` depth files unchanged. In Godot they are sampled by the
existing sand displacement shader with the session height scale `-5.0`.

### Non-negotiable separation

The final dependency direction is:

```text
Kinect depth evidence + safe conditioning RGB
  -> Any2Full Large
  -> VDA-delta temporal stabilization
  -> frozen sand depth

raw Kinect RGB
  -> Grounded-SAM-2
  -> ProPainter
  -> optional Casper display replacement on frames 40-124
  -> displayed sand RGB

frozen sand depth + independent hand observations
  -> retained MANO mesh placement
  -> blue hand rendered separately
```

There is no arrow from final ProPainter/Casper display RGB back into the frozen
depth branch. That separation is the defining provenance guarantee of v21b.

## Grounded-SAM-2 + ProPainter RGB Rebuild (2026-07-24)

### Scope and source

This rebuild changes displayed RGB only. It does not regenerate Any2Full depth,
conditioning RGB, sparse anchors, masks used by the depth pipeline, evaluation
data, or the selected VDA temporal stabilization.

Exact raw RGB input:

```text
amadeus:/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/rgbd_masks_final_factory40/input/frames
```

Remote work root:

```text
amadeus:/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work
```

An initial standard per-frame YOLO/SAM detector covered only `242/714` frames
and was rejected rather than extended with manual or heuristic masks.

### Selected standard-model mask path

```text
Grounded-SAM-2 commit: b7a9c29f196edff0eb54dbe14588d7ae5e3dde28
SAM 2 checkpoint:      checkpoints/sam2.1_hiera_large.pt
SAM 2 checkpoint SHA:  2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318
Grounding model:       IDEA-Research/grounding-dino-tiny
Text prompt:           hand. arm.
Prompt step:           10 frames
Box threshold:         0.35
Text threshold:        0.20
Tracking:              continuous ID plus reverse propagation
```

The first complete `boxThreshold=0.20` candidate was rejected before
ProPainter because late frames developed tray-sized false `arm` masks. A
Grounding DINO score audit showed that the lowest-scoring retained real prompt
point was frame 630 at about `0.364`; real hand/arm detections continued through
frame 660. The false whole-tray detections at frames 670-710 scored about
`0.292-0.317`. The selected `0.35` threshold separates those model responses
without a geometry rule or hand-authored override.

Selected mask report:

```text
Frames:               714
Active frames:        665
Empty frames:         665-713
Area minimum/median:  0 / 20,737 pixels
Area maximum:         33,607 pixels
Mask postprocessing:  none
Surface clipping:     false
```

The early, middle, late, and dense frame-620-through-713 regions were visually
audited before inpainting. The hand/arm over the tray is covered; after frame
665 the remaining hands are outside the tray, so the standard model output is
empty instead of being forced to track them.

### Official ProPainter inference

```text
ProPainter commit: e870e79321c31b733e2031af5aa2fb1fe3ac7eec
Arguments:         --save_frames --fp16 --mask_dilation 4
Other settings:    official defaults
Output:            714 PNG frames at 640 x 480
```

All pixel changes are confined to ProPainter's official four-pixel-dilated
model mask: the measured changed-pixel count outside that mask is zero. Visual
QA confirms that the skin-colored hand/forearm body is removed. Dark
hand-shaped silhouettes that remain are shadows, deliberately not targeted per
user instruction. A thin tool/pencil can remain because it was not included in
the `hand. arm.` prompt.

### Lossless transfer and local materialization

The PNG sequence was encoded as lossless `x264rgb` only to reduce transfer
cost. Source PNG pixels and decoded video pixels matched on all `714/714`
frames on Amadeus, and the Windows decode again matched the Amadeus source
frame MD5 list on all `714/714` frames with zero mismatches.

```text
Lossless MKV SHA-256:
3a55df5ef2fdb5b8de477e79166fdefd876db548d6d2b668be95016f7a3d6aeb

Route:
Amadeus -> jp -> acode -> Windows
```

The file was split into eleven parts for parallel resumable transfer. Every
part, the reassembled MKV, and the metadata archive were verified at each
materialization point. `acode` was used only for staging; no packages were
installed there.

Local transfer evidence:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer
```

New combined session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18
```

Materialization integrity:

```text
Frame count:                  714
Displayed RGB sequence SHA:  713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30
Source depth sequence SHA:    6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8
Output depth sequence SHA:    6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8
Depth unchanged:              true
```

`Godot/tools/materialize_display_rgb_session.py` now accepts explicit
`--repair-method` and `--repair-note` provenance fields. This prevents a new
standard-model run from being mislabeled with the obsolete heuristic-mask
description.

### Browser playback verification

The new combined session was loaded in the current Godot Web export and played
through `23.77 / 23.77` seconds to `frame 714/714`. The server logged HTTP 200
for all `714` unique rebuilt RGB assets and all `714` unique unchanged depth
assets. The final browser console contained zero errors and zero warnings.
Representative middle and final frames rendered with the expected stable-depth
status; the final overlay named `clean_depth_000714.png`,
`clean_rgb_000714.png`, and `frame 714/714`.

### Authoritative end-to-end production workflow

The final review session is the composition of two deliberately separate
branches:

```text
GEOMETRY BRANCH (already completed and frozen)
raw Kinect RGB/depth
  -> quality-filtered sparse metric anchors
  -> object-masked conditioning RGB
  -> Any2Full Large dense completion
  -> VDA-delta-guided temporal stabilization (strength 0.92, threshold 18)
  -> stable clean_depth_*.png
                                           \
                                            -> RGB-only materializer
                                           /   -> final Godot session
DISPLAY BRANCH (rebuilt 2026-07-24)
exact raw Kinect RGB
  -> Grounding DINO `hand. arm.` detections every 10 frames
  -> SAM 2 masks with forward continuous-ID and reverse propagation
  -> mask QA gate
  -> official ProPainter full-sequence inpainting
  -> RGB QA and lossless pixel-integrity gate
  -> rebuilt clean_rgb_*.png
```

The geometry branch is explained and measured in "Depth Correctness and
Height-Jump Resolution (2026-07-23)". During the 2026-07-24 rebuild it was
treated as immutable input. The displayed ProPainter pixels were never fed back
into Any2Full, and changing the display sequence did not change geometry.

#### 0. Freeze the accepted depth baseline

Use this session as the source:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18
```

Before any RGB work, record its complete ordered depth-sequence digest:

```text
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8
```

The final materializer must recompute this digest from both source and output
and abort if they differ. Do not copy a depth frame from another session or
rerun Any2Full merely because displayed RGB is being changed.

#### 1. Use the exact raw RGB sequence on Amadeus

```bash
TASK_WORK=/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work
TASK_RGB=$TASK_WORK/rgbd_masks_final_factory40/input/frames
TASK_MASKS=$TASK_WORK/grounded_sam2_human_full714_c035
TASK_PAINT=$TASK_WORK/propainter_grounded_sam2_c035
```

Preflight requirements:

- exactly 714 ordered frames;
- frame size `640 x 480`;
- frame order preserved from source index 0 through 713;
- no v44/restored RGB used as model input;
- no resize, crop, color conversion, or artificial pre-mask applied to the
  source PNG sequence.

#### 2. Select the mask model from evidence, not a hand-written rule

The first per-frame YOLO/SAM attempt produced active masks for only `242/714`
frames. It was rejected, not repaired.

The first Grounded-SAM-2 full run used `boxThreshold=0.20`. Its late frames
developed whole-tray false `arm` detections, so it was also rejected before
ProPainter. The recorded step-10 Grounding DINO audit is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer\metadata\dino_scores_hand_arm_step10.json
```

Relevant separation:

```text
lowest retained real score: frame 630, about 0.364
real detections continue:   through frame 660
false tray detections:      frames 670-710, about 0.292-0.317
selected box threshold:     0.35
```

This is why the selected value is `0.35`. It is a model-score threshold, not a
surface polygon, area cutoff, hand-authored frame list, temporal mask
extension, or shadow rule.

#### 3. Produce the selected Grounded-SAM-2 masks

Environment and immutable provenance:

```text
Python: /home/baleine/venvs/grounded-sam2/bin/python
Repo:   /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/Grounded-SAM-2
Commit: b7a9c29f196edff0eb54dbe14588d7ae5e3dde28
SAM 2:  checkpoints/sam2.1_hiera_large.pt
SHA:    2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318
```

Equivalent invocation:

```bash
cd "$TASK_WORK/Grounded-SAM-2"
CUDA_VISIBLE_DEVICES=<free-gpu> \
  /home/baleine/venvs/grounded-sam2/bin/python \
  grounded_sam2_tracking_sandiv.py \
  --video-dir "$TASK_RGB" \
  --output-dir "$TASK_MASKS" \
  --text "hand. arm." \
  --step 10 \
  --box-threshold 0.35 \
  --text-threshold 0.20 \
  --sam2-checkpoint checkpoints/sam2.1_hiera_large.pt \
  --sam2-config configs/sam2.1/sam2.1_hiera_l.yaml \
  --grounding-model IDEA-Research/grounding-dino-tiny
```

The script converts PNGs to a same-size JPEG staging sequence for model
inference, prompts Grounding DINO every ten frames, initializes SAM 2 masks,
propagates identities forward, then performs reverse propagation. It exports
one binary mask per source frame under:

```text
$TASK_MASKS/binary_masks
```

It does not postprocess the masks and does not clip them to the sand surface.

#### 4. Enforce the pre-inpainting mask QA gate

Do not launch ProPainter until all of the following are true:

- 714 mask files exist and correspond one-to-one with the 714 RGB frames;
- report values match `665` active frames, frames `665-713` empty, median
  active/empty-sequence area `20,737` pixels, and maximum `33,607` pixels;
- early, middle, and late contact sheets show the hand/forearm over the tray
  covered;
- dense review of frames 620-713 shows no return of the tray-sized false mask;
- empty late masks correspond to hands already outside the tray;
- no human has painted, extended, clipped, or replaced any mask;
- shadows are not added to the target.

The authoritative report is:

```text
$TASK_MASKS/mask_report.json
```

#### 5. Run official ProPainter on the whole sequence

Environment and provenance:

```text
Python: /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/propainter_venv/bin/python
Repo:   /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/ProPainter
Commit: e870e79321c31b733e2031af5aa2fb1fe3ac7eec
```

Equivalent invocation:

```bash
cd "$TASK_WORK/ProPainter"
CUDA_VISIBLE_DEVICES=<free-gpu> \
  "$TASK_WORK/propainter_venv/bin/python" \
  inference_propainter.py \
  --video "$TASK_RGB" \
  --mask "$TASK_MASKS/binary_masks" \
  --output "$TASK_PAINT" \
  --save_frames \
  --fp16 \
  --mask_dilation 4
```

All unlisted ProPainter parameters remain at official defaults. In particular,
this is one 714-frame video-inpainting run, not independent still-image
inpainting. Output PNGs are:

```text
$TASK_PAINT/frames/frames
```

#### 6. Enforce the post-inpainting RGB QA gate

Required checks:

- exactly 714 output PNGs, each `640 x 480`;
- early/middle/late contact sheets and dense late review;
- skin-colored hand/forearm body removed inside the model-derived masks;
- changed-pixel count outside ProPainter's official four-pixel-dilated mask is
  exactly zero;
- shadows are allowed to remain and must not be relabeled as missed skin;
- the thin tool/pencil is allowed to remain because the text prompt does not
  target it.

The expected visible result is therefore "hand/arm body removed, natural
inpainting where the model selected it, shadows untouched", not "every
hand-shaped dark pixel erased".

#### 7. Package and transfer without changing pixels

The PNGs were encoded only for transport using lossless `libx264rgb` at 30 fps.
The resulting stream is H.264 `gbrp`, `640 x 480`; it is not a visually lossy
delivery encode.

Equivalent packaging:

```bash
ffmpeg -framerate 30 -start_number 0 \
  -i "$TASK_PAINT/frames/frames/%04d.png" \
  -c:v libx264rgb -crf 0 \
  "$TASK_WORK/propainter_grounded_sam2_c035_714_lossless_rgb.mkv"
```

Required digest:

```text
3a55df5ef2fdb5b8de477e79166fdefd876db548d6d2b668be95016f7a3d6aeb
```

Generate a decoded-frame MD5/FrameMD5 manifest before transfer and compare it
with the source PNG pixels. The comparison must be `714/714`, zero mismatches.

The MKV was split into ten 32 MiB parts plus one final part, transferred with
parallel resumable `rsync`/SCP along:

```text
Amadeus -> jp -> acode -> Windows
```

At every hop:

- verify each part SHA-256;
- concatenate in numeric order;
- verify the reassembled MKV SHA-256;
- verify the metadata archive;
- do not install software on `acode`.

On Windows, decode back to PNG and compare all 714 decoded pixel MD5 values
against the Amadeus source manifest. The completed local transfer root is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer
```

#### 8. Materialize RGB into a new session and prove depth is unchanged

Run from the SandStories repository on Windows:

```powershell
python Godot\tools\materialize_display_rgb_session.py `
  --source-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18" `
  --rgb-dir "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer\decoded_frames" `
  --output-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18" `
  --display-rgb-source "amadeus:/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/propainter_grounded_sam2_c035/frames/frames" `
  --mask-report "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer\metadata\grounded_sam2_human_full714_c035\mask_report.json" `
  --propainter-commit "e870e79321c31b733e2031af5aa2fb1fe3ac7eec" `
  --repair-method "Grounded-SAM-2 continuous-ID plus reverse tracking masks and official ProPainter full-sequence video inpainting" `
  --repair-note "Model-derived hand/arm masks only; no hand-authored masks, no heuristic mask extension, and no shadow removal. Existing stabilized Any2Full depth is unchanged."
```

The materializer:

1. refuses to overwrite a non-empty output directory;
2. requires the RGB count to equal the source manifest frame count;
3. hard-links or copies every non-RGB session asset;
4. writes the rebuilt PNGs as `clean_rgb_000001.png` through
   `clean_rgb_000714.png`;
5. rewrites session resource paths to the new session ID;
6. records every RGB SHA-256 plus an ordered sequence digest;
7. recomputes source and output depth sequence digests;
8. aborts if depth changed;
9. embeds the model/mask/commit/method provenance in
   `processed_manifest.json`.

Expected final integrity:

```text
RGB sequence SHA-256:
713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30

Source and output depth sequence SHA-256:
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8

depthUnchanged: true
```

#### 9. Serve and perform the end-to-end playback gate

Use the Windows-native server on port 8845 and the current review URL at the
top of this handoff. A run is accepted only when:

- the page names the rebuilt session rather than the v44 predecessor;
- autoplay begins at frame 1 and ends at frame 714;
- final time is `23.77 / 23.77`;
- all 714 unique `clean_rgb` requests return HTTP 200;
- all 714 unique `clean_depth` requests return HTTP 200;
- final overlay names `clean_rgb_000714.png`,
  `clean_depth_000714.png`, and `frame 714/714`;
- browser console has zero errors and zero warnings;
- representative rendered frames show the rebuilt RGB on the unchanged stable
  sand geometry.

Do not call the workflow complete merely because ProPainter exited
successfully. The mask gate, pixel-integrity gate, depth-identity gate, and
full Godot playback gate are all mandatory.

## Rigged Virtual-Hand Workflow (2026-07-24)

### Selected visual design

The selected visual is a depth-aware, softly translucent humanoid hand driven
by the stored 21 MediaPipe landmarks.

The earlier procedural renderer remains only as a fallback. Its capsule fingers
followed every landmark reliably, but the result still looked like a skeleton,
and adding one ellipsoid palm produced an obvious bubble shape. The static OBJ
hands were also rejected as the main visual because they can translate, rotate,
and scale but cannot articulate individual fingers.

The local `RightHand_CV.fbx` candidate was inspected in Godot. It imports, but
contains only 20 numerically named bones in five separate root chains and lacks
a complete wrist/humanoid hierarchy. It is retained as research input, not the
selected runtime asset.

The selected assets come from Godot's official OpenXR hand-tracking demo:

```text
Repository: https://github.com/godotengine/godot-demo-projects
Commit:     cae8dc567a56d3e7936f171bcb85f0ccb9634ad0
Source:     xr/openxr_hand_tracking_demo/assets/gltf
License:    MIT
Installed:  Godot/assets/models/godot_humanoid_hands
```

The right and left assets each import as a `PackedScene` with a skinned mesh and
25 named bones: one hand bone plus four bones per finger. The copied license is
`LICENSE.godot-demo-projects.md`.

Asset SHA-256:

```text
RightHandHumanoid.gltf  2c442acc777e8f3943704d11f2d23c0e5bd9f49da22461059cd5a6c6f83ed56e
RightHandHumanoid.bin   89468a6868afbd6a9d5e545e7fdd5dadd7d7abab6d4389d8acc14a7804901e41
LeftHandHumanoid.gltf   a0a1f484347bf15db91f2a66773816205286d72891ccb4ebad6a71796b54b4fe
LeftHandHumanoid.bin    05f96e5aae870c8f2fde8a1fea337b060c7fde3e659b124a5ed979f0ffa1222a
hand.png                2ac198749d14b93887b52fb92e7ed5caac5ff0e187636fc708984f9b3b816833
```

### Track source and stable-depth reprojection

The virtual-hand track was not redetected from the repaired/displayed RGB and
no mask was invented. It reuses the same-capture MediaPipe sidecar:

```text
Godot/assets/processed_sessions/session_kinect_20260623_154953_object_removed_posterior_repair_core_target_contact_intent82/hand_tracks_mediapipe.json
SHA-256: 9884a976ab92cdb3548cbedd28ecb8a946cf509f9edbde8998a1fcc851f4f74c
Samples: 526 of 714 frames
```

`Godot/tools/materialize_virtual_hand_session.py` clones the selected
rebuilt-RGB/stable-depth session by hard link or copy, then:

1. Reads each sample's stored MediaPipe pixel landmarks.
2. Samples the selected stable depth with the same 3x3 filtering profile and
   per-frame baseline correction used by the Godot depth display.
3. Preserves each landmark's original relative hand-height shape.
4. Places the palm `0.14` world units above the reconstructed surface.
5. Places index fingertip `8` at surface height plus `0.022`.
6. Writes a separately named sidecar and embeds full provenance.
7. Re-hashes every source/output RGB and depth image and aborts if either
   ordered sequence changed.

Exact v3 materialization:

```powershell
python Godot\tools\materialize_virtual_hand_session.py `
  --source-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18" `
  --source-hand-tracks "Godot\assets\processed_sessions\session_kinect_20260623_154953_object_removed_posterior_repair_core_target_contact_intent82\hand_tracks_mediapipe.json" `
  --output-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v3" `
  --style godot_humanoid_glass_v1 `
  --color "#4a8f84" `
  --handedness right `
  --hand-hover 0.14 `
  --contact-lift 0.022 `
  --contact-indices 8 `
  --max-gap-seconds 0.24 `
  --endpoint-hold-seconds 0.05
```

Generated sidecar:

```text
hand_tracks_godot_humanoid_glass_v1.json
SHA-256: 8552765dfa2cfbf0a4ff084db7e0221fd478c928688fc986e44e1bb0d67f3049
```

Mandatory identity results:

```text
RGB sequence SHA-256:
713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30

Depth sequence SHA-256:
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8

rgbUnchanged:   true
depthUnchanged: true
```

### Runtime retargeting and appearance

`Godot/scripts/main.gd` now:

- chooses the matching official left/right rig for humanoid styles;
- computes a palm basis from wrist and index/middle/ring/little MCP landmarks;
- aligns and uniformly scales the rig to that palm basis;
- maps MediaPipe thumb `1-4`, index `5-8`, middle `9-12`, ring `13-16`,
  and little `17-20` to the named humanoid finger chains;
- rotates bones hierarchically while preserving the model's bound segment
  lengths, avoiding the skin tearing caused by directly translating bones;
- hides the model outside endpoint hold or across a tracking gap greater than
  `0.24 s`, rather than floating through missing observations;
- falls back to the procedural soft hand only if the selected rig cannot load.

`Godot/assets/shaders/hologram_hand.gdshader` is a depth-tested Compatibility
shader (`depth_prepass_alpha`) with no always-on-top rendering. The selected
style is muted sea-glass teal with low emission, low specular, higher roughness,
and no cast shadow. The sand surface therefore occludes any part of the hand
that is geometrically behind it.

### Verification

- `materialize_virtual_hand_session.py` passed `py_compile`.
- `validate_main.gd` loaded the reconstruction resources without a parse or
  resource error.
- Both official hand scenes imported in the isolated Godot 4.5.1 Web project.
- The v3 session and v3 hand sidecar returned HTTP 200 on port `8845`.
- Browser frame `1.26 s` showed a connected open hand rather than capsules.
- The deliberate `4.70 s` gap hid the hand; `5.75 s` restored a bent/pointing
  pose without bridging the absent samples.
- A full autoplay reached frame `714/714` and time `23.77 / 23.77`.
- The v3 browser URL produced zero errors and zero warnings.
- Final Web PCK SHA-256:
  `c7b749f57abe1fd641cda04fe3932fff23be0872a7e72da83f1bfd8de071abe6`.

## Virtual Hand v4: Stable Scale, Intent Contact, and Drawing Rod (2026-07-24)

### Why v3 changed size

The v3 runtime divided every frame's target palm span (MediaPipe landmarks
`5 -> 17`) by the rig's rest span. That is not a physical hand-size
measurement: foreshortening, partial detections, and collapsed landmarks made
it vary from `0.016590` to `0.597234` world units over the same clip
(`median 0.346481`). At frame 604 the span collapsed and the rendered hand
became a tiny dot.

v4 computes one session-level reference from valid positioning/erasing samples:

```text
rig_palm_span_reference: 0.426395
method: median_positioning_erasing_valid_span
```

The rig uses that fixed scale for the full session. It still follows the hand's
position and orientation, but if a detected target span falls outside
`0.35x..1.75x` of the reference it reuses the last valid palm basis. This
rejected 98 collapsed/foreshortened samples without changing the hand's size.

### Contact policy and tool-state evidence

v3 first lifted the palm and then changed only landmark 8's Y value. That bent a
single fingertip away from the rest of the tracked skeleton and assumed every
action was index-finger drawing.

v4 preserves the tracked pose and translates the whole 21-point hand rigidly:

```text
positioning   -> palm hover, no contact constraint
tool_drawing  -> hand hover; separate rod tip contacts the sand
erasing       -> median palm anchors 0,5,9,13,17 contact as one rigid hand
drawing       -> index fingertip 8 contacts as one rigid hand
```

The early tool state is not a hand-authored RGB mask or a fabricated shadow
rule. Review of the exact raw RGB showed the long thin rod absent from its
tray-rest location while frames 82-299 were drawn, then visibly returned by
about frame 316. The semantic intent segment is therefore:

```text
frames 82-299: tool_drawing
frames 300-411: erasing
frames 412-426: positioning
frames 427-661: finger drawing
```

Only detected MediaPipe samples are written, giving:

```text
positioning 76 | tool_drawing 154 | erasing 108 | drawing 188
```

`Godot/scripts/main.gd` builds a warm wood drawing rod with a cylindrical shaft,
tapered dark tip, and end cap. It is visible only for `tool_drawing`; its tip is
anchored to the reconstructed surface while its axis passes through the
thumb/index/middle grip estimate.

### Exact v4 materialization

```powershell
python Godot\tools\materialize_virtual_hand_session.py `
  --source-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18" `
  --source-hand-tracks "Godot\assets\processed_sessions\session_kinect_20260623_154953_object_removed_posterior_repair_core_target_contact_intent82\hand_tracks_mediapipe.json" `
  --output-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v4" `
  --style godot_humanoid_contact_tool_v2 `
  --color "#4a8f84" `
  --handedness right `
  --hand-hover 0.16 `
  --contact-lift 0.022 `
  --palm-contact-lift 0.035 `
  --tool-tip-lift 0.018 `
  --contact-indices 8 `
  --tool-drawing-frame-range 82:299 `
  --max-gap-seconds 0.24 `
  --endpoint-hold-seconds 0.05
```

Generated sidecar:

```text
hand_tracks_godot_humanoid_contact_tool_v2.json
SHA-256: c10a0e7b8b821ef17a2ffd38d27d799d3d7ff285be2c2ce94fb45a60a620459b
```

Identity gates remained unchanged:

```text
RGB sequence SHA-256:
713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30

Depth sequence SHA-256:
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8

rgbUnchanged:   true
depthUnchanged: true
```

### Verification

- Both Python tools passed `py_compile`; `validate_main.gd` loaded the runtime
  without parse or resource errors.
- Finger-drawing contact residual is exactly `0` in the materialized landmarks.
- Palm-erasing anchor residual is `0.00134` median, `0.00564` p95, and
  `0.00752` maximum world units.
- Browser checks at `5.60 s`, `11.44 s`, and `15.26 s` showed tool drawing,
  palm erasing without the tool, and later finger drawing respectively.
- Frame 604 at `20.14 s` retained a full-size hand instead of the v3 dot.
- Full autoplay reached frame `714/714` and `23.77 / 23.77`, with zero browser
  errors and zero warnings.
- Final v4 Web PCK SHA-256:
  `c0323e0e9dd7c3c5bcf6a05c58f741a317cbf307d31d4060893c876e54f6de7b`.

## Virtual Hand v5c: Pose Constraints and Depth-Correct Composition (2026-07-24)

### Root-cause combination

The v4 distortion was not one alpha bug. Four effects combined:

1. MediaPipe landmarks are occasionally collapsed or reversed while the real
   hand is occluded, near the image edge, or holding the rod.
2. The runtime accepted each new palm basis and every per-bone direction
   independently, so one bad sample could flip the palm by about 180 degrees or
   bend a phalanx beyond an anatomical range.
3. v4 constrained only the named contact set. Other fingers and palm points
   could remain below the exact displayed sand surface.
4. Both the hand and sand used transparent `blend_mix` depth prepasses.
   Material ablation showed that culling alone did not restore the missing
   hand, while opaque hand output or an alpha-scissor prepass did. The depth
   test was enabled; the inputs and transparent prepass ordering were wrong.

### Runtime and material corrections

`Godot/scripts/main.gd` now:

- accepts an absolute valid palm span of `0.20..0.70` world units;
- rejects a palm basis whose orthogonal length is below `0.24` of the session
  span reference;
- rejects a per-sample palm rotation step above `42 degrees` and reuses the
  last valid basis;
- rejects target/model segment-length ratios outside `0.28..2.60`;
- clamps proximal finger swing to `82 degrees` and later joints to
  `74 degrees`.

`Godot/assets/shaders/sand_depth.gdshader` now discards pixels outside the
surface mask and writes the remaining sand as opaque depth. The displayed mask
shape and depth displacement are unchanged.

`Godot/assets/shaders/hologram_hand.gdshader` now uses back-face culling plus a
transparent depth prepass with `ALPHA_SCISSOR_THRESHOLD = 0.5`. This preserves
the sea-glass appearance while making its depth behavior deterministic against
the sand body.

### All-landmark surface policy

`materialize_virtual_hand_session.py` samples the exact displayed stabilized
surface for every detected landmark:

```text
positioning   -> every landmark at least 0.055 above the surface
tool_drawing  -> every hand landmark at least 0.055 above; rod tip contacts
erasing       -> palm anchors contact as one rigid hand; remaining points >= 0.050
drawing       -> index fingertip 8 at 0.035; remaining points >= 0.050
```

Erasing uses the maximum required palm-anchor shift rather than the median, so
all five palm anchors clear the highest local surface without shifting
positioning/tool poses as a whole. Final measured minimum gaps are:

```text
positioning 0.055 | tool_drawing 0.055 | erasing 0.050 | drawing 0.035
```

No landmark penetrates the selected displayed surface. This is geometry
conditioning from the reconstructed depth, not a hand-authored RGB mask or a
shadow-removal heuristic.

### Exact v5c materialization

```powershell
python Godot\tools\materialize_virtual_hand_session.py `
  --source-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18" `
  --source-hand-tracks "Godot\assets\processed_sessions\session_kinect_20260623_154953_object_removed_posterior_repair_core_target_contact_intent82\hand_tracks_mediapipe.json" `
  --output-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v5c" `
  --style godot_humanoid_contact_tool_v3 `
  --color "#4a8f84" `
  --handedness right `
  --hand-hover 0.16 `
  --contact-lift 0.035 `
  --palm-contact-lift 0.055 `
  --tool-tip-lift 0.018 `
  --hover-min-clearance 0.055 `
  --noncontact-min-clearance 0.05 `
  --contact-indices 8 `
  --tool-drawing-frame-range 82:299 `
  --max-gap-seconds 0.24 `
  --endpoint-hold-seconds 0.05 `
  --rig-span-min 0.20 `
  --rig-span-max 0.70 `
  --rig-max-orientation-step-degrees 42
```

Generated sidecar:

```text
hand_tracks_godot_humanoid_contact_tool_v3.json
SHA-256: 3f22d7eecadccab7a8c7fb9b2588e493a8d90881dbd06153b27d9563b939f9ab
```

Identity gates remained unchanged:

```text
RGB sequence SHA-256:
713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30

Depth sequence SHA-256:
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8

rgbUnchanged:   true
depthUnchanged: true
```

### Verification

- Both Python tools passed `py_compile`; `validate_main.gd` loaded the final
  runtime without parse or resource errors; `git diff --check` reported no
  whitespace errors.
- Browser inspection at `9.97 s`, `11.97 s`, and `12.96 s` showed a complete
  hand, continuous anatomy, and a clean open-palm erasing pose without
  transparent-depth disappearance or whole-hand floating.
- Full v5c autoplay reached frame `714/714` and `23.77 / 23.77`.
- The browser console contained only Godot/WebGL initialization logs: zero
  errors and zero warnings.
- Final v5c Web PCK SHA-256:
  `82c05d97ed36f9085a52476f3e688bc43f055d0b9d9c34bf60ff92410a60ed6d`.

## Virtual Hand v6b: Top-Down 2.5D Model Output (2026-07-24)

### Why the 21-point rig reached its limit

The remaining v5c deformation is an observation problem, not a parameter that
can be tuned away. In a fixed top-down view, fingers overlap the palm, the tool
occludes joints, and MediaPipe supplies only 21 sparse landmarks. Its relative
depth is not enough to determine the hidden surface or a unique articulated
3D pose. Temporal smoothing can hide one bad frame but cannot make the missing
geometry observable.

The model routes considered were:

- MANO: the appropriate low-dimensional parametric hand representation, but
  its model files require registration and acceptance of the MANO license:
  `https://mano.is.tue.mpg.de/`.
- HaMeR: a stronger monocular MANO reconstructor with an MIT-licensed code
  repository, but its complete trained path still requires the separately
  licensed MANO model: `https://github.com/geopavlakos/hamer`.
- WiLoR: a newer monocular MANO route, but its official pretrained weights are
  CC-BY-NC-ND and it also depends on MANO:
  `https://github.com/rolpotamias/WiLoR`.

Those routes should be benchmarked if a real free-camera 3D hand is required,
after the user has explicitly obtained/accepted the MANO assets. No restricted
model or weight was silently copied into this project.

For the current fixed top-down viewer, v6b takes the directly observable route:
standard Grounded-SAM-2 mask pixels provide the visible hand/forearm geometry,
and raw Kinect RGB contributes luminance only. It uses no generated skeleton
and therefore cannot twist an occluded finger into an unsupported 3D pose.

### Model-component selection, without an artificial mask

The accepted Grounded-SAM-2 `hand. arm.` result contains 714 binary masks and
665 active model frames. Some frames also contain an unrelated person/foot
component outside the tray. v6b resolves that ambiguity as follows:

1. Split the original model mask into 8-connected components.
2. Select the component with maximum pixel overlap with the authoritative sand
   surface mask.
3. Retain adjacent original model components whose edge gap is at most 26 px.
4. Never fill, close, dilate, extrapolate, or hand-edit the space between them.

The selector was checked against the independently generated MediaPipe track:
the surface-overlap component and the landmark-containing component agreed in
all `491/491` comparable frames. The 26 px association threshold comes from the
measured component-gap separation in this clip (actor pieces at `2..25.02 px`,
next component at `27.89 px`), not an image-position rule. It associated
multiple original components in 60 frames while preserving their exact pixels.

This policy intentionally leaves occasional visible wrist gaps when the model
itself split the hand and arm. Do not hide those gaps with a manually invented
mask. A future improvement should rerun or replace the segmentation model.

### Runtime composition

`Godot/tools/materialize_topdown_virtual_hand_session.py`:

- hardlinks/copies the selected stable RGB and depth frames and verifies both
  complete sequence hashes;
- writes one RGBA overlay per active selected model mask;
- transfers robust raw-RGB luminance inside model pixels into the fixed
  sea-glass color `#4a8f84`;
- disables the v5c skeletal virtual hand while retaining its procedural
  drawing-tool state.

`Godot/assets/shaders/topdown_hand_overlay.gdshader` positions the RGBA layer
from the same stabilized depth frame as the sand, with a `0.032` world-unit
lift. It is intentionally an unshaded, depth-test-disabled camera-composition
layer. That is correct for this fixed top-down study view and avoids the
transparent-depth ordering failure from v4; it is not correct for a side view
or an arbitrary free camera.

`Godot/scripts/main.gd` treats `virtualHandOverlay`, RGB, and depth as one
atomic frame set, creates `TopdownVirtualHandSurface`, and makes the existing
`Virtual hand / gestures` control hide/show both hand implementations.

### Exact v6b materialization

```powershell
python Godot\tools\materialize_topdown_virtual_hand_session.py --resume `
  --source-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18" `
  --source-masks "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer\metadata\grounded_sam2_human_full714_c035\binary_masks" `
  --source-appearance-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStories\Godot\assets\processed_sessions\session_kinect_20260623_154953" `
  --source-tool-tracks "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_rgb_grounded_sam2_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714_vda_temporal_s092_t18_virtual_hand_v5c\hand_tracks_godot_humanoid_contact_tool_v3.json" `
  --validation-hand-tracks "Godot\assets\processed_sessions\session_kinect_20260623_154953_object_removed_posterior_repair_core_target_contact_intent82\hand_tracks_mediapipe.json" `
  --output-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v6b_topdown" `
  --association-max-gap-pixels 26 `
  --color "#4a8f84"
```

Authoritative report:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v6b_topdown\topdown_virtual_hand_report.json
```

Identity and provenance gates:

```text
frameCount:                    714
activeOverlayFrameCount:       622
multiComponentAssociation:      60
handAuthoredMasks:             false
imagePositionRules:            false

Source/output RGB SHA-256:
713601653b141e354ae077afafa6e24018d3cdd82650d37f9c708b568fd87d30

Source/output depth SHA-256:
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8

Overlay sequence SHA-256:
2cfe9d91b914ca93d53620319fce734e91153a398e83e923da2fc0fa81b1a666

Tool-only sidecar SHA-256:
6a69de1916e21d6a870a5bbae399a314e4daf68cabfb38214c4dcab0cacd396b

rgbUnchanged:   true
depthUnchanged: true
```

### Verification and honest limits

- The generator passed `py_compile`; `validate_main.gd` reported
  `Main reconstruction resources loaded`; `git diff --check` found no
  whitespace errors.
- Browser inspection covered early tool drawing, open palm/erasing, later
  finger drawing, and the large forearm entry/exit states. The hand silhouette
  and scale follow the observed actor rather than inferred bone lengths.
- Full autoplay reached `714/714` and `23.77 / 23.77`; the browser console
  contained zero errors and zero warnings.
- The virtual-hand layer toggle removed/restored the complete overlay.
- Final Web PCK SHA-256:
  `fca5c0f2a519315f8f4a91045a1ff0f3e29e4ad6750722cbb4f94ff9f8ac2140`.

v6b eliminates the unsupported skeletal deformation, but it is deliberately a
top-down 2.5D result. It has less volume than the rigged v5c hand, can read as a
translucent cutout, and exposes segmentation discontinuities honestly. The
next high-quality 3D branch is a separately named temporally fitted MANO
sequence initialized from HaMeR or WiLoR, not more ad-hoc MediaPipe bone
clamping.

## Virtual Hand v7 Exploration: Registered RGB-D Measured Surface (2026-07-24)

### v6b preservation gate

The accepted v6b output remains at:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v6b_topdown
```

`PRESERVED_BASELINE.json` records the accepted session/manifest/report,
complete RGB/depth/overlay sequence hashes, and final v6 Web PCK hash.
`materialize_topdown_virtual_hand_session.py` now refuses to modify any output
directory containing that marker, including when `--resume` is passed. All v7
work uses a separately named output directory.

### Why registered Kinect depth is the first 3D branch

The original processed session was created by timestamp pairing RGB and depth,
not by true camera registration. Cross-correlation therefore showed a variable
rough offset near `(+7.5, -9.5) px`; hard-coding that shift would be another
unsupported image-position rule.

The raw recording still exists on tiara:

```text
/home/baleine/from-118/SandStoriesRemote/recordings/kinect_20260623_154953
```

The official libfreenect replay helper was run with
`FREENECT_DEPTH_REGISTERED`, which uses the Kinect calibration to produce
depth in RGB pixel coordinates. The original INDEX contains audio entries and
one malformed late audio path, so a non-destructive RGB/depth-only replay view
was used:

```text
/home/baleine/rgbd-hand-v7/replay_rgbd_only
```

The verified 713 registered PGM frames are in:

```text
/home/baleine/rgbd-hand-v7/official_registered_full713_filtered
```

Only the registered depth plus checksum was compressed:

```text
/home/baleine/rgbd-hand-v7/official_registered_depth_full713.tar.zst
SHA-256 57c36a94034dc93f9601a98c243347b7beed687a338f50fe5a713aeafa4d4b8c
```

The local verified extraction is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\v7_registered_depth
```

All `713/713` files passed the transferred SHA-256 manifest. The PGM payload
must be byte-swapped when read by Pillow because the libfreenect recording
stores 16-bit samples little-endian. The source clip contains 714 RGB frames
but 713 depth frames; v7 explicitly repeats registered depth frame 713 for
frame 714, matching the original converter's pairing policy and recording this
fact in its report.

### Measured geometry construction

`Godot/tools/materialize_rgbd_virtual_hand_session.py` uses:

1. The exact v6b Grounded-SAM-2 surface-associated actor pixels as the visible
   silhouette. It creates no new hand mask.
2. Official RGB-aligned Kinect registered depth in millimetres wherever the
   sensor has a valid `250..1500 mm` measurement.
3. The unchanged stabilized Any2Full sand depth as the reference surface.
4. A per-frame median stable-minus-registered bias measured on visible sand
   outside a 24 px actor exclusion. The median bias over this sequence is only
   `3.037 mm` (`p05 2.721`, `p95 3.378 mm`).
5. Positive metric lift above that calibrated sand reference, clipped only at
   `0.36 m` for texture encoding.
6. Nearest measured lift for invalid sensor holes no farther than 8 px, with
   exponentially decayed confidence and a 0.85 px confidence-weighted
   Gaussian smoothing. Larger unsupported regions fall back to zero lift on
   the stable sand surface.

Each `virtual_hand_geometry_NNNNNN.png` is an RGB data texture:

- red: reconstructed lift normalized to `0..0.36 m`;
- green: confidence (`1` direct measurement, decayed for short-gap fill);
- blue: direct registered-depth measurement flag.

This is explicitly a measured top-surface/height-field representation, not a
closed hand mesh and not inferred hidden anatomy.

Exact materialization:

```powershell
python Godot\tools\materialize_rgbd_virtual_hand_session.py `
  --source-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v6b_topdown" `
  --source-masks "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\propainter_grounded_sam2_c035_transfer\metadata\grounded_sam2_human_full714_c035\binary_masks" `
  --registered-depth "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\v7_registered_depth" `
  --source-appearance-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStories\Godot\assets\processed_sessions\session_kinect_20260623_154953" `
  --output-session "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v7_rgbd_measured"
```

Authoritative outputs:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v7_rgbd_measured\rgbd_virtual_hand_report.json
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v7_rgbd_measured\rgbd_virtual_hand_contact_sheet.png
```

Quantitative gates:

```text
frameCount:                         714
activeActorFrameCount:              622
direct measured coverage median: 79.41%
direct measured coverage p10/p90: 73.80% / 83.28%
short-gap geometry coverage median: 84.86%
short-gap geometry coverage p10/p90: 81.22% / 88.48%

Geometry sequence SHA-256:
2fe347f0e7146cc0a2a51d007779f29c1dfda30cf8a124e658c75bb1133867e3

rgbUnchanged:      true
depthUnchanged:    true
overlayUnchanged:  true
```

### Runtime and visual validation

`Godot/assets/shaders/topdown_hand_rgbd.gdshader` is selected only when a
session provides `virtualHandGeometry`. Unlike the v6b camera-composition
shader, it:

- displaces the hand plane by metric measured lift;
- derives shading normals from lift gradients;
- renders the actor as an opaque cutout with normal depth testing and depth
  writing, avoiding the v4 alpha/depth-ordering failure;
- keeps a 0.006 world-unit clearance only to prevent sand z-fighting.

`Godot/scripts/main.gd` loads `virtualHandGeometry` atomically with RGB, sand
depth, and the v6b overlay. The RGB-D hand plane uses 384 subdivisions while
v6b remains at 256 and retains its original shader. The virtual-hand layer
toggle still controls both branches.

Validation completed:

- both materializers passed `py_compile`;
- `validate_main.gd` loaded the new shader and main scene without errors;
- the Web build completed and the 714-frame autoplay reached
  `23.77 / 23.77`;
- browser checks covered tool drawing, open-palm separation, sparse-depth
  late frames, top view, and a near-side view;
- the browser console contained zero errors and zero warnings;
- active v7 PCK was archived as `build/web/index_v7_rgbd_measured.pck`;
- v7 Web PCK SHA-256:
  `bc82fd3e899eecd1885c4373c7d2a5c970b3fe7cb93327bba299b577c70a2bbe`.

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v7_rgbd_measured%2Fsession.json&debug=1&t=rgbd-hand-v7-measured-20260724&autoplay=0
```

### Honest boundary and closed-mesh model route

The measured branch fixes the flat cutout and transparent-depth problems and
does not suffer the unsupported 21-point skeletal twisting. It also makes the
remaining evidence limits visible:

- it is a top surface, so a grazing side view exposes a height-field edge
  rather than a closed palm/back mesh;
- an original Grounded-SAM-2 wrist gap remains a wrist gap;
- fingers become blockier in low-coverage registered-depth frames.

Do not close those gaps with a hand-authored mask or call unmeasured pixels
sensor geometry.

For a closed, free-camera hand, the technically appropriate next comparison is
a temporally fitted MANO sequence initialized by HaMeR, or the video-oriented
OmniHands route for occlusion-heavy interaction. Both require separately
licensed MANO model files. The user has now explicitly confirmed that they hold
a valid MANO license and supplied their official v1.2 download. The licensed
asset handoff below supersedes the earlier missing-asset state. OmniHands is
promising for severe occlusion but its current repository does not state a
clear software license.

### Licensed MANO v1.2 and HaMeR source handoff (2026-07-24)

User-supplied official package:

```text
C:\Users\lj200\Downloads\mano_v1_2.zip
SHA-256 50976831790ea9657d8110e0c94e50e90eaf35cd76169f0b27e5d32f3fcd951f
```

Only the two MANO model files and their official `models/LICENSE.txt` were
extracted; the large SMPL+H files were not copied. Exact official v1.2 model
hashes:

```text
MANO_RIGHT.pkl
45d60aa3b27ef9107a7afd4e00808f307fd91111e1cfa35afd5c4a62de264767
3821356 bytes

MANO_LEFT.pkl
c4022f7083f2ca7c78b2b3d595abbab52debd32b09d372b16923a801f0ea6a30
3821391 bytes
```

Amadeus restricted target:

```text
/home/baleine/hand-3d-v7/mano
directory mode: 0700
model/license/manifest modes: 0600
```

`MANO_LICENSED_ASSET_MANIFEST.json` records the package hash, per-file hashes,
the user's license assertion, and the explicit rules not to redistribute,
commit, or bundle the model into a Web export. A different MANO-compatible
pair found in an existing MeshGraphormer environment was not used; its original
package files remain untouched.

Validation used the exact `smplx==0.1.28` loader required by HaMeR. Both left
and right official models produced finite `1 x 778 x 3` vertex arrays,
`1 x 16 x 3` base-joint arrays, and 1538 triangle faces. The older
`manopth` smoke path is not authoritative for the official v1.2 pickle because
some arrays use chumpy objects; HaMeR's SMPL-X loader converts them correctly.

HaMeR was shallow-cloned on the network-capable Windows workstation, including
its ViTPose submodule, then archived and transferred through the SSH jump:

```text
HaMeR commit:
3a01849f4148352e9260b69bf28b65d1671a4905

ViTPose submodule:
d5216452796c90c6bc29f5c5ec0bdba94366768a

Source archive SHA-256:
090e82c7aada0cab08bea5571162433a092c0bd0ab3a7cf6280e13757a778b8d

Amadeus source:
/home/baleine/hand-3d-v7/hamer_3a01849
```

HaMeR's required model path is present as a symlink:

```text
/home/baleine/hand-3d-v7/hamer_3a01849/_DATA/data/mano/MANO_RIGHT.pkl
  -> /home/baleine/hand-3d-v7/mano/MANO_RIGHT.pkl
```

The licensed model, source, public HaMeR checkpoint, and isolated runtime are
now complete. The old missing-checkpoint state is superseded by the benchmark
and fusion handoff below.

### HaMeR checkpoint relay and isolated Amadeus runtime (2026-07-24)

Official public demo-data archive:

```text
https://www.cs.utexas.edu/~pavlakos/hamer/data/hamer_demo_data.tar.gz
local size: 6037554929 bytes
local SHA-256:
ccfb70abd672b64c3ea90891c808d4499cc36a37dd6cf86c561a665113aef11e
```

Only the HaMeR checkpoint/config/mean-parameter subset was required for the
current crop-based inference. The 3.8 GB ViTPose checkpoint was not relayed
because the existing model-produced sidecar supplies the detector crop.

```text
HaMeR checkpoint:
/home/baleine/hand-3d-v7/hamer_3a01849/_DATA/hamer_ckpts/checkpoints/hamer.ckpt
size: 2689536166 bytes
SHA-256:
e5cc06f294d88a92dee24e603480aab04de532b49f0e08200804ee7d90e16f53

model_config.yaml SHA-256:
0e5eeb82752e47dfd01db8e13ccc4c5eba9bf83f53da8285523b8d3e87247aa3
dataset_config.yaml SHA-256:
392d10aece296152769328f14bb1c0137d6ea2f50f7e69f716ee00e9ad6ac343
mano_mean_params.npz SHA-256:
efc0ec58e4a5cef78f3abfb4e8f91623b8950be9eff8b8e0dbb0d036ebc63988
```

The checkpoint was split into fourteen 192 MiB parts. Each part was staged
one at a time on `jp`, pulled by Amadeus with rsync/resume, independently
hashed on both hosts, and deleted from the space-limited `jp` staging area
before the next part. The reassembled checkpoint hash matches the official
archive. `acode` was not modified and no package was installed there.
After verification, the three exact temporary relay keys were removed from
`acode`, the Amadeus relay key was removed from `jp`, all matching private
temporary keys were deleted, and the recoverable 9.0 GB partial relay directory
was removed from `acode`. The verified checkpoint and final result remain only
on Amadeus plus the documented local archives.

The stable-diffusion environment is only a read-only CUDA/PyTorch base. All
additional packages live in a separate overlay:

```text
base Python:
/home/baleine/stable-diffusion/stable-diffusion-webui/venv/bin/python

overlay:
/home/baleine/hand-3d-v7/hamer_overlay

overlay packages:
smplx 0.1.28
pyrender 0.1.45
freetype-py 2.5.1
PyOpenGL 3.1.0
pyglet 2.1.9
webdataset 0.2.86
braceexpand 0.1.7

chumpy compatibility source:
/home/baleine/hand-3d-v7/chumpy_580566e
commit 580566eafc9ac68b2614b64d6f7aaa84eebb70da
```

Required runtime prefix:

```bash
export PYTHONPATH=/home/baleine/hand-3d-v7/hamer_overlay:/home/baleine/hand-3d-v7/chumpy_580566e:/home/baleine/hand-3d-v7/hamer_3a01849:/home/baleine/hand-3d-v7/tools
export PYOPENGL_PLATFORM=egl
export PYGLET_HEADLESS=true
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
```

The last variable is required because trusted official Lightning checkpoints
predating PyTorch 2.6 otherwise inherit the new `weights_only=True` default.

### HaMeR + shared MANO shape + registered RGB-D hard-frame benchmark

The representative hard frames are:

```text
82, 120, 177, 231, 297, 356, 400, 526, 604
```

Reusable tools:

```text
Godot/tools/infer_hamer_from_track_sidecar.py
Godot/tools/validate_hamer_against_rgbd.py
Godot/tools/rebuild_hamer_with_shared_mano_shape.py
Godot/tools/fuse_hamer_mano_with_rgbd.py
Godot/tools/render_hamer_rgbd_fusion_diagnostics.py
```

The sidecar contributes only crop, handedness, and five semantic palm points
for global alignment. HaMeR supplies the MANO pose/topology. No hand-authored
mask, per-joint pose correction, image-position rule, or shadow extension is
used.

Initial inference:

```bash
python /home/baleine/hand-3d-v7/tools/infer_hamer_from_track_sidecar.py \
  --hamer-root /home/baleine/hand-3d-v7/hamer_3a01849 \
  --checkpoint /home/baleine/hand-3d-v7/hamer_3a01849/_DATA/hamer_ckpts/checkpoints/hamer.ckpt \
  --track-json /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_tool_only_v1.json \
  --rgb-dir /home/baleine/hand-3d-v7/inputs/raw_rgb \
  --frames 82,120,177,231,297,356,400,526,604 \
  --handedness right \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v2_skeleton
```

Raw monocular HaMeR is a good topology/pose initializer but its camera Z is
not metric enough for final rendering. Against the registered Kinect geometry:

```text
median direct RGB-D coverage: 0.9937
median fixed-metric depth RMSE: 32.64 mm
median fixed-metric absolute P90 residual: 52.58 mm
median affine diagnostic RMSE: 17.6 mm
median implied affine scale: 0.106
median affine R^2: 0.0595
```

The low R-squared and per-frame scale disagreement prove that a single global
scale/offset cannot repair the monocular depth. Frame 604 is the clearest
failure at 82.7 mm fixed-metric RMSE.

HaMeR also predicts a new ten-component MANO shape on every frame. The
component-wise median beta vector is therefore rebuilt once and shared:

```bash
python /home/baleine/hand-3d-v7/tools/rebuild_hamer_with_shared_mano_shape.py \
  --input-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v2_skeleton \
  --mano-model-path /home/baleine/hand-3d-v7/mano \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v2b_shared_shape
```

Shared betas:

```text
[0.0469876230, 0.0102761686, -0.1265419126, 0.0208176672,
 0.0081777275, 0.0635800511, 0.0372187495, 0.0043239444,
 0.0125595927, -0.0170675218]
```

Before replacing any beta, the rebuild script reproduces every original HaMeR
vertex with its original beta. The worst hard-frame self-check error is
`0.00005012 mm` for vertices and `0.00003725 mm` for joints. This is the
authoritative proof that the official MANO configuration matches HaMeR.

Final hard-frame fusion:

```bash
python /home/baleine/hand-3d-v7/tools/fuse_hamer_mano_with_rgbd.py \
  --inference-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v2b_shared_shape \
  --rgbd-session /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry/processed_manifest.json \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v8_shared_shape_rgbd_depth_only
```

Fusion policy:

1. Keep the shared-shape HaMeR top-down XY silhouette and MANO connectivity.
2. Fit one fixed-scale, minimum-angle palm-plane normal correction from five
   semantic palm points and their registered RGB-D lift.
3. Use that fit only for camera-depth/thickness, so correcting Z cannot throw
   the valid XY silhouette out of the measured hand support.
4. Allow only unit-scale global 2D rotation/translation; never resize the hand.
5. Put visible MANO vertices on the registered RGB-D top surface and preserve
   the MANO back-surface offset. Unsupported vertices fall back to the
   fixed-metric MANO depth prior.
6. Reproduce the current Godot sand shader's clean-depth baseline conversion
   before adding the measured lift and 0.006 world-unit clearance.

Hard-9 final metrics:

```text
median RGB-D-supported vertex ratio: 1.0000
minimum RGB-D-supported vertex ratio: 0.9640
median directly measured vertex ratio: 0.9974
median visible-surface RMSE: 0.5298 mm
visible-surface RMSE range: 0.408-0.709 mm
median MANO back-thickness P90: 23.21 mm
```

Topology validation finds 778 finite vertices, 1538 faces, zero degenerate
triangles, and zero non-manifold edges on every hard frame. The 16 boundary
edges are the intentional MANO wrist opening, not a reconstruction tear.

Authoritative hard-frame artifacts:

```text
remote:
/home/baleine/hand-3d-v7/results/hamer_hard9_v8_shared_shape_rgbd_depth_only

local:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\hamer_hard9_v8_shared_shape_rgbd_depth_only

bundle SHA-256:
9eee13427cd93dbaaff7f4ca80461a83ec4533624c2fe1db0b4db2e57b3324c3

fusion report SHA-256:
d40ea85b01ad89137a595409f91d51b5b616879b2e8dce4f29d0fe3364f63345

diagnostic contact sheet:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\hamer_hard9_v8_shared_shape_rgbd_depth_only_diagnostics\hamer_rgbd_fused_hard9_contact.png
contact sheet SHA-256:
28da2be5965143dea001677e67587282374a24e459e8c7ca7022e8ab410a2135
```

This completes the representative 3D proof, not a 714-frame production
sequence. The next production step is to estimate one shared beta from a
well-spaced sample, infer all frames, temporally filter MANO rotations in
rotation space, use the registered RGB-D fusion per frame, and fall back to
the temporal pose/depth prior at low-support frames. Preserve v6b and v7; the
future full sequence must use a separately named session.

### Godot MANO preview and robust RGB-D metric anchoring v9 (2026-07-24)

The first Godot integration exposed a failure that was not visible in the
top-view-only numeric check of v8. On frames 231 and 604, registered RGB-D
lift is bimodal at the projected hand boundary: valid hand pixels can be
roughly `0.13-0.31 m` above the sand while a one-pixel silhouette miss lands
on approximately zero-lift sand. The v8 per-vertex fusion attached adjacent
MANO boundary vertices to different depth modes. Because MANO is a closed
surface, the connecting triangles became vertical walls. Frame 604 looked
like two thin prongs in the default Godot view and like a column from the
side. This was real fused geometry, not alpha blending or a depth-test bug.

Do not use the v8 per-vertex mesh as the production 3D hand. Keep it only as
the reproducible counterexample documented above.

`Godot/tools/fuse_hamer_mano_with_rgbd.py` now has:

```text
--lift-fusion-mode mano_rigid_offset
--rgbd-anchor-bin-meters 0.010
--rgbd-anchor-radius-meters 0.030
```

The new mode uses only direct, z-buffer-visible RGB-D candidates, finds the
confidence-weighted dominant 1 cm camera-to-sand offset bin, and refits the
offset from candidates within 3 cm of that mode. RGB-D therefore determines
one robust absolute metric height per frame. The official MANO surface keeps
its continuous relative camera depth, pose, topology, and thickness. There
is still no hand-authored mask, per-joint correction, or image-position rule.

The v9 hard-frame command on Amadeus was:

```bash
export PYTHONPATH=/home/baleine/hand-3d-v7/hamer_overlay:/home/baleine/hand-3d-v7/chumpy_580566e:/home/baleine/hand-3d-v7/hamer_3a01849:/home/baleine/hand-3d-v7/tools
/home/baleine/stable-diffusion/stable-diffusion-webui/venv/bin/python \
  /home/baleine/hand-3d-v7/tools/fuse_hamer_mano_with_rgbd.py \
  --inference-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v2b_shared_shape \
  --rgbd-session /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry/processed_manifest.json \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_hard9_v9_mano_rigid_rgbd \
  --lift-fusion-mode mano_rigid_offset
```

V9 hard-9 validation:

```text
median RGB-D-supported vertex ratio: 1.0000
minimum RGB-D-supported vertex ratio: 0.9640
median directly measured vertex ratio: 0.9974
median dominant-mode inlier ratio: 0.7523
dominant-mode inlier ratio range: 0.5243-0.9597
median robust visible-anchor RMSE: 13.7254 mm
robust visible-anchor RMSE range: 9.9826-14.8320 mm
robust visible anchors per frame: 59-333
world-Y span per closed hand: 0.2020-0.3937 Godot units
```

The higher RMSE than v8 is intentional and honest: v8 achieved sub-millimetre
error by copying discontinuous per-pixel measurements into the mesh. V9
rejects the wrong depth mode and preserves a physically continuous hand. The
new contact sheet confirms that the frame-231/604 walls are gone. Frame 604
remains high above the sand in a side view because its direct Kinect depth
mode is about `0.30 m` above the sand; its mesh is now a normal closed hand,
not a vertical extrusion.

Authoritative v9 artifacts:

```text
remote fusion:
/home/baleine/hand-3d-v7/results/hamer_hard9_v9_mano_rigid_rgbd

remote diagnostics:
/home/baleine/hand-3d-v7/results/hamer_hard9_v9_mano_rigid_rgbd_diagnostics

local fusion:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\hamer_hard9_v9_mano_rigid_rgbd

fusion report SHA-256:
e1f044fbcd671b294a157df6734c8e446a9c0e552d6e6c9224fc396bc419f56b

local diagnostic contact sheet:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\hamer_hard9_v9_mano_rigid_rgbd_diagnostics\hamer_rgbd_fused_hard9_contact.png

contact sheet SHA-256:
c29317e7199a439b839a50c96d12826a7dd084deec78513c120464be79d18cfe
```

Godot now supports a per-frame `virtualHandMesh` JSON stream. The runtime
loads an indexed `ArrayMesh`, caches it with the other frame resources, and
uses an opaque, double-sided warm-clay PBR material with depth writes enabled.
No alpha blending is used. The compact v9 hard-9 review session is:

```text
Godot/assets/processed_sessions/session_kinect_20260623_154953_virtual_hand_v9_mano_rigid_rgbd_hard9
```

It contains nine clean RGB/depth frames and nine meshes of 778 vertices /
1538 faces. `Godot/tools/materialize_mano_rgbd_preview_session.py` reproduces
the session, and `Godot/tools/validate_mano_mesh_preview.gd` accepts a
`--session-root=` argument for headless validation. Godot 4.5.1 validation
passed, the complete nine-frame autoplay passed in the Web build, and the
default plus rotated side views were checked without runtime warnings.

Archived and active Web pack:

```text
Godot/build/web/index_v9_mano_rigid_hard9.pck
Godot/build/web/index.pck

SHA-256:
9d95d0ae0ff923d13f1e25ebab05a3d7db7aa870ad8722953b48800af2ee3821
```

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v9_mano_rigid_rgbd_hard9%2Fsession.json&debug=1&t=mano-rigid-rgbd-hard9-v9-20260724&autoplay=0
```

This is still a representative hard-9 result, not a 714-frame production
sequence. Preserve v6b, v7, v8, and v9 under their existing names. A full run
should use v9 robust anchoring plus temporal rotation/translation filtering
and must write a new session name.

### Full-timeline MANO + robust RGB-D v10 (2026-07-24)

> Historical implementation record only: the later pose-source audit proved
> that this branch inferred pose from hand-inpainted v44 RGB and its articulation
> is rejected. See "v10/v11 MANO pose-source audit and rejected tool-grip
> result". Preserve the artifacts, but do not use this section as evidence that
> v10 has valid hand motion.

The `9.00 s` duration shown by the v9 review was not the source recording
length and was not an inference failure. That session intentionally contained
the nine hard frames listed above at one frame per second. It was a compact
geometry QA reel. The real recording has `714` frames and a source duration of
`23.767706155776978 s`.

V10 completes the full-timeline branch without changing the accepted RGB or
depth streams. It does not remove shadows, create a manual mask, infer a hand
where registered RGB-D says none is present, or alter the sand reconstruction.

#### 1. Track densification and full RGB-D input

The original standard-model top-down track contained `526` samples. Its source
indices span `5-661`, with `188` gaps over the 714-frame capture. Registered
v7 RGB-D geometry was used only as a binary hand-presence gate. For a missing
track sample inside a measured-presence run,
`densify_hand_track_for_rgbd_frames.py` linearly interpolates the neighboring
model-produced crop landmarks. It never derives a crop, pose, or mask from
depth. A degenerate interpolated crop at frame `516` used the nearest original
model crop rather than an image-position heuristic.

```bash
python /home/baleine/hand-3d-v7/tools/densify_hand_track_for_rgbd_frames.py \
  --track-json /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_tool_only_v1.json \
  --geometry-dir /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/processed_manifest.json \
  --output-json /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_rgbd_presence_dense_v10b.json
```

The resulting sidecar has `622` frames: `504` original tracked crops,
`118` bracketed interpolated crops, and one nearest-original-crop fallback
among those interpolations. Its SHA-256 is:

```text
6287121f3ea0128864f28574687b7a8fd5fe829a5f6504cc7bc316bc4b82f222
```

The measured-presence runs are file suffixes `24-621`, `629-635`, and
`648-664`. Frames outside those runs are deliberately hand-free. The complete
v7 input was transferred as one tar archive to avoid the small-file SCP
bottleneck:

```text
/home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_depth_full714_20260724.tar
/home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714
```

The extracted input contains all `714` registered geometry files, all `714`
clean-depth files, and the original processed manifest.

#### 2. HaMeR inference, one shared MANO shape, and rotation-space smoothing

Full inference used the same official HaMeR checkpoint, licensed MANO v1.2
right-hand model, and exact displayed inference RGB directory as the hard-9
proof:

```text
RGB: /home/baleine/rgb-depth-uniform/propainter_v44_rgb
raw 622-frame inference:
/home/baleine/hand-3d-v7/results/hamer_dense622_v10b_raw
shared MANO shape:
/home/baleine/hand-3d-v7/results/hamer_dense622_v10b_shared_shape
```

`rebuild_hamer_with_shared_mano_shape.py` computes one component-wise median
beta vector for all frames, reproduces each source MANO mesh as a loader
self-check, and then rebuilds every frame with that one shape.

`smooth_hamer_mano_sequence.py` performs quaternion-sign-continuous Gaussian
smoothing in rotation space, not Euclidean averaging of axis-angle vectors:

```bash
python /home/baleine/hand-3d-v7/tools/smooth_hamer_mano_sequence.py \
  --input-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v10b_shared_shape \
  --mano-model-path /home/baleine/hand-3d-v7/mano \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v10c_shared_shape_temporal_robust \
  --sigma-frames 1.25 \
  --maximum-gap-frames 3 \
  --maximum-rotation-change-degrees 28
```

The camera translation path first rejects five-frame median outliers, then
uses the same Gaussian temporal support. Final temporal diagnostics:

```text
frames / contiguous segments: 622 / 3
joint rotation change P50/P90/P95/max:
5.8697 / 17.9575 / 24.0253 / 28.0000 degrees
camera-Z P0/P1/P50/P99/max:
7.0913 / 11.1587 / 24.7776 / 51.4567 / 55.4067
camera jump P50/P90/P95/P99/max:
1.1317 / 3.6554 / 4.4638 / 8.5135 / 11.4040
pre-filter maximum camera jump: 91.5825
```

#### 3. Robust registered RGB-D fusion and explicit invalid-frame policy

The full run uses v9's `mano_rigid_offset` policy. The fusion tool now accepts
`--skip-invalid-frames`; an insufficiently measured frame is recorded and
omitted instead of receiving a fabricated mesh.

```bash
python /home/baleine/hand-3d-v7/tools/fuse_hamer_mano_with_rgbd.py \
  --inference-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v10c_shared_shape_temporal_robust \
  --rgbd-session /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/processed_manifest.json \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v10e_rgbd_robust_skip_invalid \
  --lift-fusion-mode mano_rigid_offset \
  --skip-invalid-frames
```

Fusion accepted `607/622` source frames. The 15 explicitly rejected file
suffixes are:

```text
24, 25, 27, 28, 29, 30, 31, 34,
273, 274, 275, 276, 277, 278, 587
```

Seven lacked 20 fusion anchors, seven lacked 20 visible RGB-D candidates, and
one failed dominant-depth-offset fitting. Valid-frame diagnostics:

```text
RGB-D support ratio min/median/P95/max:
0.24036 / 0.98972 / 1.00000 / 1.00000
direct-measurement ratio min/median/P95/max:
0.08997 / 0.91902 / 1.00000 / 1.00000
dominant-mode inlier ratio min/median/P95/max:
0.22549 / 0.73958 / 0.96356 / 1.00000
robust anchor RMSE min/median/P95/max:
2.7865 / 12.9476 / 15.9519 / 17.6294 mm
```

Fusion report:

```text
/home/baleine/hand-3d-v7/results/hamer_dense622_v10e_rgbd_robust_skip_invalid/hamer_rgbd_fusion_report.json
SHA-256:
ad2d83cb2290fb3ba73c0807d67c21024a6da969baa403ea9b7992590c10d815
```

#### 4. Bounded fallback, compact mesh stream, and full Godot materialization

`pack_fused_mano_meshes.py` packs every accepted fused mesh. It interpolates
only an explicitly rejected fusion frame that is bracketed by valid fused
meshes and whose gap is no more than eight frames. It cannot fill a gap unless
that suffix is present in the fusion report's `skippedFrames`. Thus it does not
bridge any RGB-D-absent interval.

```bash
python /home/baleine/hand-3d-v7/tools/pack_fused_mano_meshes.py \
  --fusion-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v10e_rgbd_robust_skip_invalid \
  --output-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v10f_packed_meshes \
  --maximum-interpolation-gap 8
```

The pack contains `620` meshes: `607` direct robust fusions plus `13` bounded
temporal fallbacks. Entry suffixes `24-25` remain hidden because they have no
earlier valid fused bracket. Across the complete 714-frame timeline the hand
therefore appears only where a verified mesh exists.

The Web runtime now accepts an indexed binary mesh stream:

```text
magic "MNRB"
version 1
vertex count, index count, source file-suffix index
float32 positions
float32 normals
uint32 triangle indices
deterministic gzip wrapper
```

The JSON fallback remains supported. On the hard-9 sample, binary gzip reduced
the total stream from `1,139,253` to `211,188` bytes, or about `126.6 KB` to
`23.5 KB` per mesh (`5.4x` smaller). This removes JSON text parsing and most of
the virtual-hand transfer cost that made the earlier browser playback feel
stuttery.

Authoritative packed artifacts:

```text
remote directory:
/home/baleine/hand-3d-v7/results/hamer_dense622_v10f_packed_meshes

remote/local transfer archive:
hamer_dense622_v10f_packed_meshes.tar
SHA-256:
014a722cc90b4e7de8be04d2f5ee8a68bebc70f8743c0060da9edd567a1889a1

local unpacked directory:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\hamer_dense622_v10f_packed_meshes

packed report SHA-256:
e10e33a8128981f95d82ff2031f12c5bcef2d18ab0fbc53d152a2b6531e85829
```

The full local session is generated without duplicating the accepted RGB/depth
payloads; same-volume hardlinks are used, with copy as a portable fallback:

```powershell
python Godot/tools/materialize_mano_rgbd_full_session.py `
  --source-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v7_rgbd_measured\session.json `
  --packed-mesh-dir ..\tmp\opencode\hamer_dense622_v10f_packed_meshes `
  --output-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v10_full_mano_rgbd_packed `
  --asset-mode hardlink
```

Final local session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v10_full_mano_rgbd_packed
714 manifest frames
714 accepted clean RGB frames
714 accepted clean depth frames
620 binary MANO mesh frames
duration 23.767706155776978 s
first/last mesh file suffix: 26 / 664
session.json SHA-256:
60b1afda833291eac1ef6d426c841217bb20e19989257ef5d10fc7d7b095455d
processed_manifest.json SHA-256:
f8a8cc2f3ba53366871afeeec646bdda2b61b2c3b32264be7327a293c8ed230b
```

All `620` gzip streams were decoded locally and validated as finite indexed
meshes with `778` vertices, `4614` indices, correct stored suffixes, and
in-range triangle indices. Browser playback reached `23.77 / 23.77` and
`714/714` through the normal port-8845 dynamic-session path.

Active and archived runtime Web packs:

```text
Godot/build/web/index_v10_packed_runtime.pck
Godot/build/web/index.pck
SHA-256:
75425db91b915f47d87f3088d1b75693b6c5cac2a13eaf611fdb39028f4f40d6
```

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v10_full_mano_rgbd_packed%2Fsession.json&debug=1&t=mano-full-packed-v10-20260724&autoplay=0
```

Preserve v6b, v7, v8, v9, and v10 under their existing names.

## Current Objective

Maintain and review the completed 714-frame sand-surface reconstruction using:

1. The 2026-07-24 Grounded-SAM-2 + ProPainter rebuild as the displayed texture.
2. Only high-confidence sparse Kinect metric depth as geometric anchors.
3. Any2Full Large (`vitl`) as the dense depth-completion model.
4. A separate object-masked RGB copy used only to condition Any2Full, so the
   visible arm/tool is not reconstructed as foreground geometry.
5. The existing Godot `256 x 256` PlaneMesh and `sand_depth.gdshader`
   displacement path.

The 32-frame preview (frames 150-181) was visually accepted by the user, and
the full 714-frame run has now completed the same pipeline. See
"Full 714-Frame Result (2026-07-17)" below.

## Non-Negotiable User Requirements

- Correct Godot project:
  `/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories/Godot`
- Do not use the obsolete snapshot:
  `/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStoriesRemote_171_full/SandStoriesRemote/Godot`
- Do not broadly search `/mnt/c/Users/lj200`, `.`, a project parent, or a whole
  drive. Read and search only known, narrow directories and exact paths.
- Keep `PlaneMesh.subdivide_width = 256` and
  `PlaneMesh.subdivide_depth = 256`.
- Keep the shader-based height displacement path. Do not replace it with CPU
  meshes, preview planes, diagnostic brown materials, or low-resolution
  fallbacks.
- Keep the selected 2026-07-24 rebuilt ProPainter RGB as the displayed Godot
  texture. v44 is a historical predecessor, not the current display prior.
- The object-masked RGB is model input only. Never display it to the user.
- Do not hand-author masks, extend model masks with spatial/temporal heuristics,
  or add shadow-removal masks.
- Do not trust all Kinect pixels. Use only quality-filtered sparse anchors.
- Use the proxy below for GitHub or Hugging Face downloads:
  `http://192.168.28.206:7890`
- At the last GPU check, GPU 0 was occupied by another task. Use GPU 1 or 2 and
  do not terminate unrelated GPU work.

## Depth Correctness and Height-Jump Resolution (2026-07-23)

### What was validated

The full 714-frame Any2Full output was audited against the original
object-excluded Any2Full reference NPZ files, not merely against the grid4
pixels supplied as model input.

Original float-model evaluation:

```text
Mean held-out Kinect MAE:  1.2538 mm
Mean held-out Kinect RMSE: 2.0073 mm
Mean quality P95 error:    3.3161 mm
```

The VDA-guided candidate was re-evaluated after PNG encoding and floating-point
shader correction:

```text
Mean per-frame held-out MAE:    1.3190 mm
Mean per-frame held-out RMSE:   2.0395 mm
Mean per-frame held-out P95:    3.4645 mm
Maximum frame held-out MAE:     1.4973 mm
```

The equivalent sampled post-encoding baseline was `1.2804 mm` MAE; the selected
temporal candidate was `1.3283 mm`, an increase of about `0.048 mm` or `3.7%`.
This is the measured spatial cost of temporal stabilization.

This remains validation against quality-filtered Kinect depth reconstructed from
the stored 8-bit height sequence. It is not an independent metrology system and
must not be described as hidden-region ground truth.

### Why the whole sand surface jumped

Two independent mechanisms were present:

1. Kinect raw-depth quantization:
   - Transition `147 -> 148` changed most of the Kinect surface by exactly one
     raw-depth unit. Under the fixed visualization encoding this becomes about
     `4` height values or `2.19 mm`.
   - The Any2Full transition median was `3.983` height values, showing that the
     model correctly followed the sparse anchors but also inherited their
     frame-wide quantization step.
   - Transition `222 -> 223` contained a left/right partitioned Kinect change;
     Any2Full converted it into a smooth low-frequency half-surface shift.
2. Web texture delivery:
   - The old runtime advanced the playhead immediately, started remote PNG
     downloads asynchronously, and continued rendering the previous depth until
     a later request completed.
   - It had no lookahead prefetch, atomic depth/RGB readiness check, or
     sequential-frame gate. A playback reaching the final timer therefore did
     not prove that every intermediate depth was displayed.

### Selected correction

The independent VDA sequence is used only for temporal deltas. Any2Full remains
the spatial and metric source. Selected parameters:

```text
Method:     bidirectional VDA-delta-guided adaptive smoothing
Strength:   0.92
Threshold:  18 encoded height values
```

Measured temporal changes on a fixed stride-4 audit:

```text
Metric                                      Original     Stabilized
Mean adjacent height difference              1.5023       0.5320
Maximum absolute frame-median delta           3.9830       0.0140
Broad coherent jump count                          2            0
147 -> 148 median absolute delta              3.9830       0.0007
222 -> 223 median absolute delta              1.9555       0.0043
Stable-region global-delta standard deviation 0.1596       0.0031
```

The stabilized `147 -> 148` difference retains local motion around the
arm/tool and drawing boundary while removing the implausible whole-surface
offset. The source Any2Full session was not overwritten.

Scripts:

```text
Godot/tools/analyze_depth_stability.py
Godot/tools/render_depth_event_diagnostics.py
Godot/tools/stabilize_any2full_with_vda.py
```

Audit artifacts:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/depth_stability_audit_20260723
```

### Frame-safe Web playback

`Godot/scripts/main.gd` now:

- prefetches 12 processed frames ahead;
- waits for an 8-frame autoplay buffer;
- switches a frame only when both remote depth and RGB are cached;
- advances processed sessions sequentially and freezes the playhead on a cache
  miss instead of skipping;
- retains only a bounded cache window (3 frames behind and 12 ahead).

Use the native Windows server for review:

```text
Script: tmp/opencode/serve_sandstories_windows.py
Port:   8845
PID at handoff: 45740
```

The WSL server on `8844` remains functional but its Windows forwarding path
could only sustain roughly `4-5 fps` when every frame was required. The native
server completed a full browser run from frame 1 through frame 714 and logged
all `714` unique depth plus all `714` unique RGB responses (`200`) between
`19:47:55` and `19:48:31`, including Godot startup and buffering. Final browser
console status was zero errors and zero warnings.

## Main Technical Conclusion

Raw Any2Full inference on an inpainted display sequence is not sufficient. The
historical v44 ProPainter sequence retained forearm pixels outside its inpainted
region, so Any2Full faithfully predicted that foreground object as close depth.
This produced a large white/wedge-shaped displacement in the first Godot preview
even though scalar holdout metrics were good.

The selected solution is:

```text
Any2Full Large (vitl)
+ fixed quality-filtered grid4 Kinect anchors
+ object-masked conditioning RGB
+ Kinect metric-range clamp during Godot encoding
+ per-frame floating-point median-bias correction in the shader
```

The selected 2026-07-24 ProPainter RGB is displayed unchanged. The model-masked
skin-colored hand/forearm is removed; deliberately unprocessed shadows or the
thin tool may remain visible, but they do not become arm-shaped sand geometry
because the completed depth was conditioned separately and is unchanged.

## Selected 32-Frame Result

Evaluation range: source frames 150-181, fixed grid4 anchors.

```text
Variant                    Holdout MAE   Out-of-range surface   Adjacent height
vits raw RGB               1.435 mm      1.0351%                2.035
vitb raw RGB               1.439 mm      3.4874%                2.059
vitl raw RGB               1.348 mm      1.8833%                1.898
vitl object-masked RGB     1.280 mm      0.0027%                1.441
```

Selected variant details:

- Mean holdout MAE: `0.0012797018 m`
- Mean holdout RMSE: `0.0020512672 m`
- Mean quality P95 absolute error: `0.0034465115 m`
- Mean Kinect holdout temporal-delta residual: `0.0007404077 m`
- Mean VDA-delta residual: `3.8606052` Godot height units
- Mean adjacent Godot height difference: `1.4406303`
- Mean out-of-range surface ratio before clamp: `0.0000267462`
- Maximum out-of-range surface ratio before clamp: `0.0005275962`
- Object-mask out-of-range ratio: `0.0`
- Mean per-frame median-bias correction: `-0.12469` height units
- Peak GPU memory: about `2.23 GB`
- Warm inference time: about `0.251 s/frame`

An isolated maximum prediction of `0.945 m` still exists, but it affects a very
small area and is clipped to the Kinect metric range for Godot encoding. Check
the full sequence for isolated spikes before calling it production-ready.

## Current Verified Preview

Processed-session name:

```text
session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_preview_150_181
```

Actual data directory:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_preview_150_181
```

Godot processed-session symlink:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories/Godot/assets/processed_sessions/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_preview_150_181
```

Recommended manual-review URL:

```text
http://localhost:8844/index.html?session=http://localhost:8844/assets/processed_sessions/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_preview_150_181/session.json&debug=1&t=any2full-vitl-masked-rgb-20260716
```

Autoplay URL:

```text
http://localhost:8844/index.html?session=http://localhost:8844/assets/processed_sessions/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_preview_150_181/session.json&debug=1&autoplay=1&t=any2full-vitl-masked-autoplay-20260716
```

Verification completed:

- 32 depth PNGs, 32 RGB PNGs, and 32 valid-mask PNGs exist.
- Representative assets are `640 x 480`.
- All 96 frame assets return HTTP `200`.
- Frame 1 and frame 32 render through the current Web export.
- Session duration is correctly loaded as `1.034059 s`.
- The raw arm-depth wedge is absent in the corrected preview.
- No Godot/session runtime errors were present in the final browser check.
- The existing `256 x 256` PlaneMesh and shader displacement path are intact.

## Important Visual Interpretation

The displayed ProPainter RGB still contains the arm/tool. This is intentional
and must not be confused with failed depth removal.

Inspect geometry using lighting and silhouette, not only the RGB texture:

- Bad raw Any2Full behavior: the arm creates a bright raised wedge in depth.
- Corrected behavior: the arm remains visible as RGB color, but the sand mesh
  continues underneath without the raised foreground wedge.

The current completion is still an estimate of hidden sand geometry, not a
measurement. Do not describe it as ground-truth hidden depth.

## Correct Project and Runtime Paths

Godot project:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories/Godot
```

Local processing scripts:

```text
/mnt/c/Users/lj200/rgb-depth-uniform
```

Remote processing root:

```text
/home/baleine/rgb-depth-uniform
```

Remote Godot mirror:

```text
/home/baleine/opencode/sandstories_remote/Godot
```

Any2Full repository:

```text
/home/baleine/Any2Full
```

Any2Full commit:

```text
780edf6be2bf9260f1cce8e4ddbcb52d7bcdae9e
```

Python environment:

```text
/home/baleine/venvs/video-depth-anything
```

Required import path:

```text
PYTHONPATH=/home/baleine/Any2Full
```

## Any2Full Checkpoints

```text
/home/baleine/Any2Full/checkpoints/Any2Full_vits.pth.tar
/home/baleine/Any2Full/checkpoints/Any2Full_vitb.pth.tar
/home/baleine/Any2Full/checkpoints/Any2Full_vitl.pth.tar
```

Approximate sizes:

- Small: `195 MB`
- Base: `765 MB`
- Large: `2.0 GB`

## Current Remote Evaluation Data

Prepared 32-frame evaluation input:

```text
/home/baleine/rgb-depth-uniform/any2full_eval
```

Object-masked conditioning RGB:

```text
/home/baleine/rgb-depth-uniform/any2full_eval/rgb_object_masked
```

Selected model output:

```text
/home/baleine/rgb-depth-uniform/any2full_eval/output_vitl_object_masked_clip150_181
```

Comparison report:

```text
/home/baleine/rgb-depth-uniform/any2full_eval/clip150_181_comparison_with_masked_rgb.json
```

Raw comparison outputs retained for diagnosis:

```text
/home/baleine/rgb-depth-uniform/any2full_eval/output_vits_clip150_181
/home/baleine/rgb-depth-uniform/any2full_eval/output_vitb_clip150_181
/home/baleine/rgb-depth-uniform/any2full_eval/output_vitl_clip150_181
```

## Sparse Kinect Anchor Rules

The current quality filter is implemented in
`prepare_any2full_eval.py`:

- Surface mask required.
- Kinect valid mask required.
- Depth object mask dilated by `8 px` and excluded.
- Encoded height restricted to `40-230`.
- `9 x 9` local median.
- Maximum local residual: `8` grayscale levels.
- Maximum Sobel gradient: `48`.
- Fixed grid positions prevent anchor locations from flickering by frame.
- Use grid4, approximately `4.37%` of surface pixels over the full sequence.
- Do not use grid6 for the selected run; it was less accurate.

The Kinect metric conversion is an approximation from existing 8-bit depth:

```text
height = (png / 255 - 0.14) / 0.78
raw = p02Raw + (1 - height) * (p98Raw - p02Raw)
meters = 0.1236 * tan(raw / 2842.5 + 1.1863)
```

Constants:

```text
p02Raw = 664
p98Raw = 714
metric range = 0.8128636457 to 0.9216704175 m
```

Original Kinect PGM files are not available on Amadeus. Do not overstate the
precision of this metric reconstruction.

## Object-Masked Conditioning RGB

Script:

```text
/mnt/c/Users/lj200/rgb-depth-uniform/prepare_any2full_conditioning_rgb.py
```

Method:

1. Use the dilated depth-object mask inside the sand surface.
2. Replace all pixels outside the surface with the median visible sand color,
   preventing the external arm from influencing the model.
3. Fill masked conditioning pixels from the temporal median of visible RGB.
4. Use OpenCV Telea fill only for pixels masked in every selected frame.
5. Do not feather the final conditioning mask (`featherPixels = 0`).
6. Save this as a separate model-input RGB sequence.

For frames 150-181:

- Mean object-mask ratio on the sand surface: `24.41%`.
- The reported `49.08%` always-masked image ratio includes the entire area
  outside the sand surface. It does not mean half of the sand is missing.

These conditioning images can look patched or artificial. That is acceptable
because they are not displayed. Judge the resulting metric depth and Godot
geometry instead.

## Key Scripts

```text
/mnt/c/Users/lj200/rgb-depth-uniform/prepare_any2full_eval.py
/mnt/c/Users/lj200/rgb-depth-uniform/prepare_any2full_conditioning_rgb.py
/mnt/c/Users/lj200/rgb-depth-uniform/run_any2full_eval.py
/mnt/c/Users/lj200/rgb-depth-uniform/aggregate_any2full_eval.py
/mnt/c/Users/lj200/rgb-depth-uniform/build_any2full_godot_preview.py
```

Responsibilities:

- `prepare_any2full_eval.py`: builds sparse grid4/grid6 Kinect inputs,
  references, masks, and copied RGB.
- `prepare_any2full_conditioning_rgb.py`: produces RGB used only for Any2Full
  conditioning.
- `run_any2full_eval.py`: runs Any2Full, writes metric NPY, Godot height PNG,
  and per-frame evaluation. It supports `--rgb-dir`.
- `aggregate_any2full_eval.py`: compares spatial, range, bias, Kinect-delta,
  and VDA-delta metrics.
- `build_any2full_godot_preview.py`: creates a dynamic Godot processed session
  with per-frame floating-point baseline corrections. Pass the accepted display
  sequence with `--rgb-dir`; `--source-session` remains the source of manifests
  and masks. Do not let conditioning RGB replace the displayed ProPainter RGB.

Remote copies of these scripts are in:

```text
/home/baleine/rgb-depth-uniform
```

## Godot Runtime Changes

Main runtime:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories/Godot/scripts/main.gd
```

Important current behavior:

- `PlaneMesh.size = Vector2(5.5, 5.5)`.
- `subdivide_width = 256`.
- `subdivide_depth = 256`.
- Each manifest frame may provide `baselineHeightCorrection`.
- The correction is divided by `255.0` and passed to the shader as
  `baseline_height_offset`.
- `_ready()` now awaits the default session load and then the Web URL session
  load. This fixes a race where the correct remote title loaded but the default
  `12 s` duration overwrote the preview duration.
- Applying any new session now resets the playhead and playback state before
  loading its frame manifest.
- `autoplay=1` applies only to the final URL-requested session, not the temporary
  default session loaded during startup.
- Remote sessions wait for their first depth, RGB, and surface-mask textures to
  enter the cache before autoplay begins. This prevents the initial white
  material flash seen during the 2026-07-23 network recheck.

Shader:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories/Godot/assets/shaders/sand_depth.gdshader
```

Important shader uniform:

```glsl
uniform float baseline_height_offset = 0.0f;
```

The vertex and fragment paths add this offset only inside the surface mask.

## Web Build and Server

Do not run the normal build directly against the live project while the many
processed-session symlinks exist. It can spend a long time scanning dynamic
data.

Use the isolated build script:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/build_sandstories_web_isolated.ps1
```

Command:

```bash
"/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" \
  -NoProfile -ExecutionPolicy Bypass \
  -File "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\build_sandstories_web_isolated.ps1"
```

The isolated build excludes:

```text
assets/processed_sessions
assets/experiments
build
.godot
.venv
tools
```

Dynamic sessions are served outside the PCK by the local HTTP server.

Server script:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/serve_sandstories_v44_web.py
```

Current HTTP port: `8844`.

Current HTTP PID: `2843`

The current full-rate review path is the native Windows server on port `8845`
(`tmp/opencode/serve_sandstories_windows.py`, PID `54812` at handoff). Use
`8845` for the temporally stabilized 714-frame review. Keep `8844` only as a
WSL-compatible fallback; its forwarding throughput is insufficient for
frame-safe 30 fps PNG playback.

### Current Windows Access (rechecked 2026-07-23)

The previous 2026-07-17 network reserved TCP range `8811-8910`, which blocked
Windows localhost forwarding for port `8844`. That reservation is absent in the
current network environment. Both of these now return HTTP `200` from Windows:

```text
http://localhost:8844/index.html
https://localhost:9844/index.html
```

Use plain HTTP `8844` for normal same-machine review. The HTTPS variant remains
available as a fallback:

- Script: `tmp/opencode/serve_sandstories_v44_web_https.py`, port `9844`
  (current PID `2846`).
- Self-signed cert: `tmp/opencode/certs/localhost.crt` / `localhost.key`
  (SAN: localhost, *.localhost, 127.0.0.1, WSL IP). Browsers warn once per
  session; accept and continue.
- URL template: replace both the host and the embedded session URL with
  `https://localhost:9844`.

Current network facts:

```text
Windows physical LAN: 192.168.64.203, gateway 192.168.64.1
WSL:                  172.22.31.149, gateway 172.22.16.1
Tailscale:            100.96.0.4
BankuViaTokyo VPN:    10.8.0.2
```

`BankuViaTokyo` currently routes `192.168.28.0/24`, so the old Kinect host
`192.168.28.171` and proxy `192.168.28.206:7890` remain reachable despite the
physical move. Expect higher latency; the `.171` ping was about `272 ms` during
this check. If that VPN is disconnected, the old remote paths will stop working.

Windows can also reach the WSL address directly at `172.22.31.149:8844/9844`.
The physical LAN address `192.168.64.203:8844` is not currently exposed, so
other LAN devices need an explicit Windows port proxy/firewall rule.

Start pattern mirrors the HTTP one, e.g.:

```bash
nohup python3 \
  "/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/serve_sandstories_v44_web_https.py" \
  > "/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/serve_sandstories_v44_web_https.log" \
  2>&1 &
```

The server now sends `Cache-Control: no-store`. This prevents stale Godot PCKs
after rebuilds. If Playwright still holds an older cached PCK, clear its browser
cache before verification.

Restart pattern:

```bash
nohup python3 \
  "/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/serve_sandstories_v44_web.py" \
  > "/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/serve_sandstories_v44_web.log" \
  2>&1 &
```

## Previous Fallback Baseline

Before Any2Full, the strongest complete 714-frame branch was:

```text
session_kinect_20260623_154953_rgb_propainter_promptda_cue_temporal_vda_baseline_locked
```

It combines PromptDA, VDA temporal deltas, and a stable Kinect baseline lock.
Keep it as a fallback and comparison target; do not delete it.

Relevant historic results:

- 714 PromptDA frames completed in about `51 s`.
- Mean known cue ratio: `83.51%`.
- VDA stabilization reduced mean adjacent difference from `2.6112` to
  `2.3772`.
- Baseline lock used `13,542` stable Kinect reference pixels.
- Floating-point shader correction reduced measured baseline drift to zero.

This branch is no longer the selected dense-completion direction because the
current task requires rejecting unreliable Kinect data instead of feeding most
of it as a strong cue.

## Full 714-Frame Result (2026-07-17)

The 32-frame preview was accepted. The full run used the same selected branch
(`vitl + object-masked conditioning RGB + grid4`) with one change:
`prepare_any2full_conditioning_rgb.py` now supports `--window-radius` (local
temporal median window; `-1` keeps legacy global-median behaviour). The full
run used `--window-radius 16`.

Regression on frames 150-181 with the windowed conditioning was clean before
the full run (holdout MAE 1.2790 mm vs 1.2797 mm global; object-mask
out-of-range still 0.0; arm-band depth profiles flat).

Full-sequence metrics (`any2full_full714/full714_comparison.json` on Amadeus):

```text
Mean holdout MAE:                     0.0012538 m
Mean holdout RMSE:                    0.0020073 m
Mean quality P95 absolute error:      0.0033161 m
Mean out-of-range surface ratio:      0.00007296
Maximum out-of-range surface ratio:   0.0014714 (frame 323)
Object-mask out-of-range ratio:       0.0
Mean object-to-boundary median diff:  0.0027599 m
Mean adjacent Godot height diff:      1.4898
Kinect holdout temporal-delta mean:   0.0007253 m
Median-bias drift (std):              2.494e-05 m
Predicted surface depth range:        0.8116 to 0.9483 m (clamped on encode)
```

Ten frames have out-of-range ratios above 0.001 (worst: 323, 363, 322, 250,
408); the spikes are the same isolated ~0.94-0.95 m predictions already seen
in the 32-frame run, are clipped to the Kinect metric range during Godot
encoding, and were not visible as artifacts in the browser review.

Full-run outputs on Amadeus:

```text
/home/baleine/rgb-depth-uniform/any2full_full714                       (inputs + report)
/home/baleine/rgb-depth-uniform/any2full_full714/rgb_object_masked     (window-16 conditioning RGB)
/home/baleine/rgb-depth-uniform/any2full_full714/output_vitl_object_masked  (metric NPY + Godot PNGs)
/home/baleine/rgb-depth-uniform/any2full_full714/full714_comparison.json
/home/baleine/rgb-depth-uniform/propainter_v44_rgb                     (historical displayed RGB; superseded 2026-07-24)
```

From WSL, Amadeus is reachable through the `r1` jump host even though the WSL
SSH config does not define the Windows `amadeus` alias:

```bash
ssh -J root@192.168.28.1 baleine@192.168.91.98
```

The Windows SSH config expresses the same route as `amadeus -> r1`.

Local full-session assets (depth PNGs + JSONs):

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/any2full_full714_depth
```

Built Godot processed session (714 frames, 23.77 s):

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714
```

Godot symlink:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories/Godot/assets/processed_sessions/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714
```

### Historical v44 display RGB correction (2026-07-23)

This subsection records the predecessor state only. It was superseded by the
2026-07-24 Grounded-SAM-2 + ProPainter rebuild described near the top of this
handoff.

An audit after the network recheck found that the first materialization of this
full session had copied all `clean_rgb_*.png` files from the raw Kinect base
session. This happened because `build_any2full_godot_preview.py` previously
always copied displayed RGB from `--source-session`; the Any2Full depth, masks,
evaluation, and object-masked conditioning inputs were not affected.

The full session's 714 displayed RGB files have now been restored from:

```text
amadeus:/home/baleine/rgb-depth-uniform/propainter_v44_rgb
```

Local mirror:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/v44_rgb_714
```

Verification:

- The Amadeus source and local mirror have identical SHA-256 manifests for all
  `714/714` frames.
- The restored full session and Amadeus source also have identical SHA-256
  manifests for all `714/714` displayed RGB frames.
- Browser checks at frames 150, 171, and 181 show the accepted ProPainter result:
  the central hand is removed; the forearm outside the inpainted mask remains.
- `build_any2full_godot_preview.py` now requires a separate `--rgb-dir` so a raw
  source manifest cannot silently replace the displayed ProPainter sequence.
- Object-masked RGB remains model conditioning only and is never displayed.

Historical 2026-07-17 Windows review URL (HTTPS fallback):

```text
https://localhost:9844/index.html?session=https://localhost:9844/assets/processed_sessions/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714/session.json&debug=1&t=full714-review-20260717
```

Historical same-machine review URL after the 2026-07-23 network recheck:

```text
http://localhost:8844/index.html?session=http://localhost:8844/assets/processed_sessions/session_kinect_20260623_154953_rgb_propainter_any2full_vitl_object_masked_rgb_grid4_full_1_714/session.json&debug=1&t=rgb-restored-amadeus-20260723
```

Agent browser review covered frames 1, 93, 150, 321 (worst OOR), 441, 709:
no arm/tool-shaped raised geometry, no visible seams, no console errors. That
geometry review remains valid because the depth was unchanged. The displayed RGB
portion of the old screenshots was invalid and has been superseded by the
post-restoration checks below. Final user acceptance is still the closing step.

The 2026-07-23 browser recheck additionally verified:

- HTTP `8844` and HTTPS `9844` from both WSL and Windows.
- The session manifest, processed manifest, frame 1, frame 323, and frame 714
  assets all returned `200`.
- Non-autoplay review loads frame `1/714` with duration `23.77 s`.
- Autoplay starts from frame 1, retains valid RGB/depth material at frames 165,
  253, and 340, and ends at frame `714/714` without a white material flash.
- Browser console: `0` errors; only Chromium WebGL `ReadPixels` performance
  warnings remain.
- Final screenshot:
  `tmp/opencode/review_screenshots/sandstories_final_network_check_20260723.png`.

Post-restoration browser screenshots:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/review_screenshots/sandstories_rgb_restored_frame150_20260723.png
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/review_screenshots/sandstories_rgb_restored_frame171_20260723.png
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/review_screenshots/sandstories_rgb_restored_frame181_20260723.png
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/tmp/opencode/review_screenshots/sandstories_rgb_restored_playback_final714_20260723.png
```

These show the corrected `clean_rgb_000150.png`, `clean_rgb_000171.png`, and
`clean_rgb_000181.png` textures in the live Godot surface. Console status remained
`0` errors with the same four WebGL performance warnings. A full playback recheck
also reached `714/714` with the corrected RGB sequence. A one-frame builder smoke
test confirmed that `--rgb-dir` materializes the requested ProPainter frame and
records its source in `session.json`.

`aggregate_any2full_eval.py` now accepts any subset of model outputs (the
three size arguments are optional), which is how the single-model full-run
comparison JSON was produced.

## Historical Full-Run Plan (Do Not Execute)

The commands below are retained only as provenance. The 714-frame run,
windowed conditioning, aggregation, materialization, RGB correction, and browser
verification are complete. Do not repeat this plan unless the user explicitly
requests a new model run.

First, have the user inspect the verified 32-frame preview. Do not launch a
full 714-frame production session if the hidden-region geometry is visually
rejected.

If the preview is accepted, run the selected pipeline for all 714 frames on
Amadeus.

### 1. Prepare all 714 sparse inputs

```bash
PYTHONPATH=/home/baleine/Any2Full \
/home/baleine/venvs/video-depth-anything/bin/python \
/home/baleine/rgb-depth-uniform/prepare_any2full_eval.py \
  --rgb-session /home/baleine/rgb-depth-uniform/propainter_v44_rgb \
  --anchor-session /home/baleine/opencode/sandstories_remote/Godot/assets/processed_sessions/session_kinect_20260623_154953 \
  --object-mask-dir /home/baleine/rgb-depth-uniform/depth_object_masks_v44 \
  --output-root /home/baleine/rgb-depth-uniform/any2full_full714 \
  --frames 1 \
  --clip-start 1 \
  --clip-end 714
```

### 2. Make conditioning safe for a 714-frame sequence

Do not run the current conditioning script over all 714 frames unchanged. It
currently computes one temporal median over every frame passed through
`--frames`. That was appropriate for the verified 32-frame, approximately
one-second clip, but a global median over the full recording would mix different
sand states from roughly 24 seconds of activity.

Before the full run, extend `prepare_any2full_conditioning_rgb.py` with a local
temporal window, for example `--window-radius 16`:

- For frame `t`, compute the visible-pixel temporal median only from
  `t - 16` through `t + 16`.
- Keep the existing object mask and outside-surface replacement behavior.
- Spatially fill only pixels that remain masked throughout that local window.
- Do not use future frames outside the local window.
- Re-run frames 150-181 and confirm the arm-depth wedge remains absent and the
  current metrics do not regress materially.

### 3. Build local-window object-masked conditioning RGB for all frames

```bash
FRAMES=$(seq -s, 1 714)
PYTHONPATH=/home/baleine/Any2Full \
/home/baleine/venvs/video-depth-anything/bin/python \
/home/baleine/rgb-depth-uniform/prepare_any2full_conditioning_rgb.py \
  --input-root /home/baleine/rgb-depth-uniform/any2full_full714 \
  --output-dir /home/baleine/rgb-depth-uniform/any2full_full714/rgb_object_masked \
  --frames "$FRAMES" \
  --window-radius 16
```

Historical note: `--window-radius` now exists, was validated, and was used for
the completed full run.

### 4. Run Any2Full Large with grid4

Confirm GPU 1 or 2 is free first. Do not assume GPU 0 is available.

```bash
FRAMES=$(seq -s, 1 714)
CUDA_VISIBLE_DEVICES=1 \
PYTHONPATH=/home/baleine/Any2Full \
/home/baleine/venvs/video-depth-anything/bin/python \
/home/baleine/rgb-depth-uniform/run_any2full_eval.py \
  --any2full-root /home/baleine/Any2Full \
  --input-root /home/baleine/rgb-depth-uniform/any2full_full714 \
  --rgb-dir /home/baleine/rgb-depth-uniform/any2full_full714/rgb_object_masked \
  --output-root /home/baleine/rgb-depth-uniform/any2full_full714/output_vitl_object_masked \
  --encoder vitl \
  --checkpoint /home/baleine/Any2Full/checkpoints/Any2Full_vitl.pth.tar \
  --densities 4 \
  --frames "$FRAMES"
```

### 5. Validate before materializing the full Godot session

At minimum:

- Recompute full-sequence holdout MAE, P95, median-bias drift, adjacent depth
  change, and out-of-range ratio.
- Inspect frames around `1`, `12`, `96`, `108`, `130`, `150`, `168`, `171`,
  `181`, `182`, `400`, `443`, and `714`.
- Specifically check that the visible arm/tool does not become raised geometry.
- Check mask boundaries for seams; the 32-frame mean object-to-boundary median
  difference was `2.22 mm`.
- Keep final metric-to-Godot encoding clamped to
  `0.8128636457-0.9216704175 m`.
- Generate a dynamic processed session first. Do not package 714 frames into
  the Web PCK.

Historical note: the builder was adapted for the full evaluation and now
requires an explicit displayed `--rgb-dir`.

## Do Not Repeat These Failed Directions

- Do not use raw Any2Full RGB inference as the final branch; it reconstructs
  the arm/tool as geometry.
- Do not use `vitb`; it had the worst low-depth excursions in this clip.
- Do not switch to grid6; it was less accurate than grid4.
- Do not feed the full `83.5%` Kinect cue as trustworthy geometry.
- Do not use OpenCV inpainting to fabricate sparse anchors before Any2Full.
- Do not replace the displayed ProPainter RGB with the conditioning images.
- Do not run the normal Web build directly over processed-session symlinks.
- Do not claim the hidden sand completion is measured ground truth.

## Portable Kinect Capture Bundle (2026-07-20)

The Kinect v1 capture/conversion code prepared on `192.168.28.171` was copied
into a standalone, source-first Linux bundle:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/KinectCaptureLinux
```

Read these first:

```text
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/KinectCaptureLinux/README.md
/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/KinectCaptureLinux/SOURCE_MANIFEST.md
```

Source provenance:

```text
Host: 192.168.28.171 (tiara, user baleine)
libfreenect origin: https://github.com/OpenKinect/libfreenect.git
libfreenect commit: 09a1f098040d00e6070c18174904547ec31d2774
```

The package includes `libfreenect` source, command-line capture/conversion,
Browser Record Studio, optional OpenCV Quick Capture, official registered-depth
helpers, udev rules, setup scripts, source archives, checksums, and migration
documentation. It intentionally excludes remote ELF binaries, recordings,
diagnostics, build directories, and the incomplete remote Godot copy.

Important portable behavior:

- Run `./setup_linux.sh` on every destination Linux machine; do not reuse the
  old Arch Linux binaries or CMake cache.
- Raw recordings default to
  `${XDG_DATA_HOME:-$HOME/.local/share}/sandstories-kinect`.
- Set `KINECT_PROJECT_DIR` to this full Godot project when generated sessions
  should be written directly under `assets/processed_sessions`.
- Session IDs are strictly validated and existing recordings, logs, and
  processed sessions are not silently replaced.
- Frontends stop `fakenect-record` with `SIGINT`, log subprocess output to disk,
  and prevent stale timers or concurrent conversion from affecting later
  recordings.
- Debug servers bind to `127.0.0.1` unless LAN exposure is explicitly requested.
- The insecure remote `fwfetcher.py` TLS bypass is retained only as a provenance
  patch; the portable source restores normal certificate verification.

Verification already completed on a fresh `/tmp` copy on `tiara`:

- Python, shell, and C syntax checks passed.
- `libfreenect`, `fakenect-record`, fakenect replay, C sync, and the registered
  helper rebuilt and installed successfully.
- The complete `setup_linux.sh` entry point created a working capture venv; it
  can reuse compatible system packages offline or fall back to pip.
- Installed binaries use relative `$ORIGIN/../lib` runtime paths and still load
  after the local install directory is moved.
- Fake-recorder smoke tests passed clean shutdown, strict session validation,
  no-overwrite behavior, stale auto-stop isolation, stop/start exclusion, and
  conversion/stride locking.

Remaining hardware verification on each destination host:

```bash
cd /path/to/KinectCaptureLinux
bash ./restore_permissions.sh
./install_udev_rules.sh
./setup_linux.sh
./doctor.sh --require-device
STRIDE=1 ./tools/kinect_remote_capture_convert.sh 4 kinect_smoke_001
```

The final smoke build had no Kinect attached. A real short RGB/depth recording,
current udev rule, and `video` group access are still required before claiming
that a new destination host is capture-ready.

### v10/v11 MANO pose-source audit and rejected tool-grip result (2026-07-24)

The user's visual rejection of the v10/v11 hand motion was correct. The v10
inference manifest described its input as raw RGB, but the resolved directory
was actually:

```text
/home/baleine/rgb-depth-uniform/propainter_v44_rgb
```

That sequence has already inpainted the hand. At frame 82 the true RGB visibly
contains all five fingers while v44 contains only a blurred/inpainted forearm;
at frame 231 the true RGB contains a closed hand holding the drawing tool while
v44 again removes the hand. The v9 `inputs/raw_rgb` hard-frame directory also
contains v44-derived files, so v9 remains useful only for geometry/runtime
provenance and must not be treated as validated hand-pose evidence.

The authoritative registered RGB used for the corrected inference is:

```text
/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/raw_clean_links
714/714 valid clean_rgb_*.png links
```

The separately named true-RGB v11 diagnostic branch is:

```text
raw WiLoR-independent HaMeR:
/home/baleine/hand-3d-v7/results/hamer_dense622_v11a_rawrgb

shared MANO shape:
/home/baleine/hand-3d-v7/results/hamer_dense622_v11b_rawrgb_shared_shape

temporal rotation smoothing:
/home/baleine/hand-3d-v7/results/hamer_dense622_v11c_rawrgb_shared_shape_temporal

strict robust RGB-D fusion:
/home/baleine/hand-3d-v7/results/hamer_dense622_v11d_rawrgb_rgbd_robust_skip_invalid

packed meshes:
/home/baleine/hand-3d-v7/results/hamer_dense622_v11e_rawrgb_packed_meshes

local session:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v11_full_mano_rawrgb_rgbd_packed
```

v11 produced 613 valid RGB-D fused meshes plus 9 strictly bracketed temporal
interpolations, for 622 MANO mesh frames on the original 714-frame /
23.767706-second timeline. All 622 packed `MNRB` meshes decoded locally with
778 finite vertices, 4614 in-range indices, and the correct frame suffix.

```text
v11 inference manifest SHA-256:
9a8775801ff69f69fc7d8a2a33e852c56fa43d9117d91402a72c42346d4d03c1

fusion report SHA-256:
00eb1fd1cc9e2418d81694efdd1802290d11866780ff597a7d5d739fa08e363a

packed report SHA-256:
2ef031608210ecc7aec7b7a339d55b2d00d552297d91e5105107c0d2516f93b5

packed archive SHA-256:
893757bb68f625dfa1000681b2106d7fed7d9ecd7b7d8238150f0b54561e00fd

local session.json SHA-256:
81371e784c3b50c58615f4ab2907bfb99914984169c24332a7edd3c30b2d6397
```

`analyze_hamer_2d_track_alignment.py` directly compares each inferred
`joint_uv` with the model-produced crop landmarks and compares consecutive
motion steps. Correcting v44 to true RGB materially improves the result:

```text
                       v10/v44       v11/true RGB
mean joint error       37.91 px      18.07 px
p95 joint error        81.89 px      36.74 px
mean motion error      22.95 px      10.00 px
p95 motion error       63.11 px      25.36 px
```

This numerical improvement does not make v11 acceptable. Browser review of
frame 231 at 7.67 seconds shows that the true RGB contains a closed cylindrical
tool grip while HaMeR still predicts an open hand. Therefore v10 is rejected
because its pose RGB is wrong, and v11 is retained only as a true-RGB
diagnostic because its tool-occluded finger articulation is still wrong.
Neither is the current deliverable hand-motion result.

### WiLoR hard-frame benchmark and rejection (2026-07-24)

WiLoR was tested as a separate, stronger single-image MANO baseline before
authorizing any full-timeline run.

```text
official source:
https://github.com/rolpotamias/WiLoR

commit:
fcb911312a38fa8badd30d9656a167485d61b8f9

source archive SHA-256:
4da26b5de7e879be6bd22b4763938991424b4c6785bbb23d7f837616db0b9c62

Amadeus source:
/home/baleine/hand-3d-v7/WiLoR

detector.pt:
53582271 bytes
5ef3df44e42d2db52d4ffe91f83a22ce9925e2acc9abebf453f2c5d22e380033

wilor_final.ckpt:
2564989533 bytes
3e97aafc7dd08d883a4cc5a027df61fdb6fda6136dbd1319405413862ada6bb2
```

The source and weights were downloaded on the network-capable Windows host,
split and transferred through `jp -> acode`, pulled by Amadeus with parallel
rsync, and hash-checked per part and after reassembly. Nothing was installed on
`acode`. WiLoR uses the user's licensed MANO v1.2 model through this symlink:

```text
/home/baleine/hand-3d-v7/WiLoR/mano_data/MANO_RIGHT.pkl
  -> /home/baleine/hand-3d-v7/mano/MANO_RIGHT.pkl
```

The isolated inference overlay is:

```text
/home/baleine/hand-3d-v7/wilor_overlay
```

It only adds `dill 0.3.8`; CUDA/PyTorch and the already isolated HaMeR
dependencies remain in the existing read-only base/overlay stack.

Reusable crop-based inference:

```text
Godot/tools/infer_wilor_from_track_sidecar.py
```

It uses the model-produced hand track only for crop and handedness. The selected
true RGB, official checkpoint, official WiLoR model, and licensed MANO mesh
supply the pose. No mask or hand-authored pose correction is used.

Hard-frame output:

```text
/home/baleine/hand-3d-v7/results/wilor_hard9_v12_rawrgb_trackcrop_r25
local archive SHA-256:
0c4127950292d3d72da9c55480d2afbf98ff4b976459dbdf1aeae438c0a5a8
```

The 9-frame mean 2D joint error is `16.15 px`; tool-drawing frames average
`10.43 px`. Those numbers do not validate articulation. At frame 231 the raw
RGB shows a compact cylindrical tool grip, while WiLoR still predicts five
fingers spread in an open fan. A second frame-231 run using WiLoR's own official
detector box and official `2.0` rescale factor produces the same open-hand
failure. This rules out the existing crop as the cause.

WiLoR therefore fails the mandatory tool-grip gate and no full WiLoR sequence
was run. Preserve this hard-frame result as a rejected benchmark, not a v12
deliverable.

### OmniHands temporal hard-window benchmark and rejection (2026-07-24)

The final off-the-shelf MANO test used OmniHands' video model so frame 231 could
use temporal evidence instead of being inferred independently. The upstream
repository does not provide a clear top-level license, so this was kept as an
isolated research evaluation and none of its source or weights was integrated
or redistributed in SandStories.

```text
official source:
https://github.com/LinDixuan/OmniHands

commit:
935e1f580975263be799ebf56932e27ab18e1a01

slim evaluation-source archive SHA-256:
d5f9548d2eb94c1ac7b564f90ad502dfc6df1cb12c8c2488d60f9a00cb07db3f

Demo_Video.pth:
3105739730 bytes
67d6640cc5c14dbadb23e2482c849c1abacfa2ad2791d9876d901bdf40212a24

Amadeus source:
/home/baleine/hand-3d-v7/OmniHands_935e1f5
```

The checkpoint was downloaded on the Windows host, split, transferred through
`jp -> acode`, pulled by Amadeus, and verified per part and after reassembly.
Nothing was installed on `acode`; the exact temporary relay directories were
removed after the verified transfers, reclaiming about 5.4 GB. The user's
licensed MANO v1.2 files are referenced by symlink on Amadeus.

Reusable isolated evaluation entry point:

```text
Godot/tools/infer_omnihands_video_from_track.py
SHA-256:
e94894d0a4fffb4d476173341eceab60949f655a5711c3cfde5420a2ae15e630
```

The script uses true Kinect RGB and the standard-model right-hand track only to
choose image crops. Because the official video model expects a left/right pair,
the absent left hand is represented by one constant off-image sentinel. It does
not use a hand-authored mask, pose correction, gesture rule, RGB-D pose edit, or
post-inference vertex smoothing.

The gate run covers frames `181-281`. OmniHands' nine-token temporal input uses
`sequenceGap=10`, so frame 231 receives context at frame indices
`191, 201, 211, 221, 231, 241, 251, 261, 271`.

```text
remote output:
/home/baleine/hand-3d-v7/results/omnihands_window181_281_v13_rawrgb_trackcrop

local output:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\omnihands_window181_281_v13_rawrgb_trackcrop

101-frame output archive SHA-256:
5d01b900c9db2055942fb64ad860978a2e8c4876e16c3c4114777a9463078e96

inference manifest SHA-256:
77ac7fc5193a6e53c376d6f8bcfa7f5c692936d7a46b55f64ca0d626dad39268

alignment report SHA-256:
26d0949f867bde0f04a27711c529dd1f01506cb7782233802fff008d9bfef12f
```

Its 101-frame mean/P95 2D joint errors are `23.61/45.03 px`; mean/P95 motion-step
errors are `15.99/38.32 px`. More importantly, visual review of the saved
frame-231 overlay fails the mandatory semantic gate: the true hand is visibly
closed around the tool, while the predicted MANO hand is still broad, open, and
fanned with the wrong palm extent. Temporal context therefore does not rescue
this sequence under the evaluated official checkpoint/configuration.

No full OmniHands run and no v13 Godot session were produced. Together with the
HaMeR and WiLoR controls, this isolates the main failure to off-the-shelf MANO
pose regression under top-down tool occlusion, not RGB selection, mesh packing,
RGB-D lifting, alpha, depth testing, or playback. Any next 3D attempt must use a
tool/hand interaction objective over a temporal window and pass frame 231 before
full materialization. Do not invent manual masks or hand-authored grip poses to
make that optimization appear successful.

### v16c hand-only MANO inverse-fit + calibrated RGB-D result (2026-07-25)

The user explicitly asked to set the tool interaction aside and first make the
bare-hand motion intelligible. The resulting v16c branch is therefore a
hand-only deliverable, not a claim that the tool-grip failure above has been
solved.

The earlier v10/v11 and WiLoR/OmniHands reviews established an important
distinction:

- The true Kinect RGB is correct.
- Off-the-shelf monocular MANO regressors still hallucinate a broad five-finger
  fan when the top-down image contains a self-occluded fist, claw, or pointing
  pose. Frames 400, 526, and 604 demonstrate that this is not only a
  tool-occlusion problem.
- The measured v7 RGB-D shell follows the visible pixels, but its disconnected
  wrist support and silhouette edge create curtain/comb artifacts and do not
  provide a closed anatomical hand.

v16c uses a low-dimensional inverse fit instead of accepting the regressor's
pose. The inputs and constraints are:

1. True, non-inpainted Kinect RGB:

   ```text
   /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/raw_clean_links
   ```

2. The dense HaMeR result is used for official MANO topology, the shared
   subject shape, and initialization only:

   ```text
   /home/baleine/hand-3d-v7/results/hamer_dense622_v11a_rawrgb
   ```

3. The existing standard-model 21-point hand track supplies per-frame 2D
   observations:

   ```text
   /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_rgbd_presence_dense_v10b.json
   ```

4. The user's licensed MANO v1.2 right-hand model supplies the 778-vertex /
   1538-face hand prior:

   ```text
   /home/baleine/hand-3d-v7/WiLoR/mano_data/MANO_RIGHT.pkl
   ```

5. The already generated registered RGB-D actor support supplies measured
   location and camera-depth evidence:

   ```text
   /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714
   ```

The sequence fitter is:

```text
Godot/tools/fit_mano_hand_only_sequence.py
```

It optimizes a 15-dimensional MANO pose PCA, global orientation, and image-plane
translation against the 21 observed points. One shared MANO shape and one fixed
camera depth are used over the sequence, so the hand cannot change size
frame-by-frame. Consecutive-frame acceleration penalties regularize pose,
orientation, and image-plane translation. The fitted vertices are also
penalized when they leave the existing `virtual_hand_geometry` support. This is
not a new or dilated mask: it consumes the existing model-produced registered
RGB-D support unchanged and does not synthesize any hand pixels.

Only sidecar intents `positioning`, `erasing`, and `drawing` are included.
`tool_drawing` is intentionally excluded. The fitted frame set is:

```text
24-81, 300-621, 629-635, 648-661
401 source frames total
```

The full fitted output is:

```text
/home/baleine/hand-3d-v7/results/mano_hand_only_sequence_full_v1
```

The mean 21-point reprojection error over the 401 frames is `6.483 px`.
The containment term specifically corrects the brief tracker drift at
frames 394-398; for example, supported-vertex ratios improved from
`0.423 -> 0.888` at frame 395 and `0.415 -> 0.837` at frame 396.
The hard visual windows `390-410` and `500-615` were reviewed against raw RGB.
The resulting sequence preserves compact fist/claw states and the extended
index with curled remaining fingers instead of reverting to a uniform
five-finger fan.

The fitted MANO surface is then lifted using:

```text
Godot/tools/fuse_hamer_mano_with_rgbd.py
```

The fusion uses `mano_rigid_offset`: visible registered RGB-D samples select
one robust camera-depth offset for the entire MANO hand in each frame, while
MANO retains a continuous, closed surface. It does not overwrite individual
joints or sculpt a pose from depth. Final calibrated parameters include:

```text
hand clearance:              0.006 m
sand displacement scale:    -5.0
RGB-D anchor bin:            0.010 m
RGB-D anchor radius:         0.030 m
maximum support distance:    12 px
maximum MANO thickness:      0.065 m
world units per meter:       3.0
alignment mode:              none
hand-authored masks:         false
```

The calibrated fusion output is:

```text
/home/baleine/hand-3d-v7/results/mano_hand_only_sequence_full_v2_rgbd_calibrated
```

It contains 396 directly fused meshes. Five early frames, 26-30, lacked enough
visible RGB-D candidates and were skipped rather than accepting an unstable
depth offset. The packer deterministically interpolates those five frames
between valid frames 25 and 31, producing all 401 hand-only meshes:

```text
/home/baleine/hand-3d-v7/results/mano_hand_only_sequence_full_v2_rgbd_calibrated_packed

local:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_hand_only_sequence_full_v2_rgbd_calibrated_packed
```

Fusion QA:

```text
supported-vertex ratio mean / P10 / median / minimum:
0.992593 / 0.982005 / 1.000000 / 0.798200

frames below 0.8 support:
1

frames below 0.5 support:
0

visible rigid RGB-D residual mean / median / P90 / P95 / maximum:
13.24 / 13.60 / 15.62 / 16.18 / 17.81 mm
```

The apparent alpha/depth-test failure had a separate, concrete cause. The
original fusion reconstructed the sand surface in world Y as though its
displacement scale were `1.0`, while the source session and
`sand_depth.gdshader` render with `height_scale = displacement_scale = -5.0`.
The hand and sand were therefore in different Y coordinate systems. This is why
the same opaque hand could be completely buried around frame 358 and visible
later; increasing clearance only hid the bug. The fusion tool now accepts
`--sand-displacement-scale`, applies it when reconstructing surface world Y,
and records it in the report. v16c was regenerated with
`--sand-displacement-scale -5.0`. No alpha workaround is used: the final MANO
material is opaque, depth-writing, and double-sided.

The packed Web session is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v16c_mano_hand_only_rgbd_calibrated
```

It retains the original 714-frame / `23.767706 s` timeline and source
RGB/depth assets, with 401 packed `MNRB` MANO meshes (about 9.4 MB compressed).
Frames in the intentionally excluded tool interval have no virtual hand.

Same-machine review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v16c_mano_hand_only_rgbd_calibrated%2Fsession.json&debug=1&t=mano-hand-only-v16c-skin-20260725&autoplay=0
```

Final Web PCK:

```text
Godot/build/web/index.pck
Godot/build/web/index_v16c_mano_hand_only_rgbd_calibrated.pck
SHA-256: 6aad49094f0af21b672528e5249ece54778c700920f84ef96adeeb81564ff08b
```

Final artifact hashes:

```text
session.json:
bdcf61aa2e763c77892e20a29784a1ae47e499f6cdbd47259fe5c3d9e942c48f

processed_manifest.json:
569a689a18046c0f0629d4c04611eab163031124b87c298cd21cc34f680d3795

mano_rgbd_full_report.json:
6929c3ba5667b45caf4b1338edf8a12d5c46183e1755fac4944bcfdfb6fd7ead
```

Validation completed on 2026-07-25:

- All new Python entry points pass `python -m py_compile`.
- Godot 4.5.1 headless `validate_main.gd` reports
  `Main reconstruction resources loaded`.
- Browser review confirms frame 358 remains visible with the displaced sand
  enabled, frames 401/524 retain compact curled poses, frame 571 retains the
  extended-index pose, and frame 223 has no hand as required.
- Packed playback advances on the original full-duration timeline without the
  earlier unpacked JSON-stream stall.

Current limitation: MANO ends at the wrist and does not model the forearm, so
the hand can look disconnected at the crop boundary. Do not conceal that with a
hand-authored forearm patch. Top-down self-occlusion still means hidden finger
surfaces are model inference; v16c should be described as the accepted
hand-only baseline, not hidden-pose ground truth.

## 2026-07-25 v17h full-hand pass: restored middle interval and rigid RGB-D surface anchoring

The follow-up review found two separate failures in v16c:

1. The apparent long middle dropout was deterministic, not a Web/runtime
   failure. v16c only packed frames `24-81`, `300-621`, `629-635`, and
   `648-661`; the entire `82-299` interval was deliberately excluded because
   its sidecar label is `tool_drawing`.
2. The late "vertical mitten" deformation was only partly a pose-estimation
   problem. `fuse_hamer_mano_with_rgbd.py` added a separately reconstructed
   sand/world-Y value under every MANO vertex. Near the tray boundary, some
   vertices sampled the registered sand surface while other vertices sampled
   unmodelled background. This draped and bent an otherwise rigid MANO mesh.
   Frame 599 was the clearest failure.

The corrected branch does **not** add tool geometry, tool contact, a
tool-specific pose, a hand-authored mask, mask dilation, or shadow processing.
The existing intent label only selects frames. The same generic inverse MANO
fit is used for positioning, erasing, drawing, and tool-drawing observations.

### Confidence-weighted all-intent MANO fit

`fit_mano_hand_only_sequence.py` now:

- includes `positioning,erasing,drawing,tool_drawing` by default;
- weights finger articulation continuously using the standard 21-point track
  confidence and the amount of existing registered RGB-D actor support;
- discounts densified track samples by `0.65`;
- retains a nonzero `0.08` landmark floor;
- applies a weak-evidence first-order pose-continuity term (`0.06`) in addition
  to the existing acceleration priors; and
- records reliability statistics and support-pixel evidence in its report.

`fit_mano_hand_only_2d.py` also contains a local `smplx.MANOLayer` wrapper for
the standard 21-joint OpenPose/MediaPipe order. Reproduction no longer imports
the whole WiLoR package or its unrelated PyTorch Lightning stack.

The completed Amadeus fit is:

```text
/home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17f_reliability
```

Reproduction command:

```bash
cd /home/baleine/hand-3d-v7/tools
PYTHONPATH=/home/baleine/hand-3d-v7/tools:/home/baleine/hand-3d-v7/smplx-0.1.28-py3-none-any.whl:/home/baleine/hand-3d-v7/chumpy_580566e \
/home/baleine/venvs/video-depth-anything/bin/python fit_mano_hand_only_sequence.py \
  --input-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v11a_rawrgb \
  --track-json /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_rgbd_presence_dense_v10b.json \
  --mano-model-path /home/baleine/hand-3d-v7/WiLoR/mano_data/MANO_RIGHT.pkl \
  --rgb-dir /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/raw_clean_links \
  --observed-geometry-dir /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17f_reliability \
  --diagnostic-frames 24,81,82,181,200,220,231,260,299,300,356,400,500,526,575,599,604,610,621,629,635,648,657,661,664
```

Fit QA:

```text
source/output frames: 622
source ranges: 24-621, 629-635, 648-664
mean / P50 / P90 / P95 / maximum 21-point error:
5.031 / 3.998 / 9.481 / 12.060 / 20.294 px

articulation reliability minimum / mean / P10 / P50 / P90 / maximum:
0.131 / 0.689 / 0.404 / 0.683 / 0.955 / 0.999
```

The 25-frame diagnostic contact sheet is:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_hand_all_sequence_full_v17f_reliability\full_diagnostic_contact.png
```

It confirms the restored middle interval contains a compact/closed generic
hand at frame 231 instead of the rejected open-five-finger prior. This is not a
claim that tool contact is solved; the tool is still intentionally ignored.

### Rigid surface-height correction

`fuse_hamer_mano_with_rgbd.py` now accepts `--surface-mask`, defaulting to the
RGB-D session's existing static `surface_mask.png`. Vertices outside this
registered reconstruction support use the nearest valid surface pixel. The
mask is used unchanged; it is not synthesized, extended, or dilated.

For `--lift-fusion-mode mano_rigid_offset`, the full closed MANO mesh now gets
one median visible-inlier surface anchor (`surfaceHeightPolicy =
one_median_visible_inlier_anchor`). A different sand height is no longer added
to every vertex, so the RGB-D stage cannot bend the hand at the tray boundary.
Per-vertex fusion behavior is unchanged for other modes.

The mask copied to Amadeus is:

```text
/home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/surface_mask.png
SHA-256: a09de1f46b3a326cf3c23e81563fff22e0635074828f2529dfebbdb810c8c79f
```

Full fusion command:

```bash
cd /home/baleine/hand-3d-v7/tools
PYTHONPATH=/home/baleine/hand-3d-v7/tools \
/home/baleine/venvs/video-depth-anything/bin/python fuse_hamer_mano_with_rgbd.py \
  --inference-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17f_reliability \
  --rgbd-session /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/processed_manifest.json \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17g2_rgbd_rigid_surface \
  --lift-fusion-mode mano_rigid_offset \
  --alignment-mode none \
  --sand-displacement-scale -5.0 \
  --skip-invalid-frames
```

Fusion QA:

```text
source/directly fused/skipped frames: 622 / 612 / 10
skipped fusion-only ranges: 27-31 and 273-277
supported-vertex ratio mean / P10 / median / minimum:
0.937476 / 0.785347 / 0.998715 / 0.101542
surface-mask direct ratio mean / P10 / median / minimum:
0.959514 / 0.982005 / 1.000000 / 0.003856
visible rigid RGB-D residual mean / median / P90 / P95 / maximum:
13.15 / 13.30 / 15.67 / 16.28 / 18.20 mm
```

The two five-frame fusion-only gaps are bracketed by valid fits and were filled
deterministically by `pack_fused_mano_meshes.py
--maximum-interpolation-gap 16`. The packer deliberately did not bridge the
track's real absence at `622-628` (7 frames) or `636-647` (12 frames).

Packed result:

```text
remote:
/home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17h_rgbd_rigid_surface_packed

local:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_hand_all_sequence_full_v17h_rgbd_rigid_surface_packed

622 MNRB meshes, 13,570,095 compressed bytes
transfer tar SHA-256:
edea6eeb591ef19989a2e9624a49706556ccbbecafc77eb3fe960541ee74290f
```

Final separately named session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v17h_full_hand_rgbd_rigid_surface
714 source frames, 622 MANO meshes, 23.767706 s
```

Same-machine review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v17h_full_hand_rgbd_rigid_surface%2Fsession.json&debug=1&t=mano-full-hand-v17h-rigid-surface-20260725&autoplay=0
```

Final report hashes:

```text
fit mano_hand_only_sequence_report.json:
7359059a45f6d82e616333c8fe7656dc6647578add12f3f8b15f202af656696b

fusion hamer_rgbd_fusion_report.json:
c190cc7649c6fe2150ed806453182a4e489e54354963eb4a76989f1db24bc5e1

packed_mano_mesh_report.json:
ef9aed0b423299eaa283849a41caba9b90e8a414fae8c5af9806f8c0d0c152e2

session.json:
e9d7af19505405cb962b6a6acadcb9accc7a2214e539fd7957d4f330e1ee7112

mano_rgbd_full_report.json:
dfa5c600575165ee45973646fba31590c4b6e42e3c446fc025baf2432e38871e
```

Validation completed on 2026-07-25:

- the five affected Python entry points pass `python -m py_compile`;
- Godot 4.5.1 headless `validate_main.gd` reports
  `Main reconstruction resources loaded`;
- browser checks show the hand present at middle frames 100, 231, and 278;
- frame 599 no longer becomes the vertical depth-draped mitten, and frames 611
  and 655 retain rigid MANO geometry while leaving the tray;
- the final browser log contains zero errors and zero warnings.

v16c remains the accepted bare-hand baseline. v17h is the current all-intent
generic-hand candidate. It restores the middle interval without claiming tool
contact correctness. The two genuine late track gaps remain empty, and MANO
still ends at the wrist.

## 2026-07-25 v18e surface-ROI temporal pass: cut off-tray detections and refit frames 82-299

The user's `82-299` jitter report was reproduced and split into pose/track and
surface-height components with the new deterministic analyzer:

```text
Godot/tools/analyze_mano_temporal_stability.py
```

The analyzer measures consecutive-frame second differences and centered
five-frame high-pass residuals for screen translation, root-relative joint
shape, root-relative MANO vertices, PCA pose, global rotation, and the RGB-D
surface anchor. This avoids counting slow intentional drawing motion as
jitter.

### Root cause and tray cut

The large visible jump was not a sand-height jump. The standard 21-point track
switched at frame `273` from the active hand at approximately
`(444.9, 292.9)` to a bottom-right spectator hand at approximately
`(604.5, 478.8)`, a `245 px` wrist jump. Frames `274-281` were densified from
anchors `273` and `282`, so the one wrong source anchor contaminated nine
frames.

`fit_mano_hand_only_sequence.py` now accepts the existing registered static
surface ROI through `--track-surface-mask`. It does not create or paint a new
mask and does not alter RGB:

- a non-densified detection anchor is rejected when fewer than `20%` of its 21
  standard landmarks are inside `surface_mask.png`;
- any densified sample whose `densifiedFromFrameIndices` references a rejected
  anchor is rejected transitively; and
- only the rejected run's observation targets and initial parameters are
  bracket-interpolated between valid surrounding anchors before optimization.

For frames `82-299`, exactly one real detection anchor was outside the
registered tray ROI: frame `273`, with an inside-landmark ratio of `0.0`.
Automatic provenance propagation therefore repaired exactly frames `273-281`,
bracketed by valid frames `272` and `282`. No other frame in the requested
interval was cut. This is the precise form of "cut outside the tray and
rerun": off-tray detection evidence is removed before the MANO fit without
blacking out the image or inventing a hand/shadow mask.

The unchanged surface ROI is:

```text
/home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/surface_mask.png
SHA-256: a09de1f46b3a326cf3c23e81563fff22e0635074828f2529dfebbdb810c8c79f
```

### Temporal refit

Two additional losses were added to
`Godot/tools/fit_mano_hand_only_sequence.py`:

- representation-independent global rotation-matrix acceleration, avoiding
  axis-angle wrap/flip jitter; and
- projected camera/screen acceleration, reducing high-frequency whole-hand
  translation without freezing slow intended motion.

The refit uses context frames `70-310` but only replaces frames `82-299`. The
original full-sequence MANO betas and shared camera Z are loaded and locked
exactly from v17f, preventing a hand-size or interval-boundary jump. No tool
geometry, contact rule, intent-specific pose, hand-authored mask, mask
extension, or shadow processing is used.

Reproduction command:

```bash
cd /home/baleine/hand-3d-v7/tools
PYTHONPATH=/home/baleine/hand-3d-v7/tools:/home/baleine/hand-3d-v7/smplx-0.1.28-py3-none-any.whl:/home/baleine/hand-3d-v7/chumpy_580566e \
/home/baleine/venvs/video-depth-anything/bin/python fit_mano_hand_only_sequence.py \
  --input-dir /home/baleine/hand-3d-v7/results/hamer_dense622_v11a_rawrgb \
  --track-json /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_rgbd_presence_dense_v10b.json \
  --mano-model-path /home/baleine/hand-3d-v7/WiLoR/mano_data/MANO_RIGHT.pkl \
  --rgb-dir /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/raw_clean_links \
  --observed-geometry-dir /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_sequence_70_310_v18b_surface_roi_temporal_locked \
  --minimum-frame 70 \
  --maximum-frame 310 \
  --iterations 1200 \
  --pose-acceleration-weight 0.02 \
  --pose-velocity-weight 0.12 \
  --orientation-matrix-acceleration-weight 0.03 \
  --camera-screen-acceleration-weight 0.00002 \
  --track-surface-mask /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/surface_mask.png \
  --minimum-track-surface-landmark-ratio 0.2 \
  --shared-parameter-report /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17f_reliability/mano_hand_only_sequence_report.json
```

Selected fit:

```text
/home/baleine/hand-3d-v7/results/mano_hand_sequence_70_310_v18b_surface_roi_temporal_locked
241 context frames, 70-310
mean / P50 / P90 / P95 / maximum 21-point error:
4.657 / 3.743 / 7.236 / 9.238 / 18.642 px
shared camera Z:
19.792165756225586, exactly matching v17f
repaired source interval:
273-281, bracketed by 272 and 282
```

The additive interval merger is:

```text
Godot/tools/merge_mano_fit_interval.py
```

Merge command:

```bash
/home/baleine/venvs/video-depth-anything/bin/python merge_mano_fit_interval.py \
  --base-fit-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17f_reliability \
  --replacement-fit-dir /home/baleine/hand-3d-v7/results/mano_hand_sequence_70_310_v18b_surface_roi_temporal_locked \
  --minimum-frame 82 \
  --maximum-frame 299 \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18c_surface_roi_temporal_merged \
  --asset-mode hardlink
```

The merged sequence contains the original `622` tracked frames. Frames outside
`82-299` remain v17f hardlinks. Boundary audit over `70-310` did not put frame
`82`, `299`, or `300` among the largest acceleration outliers.

### Objective stability result

For the requested `82-299` interval, v18b/v18d compared with v17f/v17g2:

```text
metric                                      v17f       v18       reduction
wrist acceleration mean, px                9.39       4.05      56.9%
wrist acceleration P95, px                25.84      11.34      56.1%
wrist 5-frame high-pass mean, px            3.33       1.68      49.6%
root-relative joint acceleration mean, px   8.49       5.25      38.2%
MANO vertex acceleration mean, mm          17.26       9.64      44.1%
MANO vertex acceleration P95, mm           51.49      26.74      48.1%
global rotation acceleration mean, deg     29.73      12.49      58.0%
```

The surface-anchor audit stayed essentially unchanged:

```text
surface velocity mean:            2.83 -> 2.72 mm/frame
surface acceleration mean:        3.63 -> 3.62 mm/frame^2
surface 5-frame high-pass mean:    1.24 -> 1.20 mm
```

This is evidence that the requested jitter was dominated by 2D association and
MANO pose/orientation variation, not mysterious whole-sand-height motion. No
extra surface-height smoothing was added because that would trade measured
contact for a small metric change without addressing the real failure.

Local audit reports:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v17f_stability_82_299.json
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v18d_stability_82_299.json
```

### RGB-D fusion, packing, and session

Full rigid fusion:

```bash
cd /home/baleine/hand-3d-v7/tools
PYTHONPATH=/home/baleine/hand-3d-v7/tools \
/home/baleine/venvs/video-depth-anything/bin/python fuse_hamer_mano_with_rgbd.py \
  --inference-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18c_surface_roi_temporal_merged \
  --rgbd-session /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/processed_manifest.json \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18d_surface_roi_temporal_rgbd_rigid \
  --lift-fusion-mode mano_rigid_offset \
  --alignment-mode none \
  --sand-displacement-scale -5.0 \
  --skip-invalid-frames
```

Fusion QA:

```text
source/directly fused/skipped frames: 622 / 617 / 5
skipped fusion-only range: 27-31
273-281: all fused directly after the ROI/track repair
```

Packing:

```bash
/home/baleine/venvs/video-depth-anything/bin/python pack_fused_mano_meshes.py \
  --fusion-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18d_surface_roi_temporal_rgbd_rigid \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18e_surface_roi_temporal_rgbd_rigid_packed \
  --maximum-interpolation-gap 16
```

The packer interpolated only fusion-only frames `27-31`, produced `622` MNRB
meshes / `13,625,366` compressed bytes, and preserved the real source-track
gaps `622-628` and `636-647`.

Artifacts:

```text
remote packed:
/home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18e_surface_roi_temporal_rgbd_rigid_packed

local packed:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_hand_all_sequence_full_v18e_surface_roi_temporal_rgbd_rigid_packed

transfer tar SHA-256:
66e9046fdc648b7c3b45cc4cf0c7a33e36e39daea8f74a8e6ae5ebd998a7f731

final separately named session:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v18e_surface_roi_temporal
714 source frames, 622 MANO meshes, 23.767706 s
```

The session reused all `714` RGB frames, all `714` reconstructed-depth frames,
and `surface_mask.png` as the exact same hard-linked files as v17h. No RGB or
depth image was regenerated or changed.

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v18e_surface_roi_temporal%2Fsession.json&debug=1&t=mano-surface-roi-temporal-v18e-20260725&autoplay=0
```

Report hashes:

```text
v18b fit mano_hand_only_sequence_report.json:
4b2961b3702b39f60d5143ba9f8ab30601f67053a92b89211dccc8802aec6249

v18d fusion hamer_rgbd_fusion_report.json:
9c4b6ab5d3ac4e2ac368a57ac764ce6fc1a848243a60c184cc92a525c66ed39b

v18e packed_mano_mesh_report.json:
b6bbc46c6c8604125f4cc508d74519cb4662758d81e5a7f9114cb01fcc9c6063

session.json:
7c6c86f5043ecc7175dd38215449ad69dfd39372bafdeac1b2affc3cd30db0dc

mano_rgbd_full_report.json:
7d400db5cf75ab43ab83b52b5e7aebc99b21f38878a61d0ae08efc7199e9bc3e
```

Validation completed on 2026-07-25:

- the six affected Python entry points pass `python -m py_compile`;
- Godot 4.5.1 headless `validate_main.gd` reports
  `Main reconstruction resources loaded`;
- representative browser checks passed at frames `82`, `148-155`, `197-203`,
  `241-247`, `268`, `273`, `278`, `295`, `298`, and merge boundary `311`;
- a continuous browser playback passed across the requested interval;
- frame `273` now follows the actual tray hand instead of the bottom-right
  spectator, and the repaired `273-281` run remains on the same hand;
- the final browser log contains zero errors and zero warnings.

v18e is now the current generic-hand all-intent candidate. v17h is retained as
the accepted pre-temporal baseline. Tool interaction and shadow removal remain
out of scope, the two genuine late tracking gaps remain empty, and MANO still
ends at the wrist.

## 2026-07-25 v19i: reference-faithful post-300 stabilization

The user accepted the semantic result of v18e and asked for a broad search for
ways to reduce the remaining jitter after frame 300 without redesigning the
hand. v19i is a separately named successor; v18e and every earlier result are
retained.

### Failure diagnosis

The v18 fit and RGB-D fusion were measured separately over frames `300-621`.
The largest visible failures near `397-403` and `507-523` were 3D branch flips:
the top-down 2D palm direction changed smoothly, but the fitted MANO global
rotation sometimes changed by more than 100 degrees in a few frames. This was
not a new hand semantic or keypoint transition.

There was also an independent surface-height failure at the right tray edge.
As the hand left the reconstructed surface, the fraction of vertices sampling
the static tray support fell from `0.929` at frame `609` to `0.298` at frame
`621`. Nearest-support sampling then switched from the sand surface around
world Y `0.095` to a rim/background mode around world Y `0.198`. Therefore
pose/orientation stabilization and surface-anchor validation were treated as
two separate problems.

v18 post-300 baseline:

```text
metric                                  mean      P95       maximum
wrist acceleration, px                  7.519    19.342      38.666
root-relative joint acceleration, px    8.266    23.538      37.399
MANO vertex acceleration, mm           17.896    55.288     138.704
global rotation acceleration, degrees  32.465   131.504     309.289
wrist five-frame high-pass, px          2.572     6.352      11.935
vertex five-frame high-pass, mm         5.699    16.504      42.298
```

Local baseline report:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v18_post300_stability.json
```

### Stabilization experiments

Three pose variants were evaluated rather than selecting by appearance alone:

1. A fresh long-context temporal refit over `290-621` reduced most metrics by
   `30-46%`, but still had `195.1` degree maximum rotation acceleration.
2. A reference-faithful stabilizer initialized from the semantically accepted
   v18c fit and kept bounded fidelity losses to its pose, rotation matrix, and
   screen translation. This was the clear winner.
3. A stricter reference variant was also run; it increased track error and was
   worse than variant 2 on every main stability metric, so it was rejected.

The selected fit tool gained three optional, default-zero terms:

```text
--pose-reference-weight
--orientation-matrix-reference-weight
--camera-screen-reference-weight
```

They preserve the accepted per-frame solution while the existing velocity and
acceleration losses remove high-frequency motion. They do not synthesize
keypoints, masks, intents, contact poses, or tool interaction.

Selected command:

```bash
cd /home/baleine/hand-3d-v7/tools
PYTHONPATH=/home/baleine/hand-3d-v7/tools:/home/baleine/hand-3d-v7/smplx-0.1.28-py3-none-any.whl:/home/baleine/hand-3d-v7/chumpy_580566e \
/home/baleine/venvs/video-depth-anything/bin/python fit_mano_hand_only_sequence.py \
  --input-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18c_surface_roi_temporal_merged \
  --track-json /home/baleine/hand-3d-v7/inputs/hand_tracks_topdown_rgbd_presence_dense_v10b.json \
  --mano-model-path /home/baleine/hand-3d-v7/WiLoR/mano_data/MANO_RIGHT.pkl \
  --rgb-dir /home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/raw_clean_links \
  --observed-geometry-dir /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_sequence_290_621_v19b_reference_stabilized \
  --minimum-frame 290 \
  --maximum-frame 621 \
  --iterations 1200 \
  --pose-acceleration-weight 0.03 \
  --pose-velocity-weight 0.12 \
  --orientation-matrix-acceleration-weight 0.2 \
  --camera-screen-acceleration-weight 0.00003 \
  --pose-reference-weight 0.05 \
  --orientation-matrix-reference-weight 0.02 \
  --camera-screen-reference-weight 0.0002 \
  --shared-parameter-report /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v17f_reliability/mano_hand_only_sequence_report.json
```

The selected fit has `332` context frames, shared camera Z
`19.792165756225586`, and mean / P50 / P90 / P95 / maximum 21-point errors of
`5.777 / 4.622 / 10.110 / 11.478 / 22.197 px`. Its mean error is about
`1.29 px` above the unsmoothed source, while the wrist differs by only
`1.38 px` on average. Critical RGB overlays at `395-403`, `507-523`, and
`609-621` retained the accepted pose semantics.

Selected v19 versus v18 over `300-621`:

```text
metric                                  v18 mean/P95/max       v19 mean/P95/max
wrist acceleration, px                 7.519/19.342/38.666    5.008/13.027/21.652
root-relative joint acceleration, px   8.266/23.538/37.399    4.078/11.429/23.593
MANO vertex acceleration, mm          17.896/55.288/138.704   6.529/16.946/36.764
global rotation acceleration, degrees 32.465/131.504/309.289  7.980/23.114/52.265
wrist five-frame high-pass, px         2.572/6.352/11.935     1.957/4.485/7.760
vertex five-frame high-pass, mm        5.699/16.504/42.298    2.460/5.726/11.558
```

This is a `75.4%` reduction in mean rotation acceleration and an `82.4%`
reduction at P95. Vertex acceleration falls `63.5%` at the mean and `69.3%` at
P95.

Local experiment reports:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v19a_post300_stability.json
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v19b_post300_stability.json
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v19c_post300_stability.json
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_v19b_reference_overlays
```

### Reliable measured surface-anchor policy

The additive tool
`Godot/tools/stabilize_mano_rgbd_surface_anchors.py` operates on an already
fused rigid MANO sequence. A measured anchor is reliable only when:

```text
surfaceMaskDirectVertexRatio >= 0.80
nearest support distance P50 <= 0.50 px
visible RGB-D support vertices >= 20
```

Every reliable measured anchor is left bit-for-bit unchanged. Only unreliable
anchors in `300-621` are interpolated between reliable measured anchors in the
same consecutive source segment, or held from the last reliable anchor at a
segment end. Missing source frames remain missing. The mesh is translated only
along world Y; MANO pose, topology, screen position, normals, RGB, depth, and
surface mask are not changed. No hand-authored mask or synthetic surface mask
is used.

Command:

```bash
/home/baleine/venvs/video-depth-anything/bin/python stabilize_mano_rgbd_surface_anchors.py \
  --fusion-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19f_reference_stabilized_rgbd_rigid \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19g_reference_surface_anchor_stabilized \
  --minimum-frame 300 \
  --maximum-frame 621 \
  --minimum-direct-vertex-ratio 0.80 \
  --maximum-nearest-distance-p50-pixels 0.50 \
  --minimum-visible-supported-vertices 20
```

It corrected only frames `300`, `301`, and `610-621`, `14 / 616` directly
fused frames. Over `300-621`, the absolute surface-anchor acceleration maximum
fell from `201.156` to `22.393` world-Y millimetres per frame squared; the
velocity maximum fell from `106.497` to `20.308`. Frame `609` remains the
measured anchor for the final unreliable edge span, so frames `610-621` no
longer switch to the tray rim/background height mode.

### Merge, fusion, packing, and local materialization

The selected context fit replaces only `300-621`:

```bash
/home/baleine/venvs/video-depth-anything/bin/python merge_mano_fit_interval.py \
  --base-fit-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v18c_surface_roi_temporal_merged \
  --replacement-fit-dir /home/baleine/hand-3d-v7/results/mano_hand_sequence_290_621_v19b_reference_stabilized \
  --minimum-frame 300 \
  --maximum-frame 621 \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19e_reference_stabilized_merged \
  --asset-mode hardlink
```

Rigid RGB-D fusion:

```bash
PYTHONPATH=/home/baleine/hand-3d-v7/tools \
/home/baleine/venvs/video-depth-anything/bin/python fuse_hamer_mano_with_rgbd.py \
  --inference-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19e_reference_stabilized_merged \
  --rgbd-session /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714 \
  --processed-manifest /home/baleine/hand-3d-v7/inputs/rgbd_v7_geometry_full714/processed_manifest.json \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19f_reference_stabilized_rgbd_rigid \
  --lift-fusion-mode mano_rigid_offset \
  --alignment-mode none \
  --sand-displacement-scale -5.0 \
  --skip-invalid-frames
```

Fusion directly produced `616 / 622` source hand frames. Frames `27-31` retain
the known fusion-only startup failure. Frame `585` had `52` visible candidates
but only `19` samples in the winning RGB-D depth mode, one below the existing
minimum of 20. The geometry threshold was not weakened; the deterministic
packer interpolates this single frame from `584` and `586`.

Packing:

```bash
/home/baleine/venvs/video-depth-anything/bin/python pack_fused_mano_meshes.py \
  --fusion-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19g_reference_surface_anchor_stabilized \
  --output-dir /home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19h_reference_surface_anchor_packed \
  --maximum-interpolation-gap 16
```

The pack contains `622` deterministic MNRB meshes and `13,614,018` compressed
bytes. It interpolates fusion-only frames `27-31` and `585`. The genuine source
tracking gaps `622-628` and `636-647` remain empty.

Local materialization:

```powershell
python Godot/tools/materialize_mano_rgbd_full_session.py `
  --source-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v18e_surface_roi_temporal\session.json `
  --packed-mesh-dir ..\tmp\opencode\mano_hand_all_sequence_full_v19h_reference_surface_anchor_packed `
  --output-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v19i_reference_surface_stable `
  --asset-mode hardlink
```

Preservation audit:

- all `714` RGB and `714` reconstructed-depth files are the exact same
  hardlinks as v18e;
- all `300 / 300` available hand meshes outside `300-621` have the same
  deterministic SHA-256 as v18e;
- all `322` meshes in the requested interval are from the selected v19 fit;
- v18e and all intermediate v19 variants remain separately named.

### v19i artifacts and validation

```text
remote selected fit:
/home/baleine/hand-3d-v7/results/mano_hand_sequence_290_621_v19b_reference_stabilized

remote merged fit:
/home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19e_reference_stabilized_merged

remote final fusion:
/home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19g_reference_surface_anchor_stabilized

remote packed meshes:
/home/baleine/hand-3d-v7/results/mano_hand_all_sequence_full_v19h_reference_surface_anchor_packed

local packed meshes:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\mano_hand_all_sequence_full_v19h_reference_surface_anchor_packed

final local session:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v19i_reference_surface_stable
```

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v19i_reference_surface_stable%2Fsession.json&debug=1&t=mano-reference-surface-v19i-20260725&autoplay=0
```

Hashes:

```text
selected v19b fit report:
d2ac5d8572076f9d8ffd1337c14abf18a0b3983b3220adf089799d65fa390719

merged v19e fit report:
b68f8b5968271cbb58d8fc4cbb314dfa34cd8f7d620b16dce193c0bafc68df1a

final v19g fusion report:
04c30410363389c53fe52e0bb9856d6f479ea19199ba93e93e63026fd847b1f2

v19h packed report:
c143b35dd4b05fea5d780c80a2a78932d9cbc198c2561a3fd316a1ad6b82e0e4

transfer tar:
683c8b4a4d1e5202a6a5da3db163ad0ddabadf3d33acd1861fbf6ed975f9fca6

v19i session.json:
09e1b89b1d8ab0c8d2fa668c478fc8b3c21a6c5ba3c3975ba76b0046f98f1229

v19i mano_rgbd_full_report.json:
4a44821374ab6142f4170549a7525d307026f0bb1f871c3bef7048660859ffde

fit_mano_hand_only_sequence.py:
55f90417c10d9ea9df3b5d5de9215c7790b9505710ec5c383b22e701ff49e46f

stabilize_mano_rgbd_surface_anchors.py:
c83ca7cc15c83519603fc3acd0b48ad06d2bceead4f19ca425a04bac818b3494
```

Browser QA passed the merge boundary `299-301`, the previous branch-flip
ranges `397-403` and `507-523`, the interpolated frame `584-586`, and the edge
anchor range `609-621`. Continuous playback passed from frame `300` through
the repaired interval and across the preserved first real tracking gap. The
browser log contains zero errors and zero warnings.

v19i is the retained generic-hand geometry/motion baseline. Tool interaction,
shadow removal, a wrist/arm extension, and filling genuine tracking gaps remain
out of scope.

## 2026-07-25 v20a: soft-peach opaque hand material

The user accepted v19i motion and geometry, then requested a better-looking
hand color. The dull brown appearance was traced to the fixed
`StandardMaterial3D` in `main.gd`: albedo `#dfad98`, emission `#c98570`, and a
green-grey world ambient light. Because the MANO mesh is double-sided, lighting
the visible back-facing normals could darken the fixed salmon color further.
No RGB image, hand mesh, pose, or RGB-D anchor was wrong.

### Selected material

`Godot/assets/shaders/mano_hand_beauty.gdshader` is a dedicated opaque MANO
shader. It:

- uses world-space normal shaping with explicit back-face normal correction;
- mixes a soft peach base, rose shadow, cream highlight, and a restrained
  warm rim;
- is deterministic and does not sample or alter the displayed RGB;
- stays fully opaque, double-sided, and depth-writing;
- adds no alpha prepass, transparency, texture synthesis, or geometry change.

The selected v20a palette is:

```text
base:              #f3b49e
shadow:            #b96f67
highlight:         #ffe2d1
rim:               #ffede2
rim strength:      0.32
emission strength: 0.035
roughness:         0.72
```

A second preserved comparison,
`session_kinect_20260623_154953_virtual_hand_v20b_warm_ivory_rose`, used a
more muted ivory/grey-rose palette. Browser comparison rejected it because it
blended into the pale sand and reduced silhouette readability. v20a retained
the softer skin appearance while remaining clearly separated from the tray.

### Runtime and materialization

`main.gd` now selects the new shader only when
`mano_rgbd_full_sequence.materialPreset` equals
`soft_peach_porcelain_v1`. Older sessions without that preset continue to use
their original material. `materialize_mano_rgbd_full_session.py` gained
material-preset and palette arguments, so the appearance is recorded in the
session and reproducible instead of being a global hard-coded replacement.

Materialization command:

```powershell
python Godot/tools/materialize_mano_rgbd_full_session.py `
  --source-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v19i_reference_surface_stable\session.json `
  --packed-mesh-dir ..\tmp\opencode\mano_hand_all_sequence_full_v19h_reference_surface_anchor_packed `
  --output-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v20a_soft_peach `
  --asset-mode hardlink `
  --mano-material-preset soft_peach_porcelain_v1
```

Preservation audit:

```text
RGB hardlinks shared with v19i:      714 / 714
depth hardlinks shared with v19i:    714 / 714
identical MANO mesh SHA-256 values:  622 / 622
geometry, motion, and anchor changes: none
```

The first rebuilt Web package also exposed an unrelated current-source
compatibility bug in the optional reference-view UI:
`SubViewport.camera_3d = view_camera` is invalid in Godot 4.5 Web. It was
replaced with the supported `view_camera.current = true`. This changes no
reconstruction or hand data and restores clean startup with the current source
tree.

Final artifacts:

```text
session:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v20a_soft_peach

Web PCK:
Godot\build\web\index_v20a_soft_peach.pck

session.json:
1bdf05494657e16f8ebd85fcd05b74bbd217cc40f020f8eaf666ddd6facfc8f8

processed_manifest.json:
a6d316c266cd1a00a565901bf965f068e53fb48c60b6105fb39aa983e6b0fada

mano_rgbd_full_report.json:
b5ae93afd1dcad8cb2a1e6bf4f5d14e38f1cb61dbd8d86a729b243d6018d2484

index_v20a_soft_peach.pck:
80ad01bb215ba39cc0679cbcdec95e399a7f222b78505ae8da53ea131fc070ec

mano_hand_beauty.gdshader:
dc491e432a4b907e6f73aeba2cd4f2c38efb8b15ff565f9d659c0a975e2ede47
```

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v20a_soft_peach%2Fsession.json&debug=1&t=mano-soft-peach-v20a-final-20260725&autoplay=0
```

Validation passed native Godot startup, headless resource loading, and browser
checks at frames `358`, `396`, `509-515`, `584`, plus continuous playback
through `358-430`. The new browser run contains zero errors and zero warnings.
The hand remains visible with sand depth enabled at frame `358`, confirming
that the opaque material did not regress the earlier depth/alpha correction.

### v20d cerulean-blue follow-up

At user request, the same opaque shader was recolored without another PCK,
mesh, RGB, depth, or geometry change. The final blue palette is:

```text
base:              #58a9e6
shadow:            #245783
highlight:         #cdefff
rim:               #f0fbff
rim strength:      0.36
emission strength: 0.04
roughness:         0.68
```

Exact materialization command:

```powershell
python Godot/tools/materialize_mano_rgbd_full_session.py `
  --source-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v19i_reference_surface_stable\session.json `
  --packed-mesh-dir ..\tmp\opencode\mano_hand_all_sequence_full_v19h_reference_surface_anchor_packed `
  --output-session ..\tmp\opencode\session_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final `
  --asset-mode hardlink `
  --mano-material-preset soft_peach_porcelain_v1 `
  --mano-base-color "#58a9e6" `
  --mano-shadow-color "#245783" `
  --mano-highlight-color "#cdefff" `
  --mano-rim-color "#f0fbff" `
  --mano-rim-strength 0.36 `
  --mano-emission-strength 0.04 `
  --mano-roughness 0.68
```

The historical preset identifier remains `soft_peach_porcelain_v1` because it
selects the already-exported opaque porcelain shader implementation, not a
hard-coded palette. All actual colors are session parameters. The human-readable
material description was made color-neutral
(`opaque session-colored porcelain hand shader`) so blue sessions do not
incorrectly identify themselves as soft peach.

Runtime path:

1. `materialize_mano_rgbd_full_session.py` hard-links the exact v19i
   `cleanRgb`, `cleanDepth`, surface mask, and packed MNRB mesh files.
2. It writes `materialPreset` plus `materialParameters` into
   `session.json`; the mesh binaries are not repacked.
3. `main.gd::_build_mano_hand_surface()` calls
   `_mano_hand_surface_material()`.
4. That function loads `mano_hand_beauty.gdshader`, passes the seven recorded
   palette/finish parameters, and assigns the resulting `ShaderMaterial` to the
   unchanged MANO `MeshInstance3D`.
5. The shader corrects the normal sign for visible back faces, computes a
   wrapped world-space key light and view rim, then writes opaque albedo,
   emission, roughness, and specular values. It uses no texture, alpha blend,
   skeleton change, or depth displacement.

The active Web package is the same package validated for v20a because v20d is
data-driven:

```text
Godot\build\web\index.pck
Godot\build\web\index_v20a_soft_peach.pck
SHA-256:
80ad01bb215ba39cc0679cbcdec95e399a7f222b78505ae8da53ea131fc070ec
```

Preservation and validation:

```text
RGB hardlinks shared with v19i:      714 / 714
depth hardlinks shared with v19i:    714 / 714
identical MANO mesh SHA-256 values:  622 / 622
browser errors / warnings:           0 / 0

session.json:
83130b4d66010bbb4831e25c2a167727cdc65564c5c4685e22426d3287b57ff5

processed_manifest.json:
d82da284913dc247867424eaeea0275bc7ec1266f0386d8add5287ff38a91eab

mano_rgbd_full_report.json:
66968fce450723efbecb1b9940db8649768a325490f9614077f0e714ccb2e4a5
```

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final%2Fsession.json&debug=1&t=mano-cerulean-blue-v20d-final-20260725&autoplay=0
```

The user accepted v20d for temporary retention on 2026-07-25. Treat the v20d
session as immutable: do not overwrite it or silently change its palette.
Create a separately named session for any later appearance experiment. v20a
remains the retained warm-color comparison and v19i remains the exact
geometry/motion baseline.

## v21a Proposal-Aligned Experiment Runner (2026-07-25)

### Source and scope

This iteration was derived from:

```text
C:\Users\lj200\Downloads\JINGLI_MasterResearchProposal_SandStories (1).pdf
Digitising Sand Stories: Multimodal Visualisation of Community Spatial Knowledge
```

The PDF's full methodology and the rendered methodology pages were checked,
not inferred from the old `Study Probe` UI. v21a changes the Godot experiment
runtime and Web package. It does **not** regenerate or overwrite the accepted
v20d session, its cerulean-blue material, any RGB/depth frame, or any MANO
mesh.

Proposal-to-runtime mapping:

| Proposal element | v21a implementation |
| --- | --- |
| RQ1 modality contribution | Stage 1 baseline plus `no_audio`, `no_gestures`, `no_objects`, and `no_sand` |
| Online between-subjects Stage 1, target 100 | Anonymous participant code and deterministic five-condition assignment; fixed `condition` is QA-only |
| Complete-representation training before condition | Three-item gated training checklist; ablation is applied/revealed only on `Begin main task` |
| No fixed views in Stage 1 | Reference-view button/panes are hidden and their SubViewports remain disabled |
| Interpretation completeness | Participant summary, MCQ/short comprehension questions, and evidence text |
| Link answers to evidence | `Mark current 3D view` captures playhead, camera pose/target, and active layers per question |
| Confidence/difficulty/modality reliance | 1-7 ratings and modality-reliance checklist |
| NASA-TLX | Six raw 0-100 dimensions: mental, physical, temporal, performance, effort, frustration |
| In-person within-subject Stage 2, 3-4 experts/practitioners/non-experts | Stage 2 group covariate, full modality/annotation mode, dedicated training, usefulness rating, observer and interview notes |
| RQ2 cross-modal links | Stage 2 enables session annotation events, surface regions, and referential links |
| Fidelity gates | Readiness audit checks real sand, gestures, objects, audio, annotations, and creator-validated experiment content |

Think-aloud instructions and the physical observer procedure remain human study
protocol responsibilities; the runtime stores observer/interview notes but
does not pretend it can enforce think-aloud behaviour.

### Participant workflow

The new `scripts/experiment_runner.gd` presents six phases:

1. study information, voluntary anonymous participation, consent checkbox, and
   visible readiness/pilot warning;
2. anonymous participant code plus age range, sand-drawing experience,
   multimodal-analysis experience, and the Stage 2 cohort when applicable;
3. gated interface training on the complete representation;
4. interpretation summary, comprehension responses, evidence explanations,
   and per-question 3D evidence snapshots;
5. ease/confidence/difficulty, modalities relied on, raw NASA-TLX, plus Stage 2
   annotation usefulness/observer/interview fields;
6. a completion summary and anonymous JSON export.

The Web entry points are:

```text
index.html?study=pilot&participant=qa001
index.html?study=stage1&participant=p001
index.html?study=stage1&participant=p001&condition=no_gestures
index.html?study=stage2&participant=p201
```

`pilot` is forced to baseline and visibly says the result must not be treated
as research data. These direct `index.html` entry points retain the original
stable client-hash fallback for native/standalone use. The standard
`experiment_host.html` path now creates a server run and uses randomized
balanced blocks of five; formal Web recruitment must use that host rather than
the direct Godot runner.

Stage 1 modality integrity is enforced rather than merely suggested:

- the omitted layer is hidden;
- its participant toggle is disabled;
- annotations are locked;
- fixed reference views are unavailable;
- `no_audio` also stops/mutes actual narration playback;
- all remaining modalities stay on the shared playhead.

The training phase temporarily requests `baseline`, regardless of the
participant's future Stage 1 assignment. Browser QA initially found that the
Web query parser had applied `condition=no_gestures` during consent. `_ready()`
now resets Stage 1/pilot to baseline after parsing launch parameters; the
runner retains the future assignment and requests it only when training is
complete. This prevents an allocation-revealing training/consent leak.

### Session contract and collected package

`data/session_schema.json` now accepts an optional `experiment` object:

```text
protocolId
readyForDataCollection
readinessNotes
summaryPrompt
stage1Questions
stage2Questions
```

Questions may be multiple choice or short response and include a separate
evidence prompt. If a historical session has no `experiment` object, the
runner can display its `study_tasks` as a pilot fallback, but that fallback does
not make the session research-ready.

`data_sources.audio` now loads synchronized local Godot audio resources or
remote OGG/MP3 bytes through an `AudioStreamPlayer`. Missing audio is reported
honestly and disables the narration toggle; the runtime never simulates an
audio modality.

The final package contains:

```text
protocol/stage/condition/run/session identifiers
readyForDataCollection plus readiness warnings
anonymous participant covariates
summary, comprehension, and evidence responses
marked timestamps/camera/layers
Likert and raw NASA-TLX responses
Stage 2 usefulness/observer/interview fields
phase durations and completion time
runtime build/session path
all in-memory interaction events for the run
```

Native runs write to:

```text
user://experiment_submissions/<run-id>.json
```

Web host runs now autosave the same anonymous package to the experiment server,
with retry and refresh recovery. The base64-safe browser download remains a
manual backup. No name, email, or other direct identifier is requested.

### Data-readiness boundary

The sample session contains representative questions only to validate the
interface and is explicitly `readyForDataCollection=false`. The accepted v20d
session contains the visual hand/sand sequence but does not contain all
proposal modalities or validated experimental ground truth. The runner
therefore reports the missing modalities/content and also sets
`readyForDataCollection=false`.

Do not start formal recruitment until all of the following exist:

1. real synchronized narration audio;
2. complete object/tool observations matching the story;
3. creator/community-validated interpretations, questions, answer keys, and
   evidence expectations;
4. final ethics-approved participant information and consent wording;
5. an approved production deployment, access, retention, and backup policy for
   the existing experiment persistence service;
6. Stage 2 session ordering/counterbalancing and the finalized observer guide;
7. a pilot proving all five conditions and the Stage 2 annotation path on the
   actual study session.

This boundary is intentional: v21a is a valid experiment *runner*, not a claim
that the current demonstration content is valid research material.

### Related runtime reliability fixes

Proposal work exercised code paths that the old manual Study Probe did not.
The same v21a runtime therefore also:

- uses a session-load generation token so stale remote HTTP responses cannot
  overwrite a newer session;
- frees old video players and creates them only for explicitly declared
  streams, instead of decoding hidden fallback videos;
- leaves the two fixed-view SubViewports at `UPDATE_DISABLED` unless their
  panel is actually visible;
- synchronizes real audio to play/pause/seek/end-of-session state;
- restarts playback cleanly after reaching the end;
- hardens `tools/static_server.mjs` against encoded path traversal,
  directory-stream crashes, unsupported methods, and stream errors;
- replaces the stale reconstruction smoke test with checks against the current
  runtime and conditions.

### Files and preserved Web packages

Primary v21a files:

```text
Godot\scripts\experiment_runner.gd
Godot\scripts\main.gd
Godot\data\experiment_protocol.json
Godot\data\sample_session\session.json
Godot\data\session_schema.json
Godot\tools\validate_experiment_runner.gd
Godot\tools\smoke_reconstruction.gd
Godot\tools\static_server.mjs
Godot\README.md
```

The previously accepted runtime was archived before activating v21a:

```text
Godot\build\web\index_v20d_cerulean_blue_final.pck
bytes:   44,883,964
SHA-256:
80ad01bb215ba39cc0679cbcdec95e399a7f222b78505ae8da53ea131fc070ec
```

The proposal-runner runtime is separately archived:

```text
Godot\build\web\index.pck
Godot\build\web\index_v21a_proposal_experiment_runner.pck
bytes:   44,922,472
SHA-256:
9ba50de5dd5b972330fd44169cc8c8831151d6599c81c169f7378a9dbba7d499
```

Do not replace the v20d archive. v20d names the accepted visual/session
baseline; v21a names the newer experiment runtime.

### Validation

Completed validation for v21a:

```text
all 9 GDScript files: Godot 4.5.1 --check-only passed
tools/validate_main.gd: passed
tools/smoke_reconstruction.gd: passed
tools/unicode_font_check.gd: passed
tools/validate_experiment_runner.gd: passed
38/38 local session JSON files: Draft 2020-12 schema passed
Godot/tools Python compileall: passed
static server: directory 404, encoded traversal 403, HEAD 200, server survived
Web build: completed successfully
```

Browser checks used the actual exported PCK, not the native editor:

```text
pilot consent/readiness screen: rendered
Stage 1 consent/profile/training: complete representation retained
Stage 1 no_gestures main task: condition revealed only after training
gesture layer: hidden and toggle locked in the main task
interpretation/MCQ/evidence UI: rendered
browser console errors/warnings: 0 / 0
```

QA URL for the fixed condition path:

```text
http://localhost:8845/index.html?study=stage1&participant=qa-no-gestures&condition=no_gestures&debug=1&t=proposal-v21a-training-fix-20260725
```

## Godot Project Review (2026-07-25)

The review covered the complete non-generated `Godot/` project: configuration,
scenes, the 4,054-line runtime, seven GDScript files, seven spatial shaders,
44 Python tools, Web export/serving, the session schema, and current validation
scripts. This was a diagnostic review; the open issues below were not silently
fixed as part of retaining v20d. The later v21a experiment-runtime work fixed
findings 2-6. Findings 1 and 7 remain open.

Prioritized open findings:

1. **OPEN:** `tools/prepare_production_session.py` constructs its destructive v2 output
   path directly from manifest `sessionId`, then recursively deletes the
   resolved directory if it exists. A value such as `x/../../../../docs`
   escapes `assets/processed_sessions`; validate the identifier and verify the
   resolved output remains beneath the intended root before `shutil.rmtree`.
2. **FIXED IN v21a:** `scripts/main.gd` created both fixed-reference `SubViewport`s with
   `UPDATE_ALWAYS` even while their panel is hidden. The default Web view
   therefore renders the full 3D world two extra times per frame. Disable the
   viewports until reference views are visible.
3. **FIXED IN v21a:** Every session build created, autoplayed, looped, and started two hidden fallback
   OGV players even when `use_video_streams` is false. The players are children
   of the root rather than a cleared layer, so session changes orphan the old
   players and only the newest pair can be paused. Create them only when
   required and stop/free the previous pair before rebuilding.
4. **FIXED IN v21a:** Remote session loading had no generation/cancellation token. The session
   selector starts `_load_session` without awaiting it, while the loader mutates
   global session/frame/cache state across several awaits. Rapid selections or
   a selection during URL-session startup can let an older response overwrite
   or mix with the newer session.
5. **FIXED IN v21a:** `tools/static_server.mjs` used a string-prefix path containment check, which
   accepts an encoded traversal into a same-prefix sibling directory. It also
   streams directories without checking `stats.isFile()` or handling stream
   errors; an isolated loopback request for an existing directory terminated
   the server with exit code 1. This matters because the production-adapter
   document recommends binding it to `0.0.0.0`.
6. **FIXED IN v21a:** `tools/smoke_reconstruction.gd` was stale: it accessed removed
   `heightmap_wire_node`, `_set_reconstruction_display_mode`, and
   `_on_reconstruction_method_selected` APIs. A real headless run raises at
   line 15 and otherwise never reaches `quit`. The MANO preview validator also
   does not assign its parsed session to the runtime and therefore never tests
   the current session-selected beauty shader.
7. **OPEN:** Web build and ML reproduction remain workstation-specific:
   `build_web.ps1` and `export_presets.cfg` contain absolute user paths, the
   fixed temp directory is unsafe for concurrent builds, and
   `requirements-ml.txt` omits currently imported `smplx`, `einops`, and
   `matplotlib` while leaving all dependencies unpinned. Several README/example
   commands still refer to the obsolete `SandStoriesGodot` directory.

Validation evidence:

- v20d and v19i have the same hard-linked `714` RGB files, `714` depth files,
  and `622` MANO meshes; there were zero name or file-identity mismatches.
- v20d session, processed-manifest, and report SHA-256 values match those
  recorded above.
- All seven GDScript files pass Godot 4.5.1 `--check-only`.
- `validate_main.gd`, the main scene startup, and `unicode_font_check.gd` pass.
- All 44 Python tools pass `compileall`.
- All 38 locally discoverable session files pass the Draft 2020-12 session
  schema.
- The repository's two existing Python `unittest` cases pass.
- Historical note: `smoke_reconstruction.gd` was the one confirmed
  failing/hanging v20d validation. It was rewritten and passes in v21a; see the
  v21a validation block above.

## v20d Shadow-Removal / Video-Inpainting Investigation (2026-07-27)

### Scope and preservation gate

The user explicitly resumed shadow-removal research after accepting v20d.
This supersedes the older note that shadows were out of scope, but it does
**not** authorize a hand-authored shadow mask or an arbitrary image-position /
frame-range cleanup rule.

The accepted v20d session remains immutable:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\
session_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final
```

All work below used separately named probe directories. No RGB, depth, MANO
mesh, session JSON, Web PCK, or material in v20d was overwritten. The initial
deterministic/inpainting candidates all failed at least one visual fidelity
gate; the later Casper result was published only as the bounded,
non-production v21b RGB-display review session documented below.

All masks used below were generated from standard-model or captured evidence:

- ShadowSAM probability;
- Grounded-SAM-2 actor support;
- the unchanged registered sand `surface_mask.png`;
- multi-scale photometric radiance deficit;
- reconstructed-depth relief protection; and
- automatic actor-free prefix/suffix controls.

There was no manually painted mask, fixed shadow polygon, skin-colour rule,
hand-position rule, selected cleanup frame interval, or manually selected
temporal reference frame.

### Research conclusion before implementation

The task looks superficially like video inpainting, but the observed shadow is
not a missing-object hole. Most of its pixels still contain useful sand texture
under a low-frequency, coloured, multiplicative illumination field. Treating
all those pixels as absent discards evidence that should be preserved.

The directly relevant research split is:

1. **content completion / object removal**, including ProPainter,
   DiffuEraser, VideoPainter, EffectErase, VOID, and SVOR; and
2. **video shadow removal / illumination decomposition**, including PSTNet
   and the May-2026 Open-VSRD diffusion work.

Useful primary references:

```text
https://github.com/sczhou/ProPainter
https://github.com/lixiaowen-xw/DiffuEraser
https://github.com/FudanCVL/EffectErase
https://github.com/netflix/void-model
https://github.com/TencentARC/VideoPainter
https://arxiv.org/abs/2303.09370
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6827464
https://github.com/city-cheng/DTTNet
```

PSTNet is specifically a physical/spatial/temporal video-shadow remover, but
there is no public implementation/checkpoint. Open-VSRD is even closer and
uses alternating bidirectional diffusion plus a temporal VAE, but its May-2026
paper says the dataset/code will be released; they were not public during this
investigation. DTTNet is a video **shadow detector**, not a remover.

EffectErase is the most practical current model explicitly trained to remove
object side effects such as shadows and reflections. DiffuEraser is the most
practical currently reproducible general video inpainter that explicitly
blends generated pixels back through a blurred mask and uses ProPainter as a
weak prior. Both were therefore run rather than judged only from papers.

### Automatic ShadowSAM + photometric + depth matte

The reusable fusion implementation is:

```text
Godot\tools\fuse_shadowsam_depth_photometric.py
SHA-256:
7150583c561c5aeed836273dcddf491fae9d4025bb852947ace4ced5a76d8fc2
```

Its selected probe settings were:

```text
spatial sigma:        6.0
closing size:         129
deficit threshold:    0.045
deficit softness:     0.13
model threshold:      0.32
model softness:       0.42
maximum scalar gain:  1.70
depth protection:     0.82
```

The 61-frame automatic result/mattes are on Amadeus:

```text
/home/baleine/shadow-v21/shadowsam_surface_clip052_112_20260727a
/home/baleine/shadow-v21/shadowsam_depth_controls_clip052_112_20260727a
```

ShadowSAM alone was not a usable mask: its raw high-probability output also
selected the tray border, existing grooves, and many real dark sand features.
The fused matte was substantially safer, but its precision/recall tradeoff
still matters: a narrow threshold leaves the penumbra, while expansion begins
to consume real relief.

### Rejected deterministic / learned relighting probes

`remove_cast_shadows_depth_temporal.py` tested a fixed-camera temporal upper
envelope with reconstructed-depth agreement. It either missed the hard shadow
or responded to legitimate evolving sand relief, depending on thresholds.

`run_shadowrefiner.py` tested official mask-free ShadowRefiner. It changed
global dark appearance but did not remove the central hard shadow reliably.

`train_rgbd_sand_shadow_remover.py` trains a positive log-illumination-gain
U-Net from synthetic RGB-D shadow augmentation. It cannot redraw texture. The
full 4,000-step Amadeus run produced:

```text
/home/baleine/shadow-v21/rgbd_gain_unet_v21e_20260727a/checkpoint_best.pt
best synthetic validation PSNR: 33.9706 dB
checkpoint size:                approximately 30 MB
```

Automatic 95th-percentile prefix/suffix control calibration made controls
`f0`, `f20`, `f665`, and `f713` exactly unchanged. The model correctly
localized the central shadow, but scalar gain could not recover the hard core
or its colour: strength 1 left a dark core; strength 2 produced an
over-bright/magenta patch. This is evidence that deep umbra has insufficient
captured RGB signal for gain-only recovery.

The fusion tool now has an optional `--chromatic-gain` mode and
`--frame-numbers` probe filter. A four-frame RGB low-frequency correction at
maximum gain 2.4 / strength 1.15 preserved texture but amplified the hard core
into pink-purple noise. It was rejected.

### ProPainter video-inpainting probes

Clip preparation is reproducible with:

```text
Godot\tools\prepare_propainter_shadow_clip.py
SHA-256:
817472ac070d43d069e79cc23aa7f122dd7ac5cad3680d894e93c6f2a2cf3676
```

Direct 61-frame fused-matte input/output:

```text
/home/baleine/shadow-v21/propainter_shadow_clip052_112_input_20260727a
/home/baleine/shadow-v21/propainter_shadow_clip052_112_output_20260727b
```

A second hybrid used mild calibrated RGB-D relighting followed by ProPainter
only on the remaining high-gain core:

```text
/home/baleine/shadow-v21/propainter_hybrid_clip000_112_input_t040
/home/baleine/shadow-v21/propainter_hybrid_clip000_112_output_t040
/home/baleine/shadow-v21/propainter_hybrid_clip000_112_input_t050
/home/baleine/shadow-v21/propainter_hybrid_clip000_112_output_t050
```

Both paths replaced the shadow with a grey/blurry smear while retaining parts
of the shadow. ProPainter propagation is useful for missing objects, but it
destroyed still-valid dark sand texture here. Both were rejected.

### Official EffectErase reproduction and result

Official source and model provenance:

```text
repo:
/home/baleine/shadow-v21/EffectErase
commit:
bcee0a5da5ef387c2ba39390dc4d579503669fb8

isolated environment:
/home/baleine/venvs/effecterase

EffectErase.ckpt:
1,438,679,011 bytes
SHA-256:
4e9ace4607a348a0d820328f827f7f4f751a0e44d4cf60665c03e9740dfa024d

base:
alibaba-pai/Wan2.1-Fun-1.3B-InP
```

The official example forgot to forward its CLI `num_frames` value to
`WanRemovePipeline`. A 21-frame input was VAE-encoded to six latent frames,
while the pipeline silently created default 81-frame / 21-latent-frame noise,
then failed at `torch.cat`. The retained, minimal fix only forwards
`num_frames=args.num_frames`:

```text
Godot\tools\effecterase_infer_remove_wan.py
SHA-256:
454e7de0484aeecd64864ba16d05ec2f6817f8f970873eff98b3f5b8b23ee766
```

The corrected official 21-frame / 50-step / `640x480` run:

```text
source frames: 64-84
hard test:     source frame 82 = output frame 18
runtime:       377.03 seconds
GPU:           one RTX 2080 Ti 22 GB

remote:
/home/baleine/shadow-v21/effecterase_shadow_clip064_084/
output_effecterase_50step.mp4

local:
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\shadow_analysis\
effecterase_clip064_084\output_effecterase_50step.mp4

output SHA-256:
69a778d0724725359b067aff828b5f5957271f756d1c4943a21d7e9249c91dce
```

EffectErase removed the central hard shadow, but regenerated the **entire**
sand surface with different grooves, texture, and brightness. Compositing only
its generated pixels through Gaussian-feathered fused mattes (sigma 2, 5, and
9) or a 12-pixel dilation kept v20d outside the matte but created a visibly
different grey sand patch and/or left a dark fringe. It was rejected both as a
direct output and as a local patch source. The official code/license should
also be treated as non-commercial (`CC BY-NC 4.0`).

### Official DiffuEraser reproduction and result

The repository's normal clone failed through the Amadeus HTTP/2 proxy, so the
official `master` archive was downloaded instead:

```text
/home/baleine/shadow-v21/DiffuEraser-master.tar.gz
SHA-256:
4ccff4c03924d2aa5859d727ff418d9daef7a5dbbd56639ee80d32242f53b935
```

Weights were fetched with pinned Hugging Face revisions:

```text
lixiaowen/diffuEraser
ad510dca07fa8e155d4bd8d002085bb8ec8f60e5

stable-diffusion-v1-5/stable-diffusion-v1-5
451f4fe16113bff5a5d2269ed5ad43b0592e9a14

stabilityai/sd-vae-ft-mse
31f26fdeee1355a5c34592e401dd41e45d25a493

wangfuyun/PCM_Weights
39560fead4ce00f94db3cb8e93dd8fba90ec0be6
```

Download/bootstrap files:

```text
Godot\tools\download_diffueraser_models_amadeus.sh
SHA-256:
bbc0471d918458eec910f55cf9230e8b59929b7adf025144445507cb2ec4f51b

Godot\tools\requirements_diffueraser_reuse_torch.txt
SHA-256:
a25cecb1000d624bff8e24e77647fecc94e5e86ae19cd13e328c0d799c1276bf

Godot\tools\effecterase_site_packages.pth
SHA-256:
1abca4a943278ba57d0630aa18f19ec86ad1791fc8ab82151596e020295f50f0
```

Runtime:

```text
source:
/home/baleine/shadow-v21/DiffuEraser

isolated app environment:
/home/baleine/venvs/diffueraser

Torch/CUDA inherited read-only from the separate EffectErase environment:
torch 2.5.1+cu121, torchvision 0.20.1+cu121

DiffuEraser-local:
diffusers 0.29.2, transformers 4.41.1, peft 0.13.2,
OpenCV 4.9.0, NumPy 1.26.4
```

The exact official Torch 2.3.1 duplicate download was deliberately stopped
after compatibility/import tests passed against Torch 2.5.1. No package was
installed on acode. Amadeus retained approximately 242 GB free before this
11-GiB model download.

The first 60-frame, two-step PCM run used source frames `52-111`, automatic
fused matte threshold `0.05`, internal mask dilation `4`, and `640x480`:

```text
remote:
/home/baleine/shadow-v21/diffueraser_shadow_clip052_111_d4_20260727a/
diffueraser_result.mp4

runtime:
63.1271 seconds

local SHA-256:
b0666dd3888896dca4e3448d1ff3e78d5676c43413ba23b4ba2a6d0354d2f3b5
```

The second controlled run changed only the automatic matte threshold to
`0.40`, retaining dilation `4`:

```text
remote:
/home/baleine/shadow-v21/
diffueraser_shadow_clip052_111_core040_d4_20260727a/
diffueraser_result.mp4

runtime:
62.5905 seconds

local SHA-256:
c75dc2bf1e4f66f26629e512d897079c8dc47a73dd443e478bf50adebaA98fda
```

Both runs preserved most unmasked content, but generated a bright white spot
inside the frame-82 hard-shadow core while leaving a dark penumbra. Raising the
threshold only made the white spot smaller. This isolates the failure to the
model's interpretation of the near-black soft shadow, not merely to an overly
wide matte. Both runs were rejected.

### Automatic real temporal-plate probe

`temporal_plate_shadow_inpaint.py` explores a non-generative video-inpainting
fallback. It automatically ranks real neighbouring frames by:

- reconstructed-depth agreement;
- actor overlap;
- candidate shadow-matte overlap;
- recovered brightness; and
- temporal distance.

It then colour-matches the best real plate on an automatic ring and feathers
only the high-confidence core:

```text
Godot\tools\temporal_plate_shadow_inpaint.py
SHA-256:
922b4bd5b31d80e7e79b20d9d305e8cc20a549912d0b5006877c8b7efbf65369
```

Strict selection correctly refused to invent a result. A diagnostic relaxed
selection chose frame 101 for target frame 82:

```text
depth agreement:   0.788593
depth MAE:         2.821876 encoded units
actor overlap:     0
shadow overlap:    0.038888
temporal distance: 19 frames
```

The reference was real and bright, but contained a later, more complete arc
groove and therefore leaked future scene state into frame 82. Earlier candidate
frames 53-56 had no future arc but would erase the partial groove visible in
target depth. This demonstrates why a real temporal plate is also insufficient
without a target-depth-conditioned renderer. The output was rejected.

### Current selected conclusion and next credible route

No tested method justified changing v20d, so there is intentionally no
`v21_shadow_removed` session and no browser/PCK validation for a new visual
version.

Do **not** repeat these already falsified assumptions:

- shadow pixels are an ordinary missing-object hole;
- a larger/dilated mask alone fixes the result;
- a global or scalar positive gain can recover the deep core;
- a generated whole-frame EffectErase output can be used directly;
- DiffuEraser will automatically interpret the dark soft blob as sand; or
- the nearest bright real frame has the same sand geometry.

The credible next route is target-depth-conditioned **illumination
decomposition**, with two distinct regimes:

1. preserve original RGB high-frequency texture and predict only low-frequency
   per-channel illumination in recoverable penumbra; and
2. for saturated umbra, render the **target frame's** depth/normals into the
   missing low-frequency sand appearance, rather than copying future RGB or
   generating unconstrained content.

The strongest external model candidate is the NTIRE-2026 winning
semantic/geometric cascade (DINOv2 + depth + surface normals) once its trained
checkpoint/code is public. Open-VSRD is the strongest dedicated video candidate
once its promised dataset/code is released. Until then, any internal
implementation should be trained/validated against synthetic paired shadows
and the existing actor-free captured controls, and must retain:

- byte-identical output outside the registered surface;
- exact no-op automatic controls;
- temporal flicker metrics;
- target-depth edge/normal agreement inside the repaired core; and
- separate hard-frame review at frame 82 before any full 714-frame run.

### Full Casper CogVideoX-5B three-GPU probe (2026-07-27)

The preceding "no candidate" conclusion records the state before the full
Generative Omnimatte/Casper run. It is superseded for review purposes by this
probe, but v20d remains the accepted immutable baseline.

The quality-first input is global RGB frames `40-124`, inclusive:

```text
85 frames
480x640
10 fps
clean-background mode
50 DDIM inference steps
seed 43
Grounded-SAM-2 actor masks, internal dilation width 11
no painted shadow mask or heuristic mask extension
```

Amadeus model assets:

```text
/home/baleine/shadow-v21/models/casper_cogvideox5b.safetensors
/home/baleine/shadow-v21/models/CogVideoX-Fun-V1.5-5b-InP/
```

The Casper and base-transformer weights were independently SHA-256 verified
after the `jp` relay. Casper:

```text
46359462667311fe111e0107fae693be1d431b99b06092668fcae525e1d813ad
```

After all Amadeus hashes passed, the temporary JP relay directory (about
`8.9 GB`), its one-purpose authorized-key entry, and Amadeus's temporary relay
private/public key were removed. The verified Amadeus model files were
retained. Restoring the deleted JP cache would require downloading or relaying
the public model shards again.

The public default uses BF16, while the three Amadeus RTX 2080 Ti cards require
an FP16 compatibility path. A diagnostic two-step run located the first error
exactly: diffusion step 1, transformer block 13, text feed-forward residual,
where `1 / 694272` values exceeded FP16 range. All attention, normalization,
and feed-forward inputs/outputs were finite before that residual. The final
path therefore uses:

- xFormers CUTLASS attention, checked on all three GPUs against full
  mathematical attention (`max error 0.000244`, mean `0.000017`);
- three-way Ulysses sequence parallelism;
- FP32 accumulation only for the small text residual branch;
- conversion back to FP16 with clipping only beyond representable FP16 range;
- layer- and diffusion-step finite assertions; and
- latent persistence before a separate single-GPU VAE decode.

This retains the complete 5B model, 85-frame temporal window, 480x640 input,
and 50 sampling steps. It is not the weaker 1.3B route.

Reproducible entry point:

```text
SandStories/Godot/tools/run_casper_cog5b_3gpu_safe_amadeus.sh
```

The 50-step denoising phase completed in about `3:02`. The saved latent had:

```text
shape:           (1, 22, 16, 60, 80)
finite values:   1689600 / 1689600
range:           [-2.345703125, 2.591796875]
```

Remote output:

```text
/home/baleine/shadow-v21/casper_outputs/cog5b_3gpu_safe50_f040_124/
  sand_f040_124-fg=-1-seed=43-latents.pt
  sand_f040_124-casper-cog5b-safe50.mp4
```

The raw decoded output removes the central hand/arm-associated shadow and
preserves the correct progressive circular-groove timeline. It does not import
the completed later circle into earlier frames. However, raw Casper reconstructs
the full frame and retains only about `77.9%` of source sand high-frequency
energy.

The retained playback candidate uses one-level Laplacian detail fusion:

```text
fused = source + blur(Casper, radius=1) - blur(source, radius=1)
```

Only the existing registered `surface_mask.png` receives the correction, with
feathering constrained inside its hard boundary. There is no hand-authored
shadow support. Larger `8/16/24` and `4/6` pixel bands were rejected because
they visibly reintroduced the shadow oval.

Final 85-frame probe metrics:

```text
outside-surface changed pixels: 0 / 11612275
mean global structural similarity vs source: 0.98442
retained sand high-frequency energy: 0.97363
mean adjacent-frame sand change: 1.74393
source adjacent-frame sand change: 3.21654
frame-82 broad shadow residual ratio: 0.00384
frame-82 automatic broad-effect pixels: 32046
```

Local playback and evidence:

```text
tmp/shadow_analysis/casper_results/cog5b_3gpu_safe50_f040_124/
  fused_hard_surface_radius_01.mp4
  sand_f040_124-casper-cog5b-safe50.mp4
  input_timeline_9.png
  output_timeline_9.png
  compare_f082_source_casper_hard_r01_r02.png
```

Review-video SHA-256:

```text
raw Casper:
C05294526B7FAF449C4AA2ADAC962D8E0F09B31B02F5DDBBBDFC5EB12B3FD9AA

retained radius-1 measured-detail fusion:
3B74AF3B035A823F8741035E3AA57177475A9B9E74A2F94B6EA2F96B741D23FA
```

The candidate is suitable for human playback review. It is not a unique
shadow-free ground truth: Casper still supplies the counterfactual
low-frequency appearance.

### v21b RGB-only Godot review branch (2026-07-27)

The user accepted the architectural boundary that Casper may replace the
displayed RGB but must not participate in any RGB-D reconstruction or hand
calculation. The 85 fused frames were therefore materialized into a separately
named review session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\
session_kinect_20260623_154953_virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124
```

Reusable materializer:

```text
SandStories/Godot/tools/materialize_rgb_only_review_session.py
```

Exact invocation from the repository root:

```powershell
python SandStories/Godot/tools/materialize_rgb_only_review_session.py `
  --source-session tmp/opencode/session_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final `
  --replacement-frames tmp/shadow_analysis/casper_results/cog5b_3gpu_safe50_f040_124/fused_hard_surface/radius_01 `
  --replacement-start 40 `
  --replacement-end 124 `
  --output-session tmp/opencode/session_kinect_20260623_154953_virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124
```

The materializer refuses to overwrite an existing destination. It copies the
v20d session contract, hard-links unchanged assets where the filesystem
supports it, replaces only `clean_rgb_000040.png` through
`clean_rgb_000124.png`, and writes explicit review metadata:

```text
production_session:       false
review_candidate:         true
mode:                     display-rgb-only
depthRecomputed:          false
manoRecomputed:           false
rgbdFusionRecomputed:     false
any2FullRecomputed:       false
```

Materialization/identity proof:

```text
source timeline:                           714 frames / 23.767706155776978 s
replacement window:                        40-124 inclusive / 85 frames
MANO mesh entries:                         622
hard-linked assets:                        2052
copied assets:                             0
depth files sharing the v20d file object:  714 / 714
MANO files sharing the v20d file object:   622 / 622
outside-window RGB sharing v20d:           629 / 629
replacement RGB sharing Casper fusion:      85 / 85
```

Sequence SHA-256:

```text
unchanged depth:
6076e890d26394ba633810cc4428ba522cc6cadd59665f0b24b28d156a1773f8

unchanged MANO meshes:
a8bbc30e412dc6c78db22514717b32507e6bbe35e6be5256dd4702093b9ebe84

unchanged outside-window RGB:
a91b6ab004f3197877aaa494f63404d36d47e9bfc930a67c22b9bd031bdafc9a

85 replacement RGB frames:
2129d5aa2dd3773d530a3e811ccc1359ec8673b861b73a88fa431694d01bf761

complete v21b RGB sequence:
ade1ed99ce153bb4d7244136855094b8952ccbbeaa0cfa54fb91149009dbb3bd
```

The complete machine-readable proof is retained as:

```text
rgb_only_display_override_report.json
```

The existing Windows server on port `8845` serves the session without a PCK
change. Browser QA confirmed:

- session JSON, RGB 40/124, depth 82, and the processed manifest return HTTP
  `200`;
- frame 82 reports `material=clean_rgb_000082.png` while the original
  cerulean MANO hand remains present;
- the `39 -> 40` and `124 -> 125` boundaries show no gross brightness or
  geometry discontinuity in manual frame stepping; and
- the browser console reports zero errors and zero warnings.

Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_kinect_20260623_154953_virtual_hand_v21b_casper5b_shadow_rgb_only_probe_f040_124%2Fsession.json&debug=1&t=casper5b-rgb-only-v21b-f040-124-20260727&autoplay=0
```

This branch does not yet replace the whole 714-frame display sequence. Keep
v20d immutable, review v21b only as a bounded RGB overlay experiment, and run
overlapping-window seam/causal-timeline QA before extending beyond frame 124.

## Handoff State

Completed:

- Deployed Any2Full Small, Base, and Large on Amadeus.
- Benchmarked all three model sizes and grid4/grid6 representative inputs.
- Evaluated 32 consecutive frames for vits, vitb, and vitl.
- Identified raw-RGB arm-depth leakage through a real Godot preview.
- Added object-masked conditioning RGB and reran vitl.
- Selected `vitl_object_masked_rgb + grid4`.
- Built and verified the corrected 32-frame Godot/Web preview.
- Fixed the Web remote-session startup race.
- Disabled dev-server caching for current PCK verification.
- User visually accepted the 32-frame preview.
- Added `--window-radius` local temporal window to the conditioning script
  and regression-checked it on 150-181.
- Prepared all 714 sparse grid4 inputs (mean grid4 ratio 4.37%).
- Built window-16 object-masked conditioning RGB for all 714 frames.
- Ran full 714-frame vitl inference and full-sequence aggregation.
- Made the aggregate script accept single-model output subsets.
- Built the full 714-frame dynamic Godot processed session and agent-reviewed
  representative frames (no wedges, no seams, no console errors).
- Added the HTTPS dev server for Windows browser access (port 9844).
- Rechecked the new physical/VPN network, restored both Web servers, and made
  HTTP 8844 the current same-machine review path.
- Fixed URL-session autoplay so it resets to frame 1, ignores the temporary
  default session, and waits for initial remote textures before playback.
- Rebuilt the isolated Web export and verified textured playback through
  `714/714` with zero browser-console errors.
- Reconnected to Amadeus through `r1`, confirmed the authoritative
  `propainter_v44_rgb` source, and matched all 714 SHA-256 hashes locally.
- Replaced the full session's mistakenly copied raw RGB with the authoritative
  ProPainter RGB without changing Any2Full depth or masks.
- Made `build_any2full_godot_preview.py` require an explicit displayed
  `--rgb-dir` and passed a one-frame materialization smoke test.
- Rechecked restored frames 150, 171, and 181 plus a complete `714/714` browser
  playback with zero console errors.
- Audited all 714 reconstructed depth frames against the original
  object-excluded reference NPZ files and quantified spatial/temporal accuracy.
- Identified Kinect one-unit raw-depth quantization at transition 147-148 and a
  partitioned quantization change at 222-223 as the data-level sources of the
  apparent whole-surface height jumps.
- Created the separate VDA-guided temporal candidate
  `...full_1_714_vda_temporal_s092_t18`, reducing broad coherent jumps from two
  to zero for about `0.048 mm` sampled held-out MAE cost.
- Added bounded lookahead prefetch, atomic depth/RGB frame readiness, sequential
  frame gating, autoplay buffering, and cache eviction to the Godot runtime.
- Added the native Windows review server on port `8845` and verified one
  complete browser playback requested all `714/714` depth and `714/714` RGB
  assets with zero console errors or warnings.
- Rejected v44 as the authoritative displayed-RGB prior after the user's hand
  ghost review; retained v44 unchanged for provenance.
- Rebuilt all 714 displayed RGB frames from the exact raw Kinect sequence using
  Grounded-SAM-2 continuous-ID/reverse tracking and official ProPainter.
- Rejected the incomplete per-frame YOLO/SAM result and the late whole-tray
  false masks from the low-threshold Grounded-SAM-2 run before inpainting.
- Calibrated Grounding DINO to `boxThreshold=0.35` from the recorded model
  scores, without hand-authored masks, heuristic extension, surface clipping,
  or shadow removal.
- Verified the selected masks (`665/714` active), the 714-frame ProPainter
  output, and zero changed pixels outside ProPainter's official dilated mask.
- Transferred the result losslessly through `jp` and `acode`, matched every
  source/decoded frame on Amadeus and Windows, and installed nothing on
  `acode`.
- Materialized the separately named rebuilt-RGB session while proving the
  selected stabilized depth sequence stayed byte-identical by SHA-256.
- Played the new combined session to `714/714`; the server served all 714
  unique RGB and depth assets with HTTP 200 and the browser reported zero
  errors and zero warnings.
- Documented the authoritative two-branch production workflow, exact model
  commits/parameters, reproducible commands, transfer path, and four mandatory
  QA gates in this handoff.
- Copied the prepared Kinect capture stack from `192.168.28.171` into the
  standalone `KinectCaptureLinux` source bundle.
- Removed source-machine path assumptions and unsafe implicit output deletion.
- Verified a clean Linux rebuild, relative runtime library loading, and
  fake-recorder process/session safety on `tiara`.
- Added the official MIT-licensed left/right Godot humanoid hand assets and
  rejected the incomplete local FBX after inspecting its 20-bone hierarchy.
- Reprojected the same-capture 526-sample MediaPipe track onto the selected
  stable depth without changing any RGB or depth image.
- Added hierarchical MediaPipe-to-humanoid retargeting, depth-aware sea-glass
  rendering, tracking-gap visibility gates, and a procedural fallback.
- Built the separately named virtual-hand v3 session and completed a `714/714`
  Web playback with zero errors and zero warnings.
- Diagnosed v3's per-frame palm-span scaling and single-fingertip contact
  overwrite from both track statistics and the frame-604 visual failure.
- Added stable session-scale retargeting, intent-specific rigid contact, and the
  raw-RGB-supported early tool-drawing state without modifying RGB/depth.
- Built the separately named virtual-hand v4 session and completed a `714/714`
  Web playback with zero errors and zero warnings.
- Diagnosed v4's deformation as the combination of bad occluded landmarks,
  unconstrained palm/bone retargeting, incomplete surface clearance, and
  conflicting transparent sand/hand depth prepasses.
- Added palm-basis continuity, anatomical segment/swing gates, all-landmark
  intent-aware surface clearance, opaque masked sand depth, and a stable
  alpha-scissor hand depth prepass.
- Built the separately named virtual-hand v5c session, proved RGB/depth
  byte-identical, and completed a `714/714` Web playback with zero errors and
  zero warnings.
- Quantified the remaining v5c deformation as an underconstrained top-down
  sparse-landmark problem and reviewed MANO, HaMeR, and WiLoR requirements.
- Built the separately named v6b top-down 2.5D prototype from standard
  Grounded-SAM-2 pixels plus raw-RGB luminance, with no hand-authored mask,
  image-position rule, gap filling, or RGB/depth change.
- Proved the surface-overlap component selector agreed with independent
  MediaPipe evidence in `491/491` comparable frames.
- Completed a v6b `714/714` Web playback and layer-toggle test with zero browser
  errors and zero warnings.
- Completed the separately named full-timeline v10 MANO branch: 622 HaMeR
  inferences with one shared official MANO shape, quaternion temporal
  smoothing, 607 valid robust RGB-D fusions, 13 strictly bracketed temporal
  fallbacks, and 620 compact binary meshes on the original 714-frame /
  23.7677-second timeline.
- Added gzip binary `MNRB` mesh loading and bounded resource prefetch to remove
  the hard-9 JSON-stream bottleneck, while retaining JSON compatibility.
- Decoded and topology-checked all 620 packed meshes and played the final Web
  session through `714/714` and `23.77/23.77`.
- Audited v10 and proved its pose inference used hand-inpainted v44 RGB; rebuilt
  the separately named v11 diagnostic from true RGB and rejected it at the
  frame-231 closed-tool-grip gate.
- Benchmarked official WiLoR on the hard frames and with its own frame-231
  detector crop; both predictions remained an anatomically wrong open hand, so
  no full WiLoR run was authorized.
- Benchmarked the OmniHands video checkpoint on the true-RGB temporal window
  `181-281`; its 101 outputs completed, but frame 231 still failed the grip gate,
  so no full run or v13 Godot session was created.
- Added reproducible crop-sidecar inference tools for WiLoR and OmniHands and
  generalized the 2D alignment analyzer to their inference manifests.
- Separated the bare-hand problem from the tool-interaction problem and built
  the v16c hand-only branch from a temporally regularized, 15D MANO inverse fit
  to standard-model 21-point observations, with one shared shape and fixed
  camera depth so the hand cannot pump in scale.
- Constrained the fitted MANO surface to the existing registered RGB-D actor
  support without generating, extending, or hand-authoring a mask.
- Fused 396 frames with robust rigid RGB-D camera-depth offsets, rejected five
  underconstrained early fusions, and deterministically packed 401 meshes on
  the original 714-frame / 23.7677-second timeline.
- Found and fixed the real hand/sand depth-coordinate bug: RGB-D fusion now
  applies the session's `-5.0` sand displacement scale when reconstructing
  surface world Y. The fix replaces the misleading high-clearance diagnostic;
  it is not an alpha or depth-prepass workaround.
- Built and browser-reviewed the separately named v16c Web session. Bare-hand
  fist/claw/pointing frames no longer collapse to the same open-fan prior,
  frame 358 remains visible against the displaced sand, and the intentionally
  excluded tool interval remains empty.
- Archived the validated v16c PCK and recorded the complete model/data/fitting,
  RGB-D fusion, packing, materialization, validation, artifact, URL, and hash
  workflow above.
- Proved v16c's long middle disappearance came from excluding
  `tool_drawing`, then fitted all 622 tracked frames with one generic,
  confidence/support-weighted MANO sequence and no tool/contact pose rule.
- Proved the late 3D distortion came from adding different reconstructed sand
  heights under individual MANO vertices near the tray boundary.
- Added unchanged static-surface nearest sampling and one median visible-inlier
  surface anchor for rigid MANO fusion, preserving the closed mesh shape.
- Fused 612 frames directly, interpolated only the two explicitly reported
  five-frame fusion failures, packed 622 meshes, and preserved the real
  `622-628` and `636-647` tracking gaps.
- Built and browser-validated the separately named v17h full-hand candidate;
  middle frames 100/231/278 are present, late frame 599 no longer depth-drapes,
  and the final browser reports zero errors or warnings.
- Diagnosed v17h's `82-299` jitter with a reproducible component-level
  analyzer and proved the dominant failure was an off-tray spectator-hand
  association at frame 273, not whole-surface height motion.
- Reused the unchanged registered `surface_mask.png` as an automatic track ROI,
  rejected the one outside anchor, propagated invalidity through its densified
  dependants `273-281`, and bracket-repaired them without RGB masking or a
  hand-authored mask.
- Added rotation-matrix and projected-screen temporal losses, locked the
  original full-sequence shape/camera scale, refit with context `70-310`, and
  replaced only `82-299`.
- Reduced requested-interval wrist, vertex, and rotation jitter metrics by
  approximately `40-58%`, fused `617/622` frames directly, and packed the five
  remaining early fusion fallbacks into a separate 622-mesh v18e session.
- Browser-validated the repaired hard intervals and continuous requested-range
  playback with zero errors or warnings while preserving all RGB/depth files
  and the genuine late tracking gaps.
- Diagnosed the remaining post-300 motion as accepted pose plus unstable
  per-frame RGB-D surface-anchor mode changes rather than another semantic hand
  failure.
- Built v19i with one fixed reference-surface anchor policy, preserved every
  accepted v18e MANO pose and all original RGB/depth assets, and retained the
  genuine missing-hand intervals.
- Browser-reviewed v19i across the previously unstable late interval and
  accepted it as the geometry/motion baseline.
- Added the opaque, double-sided, normal-sign-stable MANO beauty shader and
  made its palette/roughness/rim/emission parameters session-selectable.
- Built v20a from v19i as the retained soft-peach appearance comparison without
  changing any RGB, depth, or MANO mesh.
- Built v20d from the exact same v19i assets with the accepted cerulean-blue
  palette, kept the v20a Web PCK because the runtime shader code is identical,
  and recorded the exact materialization command, hashes, and review URL above.
- User accepted v20d for temporary retention. It is immutable; any later
  appearance experiment must use a separately named output session.
- Parsed and visually checked the attached research proposal methodology, then
  implemented the separately versioned v21a Stage 1/Stage 2 experiment runner.
- Added honest modality/content readiness gates, real narration playback,
  condition locks, evidence snapshots, Likert/raw NASA-TLX capture, anonymous
  JSON export, and proposal-derived session/protocol contracts.
- Found and fixed the Web-only pre-training condition leak, archived both the
  accepted v20d PCK and the v21a PCK, and browser-validated the fixed Stage 1
  sequence with zero errors or warnings.
- Addressed project-review findings 2-6: hidden SubViewport rendering, orphaned
  fallback video decoders, remote session races, static-server path/stream
  handling, and the stale reconstruction smoke test.
- Investigated shadow removal from the immutable v20d baseline with automatic
  ShadowSAM/photometric/depth evidence and actor-free controls, without a
  painted mask or fixed cleanup region.
- Reproduced and hard-frame-tested ProPainter, official EffectErase, and
  official DiffuEraser video-inpainting paths on Amadeus; recorded exact model
  revisions, environments, parameters, runtimes, hashes, and failure evidence.
- Rejected all three content-generation routes at frame 82: ProPainter blurred
  the sand, EffectErase regenerated the whole surface, and DiffuEraser produced
  a bright white core while leaving penumbra.
- Tested scalar/RGB low-frequency illumination correction and automatic real
  temporal plates; rejected gain amplification because the core became
  magenta/noisy and rejected the plate because it leaked future groove state.
- Deliberately left v20d unchanged and rejected the lower-fidelity shadow
  candidates before creating the later bounded v21b RGB-only review branch.
- Ran the full public Generative Omnimatte/Casper CogVideoX-5B recommendation
  on all three Amadeus GPUs, 85 frames at 480x640 and 50 steps, rather than
  substituting the weaker 1.3B route.
- Diagnosed and fixed the Turing FP16 numerical-range failure at the exact
  block-13 text residual, retained finite assertions, saved a fully finite
  latent, and decoded all 85 frames separately.
- Verified that full Casper removes the hard central actor-associated shadow
  while preserving the progressive groove timeline; measured its raw
  whole-frame denoising instead of hiding it.
- Added measured-detail Laplacian fusion constrained by the existing registered
  surface mask. The retained one-pixel probe changes zero outside-surface
  pixels, retains 97.4% sand high-frequency energy, and leaves only 0.38% of
  the broad frame-82 source-to-Casper shadow difference.
- Added a non-overwriting RGB-only session materializer and created v21b by
  replacing only display RGB `40-124` with the retained Casper fusion.
- Proved all 714 depth frames, all 622 MANO meshes, and all 629 RGB frames
  outside the replacement window are the exact v20d file objects; no Any2Full,
  depth stabilization, MANO fitting, or RGB-D fusion was rerun.
- Browser-stepped frames 39/40, 82, and 124/125 in v21b, retained the original
  cerulean MANO overlay, and observed zero console errors or warnings.

Pending:

- Keep `readyForDataCollection=false` until narration, object/tool evidence,
  creator/community-validated content, ethics-approved wording, approved
  production storage/retention, and Stage 2 ordering/observer procedures are
  complete.
- Preserve `index_v21a_proposal_experiment_runner.pck` independently from the
  immutable v20d archive. Use `study=pilot` for UI work; do not label pilot
  downloads as research data.
- Fix remaining project-review finding 1 (untrusted `sessionId` output-path
  containment) before running `prepare_production_session.py` on an untrusted
  manifest, and finding 7 before claiming portable/reproducible builds.
- Preserve accepted v6b, measured v7, hand-only v16c, all-intent v17h,
  surface-ROI temporal v18e, reference-surface-stable v19i, soft-peach v20a,
  and accepted cerulean-blue v20d.
- Preserve v8/v9/v10/v11 plus the WiLoR and OmniHands outputs as
  geometry/runtime or rejected-pose diagnostics. The 9-second v9 reel remains
  a hard-frame QA reel, not the full recording.
- Treat v16c as the bare-hand baseline, v17h as the pre-temporal all-intent
  baseline, v18e as the ROI/pose-temporal baseline, v19i as the retained
  geometry/motion baseline, v20a as the warm appearance comparison, and v20d
  as the current accepted appearance session. None of these branches contains
  a forearm.
- Do not overwrite v20d or silently change its palette. Do not rerun hand pose,
  RGB-D fusion, stabilization, mesh packing, Any2Full, or ProPainter merely to
  create another color: start from v19i and materialize a separately named
  metadata-only appearance session.
- When tool work resumes, create a separately named branch and jointly
  constrain the hand against observed tool interaction over time, using
  standard-model evidence only. It must first pass the frame-231 closed-grip
  gate. If reliable tool/hand evidence cannot be obtained without hand-authored
  masks or pose rules, leave those frames hidden rather than fabricating a grip.
- Shadow removal is now an active research branch, but v20d remains the
  accepted immutable baseline. Do not invent a manual/heuristic mask extension
  or publish any candidate that has not passed the frame-82 fidelity gate.
- Playback-review the v21b Godot session as well as
  `tmp/shadow_analysis/casper_results/cog5b_3gpu_safe50_f040_124/fused_hard_surface_radius_01.mp4`.
  If the bounded RGB replacement is accepted, extend Casper in overlapping
  temporal windows and validate seams plus the full deformation timeline.
  Never feed generated RGB back into the depth/MANO/RGB-D pipelines and do not
  overwrite v20d.
- If the Casper playback or long-window seams fail, the next credible route is
  target-depth/normal conditioned illumination decomposition: preserve captured
  RGB texture in penumbra and synthesize only target-geometry-consistent
  low-frequency appearance in saturated umbra. Re-evaluate dedicated Open-VSRD
  or the NTIRE-2026 geometric cascade when official code/checkpoints become
  public.
- If the user requests a materially different hand/arm result, preserve v44 and
  the current candidate and create another separately named standard-model
  ProPainter/session variant on Amadeus.
- Run `doctor.sh --require-device` and one short real Kinect capture after the
  bundle is installed on each destination Linux host.

## 2026-08-03 experiment infrastructure: persistence, recovery, and preflight

This iteration deliberately did not add a new story/package abstraction and
did not freeze the final research export tables. Existing `session.json` plus
`experiment_protocol.json` remain the content contract.

The local review server now also owns an experiment persistence API:

- `Godot/tools/experiment_api.mjs` creates anonymous runs, assigns Stage 1 by
  randomized balanced blocks of five, hashes resume tokens at rest, atomically
  saves the latest draft, deduplicates event batches, resumes a run, and seals
  a completed submission against later mutation.
- `Godot/tools/static_server.mjs` exposes the API under
  `/api/experiment/*`. `start_review_server.ps1` writes data to the ignored
  `server_data/experiments` directory by default and accepts an explicit
  `-ExperimentDataDir`.
- Fixed condition assignment is QA-only and is disabled unless the server is
  started with `-AllowConditionOverride`.

`Godot/web/experiment_host.js` now uses local-first autosave. It debounces full
draft replacement, appends interaction events in idempotent batches, retries
after network loss, resumes after refresh with the stored bearer token, drains
all pending events before completion, and retains manual JSON download only as
a backup. The assigned Stage 1 condition is stored separately from the active
training condition, so training remains baseline without losing or revealing
the server assignment.

Preflight is split into static and runtime checks:

- `Godot/tools/experiment_preflight.mjs` checks an existing session's protocol,
  modalities, question structure, temporal bounds, references, manifest frame
  count/order, and referenced RGB/depth/MANO assets.
- `Godot/tools/validate_experiment_runner.gd` now exercises all five Stage 1
  conditions and checks omitted-layer visibility and locks plus baseline
  restoration.

Verification completed on 2026-08-03:

- `node --test Godot/tools/experiment_api.test.mjs
  Godot/tools/experiment_preflight.test.mjs`: 7/7 passed.
- The live server API completed create -> balanced assignment -> draft -> event
  append -> resume -> immutable completion successfully.
- A headless Edge run completed the real Web host flow through Godot training,
  task, questionnaire, and server completion with 16/16 events drained and no
  console errors. Refresh restored the training step and remote run token.
- A forced draft-request network failure switched the host to local backup,
  then an online event retried successfully and drained 5/5 queued events.
- Direct Godot Web bridge checks applied baseline, no-audio, no-gestures,
  no-objects, and no-sand; every omitted runtime layer was false and the browser
  reported no errors.
- v20d static preflight correctly failed content readiness (13 failures): its
  existing RGB-D/MANO assets passed, while formal protocol metadata, narration,
  objects, questions, and Stage 2 relations are still absent.

## 2026-08-03 paused known-object probe: the v20d pen

This branch is paused at the user's request while work switches to a different
LiDAR-produced input and the older workflow. Do not resume it until explicitly
requested. The accepted v20d session remains immutable, and no object-enabled
session or Godot Web build was materialized from this probe.

The probe used only standard-model evidence for the pen; it did not use a
hand-painted mask, a fixed cleanup region, a synthetic grip, or a special rule
for the drawing tool:

- Source session:
  `tmp/opencode/session_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final`.
- Grounding DINO (`pen.`) supplied object detections and SAM2 propagated their
  masks. The retained multiseed set is
  `tmp/opencode/object_pen_v20d_probe/grounded_sam2_pen_multiseed_full714_v5`
  locally and
  `/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/object_pen_v20d_probe/grounded_sam2_pen_multiseed_full714_v5`
  on Amadeus. It contains 714 masks and 626 model-active frames.
- The primary seed-0 track was recovered only from independently rerun model
  tracks: seed 230 supplied frames 233-239, seed 323 supplied 299-322, and seed
  460 supplied 27 frames in 427-432, 439-450, 458-465, and 525. Selection used
  the known slender-object geometry gate (median area 908 px; accepted area
  181.6-1816 px; PCA aspect at least 4.3; recovery gap distance at most 4).
  Accepted masks were copied byte-for-byte; the merger did no pixel union or
  morphology.
- Reject the seed-470 recovery output. Hard-frame QA showed that it follows the
  dark sand groove rather than the pen, so that curve must not be erased.
- Official ProPainter then removed the selected pen masks over the full
  714-frame RGB sequence with `--save_frames --save_fps 30 --fp16` and its
  default mask dilation 4. The retained frames are at
  `/home/baleine/rgb-depth-uniform/propainter_allhands_v45_work/object_pen_v20d_probe/propainter_pen_removed_full714_v2/frames/frames`.
  The local contact sheet is
  `tmp/opencode/object_pen_v20d_probe/propainter_pen_removed_full714_v2_qa.png`.
  The final PNG archive SHA-256 is
  `b9c40c997a282685ab411fce3aa7cbe1f7692218696676a7262fd20d3e94687e`.
- Registered v20d depth was sampled under each selected mask to recover a
  measured cylinder center, axis, endpoints, diameter, and visibility rather
  than inferring a grip. The retained track is
  `tmp/opencode/object_pen_v20d_probe/pen_track_rgbd_v2.json`, with report and
  QA files beside it. It exports 630 samples (626 model-active plus four short
  interpolations), hides long gaps, uses reference diameter
  `0.0731253287613487` and reference length `1.0796575218402644`, and has
  SHA-256
  `154c7f556f178a5c6c140ab4bba09899e29a60320037c87b544e68758ee53454`.

Uncommitted infrastructure for this probe is present in
`Godot/data/session_schema.json`, `Godot/scripts/main.gd`, and the tools
`extract_tracked_cylinder_from_rgbd.py`,
`materialize_tracked_object_session.py`,
`track_known_object_grounded_sam2.py`,
`merge_known_object_model_tracks.py`, and
`audit_object_separation_rgb.py`. `audit_grounded_shadow_detections.py` also
contains a Grounding DINO API-compatibility fix. These changes were syntax and
schema checked, but the unfinished object path has not been committed, built,
or browser-reviewed.

Transfer was deliberately stopped rather than allowed to run in the
background. Amadeus retains the authoritative lossless RGB transport file
`propainter_pen_removed_full714_v2_lossless_rgb.mkv` (about 338 MB) and the PNG
archive. The local file
`tmp/opencode/object_pen_v20d_probe/propainter_pen_removed_full714_v2_frames.tar`
is an incomplete roughly 109 MB partial and must not be treated as valid. A
resumable 62,062,592-byte MKV partial remains at
`/home/baleine/sandstories_object_pen_transfer_20260803/` on acode. The
temporary acode authorized-key entry and its Amadeus private/public key pair
were removed after pausing; no related local SSH/SCP or Amadeus rsync,
ProPainter, FFmpeg, or tracking process remains.

If this branch is resumed, continue by transferring and pixel-verifying the
authoritative v2 RGB, run `audit_object_separation_rgb.py`, materialize a new
separately named session that references the v20d depth/MANO assets without
overwriting them, then build and browser-test normal and `no-objects`
conditions. Until all four steps pass, do not describe the pen pipeline as a
finished experiment asset.

## 2026-08-03 completed iPhone LiDAR reconstruction

This work temporarily supersedes the paused v20d pen probe. It applies the
accepted Kinect-era reconstruction workflow to the independent iPhone LiDAR
capture `session_5532036C-251F-4A20-89DC-A0745E463F87 (1).zip` without
overwriting the Kinect sessions.

### Source and transfer provenance

- Original archive SHA-256:
  `4d427258d79a40633bcf027db97e00b46b3da5b547a7acd7b8e64405b5b45900`.
- Local immutable unpack:
  `tmp/opencode/session_lidar_5532036C-251F-4A20-89DC-A0745E463F87_raw`.
- The required inbound route was followed exactly:
  Windows -> `jp` -> `acode` -> Amadeus. SHA-256 was checked at each hop.
  The completed review sessions came back in reverse through
  Amadeus -> `acode` -> `jp` -> Windows, again with per-part and whole-archive
  SHA checks. No packages were installed on `acode`.
- Authoritative Amadeus work root:
  `/home/baleine/rgb-depth-uniform/lidar_5532036c_full_pipeline`.
- The lossless return archive has SHA-256
  `dcb81b8f6879d4c79415119621b467cb48b1d1d2493bc88d7cbfdfc6e96e2882`.
  Repeated RGB PNGs were transported once as lossless `libx264rgb -crf 0`;
  1,477 decoded RGB frame MD5 values match the original ProPainter PNG pixels.
  This was transport-only and did not change model inputs or output pixels.

The package contains 1,477 frames over 57.27 seconds (actual cadence about
25.77 fps), 1920x1440 H.264 RGB, 256x192 float32 metric depth and confidence,
44.1-kHz mono AAC narration, and three captured strokes. Every frame metadata
record selected `smoothedSceneDepth`. The generic manifest prose calling
`depth.f32` unsmoothed is not authoritative for this capture; the capture code
writes the selected depth source, so these stored samples are already the
LiDAR framework's smoothed scene depth.

### Display RGB reconstruction

1. Decode the packaged H.264 exactly and Lanczos-resample 1920x1440 to
   640x480. The original package remains immutable.
2. Detect `hand. arm.` with `IDEA-Research/grounding-dino-tiny`, box threshold
   0.35 and text threshold 0.20. Propagate with SAM 2.1 Hiera Large using
   step 10, forward and reverse continuous IDs. The retained masks contain
   model evidence only: no hand-authored mask, no sand-surface clipping, no
   shadow mask, and no post-processing before ProPainter. They are active in
   1,331/1,477 frames with median area 26,610 pixels.
3. Run official ProPainter once across all 1,477 frames with `--save_frames`,
   `--fp16`, official mask dilation 4, and unchanged reference stride 10. It
   was not temporally chunked. To fit the long sequence on a 22-GB GPU, the
   open-file limit was raised to 8,192 and unchanged FP32 RAFT flow chunks were
   concatenated on CPU before the requested fp16 GPU cast. A 24-frame
   regression was byte-identical to the upstream GPU-resident path (24/24,
   maximum channel difference 0). Pixels outside the official dilated mask
   were unchanged.

Retained upstream commits are Grounded-SAM-2
`b7a9c29f196edff0eb54dbe14588d7ae5e3dde28` and ProPainter
`e870e79321c31b733e2031af5aa2fb1fe3ac7eec`. ProPainter removes the modeled
hand/arm but does not deliberately remove cast shadows; blurred gray hover
regions therefore remain a declared RGB limitation rather than an invented
mask heuristic.

### Metric depth reconstruction

1. Build a model-free sand surface mask from the stable high-confidence
   central LiDAR depth component. Retain confidence >= 2, depth 0.15-2.5 m,
   5x5 local residual <= 8 mm and Sobel <= 80 mm, and exclude the model hand
   mask dilated by 8 pixels. There is no hand-painted ROI.
2. Only mapped native LiDAR sample centres are treated as metric evidence;
   interpolation is never labeled ground truth. Sampling every second native
   x/y coordinate produces the effective 640x480 target grid-4 anchors. The
   fixed first-60-frame metric encoding range is
   `[0.5303058565, 0.6559135050]` metres.
3. Build Any2Full conditioning RGB separately from display RGB: visible
   temporal median radius 16, model object masks, no feathering, and spatial
   Telea fill only for pixels masked in every temporal neighbour. This branch
   is never shown to the participant.
4. Run Any2Full Large/VIT-L independently for all 1,477 frames. Three Amadeus
   GPUs schedule three disjoint frame ranges, then a merge verifies exactly
   frames 1-1477 with no duplicates or gaps. The retained Any2Full commit is
   `780edf6b...` (full hash remains in the session manifest).
5. Run official VDA ViT-S once over the full RGB sequence. VDA supplies only
   temporal delta guidance; it never replaces Any2Full metric scale or spatial
   detail. Full-sequence tuning selected strength 0.85 and broad-jump threshold
   18. The unstabilized Any2Full session is retained for audit and the VDA
   temporal session is the default review result.

Raw Any2Full full-sequence held-out metrics are MAE 0.792 mm, RMSE 1.246 mm and
quality-region p95 absolute error 2.438 mm. Evaluation after the final Godot
PNG encoding/correction gives:

- unstabilized: MAE 0.850 mm, RMSE 2.146 mm, p95 2.548 mm;
- VDA-temporal: MAE 1.049 mm, RMSE 2.287 mm, p95 2.929 mm.

VDA deliberately trades roughly 0.20 mm of held-out MAE for temporal comfort:
broad surface jumps fall from 58 to 9 and mean adjacent-frame surface change
falls from about 1.999 to 1.366 mm. Both branches remain available so this
trade-off is explicit.

### LiDAR versus Kinect interpretation

The LiDAR stream is 256x192 (49,152 samples/frame) versus Kinect 640x480
(307,200, exactly 6.25x as many spatial samples) and about 25.77 versus 30 fps.
On the stable first 60 LiDAR frames, per-pixel temporal standard deviation has
median 0.357 mm and p95 0.791 mm; the available Kinect encoded-depth proxy has
median 0.836 mm and p95 1.822 mm. This capture's LiDAR is therefore more
temporally repeatable, and the final model agrees better with its held-out
samples, but it is much sparser and already framework-smoothed. The scenes are
different and no external ground-truth surface was captured, so these numbers
must not be presented as a same-scene sensor-accuracy benchmark.

### Final local Godot sessions

- Unstabilized audit branch:
  `tmp/opencode/session_lidar_5532036C_251F_4A20_89DC_A0745E463F87_rgb_grounded_sam2_propainter_any2full_vitl_grid4_full1477`.
- Default stable branch:
  `tmp/opencode/session_lidar_5532036C_251F_4A20_89DC_A0745E463F87_rgb_grounded_sam2_propainter_any2full_vitl_grid4_full1477_vda_temporal_s085_t18`.
- Each contains 1,477 RGB, 1,477 depth and 1,477 valid-mask PNGs. The restored
  local RGB byte-sequence SHA is
  `a698753b7e198fae372fc10ef0aa95d7f60ad75e9bdd6ef409778a19eff2f6d5`;
  its pixel framemd5 sequence matches Amadeus exactly. Depth sequence SHAs are
  `578de534d7822c022675a496a479f78c55c46e91522c57fe4ffcfa966f5b7b14`
  (raw Any2Full) and
  `d403f6e83f49060a35b61107172b6032b2c8da905aa60ff09ef37e5127644931`
  (VDA temporal).
- `audio.m4a` is retained as capture provenance. Godot Web narration is
  `audio.ogg`, transcoded once with Vorbis quality 5 and referenced by both
  session JSON files.

New reusable tools for this branch are
`analyze_lidar_kinect_precision.py`, `prepare_lidar_any2full_eval.py`,
`grounded_sam2_tracking_sandiv_cpu_offload.py`,
`inference_propainter_long_sequence.py`,
`prepare_any2full_conditioning_rgb_remote.py`,
`run_any2full_eval_remote.py`, `aggregate_any2full_evaluations.py`,
`run_vda_sandstories.py`, `materialize_vda_temporal_guide.py`,
`stabilize_any2full_with_vda.py`,
`evaluate_processed_depth_against_lidar.py`,
`attach_processed_depth_evaluation.py`,
`build_lidar_any2full_godot_session.py`,
`restore_lossless_rgb_transport.py`, and
`materialize_godot_web_audio.py`.

Local QA completed against the rebuilt Godot 4.5.1 Web export on port 8845.
After materializing the Linux hard-linked surface mask and Web-compatible OGG,
a fresh in-app-browser load emitted no warning or error, representative start,
middle, late and final frames rendered, the depth/material-only view retained
visible sand relief, and a complete 57.27-second playback returned to frame 0
with an empty warning/error log. The stable review tab is intentionally left
open. The temporary Amadeus -> acode and acode -> jp SSH keys and their exact
authorized-key markers were removed after the four-way hash verification;
the source and verified staging data were retained.

## 2026-08-03 LiDAR depth-detail and hand-imprint follow-up

The initial high-detail Godot experiment is a diagnostic branch, not a selected
replacement for the stable LiDAR session. `session_surface_detail_v22a.json`
requests a 639x479-subdivision mesh and bypasses the legacy masked-depth 3x3
filter. It proves that the old 256x256 mesh/shader path hid valid relief, but it
also exposes Any2Full/VDA contour and completion artifacts as false grooves.
The Kinect v20d baseline and both accepted LiDAR session JSON files remain
unchanged; the new renderer settings default to the legacy behavior.

Seven static representative frames were evaluated with Any2Full, the current
VDA-stabilized output, causal object-gated state, linear anchors, bilateral
state, bounded Any2Full detail and bounded VDA detail. The key averages are:

- raw Any2Full: held-out MAE/p95 0.776/2.391 mm, high-frequency RMS 0.452 mm;
- current VDA-stable: 1.053/3.044 mm and 2.685 mm high-frequency RMS;
- causal bilateral: 0.302/0.922 mm;
- causal bilateral plus 55% clipped Any2Full detail: 0.327/0.983 mm;
- causal bilateral plus VDA detail: 0.498/1.306 mm.

Linear anchor interpolation scores well but is rejected because the static
relief pages show sparse-triangulation fans. Direct VDA detail is rejected
because the pages show contour stripes. Across the active-mask sample frames,
raw Any2Full differs from the last visible causal sand state by 8.147 mm RMS on
average; the current VDA-stable branch differs by 14.991 mm. Frame 629 reaches
15.597 mm for Any2Full and 29.813 mm for the VDA-stable branch.

The existing full-sequence VDA guide was proven to use raw RGB: decoded guide
input frames match raw RGB at about 3-4 gray-level RMSE and differ from repaired
RGB by 13-42. A local NVIDIA RTX 3080 Ti environment was therefore created with
official VDA Small and three matched 64-frame raw/model-masked input windows.
The A/B shows that raw VDA treats the hand as geometry, while model-masked input
still exposes large-fill bands and unmasked illumination/shadows. VDA must not
write inside `object_dilated`, must never contribute high-frequency residual,
and is now optional low-frequency timing guidance only.

The complete next-run specification and acceptance gates are in
`docs/LIDAR_RECONSTRUCTION_PIPELINE.md`. Static pages and machine-readable
reports are retained under `tmp/opencode/lidar_static_depth_method_probe_v1`
and `tmp/opencode/lidar_vda_local_probe/comparison`. New reusable tools are
`analyze_lidar_depth_detail_candidates.py`,
`prepare_lidar_vda_probe_inputs.py`, and
`compare_vda_raw_conditioned_probe.py`. No hand-authored mask or shadow mask
was introduced.

## 2026-08-03 selected LiDAR hand-imprint repair v24b

The full-sequence `causal_any2full_detail_v23b` branch is rejected despite its
good held-out LiDAR and temporal aggregate metrics. Direct depth-only review
at 19.63 seconds (manifest frame 458) exposed a clear hand/finger outline in
the sand mesh. The model mask moved, so contaminated Any2Full values entered
the causal state when pixels were released. Simple causal release holds of
12, 30 and 60 frames did not solve this; they only delayed or froze the same
semantic leakage. `docs/LIDAR_RECONSTRUCTION_PIPELINE.md` now labels v23b as a
rejected audit artifact.

The selected replacement is the separately named local session:

```text
tmp/opencode/session_lidar_5532036C_251F_4A20_89DC_A0745E463F87_temporal_anchor_surface_v24b
```

Its depth is produced offline from the existing Grounded-SAM-2 model masks and
real grid-4 LiDAR anchors. There is no manual hand ROI, shadow mask or
hand-authored geometry. A LiDAR anchor observation is valid only when the
model mask is clear for +/-15 frames. A centred +/-60-frame median follows
local changes; +/-180 is fallback only where the short window has no safe
sample. Missing lattice cells are spatially filled, robust-clamped, Gaussian
filtered at sigma 2 lattice cells and linearly upsampled. This metric surface
replaces the temporal object envelope and blends to current Any2Full low
frequency over 48 pixels. Any2Full adds only 55% high-pass clipped to +/-3 mm,
with zero weight through 16 pixels from the envelope and a smooth ramp to full
at 32 pixels. The manifest truthfully records `futureFramesUsed: true`.

The rejected v24a full run applied temporal LiDAR over the whole lattice ROI.
It removed the hand but over-smoothed the story and reached held-out MAE
2.627 mm. The v24b spatial blend gives held-out MAE/RMSE/p95
0.921/1.735/3.081 mm, high-frequency RMS 0.303 mm, mean adjacent change
0.307 mm, maximum absolute frame-median delta 0.467 mm and zero broad jumps.
Static gates 269/458/629/806 and the fully materialized Godot frame 459 at
19.67 seconds contain no explicit hand outline. The unavoidable limitation is
that the actively occluded region is smoother than visible sand because the
sparse sensor contains no trustworthy high-frequency evidence there.

The session has 1,477 RGB, 1,477 depth and 1,477 valid-mask frames and directly
samples the already filtered depth on a 639x479 mesh. Its depth-sequence SHA is
`067741e629cedc55e76ff4422d73577b9a11a9b5948b05873aad6ead044a4f7c`.
The 44,739,968-byte return archive SHA is
`54fd1cffb2c9251ea93b88b45cce8d8568b9c9eee0d6a8a4fc9c7fa2f3271fa5`.
The archive travelled Amadeus -> acode -> jp -> Windows and matched at every
hop. Acode had 183 GB and jp 9.8 GB free before staging; no package was
installed on acode. Both exact staging directories, both one-purpose
authorized-key lines and all temporary private/public relay keys were removed
after local verification.

Godot 4.5.1 Web on port 8845 played the complete 57.27 seconds through frame
1477 with no browser warning/error. The selected tab is left on the v24b
session for user review. Reusable code is
`tools/probe_lidar_bidirectional_surface_completion.py`,
`tools/materialize_lidar_temporal_anchor_surface.py`, and the extended
`tools/build_lidar_causal_godot_session.py`. The Amadeus environment gained
only `bottleneck` in the Grounded-SAM-2 processing venv to compute centred
NaN-aware temporal medians efficiently.

## 2026-08-04 portable v24b integration package

The accepted-for-use v24b session was packaged for transfer to another AI or
SandStories checkout. The distribution files are:

```text
tmp/opencode/deliverables/SandStories_LiDAR_v24b_integration_20260804.zip
tmp/opencode/deliverables/SandStories_LiDAR_v24b_integration_20260804.zip.sha256
```

The ZIP is 792,366,377 bytes and its SHA-256 is
`b4b9c84d1f2b8442e216b5b5718a4b35d66afcd687b670b65ca15bc11a469d56`.
It contains the exact 4,444-file self-contained session, root `AGENT.md`, a
machine-readable package manifest, the LiDAR reconstruction document, session
schema, and four source/provenance tools. The package root is intentionally a
valid dynamic-session root, so `tools/start_review_server.ps1` can receive it
directly through `-DynamicSessionsDir` without copying the 755 MiB session.

Packaging QA listed 4,458 ZIP entries, found no `__pycache__`/`.pyc`, extracted
and parsed `AGENT.md`, both manifests, `session.json` and frame 458 depth, and
recomputed the packaged depth-sequence SHA as
`067741e629cedc55e76ff4422d73577b9a11a9b5948b05873aad6ead044a4f7c`.
The integration instructions preserve the exact session directory name,
639x479 mesh, direct sampling of the already filtered depth, per-frame
manifest timing/correction, surface mask, frame-458 semantic gate, complete
playback audit, offline/future-frame disclosure and the honest locally smooth
occlusion limitation.

## 2026-08-04 PARADISEC WDVA1 meaning audit and MIR_25 comparison probe

The selected WDVA1 subset is documented in
`_external_research/PARADISEC_WDVA1_formative_subset/CATALOG.md`. In this
collection, `MIR` is *mirlpa* sand-story documentation: meaning is distributed
over narration, drawing/erasing, pointing, hand movement, story sticks or
wires, spatial layout and the changing trace. `SIGN` is Western Desert
sign/gesture documentation and is a useful embodied-language contrast, but it
normally has no sand surface. `FINAL.mp4` files are edited viewing derivatives;
numbered `01/02` files are separate cameras; `A.mp3` is annotation-linked
audio; EAF is the time-aligned ELAN source; PDF/TXT are reading exports, not
geometry. `TransSpeech` is English translation, while `LH/RH-IDgloss` are
left/right-hand sign glosses. `xx` means unresolved annotation.

The catalog gives a content-level interpretation of MIR_01, MIR_02, MIR_18,
MIR_22, MIR_25, MIR_26, SIGN_05, SIGN_06 and SIGN_15. WDVA1 is retained as
formative/reference material, not silently promoted to participant stimulus:
there is no measured depth and no creator validation through this project's
RGB-D protocol.

`MIR_25` was selected for the first end-to-end comparison because it is a
compact 2:36 goal-oriented honey-ant story with a stable sand camera and 40
English translations. The downloaded raw derivatives were verified at exact
sizes: camera 01 is 194,891,911 bytes and camera 02 is 200,997,496 bytes.
Camera 02 is the uninterrupted 1920x1080, 25 fps sand close-up and is the model
input. The implemented probe is source time 31.600--61.600 seconds: 750 source
frames covering going bush, travelling with the girls, parking, searching,
digging, cooking kangaroo tails and locating the car. Ten overlapping
`TransSpeech` reference annotations are now resolved to their parent spans and
carried into the session.

Exact RGB branch:

1. Grounding DINO Tiny + SAM 2.1 Hiera Large via Grounded-SAM-2 commit
   `b7a9c29f196edff0eb54dbe14588d7ae5e3dde28`; prompt `hand. arm.`, propagation
   step 10, box threshold 0.35, text threshold 0.25. All 750 frames contain a
   tracked mask; area min/median/max is 5,082/11,031/27,533 pixels. No mask was
   hand edited.
2. Official ProPainter commit
   `e870e79321c31b733e2031af5aa2fb1fe3ac7eec`, one continuous 750-frame FP16
   run at 640x360, official 4-pixel mask dilation. RAFT flow tensors were
   offloaded to CPU as a memory-placement change only. QA found 12,029,883
   changed pixels inside the dilated mask and exactly zero outside. Thin tools
   and cast shadows were deliberately not assigned invented masks.

Exact depth branch:

1. The lossless ProPainter RGB is cropped by one fixed camera ROI x=0, y=120,
   width=640, height=240 to remove permanent legs/feet and non-surface framing.
   This is an identical camera crop on every frame, not a semantic mask.
2. Official Video Depth Anything Small, commit
   `4f5ae23172ba60fd7bc11ef671cca678842c7072`, estimates temporally consistent
   monocular relative depth. Any2Full is intentionally absent: the archive has
   no LiDAR/Kinect samples with which to constrain metric completion.
3. Each frame is robust-affine aligned to one temporal-median reference using
   automatically selected stable pixels; coefficients receive a 25-frame
   median filter. One fixed temporal-reference Gaussian camera plane at sigma
   45 pixels is removed. The inverse-depth convention is detected from the
   fixed camera geometry.
4. A single spatial-median offset from the fixed central ROI locks false global
   surface translation. There is no per-frame scale/range normalisation. One
   sequence-wide p0.5/p99.5 symmetric span encodes every frame around 0.5. The
   final encoded frame-median range is 0.495558--0.500764; this is the explicit
   whole-surface height-jump gate.

Reusable materializer:

```text
tools/materialize_archive_video_only_probe.py
```

It retains the complete 25 fps audit sequence as 750 RGB PNGs + 750 relative
depth PNGs and writes the model commits, masks, ROI, stabilisation choices,
ELAN spans and ordered-sequence hashes into `processed_manifest.json`. It also
creates 320x120 synchronized Theora delivery streams. The Web delivery is 5
fps/150 frames (source step 5), while analysis/provenance remains 25 fps/750
frames. The depth OGV decode audit against selected PNGs is 0.844/255 mean
absolute error, 2.913/255 mean frame-p99, and 18/255 absolute worst-case. The
Godot mesh is 159x59 subdivisions; the texture/depth delivery images remain
320x120.

The Godot runtime now treats a packed-video manifest as provenance/UI data
instead of continuing to fetch and apply two remote PNGs per frame. Initial
PNG prefetch/autoplay buffering is skipped for packed sessions, video playback
and explicit seeks set both streams to the same playhead, and the source label
follows the equivalent audit-frame index. This removes the deterministic
remote-PNG playhead rollback. Automated Chrome playback remained subject to
background Canvas throttling, so its wall-clock ratio is not claimed as a
foreground performance measurement; direct visual QA confirmed that both
packed textures advance and no per-frame PNG stall recurs.

Selected local session:

```text
tmp/opencode/session_archive_wdva1_mir25_video_only_relative_v1
```

It contains 1,506 files / 74,341,126 bytes. Hashes after the final materialise:

```text
session.json          3829e535d5dc5fb181e39f9aa9e87efa1bbb296c360bd6eec242414116f487fa
processed_manifest    352ea79e4517c5b66fb7be1c4cf6d976044e3c8598dc4ff3b03dc88237177056
depth_stream.ogv      df16205d881d8a50079e6ad3598c165402b8c3b2f63d3eb09fa3d5bb3736d111
texture_stream.ogv    f387b762d0a2673e2d5d4c2016affdd49ede59e6af1bdb67fb2d3b2a6f013c46
```

The session is explicitly `comparison_only=true`,
`readyForDataCollection=false`, `metric=false`, and has no object/tool or
virtual-hand reconstruction. Review URL:

```text
http://localhost:8845/index.html?session=http%3A%2F%2Flocalhost%3A8845%2Fassets%2Fprocessed_sessions%2Fsession_archive_wdva1_mir25_video_only_relative_v1%2Fsession.json&debug=1&autoplay=1&t=wdva1-mir25-packed-ogv5-final-20260804
```

## 2026-08-08 experiment-platform readiness hardening

The infrastructure items that do not depend on the next dry-sand capture have
been implemented. The standard participant route now fails closed: an unready
session cannot advance past study information, and an unavailable experiment
server cannot be replaced by the old deterministic client assignment during a
formal run. `researcher=1` and `pilot=1` remain explicit QA routes. The server
accepts an unready run only when started with `-AllowConditionOverride`, records
it as `pilotRun`, and rejects a non-pilot completion whose submission fails
readiness.

Readiness now requires all of the following:

- matching `experiment.protocolId` and an explicit protocol-level
  `ethicsApprovedForDataCollection=true`;
- sand, gestures, objects and narration for the Stage 1 contrast source;
- validated surface/gesture/reference relations for Stage 2;
- creator-authored summary prompt and stage questions, plus a public validation
  receipt covering every question; expected answers/coding rules remain in
  researcher-only storage;
- a neutral `participantTitle` and `minimumPlaybackProgress`;
- a separate `experiment.trainingSession` with sand + hand data, plus named
  `trainingCues.playback` and `trainingCues.referential` moments.

The host now really switches to the neutral session during guided practice and
back to the assessed story before applying the assigned condition. Guided
playback no longer assumes that time zero contains meaningful action. The
participant UI hides technical session titles and explicit condition names;
unavailable/omitted modality toggles are not displayed. Formal tasks require
the configured playback progress, evidence text, and at least one timestamped
snapshot per question. Up to six snapshots can be attached without overwriting
earlier evidence. NASA-TLX values remain unset until the participant touches
each slider, and modality-reliance choices are filtered to what was actually
available in that condition.

The desktop layout is viewport-bounded so a long right-hand task scrolls inside
its card instead of stretching the Godot canvas and pushing transport controls
far below the screen. Mobile layout still stacks naturally. Stage 2 now has a
server-balanced relation-order contract (`hidden_then_visible` versus
`visible_then_hidden`) stored with the run. Stage 1 has an empty protocol
`stimuli` registry and `assignmentUnit=condition_x_story`, ready to be populated
after the two final self-authored stories exist; no placeholder story is treated
as experimental material.

Browser QA exposed and fixed one additional seek race in remote per-frame PNG
sessions. Godot reports the requested playhead immediately, but the host must
not start playback until the corresponding surface-frame textures have loaded;
otherwise `_update_surface_frame_from_time()` can pull the playhead back to the
previous displayed frame. The host now polls `get_state` until `frameIndex`
changes. Guided playback using the v21b pilot fallback cue now starts at
3.565 seconds and ends at 6.0 seconds instead of replaying from zero. User
timeline scrubbing while playing uses pause → seek-and-wait → resume for the
same reason.

Actual 1280×720 browser measurements after the layout fix: workspace/viewer/task
cards are 620 px tall (top 76, bottom 696), the sand stage is 418 px tall, and
the transport remains inside the viewport. The old page was 1,883 px tall with
transport near y=1,667; the updated body is 782 px including the footer. Formal
v21b entry showed the neutral title/condition and a disabled Continue button.
Explicit pilot entry created a server record with `pilotRun=true` and
`readyForDataCollection=false`. Guided training completed, condition names were
not shown in the participant task, two evidence marks accumulated without
overwrite and could be removed, unavailable modality choices were absent, and
all six NASA-TLX outputs displayed `Not set` until individually touched.
An explicit Stage 2 pilot also reached guided practice and persisted
`assignmentMethod=server_stage2_balanced_order` with order
`hidden_then_visible`; the complementary order is covered by the 9/9 automated
balanced-block test.

Static preflight and the session schema were extended for these fields. The
preflight accepts `--training-session` or resolves the declared training path.
The JavaScript/API/preflight suite passes 9/9 tests as of this update.

Intentionally deferred until the sand is dry and new capture is possible:

- record at least two complete self-authored stories plus a separate neutral
  training sequence;
- produce real narration, object/tool tracks, creator questions/rubrics and
  Stage 2 referential annotations;
- populate the Stage 1 stimulus registry and exercise the paired Stage 2 order
  with the real annotated material;
- replace placeholder participant information/consent, set the ethics switch,
  and approve deployment, retention, access and backup policy.

## 2026-08-11 full-sequence Casper + Any2Full v22d

The full 714-frame Kinect shadow-removal experiment is complete and locally
reviewable. The prior apparent Casper limitation was a distributed host-memory
bug: every rank loaded and VAE-encoded the full RGB/mask sequence. The fixed
path makes rank 0 the only full-resolution loader/encoder, releases T5/VAE as
soon as their stages finish, chunks reference noise, and broadcasts only the
compact FP16 conditioning tensor. This permits one continuous three-GPU,
50-step Casper CoGVideoX-5B run; no window stitching is used.

The selected session is
`session_kinect_20260623_154953_v22d_casper_lowfreq_any2full_vda_stable` under
`C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode`. Godot displays
the pure full-frame Casper RGB. Any2Full Large/ViT-L receives conservative
Casper low-frequency + ProPainter detail conditioning and only
quality-filtered Kinect grid4 metric anchors outside the model-derived
human/object union mask. VDA Small supplies temporal deltas only. Tuned
bidirectional stabilization reduces broad jumps from 2 to 0, mean adjacent
height difference from 1.4748 to 0.9271, p95 from 5.0181 to 2.0136, and the
maximum whole-surface median jump from 3.9744 to 1.0292. The sampled Kinect
holdout MAE changes from 1.2869 to 1.3093 mm.

The local session has 714 RGB/depth/mask triplets and passed browser seek and
playback QA at frames 300--307 with no warning/error log. The exact package
SHA-256 is
`fe0ffe71947bc05be2b668e2e7768457c92a69d710e7745414a0e1f693e600de`.
Complete provenance, root-cause analysis, commands, metrics, limitations and
the review URL are in `docs/KINECT_CASPER_ANY2FULL_V22_WORKFLOW.md`.

## 2026-08-12 Any2Full hand-region temporal-anchor v22p

The remaining v22k motion was traced to consecutive hand-masked pixels where
frame-independent Any2Full had no current metric observation. A bounded probe
rejected denser outside-mask grid2 and alternate RGB conditioning, then selected
bidirectional metric anchors only when the nearest visible Kinect samples
before and after agree within 1.5 mm.

The complete 714-frame rerun added 625,489 accepted anchors and reduced raw
persistent-completion motion from 0.6779 to 0.1819 mm while preserving the far
visible-surface value and slightly improving Kinect holdout MAE from 1.2600 to
1.2522 mm. The final v22p candidate reuses v22k's scalar corner lock,
five-frame median, stable-plane sigma-6 correction and RG16 encoding. Under the
same displayed-height analyzer, v22k -> v22p persistent hand-region motion is
0.5761 -> 0.1330 and mask-transition motion is 1.1064 -> 0.3243 height unit;
far-surface motion is unchanged within 0.004 height unit.

Selected session:

```text
C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\tmp\opencode\session_kinect_20260623_154953_v22p_temporal_anchor_stable_plane_gauss6_rg16
```

It contains 714 RGB/depth/validity-mask triplets. Browser QA covered continuous
frames 1--204 and 402--566 with no warnings or errors. Full method, metrics,
limitations and the review URL are in
`docs/KINECT_CASPER_ANY2FULL_V22_WORKFLOW.md`.
