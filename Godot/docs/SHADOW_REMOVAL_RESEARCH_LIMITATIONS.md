# Shadow Removal: Research Directions, Quality Gates, and Limitations

Date: 2026-07-27
Accepted baseline: `session_kinect_20260623_154953_virtual_hand_v20d_cerulean_blue_final`

## 1. Scope and non-negotiable constraints

The accepted v20d session is immutable. Shadow-removal experiments must be
materialized under separately named branches and must not silently modify the
accepted RGB, depth, MANO motion, or appearance assets.

The intended edit is unusually strict:

- remove the cast shadow associated with the observed hand/arm;
- preserve the sand deformation caused by that hand;
- preserve real grain-scale texture and existing grooves;
- avoid inventing a hand-authored cleanup mask;
- remain temporally stable; and
- preserve pixels outside the automatically inferred actor/effect region.

This is not ordinary object deletion. The hand, its cast shadow, and the sand
deformation are causally coupled, but the desired output removes only the first
two visual causes while retaining the deformation.

## 2. What has already been established

The hard quality gate is global frame 82 and its temporal neighbourhood.
Existing automatic evidence shows a broad, soft, central shadow rather than a
fully clipped black region. In the high-confidence shadow core, median RGB is
approximately `[123, 121, 133]`; only about 10% of core pixels have luma at or
below 64. The problem is therefore not simply unrecoverable black clipping.
The stronger obstacles are reduced texture signal-to-noise ratio, uncertain
penumbra support, chromatic shift, and the absence of a paired shadow-free
observation of the same deforming sand state.

The following candidates were run on real project data and rejected:

| Candidate | Intended advantage | Observed hard-frame failure |
|---|---|---|
| ProPainter | temporally propagated video inpainting | blurred/replaced sand texture while the cast shadow remained problematic |
| EffectErase, Wan 1.3B | prompt-conditioned actor/effect removal | regenerated a large portion of the sand surface |
| DiffuEraser | dedicated diffusion video inpainting | produced a bright white core and retained penumbra |
| scalar/RGB illumination gain | retain the captured texture | amplified chroma/noise and produced magenta/overbright core pixels |
| real temporal clean plate | use observed sand rather than generation | leaked future groove/deformation state into earlier frames |

No candidate passed the fidelity gate, so no shadow-removal v21 session was
published.

The v20d dense depth is also not an independent geometry oracle. It was
completed by Any2Full ViTL using object-masked RGB, fixed sparse Kinect anchors,
and per-frame held-out Kinect bias correction. Depth and normals are valuable
constraints, but any method that treats them as shadow-independent ground truth
would overstate the evidence.

## 3. Direction matrix

