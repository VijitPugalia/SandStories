# Sand Stories Godot Prototype

Godot 4 scaffold for the sand stories probing system described in the proposal.

## Detailed Docs

- `docs/ARCHITECTURE.zh.md`: architecture, runtime layers, data flow, WebGL export, and next engineering steps.
- `docs/EXPLANATION.zh.md`: practical explanation for connecting real depth/material streams, MediaPipe hand landmarks, objects, and annotation links.

## What is already wired

- 3D scene with a reconstructed SandMap RGB-D surface as the default view.
- Reused sand shader from `C:/Users/lj200/Documents/sand-layers`.
- Reused and split OBJ hand models from `C:/Users/lj200/Documents/sand-layers`.
- Reused heightmap reconstruction shader and sample maps from `C:/Users/lj200/Documents/SandMap`.
- Gesture layer driven by independent timestamped hand tracks.
- Split left/right hand meshes with MediaPipe-style 21-point landmark skeletons.
- Procedural translucent hologram hands generated from 21 landmarks, with debug landmarks/skeleton available when needed.
- Object layer driven by session JSON.
- Annotation layer with timestamped 3D labels.
- Sand-region highlighting for segmented drawings on the surface.
- Referential links that connect active hand gestures, labels, drawings, and objects.
- Stage 1 condition selector for baseline, no audio, no gestures, no objects, and no sand surface.
- Stage 2 annotation mode that enables explicit links and highlights for polysemiotic analysis.
- Study task panel with evidence-marking and response-draft logging.
- Two synced fixed-view proxy panes: top-down and front-view.
- Browser-friendly camera controls: left drag orbit, Shift/middle drag pan, wheel/Q/E zoom, WASD/arrow pan, R/1/2/3 presets.
- Bundled Noto Sans SC UI/Label3D font for Chinese names, CJK annotations, and WebGL text rendering.
- Playback controls, time slider, camera rotate/pan/zoom.
- Independent layer toggles for sand, gestures, objects, and annotations.
- Heightmap surface mode can use static PNG maps or optional `.ogv` video streams.
- Surface calibration sliders adjust depth UV offset, texture UV offset, and displacement height.
- JSONL interaction logging to `user://interaction_log.jsonl`.

## Project Layout

- `project.godot`: Godot project config.
- `scenes/Main.tscn`: main scene entry point.
- `scripts/main.gd`: runtime scene, UI, playback, logging, and data loading.
- `assets/models/hands.obj`: imported hand model from the previous shader/model test project.
- `assets/models/hand_left.obj`: split single left-hand mesh.
- `assets/models/hand_right.obj`: split single right-hand mesh.
- `assets/fonts/NotoSansSC-VF.ttf`: bundled CJK font for reliable Chinese text in UI and 3D labels.
- `assets/shaders/sand_surface.gdshader`: imported procedural sand surface shader.
- `assets/shaders/sand_depth.gdshader`: imported texture-driven displacement shader from SandMap.
- `assets/shaders/hologram_hand.gdshader`: translucent virtual-hand shader with rim glow and subtle scanlines.
- `assets/heightmaps/`: imported depth/height map samples from SandMap.
- `assets/source_images/`: original RGB texture paired with the SandMap heightmap.
- `assets/video/sand_layers_test.avi`: archived test capture from the previous prototype.
- Optional `assets/video/depth_stream.ogv`: depth-map video stream used by the heightmap material.
- Optional `assets/video/texture_stream.ogv`: material/RGB video stream used by the heightmap material.
- `data/sample_session/session.json`: sample data matching the prototype schema.
- `data/session_schema.json`: import contract for processed RGB-D, gesture, object, annotation, and task data.
- `docs/ARCHITECTURE.zh.md`: detailed Chinese architecture document.
- `docs/EXPLANATION.zh.md`: detailed Chinese integration and explanation document.
- `tools/split_hands_obj.py`: splits the original double-hand OBJ into independent left/right meshes.
- `tools/refresh_sample_hand_tracks.py`: regenerates the demo hand tracks and mirrors the right-hand landmarks.
- `tools/unicode_font_check.gd`: headless Godot check for CJK glyph coverage and JSON Unicode round-trip.
- `export_presets.cfg`: Web/WebGL export preset.

## Study Probe Controls

The right-side Study Probe panel maps directly to the proposed method:

- Stage 1 conditions omit one modality at a time while keeping the timeline and remaining layers synced.
- Stage 2 enables annotation, sand-surface region highlights, and referential links between gesture events, drawings, and objects.
- `Mark current view as evidence` logs the current timestamp, camera pose, visible layers, and condition to `user://interaction_log.jsonl`.
- `Log response draft` stores participant notes together with the current condition and evidence marker.

