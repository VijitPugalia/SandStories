# Agent Handoff: SandStories Godot RGB/LiDAR Visualization

## Current Objective

Continue making the SandStories Godot/Web visualization credible enough for visual inspection. The user is specifically concerned that the current CV/fusion pipeline is wrong. Do not blindly tune shaders. First verify whether produced height maps align with the RGB visual evidence.

## Project Location

- Godot project: `/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStoriesGodot`
- Raw v2 session used for current work: `assets/sessions/session_7969C412-E9DB-4666-8C48-11312A750035`
- Current fused processed session: `assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment`
- Current diagnostic output: `assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment_height_visual_diagnostic`

## Important Context

- The Godot project was not originally a git repository. It is now being prepared as a local source repository.
- Do not commit large generated data unless the user explicitly asks. Raw sessions, processed sessions, experiment outputs, Web builds, virtualenvs, and export templates should stay local/untracked.
- The iOS capture repo is separate: `/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/SandStories`. That repo already has a GitHub fork and working CI. This handoff is for the Godot project.

## Current Technical Finding

The earlier fused visualization looked wrong because the height map was wrong, not just the shader.

The new independent diagnostic tool showed:

- The first fused height map had almost no agreement with RGB visual evidence.
- Directly mixing current-frame LiDAR delta into the height map was a major error. It introduced hand/tool/occlusion shapes and low-resolution depth noise as fake terrain.
- LiDAR should be used for gating, occlusion plausibility, and low-frequency facts, but not directly added into high-frequency visual height for this fixed-camera diagnostic.
- The current best version uses RGB-derived signed visual height for visible relief and treats persistent RGB-supported updates separately.

## Key Files

- `tools/fixed_camera_change_experiment.py`
  - Main experimental fixed-camera RGB/LiDAR fusion pipeline.
  - Current best version includes `_rgb_signed_visual_height()`.
  - LiDAR delta is no longer directly added to final `fused` height.
  - Current fused height formula is based on signed RGB visual height plus persistent RGB-supported update.

- `tools/diagnose_heightmap_visual_match.py`
  - Independent diagnostic tool added to render height maps with fixed lighting and compare height edges against RGB edges.
  - Produces a contact sheet and numeric metrics.
  - This is the main sanity check before shader/Web tuning.

- `tools/sync_fused_experiment_session.py`
  - Syncs experiment output into a compact Godot processed session.
  - Also applies Web-oriented depth/texture contrast enhancement.

- `scripts/main.gd`
  - Godot runtime session loader and visualization logic.

- `assets/shaders/sand_depth.gdshader`
  - Shader consuming the fused height/depth and RGB texture.

- `export_presets.cfg`
  - Web export config. It has been adjusted during experiments. Review before production/full-data exports.

## Diagnostic Tool Usage

Run from the Godot project root:

```bash
.venv/bin/python tools/diagnose_heightmap_visual_match.py assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment --edge-percentile 92 --render-strength 18
```

Important outputs:

- `assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment_height_visual_diagnostic/height_visual_contact_sheet.png`
- `assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment_height_visual_diagnostic/height_visual_diagnostics.json`

Contact sheet columns:

- `rgb`: RGB visual reference.
- `height`: current fused height map.
- `shaded`: fixed-lighting render of the height map.
- `rgb_edges`: high-percentile RGB edge map.
- `height_edges`: high-percentile height edge map.
- `mismatch`: green means RGB and height agree; red means height edge without RGB support; blue means RGB edge missing from height.
- `persistent`: persistent update mask.

## Latest Diagnostic Scores

The values below are for the current best signed-height version:

- `meanCorr`: about `0.233`
- `meanEdgeIou`: about `0.109`

Earlier versions for comparison:

- Original LiDAR-mixed height: `meanCorr` about `-0.003`, `meanEdgeIou` about `0.053`.
- RGB-only unsigned relief: `meanCorr` about `0.099`, `meanEdgeIou` about `0.075`.
- Over-smoothed mid-scale residual: `meanCorr` about `-0.046`, `meanEdgeIou` about `0.027`.

Interpretation: the current signed-height version is the least wrong so far, but still not a final geometric reconstruction. It preserves the obvious large grooves/letter-like marks better than the other versions, but it can still amplify sand grain texture.

## Current Web Visualization

Latest local Web URL used for validation:

```text
http://127.0.0.1:8775/index.html?session=res://assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment/session.json&debug=1&fused=signedheight1
```

Latest screenshots:

- `/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/sandstories-signedheight-web.png`
- `/mnt/c/Users/lj200/Documents/ProjectUniMelb/Sandiv/sandstories-signedheight-afterplay.png`

Validation state:

- Godot WebGL loaded successfully.
- Canvas size was `1280x720`.
- Playback click was tested and after-play screenshot was captured.
- Console only showed `favicon.ico` 404 and WebGL `ReadPixels` performance warnings.

## Reproduction Commands

Regenerate the current fixed-camera experiment:

```bash
.venv/bin/python tools/fixed_camera_change_experiment.py assets/sessions/session_7969C412-E9DB-4666-8C48-11312A750035 --width 960 --frame-range 1:1822:6 --contact-sheet-count 12
```

Sync experiment into the Godot processed session:

```bash
.venv/bin/python tools/sync_fused_experiment_session.py assets/experiments/session_7969C412-E9DB-4666-8C48-11312A750035_fixed_camera_change assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment
```

Run height-vs-visual diagnostic:

```bash
.venv/bin/python tools/diagnose_heightmap_visual_match.py assets/processed_sessions/session_7969C412-E9DB-4666-8C48-11312A750035_fused_experiment --edge-percentile 92 --render-strength 18
```

Build Godot Web export:

```bash
powershell.exe -ExecutionPolicy Bypass -File "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStoriesGodot\tools\build_web.ps1"
```

Serve local Web build on a fresh port:

```bash
/home/baleine/.local/node-v24.15.0-linux-x64/bin/node tools/static_server.mjs build/web 8776 127.0.0.1
```

## Suggested Next Steps

1. Use the diagnostic contact sheet before every CV/shader change.
2. Improve signed-height denoising without destroying the large groove/letter alignment. The over-smoothed mid-scale residual was worse, so do not simply blur the height map aggressively.
3. Separate “diagnostic export assets” from Web runtime assets. The latest Web `index.pck` grew because diagnostic PNGs were included.
4. Review `export_presets.cfg` and exclude diagnostic outputs from normal Web builds.
5. If the user says the signed-height Web view still looks wrong, inspect `height_visual_contact_sheet.png` first, not only the Godot render.

## Practical Warning

This pipeline currently produces a visually plausible RGB-supported relief map, not true high-resolution measured geometry. Phrase it as “visual/evidence height” or “RGB-supported signed relief,” not as accurate LiDAR reconstruction.