| Direction | Public readiness | Fit to this recording | Main risk | Current decision |
|---|---:|---:|---|---|
| Generative Omnimatte / Casper, CogVideoX-5B | runnable and probed | high semantic fit: models an actor together with associated shadow/reflection effects | raw output redraws/denoises valid high-frequency evidence; public CogVideoX reimplementation is weaker than the original Lumiere model | retain as the strongest review candidate; use measured-detail fusion and do not call it ground truth |
| Original Omnimatte | runnable research code | medium | per-video residual decomposition may absorb real, changing sand deformation into the actor layer | research reference, not first production candidate |
| FactorMatte | runnable research code | medium | counterfactual layer priors remain ambiguous on a deformable surface; per-video optimization cost | possible diagnostic decomposition |
| OmnimatteRF | runnable research code | low–medium | unnecessary 3D radiance-field complexity for a fixed top-down camera; pose/background sensitivity | do not prioritize |
| OmnimatteZero | public code | medium | attention-derived masks/effects and approximately 32 GB recommended memory; no direct truth guarantee | lower priority than full Casper probe |
| EasyOmnimatte | code/checkpoints unavailable as of review | potentially high | cannot reproduce yet; reported peak memory is also near/above a single 2080 Ti | revisit after official release |
| Object-WIPER | CVPR 2026 paper; release promised but no usable public implementation located | high semantic fit and training-free | still reconstructs hidden content through a video diffusion prior; not currently reproducible | strongest watch-list candidate |
| SVOR | official code and weights released | high effect-removal and temporal fit | public release is built on Wan2.1-VACE-1.3B and uses about 33 GB without offload; a smaller base is not automatically more faithful | compare only after the full 5B Casper quality gate |
| UnderEraser | official inference code and weights released | high effect-understanding fit | Wan2.1-Fun-14B base is much larger; public inference path does not document three-card sequence parallelism | investigate if Casper fails and storage/runtime budget permits |
| ROSE | project and paper public; no runnable release located | high task match: explicitly models shadows/reflections/light | synthetic paired supervision may not transfer to deformable microgeometry | watch for code/checkpoint release |
| VOID object/interaction deletion | public, very large | semantic fit is tempting | 40 GB+ pipeline and may delete genuine hand-created deformation together with shadow | not suitable for evidence-preserving output |
| Open-VSRD | paper/dataset direction only | high task match | no usable official implementation/checkpoint located | cite and revisit |
| PSTNet and related video-shadow networks | paper; incomplete public path | high task match | no reliable reproducible release found | cite and revisit |
| PhaSR | official image code and model zoo released | high geometric/illumination relevance and computationally light | image-only; relies on monocular Depth Anything normals and has no temporal identity constraint | practical per-frame benchmark, followed by strict temporal evaluation |
| HomoFormer and image shadow removers | public weights for some models | medium on individual frames | image-domain prior and no temporal identity; domain gap to deformable sand | fallback benchmark, not preferred output |
| Shadow-removal refinement / CDD | public refinement code | useful at edges only | requires a credible upstream removal and shadow mask; cannot recover a wrong core | use only after a core method passes |
| SoftShadow / detail-preserving diffusion / MetaShadow | promising papers | potentially high | official runnable checkpoints not located; mostly image-based | research watch list |
| RGB-D illumination/reflectance decomposition | implementable | physically interpretable | intrinsic decomposition is underdetermined; completed depth is RGB-conditioned; normals do not reveal occluded albedo | useful constraint/diagnostic, not a truth source |
| Temporal clean plate / background mosaic | implementable | excellent for rigid scenes | invalid when the sand state changes because of the same interaction | rejected for this sequence |
| Capture-side diffuse or multiplexed light | requires recapture | highest reliability | changes acquisition hardware/protocol | primary recommendation for future studies |

## 4. Full Casper quality-first probe

The active quality-first test uses the public Generative Omnimatte
CogVideoX-5B recommendation rather than the weaker 1.3B variant.

- input: exact raw RGB frames 40–124, inclusive;
- temporal window: 85 frames at 10 fps;
- spatial size: 480 × 640, preserving the 4:3 capture geometry;
- actor support: exact existing Grounded-SAM2 `hand. arm.` masks, without
  hand-drawn extensions;
- prompt: fixed top-down blue-rimmed sandbox with light grey sand;
- mode: clean-background / actor-associated-effect removal;
- sampling: FP16, 50 inference steps;
- distribution: sequence parallelism across all three Amadeus GPUs;
- quality target: global frame 82, which is clip index 42.

The experiment is an admission test, not a presumed solution. It must be
rejected if it creates plausible but unobserved grain structure, changes grooves,
alters pixels outside the inferred effect area, produces colour drift, or
introduces temporal boiling.

### Three-GPU result

The full probe completed successfully on three NVIDIA RTX 2080 Ti GPUs. The
public configuration defaults to BF16, which is not a practical native
execution mode on this Turing hardware. Direct FP16 execution first overflowed
one text-condition residual value at diffusion step 1, transformer block 13;
that single overflow subsequently contaminated the full latent tensor. The
compatibility path therefore:

- uses xFormers CUTLASS attention, numerically checked against full attention;
- uses three-way Ulysses sequence parallelism;
- accumulates only the small text residual branch in FP32 before converting
  back to FP16;
- clamps only values outside the representable FP16 range; and
- keeps layer- and diffusion-step finite-value assertions active.

This is a numerical range compatibility measure, not a smaller model or a
lower-resolution run. The 50 denoising steps completed in about 3 minutes after
model/input preparation. All `1,689,600` latent values were finite; the saved
latent range was `[-2.3457, 2.5918]`.

The decoded 85-frame result removed the central hand/arm-associated shadow and
retained the correct temporal construction of the circular groove. It did not
copy the completed future groove into earlier frames. The raw decoded video is
very stable but performs a mild whole-frame VAE reconstruction:

