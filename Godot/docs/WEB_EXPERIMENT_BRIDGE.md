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

1. study information and pilot consent;
2. anonymous background questionnaire;
3. baseline viewer training;
4. the assigned interpretation task and timestamped evidence;
5. confidence, difficulty, usability, modality reliance, and NASA-TLX; and
6. an anonymous downloadable response package.

Stage 1 uses deterministic client-side assignment across the five proposal
conditions unless a fixed condition is supplied. Stage 2 adds the participant
group, think-aloud prompts, relation-oriented training, annotation usefulness,
and uncertainty/interview notes.

Useful launch parameters:

```text
?stage=stage1|stage2
&participant=<anonymous-code>
&condition=baseline|no_audio|no_gestures|no_objects|no_sand|stage2
&session=<encoded-session-json-url>
&training_session=<encoded-training-session-json-url>
&researcher=1
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
questions. A session is never labelled ready for research data unless its
metadata marks the content as creator-validated and all modalities required by
the selected stage are present.

Draft responses are stored locally under the anonymous participant code and can
be downloaded as JSON. This is a pilot transport only; production recruitment
still needs ethics-approved copy, server-side balanced allocation, secure
submission, and retention controls.

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
