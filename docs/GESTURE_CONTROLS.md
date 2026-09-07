# UI Gestures and Control Heuristics

SandStories uses touchless controls while the iPhone is mounted out of reach. Vision hand-pose observations feed a separate, time-based state machine. Drawing strokes and UI-control gestures remain separate data paths.

The normal hand-pose processing target is 15 fps and may reduce to 8 fps under thermal pressure. Gesture timing uses timestamps rather than frame counts, so the same holds apply at either rate.

Vision image orientation follows the active interface orientation. Portrait, upside-down portrait, landscape-left, and landscape-right frames are mapped before hand-pose detection.

## Gesture controls

Operators can enable or disable each control in Settings. Disabling a control clears its partial recognition state.

### Yo Gesture (2s): Pause or Resume

Hold the thumb, index finger, and little finger extended while keeping the middle and ring fingers folded for 2 seconds.

Finger extension is measured relative to the wrist and each finger base, so the pose works with either hand and does not depend on screen rotation. An active thumb/index pinch is excluded. One missing folded-finger observation is tolerated, but the thumb, index, and little finger must be tracked.

A brief landmark dropout of up to 0.2 seconds is bridged only while the wrist remains tracked. A successful hold pauses an active recording or resumes a paused recording.

The gesture fires once per hold. Stop presenting the pose for at least 0.5 seconds before it can trigger again.

Pausing stops RGB/depth frame capture, stroke capture, and audio recording. Gesture recognition remains active so the same pose can resume capture.

### Cover Camera (3s): Stop and Save

Cover the rear camera lens continuously for 3 seconds.

The app samples a 16 by 16 grid from the camera luminance plane. It calibrates an uncovered brightness baseline for one second, then treats the lens as covered only when the frame mean is at most 0.12 and at most 35 percent of the baseline, with normalized luminance deviation at most 0.08. Baseline updates stop while a cover candidate is active.

Brief shadows, textured dark scenes, and covers shorter than 3 seconds do not stop recording. Cover recognition stays active while recording is paused. Approximately three dark seconds will appear at the end of the RGB recording.

### Pinch and Hold (2s): Mark Segment

Bring the thumb tip and index fingertip together and hold them together continuously for 2 seconds.

A pinch becomes active at a normalized fingertip distance of 0.05 or less. It remains active through the dead band and is released at 0.07 or more. A successful hold writes one segment marker to the session manifest. Continued holding cannot create duplicates; the fingers must separate before another mark.

If the hand disappears or either fingertip becomes unreliable before two seconds, the partial hold is cleared.

## On-screen feedback

Feedback appears only after the requested action is accepted. It is a small, non-blocking glass popup that disappears after two seconds. A new message replaces the previous one.

- Gesture captured: Recording paused
- Gesture captured: Recording resumed
- Gesture captured: Recording stopped
- Gesture captured: Segment marked

The segment message appears only after the manifest write succeeds. Gesture feedback has no app sound or haptic.

No fingertip or hand-tracking dot is rendered in the camera viewfinder.

## State clearing and cooldown

Camera cover has command priority, followed by Yo and pinch. At most one command is emitted for a frame.

Hand loss clears incomplete Yo and pinch candidates. Invalid Yo landmarks clear the candidate unless the wrist remains tracked and the gap lasts no more than 0.2 seconds. Each disabled setting clears its candidate state and camera-cover calibration. Accepted commands retain the existing two-second command cooldown, with release-to-rearm rules preventing repeated commands from a continuously held control.