- mean global RGB MAE against the v20d source: `10.80 / 255`;
- mean global structural similarity: approximately `0.946`;
- retained sand high-frequency energy outside the dilated actor support:
  approximately `77.9%`; and
- mean adjacent-frame change on the retained sand region: `0.109`, versus
  `3.217` in the captured source.

The raw output is therefore semantically strong but too denoised to replace
the measured RGB directly.

### Measured-detail fusion

A one-level Laplacian fusion keeps the original measured detail while taking
only Casper's broad, shadow-free appearance:

```text
fused = source + blur(Casper, r) - blur(source, r)
```

The correction is applied only inside the existing registered
`surface_mask.png`; no shadow polygon, hand-authored matte, image-position
rule, or heuristic actor-mask extension is introduced. A one-pixel Gaussian
radius was selected after larger `8/16/24` and `4/6` pixel bands visibly
reintroduced the shadow's mid-frequency oval. On all 85 probe frames, the
one-pixel candidate measured:

- exactly `0 / 11,612,275` changed pixels outside the registered surface;
- mean global structural similarity `0.9844` against the source;
- `97.4%` retained sand high-frequency energy;
- adjacent-frame sand change `1.744`, versus `3.217` in the source; and
- at frame 82, only `0.38%` residual low-frequency difference relative to the
  original-to-Casper shadow correction over `32,046` automatically detected
  broad-brightening pixels.

These metrics make the fused probe suitable for playback review. They do not
prove the generated low-frequency counterfactual is the true shadow-free
radiance. v20d remains the immutable accepted baseline, and no production
`v21_shadow_removed` session has been published.

Probe artifacts:

```text
tmp/shadow_analysis/casper_results/cog5b_3gpu_safe50_f040_124/
  sand_f040_124-casper-cog5b-safe50.mp4
  fused_hard_surface_radius_01.mp4
  output_timeline_9.png
  input_timeline_9.png
```

Reproducible tools:

```text
SandStories/Godot/tools/run_casper_cog5b_3gpu_safe_amadeus.sh
SandStories/Godot/tools/decode_casper_latents_amadeus.py
SandStories/Godot/tools/fuse_casper_lowfreq_with_source.py
```

## 5. Evaluation protocol

No-reference perceptual quality alone is insufficient. A generated sand surface
can look convincing while being scientifically false. A candidate must pass all
of the following:

1. **Outside-edit preservation.** Compute RGB MAE, SSIM, and high-frequency
   energy change outside the automatic actor/effect support. Any broad scene
   regeneration is a hard failure.
2. **Shadow residual.** Measure remaining luminance/chromatic discontinuity
   across the automatic shadow core and penumbra, while excluding tray edges.
3. **Texture continuity.** Compare local gradients and oriented high-frequency
   structure across the former shadow boundary. Uniform bright fill is a hard
   failure.
4. **Temporal stability.** Measure frame-to-frame residual after local motion
   compensation and inspect for flicker, boiling, duplicated grooves, and
   delayed shadow remnants.
5. **Causal preservation.** Manually verify that real sand deformation remains
   at the correct time. A temporally clean but causally wrong surface fails.
6. **Hard-frame visual review.** Review a contact sheet and playback centred on
   frame 82 before considering a longer run.

Passing these tests demonstrates that the candidate is less destructive than
the rejected alternatives; it still does not prove recovery of the true
unobserved shadow-free radiance.

## 6. Recommended boundary for the current project

For the existing recording, retain v20d as the scientific baseline. The fused
Casper probe is the current optional visual-review candidate because it passes
the bounded hard-frame checks above, but it still requires human playback
review and a longer/full-sequence run before any production promotion. A
visible, documented cast shadow remains preferable to a clean-looking but
fabricated sand history.

For future data collection, prevention is more defensible than post-hoc
generation:

- use a large diffuse overhead source or symmetric multi-light arrangement to
  reduce the umbra at capture time;
- if hardware permits, use synchronized or rapidly multiplexed lighting so
  differently illuminated observations correspond to the same hand/sand state;
- capture higher bit depth or bracketed exposure to improve shadow-region SNR;
- use flash/no-flash detail transfer only when the pair is synchronized tightly
  enough to avoid hand and sand-state mismatch;
