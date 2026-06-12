# Depth Diagnostic Protocol

Use this protocol to decide whether fine sand traces are missing because of ARKit smoothing, raw scene-depth limits, low confidence, or visualization mismatch.

## Capture Setup

- Mount the LiDAR iPhone/iPad fixed above the sand. Do not hand-hold it.
- Keep the device still for the full diagnostic run.
- Use a tray area that fills as much of the camera view as practical.
- Run each test twice:
  - **Raw-only depth diagnostic** enabled.
  - **Raw-only depth diagnostic** disabled, so raw + smoothed depth are both exported.

The Depth diagnostic button records for 20 seconds, disables audio, forces the depth motion threshold to `0`, and writes diagnostic counters into `manifest.json`.

## Test Sequence

1. **Flat baseline**: leave the sand undisturbed for the full 20 seconds.
2. **Deep groove**: wait 3 seconds, draw one clearly deep line, then leave the device still.
3. **Shallow groove**: wait 3 seconds, draw one normal storytelling trace, then leave the device still.
4. **Side-lit shallow groove**: repeat the shallow groove with stronger oblique lighting so RGB shadows/texture are visible.

Use the same camera height and sand area for all four tests.

## Offline Analysis

From the repository root:

```bash
python scripts/analyze_depth_diagnostic.py "/path/to/session_UUID"
python scripts/visualize_sandstories_session.py "/path/to/session_UUID" --frame 0 --depth-source raw --save raw_frame_0.png
python scripts/visualize_sandstories_session.py "/path/to/session_UUID" --frame 0 --depth-source smoothed --save smoothed_frame_0.png
```

The analyzer writes:

- `depth_diagnostic_report.json`
- `depth_diagnostic_contactsheet.png`

## Interpretation

- `arkit_smoothing_likely`: raw depth changes are much stronger than smoothed depth changes.
- `raw_depth_change_detected`: raw depth contains measurable geometry change; inspect the contact sheet for trace shape.
- `raw_depth_signal_too_small_or_missing`: raw depth deltas are below a few millimetres in sampled frames.
- `uncertain_no_confidence_stream`: depth exists, but confidence was unavailable.

If RGB shows clear traces but raw depth does not, treat LiDAR as coarse geometry/alignment and use RGB/vision as the primary fine-trace channel.