The two fixed-view panes are proxies for the top-down RGB/depth and front-view streams described in the proposal. They currently render synced Godot cameras over the reconstructed scene until real top/front video sources are added.

The app also reads Web query parameters for experiment assignment:

```text
index.html?condition=no_gestures
index.html?condition=stage2&video=1&view=top
index.html?unicode=1
```

Supported `condition` values are `baseline`, `no_audio`, `no_gestures`, `no_objects`, `no_sand`, and `stage2`.

`unicode=1` enables a CJK smoke test with 40 Chinese participant names, Chinese task text, Chinese 3D annotations, and a Unicode log event.

## Data Interface

Session files are designed as the boundary between capture/post-processing and the Godot study probe:

- `data_sources.depth_map` and `data_sources.texture_map` are the aligned static SandMap depth/material images used by default.
- `data_sources.depth_video` and `data_sources.texture_video` are synced OGV streams that can replace the static maps with the UI toggle or `?video=1`.
- `participants` accepts UTF-8 strings or objects with `display_name`; Chinese names are rendered in the Study Inspector.
- `hand_tracks` is the preferred multi-hand format, with one independent track per hand and MediaPipe-style 21-point landmarks.
- `mediapipe_hands` is an accepted frame-first MediaPipe export that the runtime normalizes into `hand_tracks`.
- `hand_samples` remains as a legacy single-hand fallback.
- `objects` accepts YOLO/manual detections with `primitive` or optional `model_path` for custom meshes.
- `surface_regions`, `gesture_events`, and `references` encode the Zlatev-style annotation/highlight/link layer.
- `study_tasks` drives the participant-facing task list.

## Run

Open `SandStoriesGodot/project.godot` with Godot 4.x and press Run.

The local Godot binary used for validation is:

```powershell
C:\Users\lj200\Documents\Tools\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64_console.exe
```

## Video Stream Surface

The heightmap surface looks for two optional Godot video resources:

- `res://assets/video/depth_stream.ogv`
- `res://assets/video/texture_stream.ogv`

If those files are present, the shader receives live video textures through `VideoStreamPlayer.get_video_texture()`. If they are absent, the surface falls back to the imported SandMap PNG files.

For Web/WebGL, use `.ogv` streams rather than the archived `.avi`. Keep both videos the same resolution, duration, and frame rate so the depth and material maps stay aligned.

## Web Export

The most reliable local path is the build script:

```powershell
.\tools\build_web.ps1
```

It writes to:

```text
SandStoriesGodot/build/web/index.html
```

The script uses Godot to export `index.pck`, then assembles `index.html`, `index.js`, and `index.wasm` from the official `web_nothreads_release.zip` template.

The direct Godot command is still documented here, but the script is preferred because Godot 4.5.1's full Web export command can fail with an empty configuration-error message even when pack export succeeds:

```powershell
New-Item -ItemType Directory -Force SandStoriesGodot\build\web
& "C:\Users\lj200\Documents\Tools\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_win64_console.exe" --headless --path "C:\Users\lj200\Documents\ProjectUniMelb\Sandiv\SandStoriesGodot" --export-release Web build/web/index.html
```

Use the non-Mono Godot binary for Web export. Godot 4 does not export C#/.NET projects to Web from the Mono build. The machine also needs the Godot `4.5.1.stable` Web export templates installed at:

```text
C:/Users/lj200/AppData/Roaming/Godot/export_templates/4.5.1.stable/
```

The required template files are:

```text
web_nothreads_debug.zip
web_nothreads_release.zip
```

## Test Stream Generation

The current checked-in `.ogv` streams were generated from the archived AVI as placeholders:

```powershell
ffmpeg -y -i SandStoriesGodot\assets\video\sand_layers_test.avi -an -c:v libtheora -q:v 7 SandStoriesGodot\assets\video\texture_stream.ogv
ffmpeg -y -i SandStoriesGodot\assets\video\sand_layers_test.avi -an -vf format=gray -c:v libtheora -q:v 7 SandStoriesGodot\assets\video\depth_stream.ogv
```

Replace those with real synced depth/material streams when capture output is ready.

## Next Integration Points

- Replace `surface_heights` with frame-based height maps for animated sand changes.
- Add top-down/front video panes and audio playback once source media files exist.
- Replace the current fixed-view proxy panes with actual top-down/front video streams once source media files exist.
- Add URL/query-param driven assignment for online Stage 1 conditions.
- Replace sample annotations with exported ELAN/Zlatev-style events.