- treat cross-polarization as a specular-control technique, not cast-shadow
  removal.

## 7. Limitation text suitable for the thesis

### Concise version

Cast-shadow removal was investigated but not assumed to recover a unique ground
truth. The hand simultaneously occludes, shades, and deforms the sand, while no
paired shadow-free observation exists for the same evolving surface state.
Temporal inpainting can therefore import an incorrect sand state, and
generative removal can produce perceptually plausible but unobserved texture.
Depth and surface normals provide useful constraints but are not independent
ground truth because dense depth was completed from RGB with sparse Kinect
anchors. We consequently retain the original shadow whenever a candidate
cannot preserve local texture, deformation timing, and pixels outside the
automatically inferred effect region.

### Expanded version

Removing the participant's cast shadow is an underdetermined counterfactual
editing problem rather than a conventional restoration problem. The desired
image asks how the deformable sand would have appeared under different
illumination while retaining the deformation caused by the same hand. No
simultaneous shadow-free target is available, and frames from other times are
not interchangeable because the sand geometry changes during interaction.
Classical illumination correction preserves observed samples but becomes
unstable where shadow-region chroma and fine texture have low signal-to-noise
ratio. Video inpainting and diffusion models can improve perceptual coherence,
but may redraw grooves or grain structure and thus alter experimental evidence.
Furthermore, the dense depth and derived normals used in this project are
conditioned partly on RGB and sparse Kinect anchors, so they cannot fully
disambiguate reflectance from illumination. The system therefore reports
shadow removal as an optional visual transformation, evaluates it with strict
outside-region preservation and temporal/deformation checks, and retains the
unmodified v20d baseline whenever those checks fail.

## 8. Primary references

- Lu et al., [Generative Omnimatte](https://gen-omnimatte.github.io/) and its
  [public CogVideoX reimplementation](https://github.com/gen-omnimatte/gen-omnimatte-public).
- Kushwaha et al.,
  [Object-WIPER](https://openaccess.thecvf.com/content/CVPR2026/html/Kushwaha_Object-WIPER_Training-Free_Object_and_Associated_Effect_Removal_in_Videos_CVPR_2026_paper.html).
- Hu et al., [SVOR](https://github.com/xiaomi-research/SVOR).
- Liu et al., [UnderEraser](https://github.com/WeChatCV/UnderEraser).
- Miao et al., [ROSE](https://rose2025-inpaint.github.io/).
- Lu et al., [Omnimatte](https://omnimatte.github.io/).
- Gu et al., [FactorMatte](https://factormatte.github.io/).
- Lin et al., [OmnimatteRF](https://omnimatte-rf.github.io/).
- Samuel et al.,
  [OmnimatteZero](https://github.com/dvirsamuel/OmnimatteZero).
- Xiao et al.,
  [Shadow Removal from a Single RGB-D Image](https://openaccess.thecvf.com/content_cvpr_2014/html/Xiao_Shadow_Removal_from_2014_CVPR_paper.html).
- Bonneel et al.,
  [Intrinsic Decomposition of Image Sequences](https://perso.liris.cnrs.fr/nbonneel/intrinsic.htm).
- Hu et al.,
  [Shadow Removal Refinement via Material-Consistent Shadow Edges](https://openaccess.thecvf.com/content/WACV2025/papers/Hu_Shadow_Removal_Refinement_via_Material-Consistent_Shadow_Edges_WACV_2025_paper.pdf).
- Wang et al.,
  [SoftShadow](https://openaccess.thecvf.com/content/CVPR2025/html/Wang_SoftShadow_Leveraging_Soft_Masks_for_Penumbra-Aware_Shadow_Removal_CVPR_2025_paper.html).
- Xu et al.,
  [Detail-Preserving Latent Diffusion for Stable Shadow Removal](https://openaccess.thecvf.com/content/CVPR2025/papers/Xu_Detail-Preserving_Latent_Diffusion_for_Stable_Shadow_Removal_CVPR_2025_paper.pdf).
- Lee et al., [PhaSR](https://github.com/ming053l/PhaSR).
- Eisemann and Durand,
  [Flash Photography Enhancement via Intrinsic Relighting](https://hhoppe.com/proj/flash/).
