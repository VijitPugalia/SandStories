# SandStories Web experiment bridge

SandStories can run as an embedded Godot canvas while an ordinary web page
owns the experiment controls, instructions, consent flow, questionnaires, and
data collection UI.

## Demo host

Build and start the normal review server, then open:

```text
http://localhost:8845/experiment_host.html
```

The host implements the proposal's six-step participant flow:

1. study information and consent;
2. anonymous background questionnaire;
3. baseline viewer training;
4. the assigned interpretation task and timestamped evidence;
5. confidence, difficulty, usability, modality reliance, and NASA-TLX; and
6. an anonymous server submission with a downloadable backup.

Stage 1 requests randomized balanced-block assignment from the experiment
server across the five proposal conditions. Its old deterministic client hash
is retained only as an offline pilot fallback and must not be used for formal
recruitment. Stage 2 adds the participant group, think-aloud prompts,
relation-oriented training, annotation usefulness, and uncertainty/interview
notes.

The participant route now fails closed. It cannot leave study information
unless the main story, a distinct neutral training session, the active
protocol, creator questions/validation receipt, required modalities, and the ethics switch
all pass readiness. `researcher=1` or `pilot=1` is an explicit QA escape hatch;
those runs are labelled `pilotRun` and are not research data. The server also
rejects an unready run unless it was started by a QA-enabled server.

Useful launch parameters:

```text
?stage=stage1|stage2
&participant=<anonymous-code>
&condition=baseline|no_audio|no_gestures|no_objects|no_sand|stage2
&session=<encoded-session-json-url>
&training_session=<encoded-training-session-json-url>
&researcher=1
&pilot=1
```

The host embeds `index.html` with `embed=1`, which hides the Godot HUD. The
standard HTML controls communicate with the iframe through same-origin
`postMessage`.

`researcher=1` exposes a separate pilot drawer for stage, condition, session,
RGB surface colour, event diagnostics, reset, and draft export. These controls
are not shown to participants.

The host reads `experiment_protocol.json` and the selected session's
`experiment` object. Session-specific `summaryPrompt`, `stage1Questions`, and
`stage2Questions` take precedence over the visibly labelled pilot fallback
questions. A formal session must also provide `participantTitle`,
`questionValidation`, `minimumPlaybackProgress`, and `trainingSession`.
`questionValidation` exposes only an opaque rubric ID and the validated
question IDs; expected answers and coding rules stay in researcher storage,
not in participant-served JSON. The training session provides
creator-checked `experiment.trainingCues.playback` and
`experiment.trainingCues.referential` moments, so guided practice no longer
assumes that time zero contains an action. The host switches to this session
for training and back to the assessed story before the task.

For remote per-frame PNG sessions, a seek command can update the playhead before
the requested surface textures finish loading. The host therefore waits until
Godot reports a changed surface-frame index before starting a guided cue.
Timeline scrubbing while playing follows the same pause → seek-and-wait → resume
sequence, preventing the older displayed frame from pulling playback back.

Each question can set `minEvidenceMarks` (one by default). Participants may
attach up to six timestamped view/layer/camera snapshots instead of silently
overwriting one snapshot. Formal runs also enforce the configured playback
progress. NASA-TLX sliders are unset until touched, and questionnaire modality
choices include only the sources that were actually available in the assigned
condition.

Draft responses are written locally first and then synchronized to the
same-origin experiment API. The local copy is the offline queue and the manual
JSON download remains an emergency backup; it is no longer the primary
submission path. A refresh resumes the server run using an anonymous bearer
token kept in local storage. Failed saves retry when the browser is online.

The bundled server performs randomized balanced-block assignment for Stage 1,
stores idempotent event batches separately from the latest draft, and makes a
completed run immutable. It also balanced-block assigns the two Stage 2
relation orders declared in `experiment_protocol.json` and stores the selected
order with every run. The Stage 1 `stimuli` list and `assignmentUnit` are the
reserved story-allocation contract to populate when the final two self-authored
stories exist. Final deployment still needs ethics-approved copy and an
approved access, retention, backup, and hosting policy.

## Experiment persistence API

