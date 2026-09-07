# UI Gestures and Control Heuristics

SandStories uses touchless gestures while the iPhone is mounted out of reach. Vision hand-pose observations feed a separate, time-based state machine. Drawing strokes and UI-control gestures remain separate data paths.

The normal hand-pose processing target is 15 fps and may reduce to 8 fps under thermal pressure. Gesture timing uses timestamps rather than frame counts, so the same holds and windows apply at either rate.

Vision image orientation follows the active interface orientation. Portrait, upside-down portrait, landscape-left, and landscape-right frames are mapped before hand-pose detection.

## Gesture controls

Operators can enable or disable each gesture in Settings. Disabling a gesture clears its partial recognition state.

### Open Palm: Pause or Resume

Hold an open palm relatively still for 3 seconds.

At least three of the four non-thumb fingers must have reliable tip/base landmarks and be extended. The thumb is not part of the open-palm extension gate because its foreshortened camera angle made real palms fail continuously. One unreliable or curled non-thumb finger is tolerated. An active thumb/index pinch is explicitly excluded. A brief landmark dropout of up to 0.2 seconds is bridged only while the wrist remains tracked.

The wrist range during the hold must stay below 0.08 on both normalized image axes. A successful hold pauses an active recording or resumes a paused recording.

The gesture fires once per hold. The hand must stop presenting an open palm for at least 0.5 seconds before another palm hold can trigger.

Pausing stops RGB/depth frame capture, stroke capture, and audio recording. Resuming restarts those streams.

### Wave Hand: Stop Recording

Present an open palm and move the wrist horizontally back and forth.

The state machine keeps four seconds of timestamped wrist positions. It emits Stop when all of these are true:

- The horizontal span is at least 0.12 in normalized image coordinates.
- Movement crosses the existing 0.005 per-sample noise gate.
- The qualified horizontal direction changes at least three times.

Three direction changes are the complete gesture. There is no second layer that asks for three complete wave detections. After Stop fires, the open palm must leave the frame or close before another wave can trigger.

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

Hand loss clears incomplete palm, wave, and pinch candidates. Invalid palm landmarks clear the candidate unless the wrist remains tracked and the gap lasts no more than 0.2 seconds. Each disabled setting also clears its candidate state. Accepted commands retain the existing two-second command cooldown, with release-to-rearm rules preventing repeated commands from a continuously held gesture.