`tools/static_server.mjs` serves both the Web build and these same-origin routes:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/experiment/health` | storage and protocol health |
| `POST` | `/api/experiment/runs` | create a run and assign its condition |
| `GET` | `/api/experiment/runs/:id` | resume metadata and latest draft |
| `PUT` | `/api/experiment/runs/:id/draft` | atomically replace the current draft |
| `POST` | `/api/experiment/runs/:id/events` | append an idempotent event batch |
| `POST` | `/api/experiment/runs/:id/complete` | persist and seal the final submission |

All run-specific routes require the `X-SandStories-Run-Token` returned at run
creation. Only a SHA-256 digest of that token is stored on the server. Run data
defaults to `server_data/experiments`; pass `-ExperimentDataDir` to
`start_review_server.ps1` to change it. The on-disk representation is an
internal persistence format, not the final research export schema.

Condition overrides and pilot-run acceptance are disabled by default. Start a
local QA server with `-AllowConditionOverride` only when a fixed `condition=`
launch URL or an unready `pilot=1` run is needed.

## Preflight

The static preflight reads the existing session contract directly; it does not
introduce a second story manifest:

```powershell
node .\tools\experiment_preflight.mjs `
  --session C:\path\to\session.json `
  --training-session C:\path\to\training_session.json `
  --protocol .\data\experiment_protocol.json `
  --project-root .
```

It checks protocol identity and ethics state, the independent training story
and timed cues, all required modalities, participant title, question-validation
coverage, playback requirement, annotation references, temporal bounds,
processed-manifest counts and ordering, and every referenced clean
RGB/depth/MANO frame asset. It intentionally fails v20d because v20d has no
real narration, objects, formal questions, Stage 2 relations, separate neutral
training story, or ethics-approved copy; that is a content-readiness result,
not a playback regression.

`tools/validate_experiment_runner.gd` is the runtime half of preflight. It
applies all five Stage 1 conditions and verifies that each omitted layer is
both invisible and locked, then verifies that baseline restores the layers.

Infrastructure tests run with:

```powershell
node --test .\tools\experiment_api.test.mjs .\tools\experiment_preflight.test.mjs
```

## Direct JavaScript API

On `index.html`, the bridge is available as `window.SandStories`:

```js
await window.SandStories.ready;
await window.SandStories.play();
await window.SandStories.seek(4.5);
await window.SandStories.setCondition("no_gestures");
await window.SandStories.setLayer("objects", false);
await window.SandStories.setSurfaceControl("material_strength", 0);
await window.SandStories.setView("top");
const state = await window.SandStories.getState();
```

Supported commands:

| Command | Payload |
| --- | --- |
| `get_state` | `{}` |
| `set_playing` | `{ playing: boolean }` |
| `toggle_playback` | `{}` |
| `seek` | `{ seconds: number }` |
| `seek_normalized` | `{ progress: number }`, clamped to `0..1` |
| `load_session` | `{ url: string }` |
| `set_condition` | `{ condition: string }` |
| `set_layer` | `{ layer: string, visible: boolean }` |
| `set_surface_control` | `{ key: string, value: number }` |
| `set_view` | `{ preset: "top" \| "front" \| "orbit" }` |
| `set_focus_mode` | `{ enabled: boolean }` |
| `set_training_guide` | `{ mode: "off" \| "playback" \| "camera" \| "layers" \| "occlusion" \| "segmentation" \| "referential", step?: number, total?: number }` |
| `mark_evidence` | `{}` |
| `record_host_event` | arbitrary JSON object stored as one `host_event` |

Godot validates commands against these allowlists; the bridge does not expose
arbitrary node paths or method calls.

The training guide uses a dedicated Godot canvas and world-space target, so it
remains visible in embedded mode even though the normal Godot HUD is hidden.
The experiment host always sends `mode: "off"` and restores the training
surface/view state before the main task begins. Tutorial graphics are therefore
not part of an experimental condition or evidence capture.

## Browser events

The Godot page dispatches these `CustomEvent`s:

```text
sandstories:ready
sandstories:state
sandstories:event
sandstories:command_result
```

The latest snapshot is also available as `window.SandStories.state`.

```js
window.addEventListener("sandstories:state", (event) => {
  console.log(event.detail.time, event.detail.playing);
});
```

An iframe parent receives the same messages through `postMessage` with a
matching `type`. Commands sent into the iframe use:

```js
iframe.contentWindow.postMessage({
  type: "sandstories:command",
  requestId: "experiment-command-1",
  command: "seek",
  payload: { seconds: 4.5 },
}, window.location.origin);
```

The embedded page accepts messages only from its parent and from the
`parent_origin` query parameter. The provided host always sets that parameter
to its own origin.

## State snapshot

State messages include:

- session URL and title;
- ready, playing, time, duration, and normalized progress;
- active experimental condition;
- active training-guide mode (`off` outside guided practice);
- layer visibility;
- surface calibration including RGB map blend;
- processed frame index/count; and
- camera position parameters.

This is sufficient for a web experiment shell to keep its UI synchronized
without inspecting the Godot canvas or duplicating reconstruction logic.
