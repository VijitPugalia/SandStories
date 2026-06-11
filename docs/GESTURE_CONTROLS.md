# UI Gestures and Control Heuristics

This document describes the design, heuristics, and integration of touchless hands-free UI control gestures used to manage SandStories sessions. These gestures allow operators to control the recording session when the capturing iPhone is mounted overhead/face-down on a tripod and out of reach.

## 1. Hand Pose Pipeline Architecture

The gesture detection system leverages Apple's `Vision` framework (`VNDetectHumanHandPoseRequest`) serialized inside a dedicated background actor (`HandPoseVisionProcessor`) at 30 fps.

To maintain cultural safety and drawing fidelity, the **UI Control Gesture** detection runs on a completely separate code path from the narrative drawing stroke capture. Drawing strokes are captured continuously during normal recording, and gestures only trigger system state events (Start, Stop, Pause, Resume, Mark Segment) without labeling or classifying the sand art or narrative gestures.

---

## 2. Gesture Control Heuristics

All coordinate checks and distance checks are computed in normalized image space: $[0.0, 1.0] \times [0.0, 1.0]$. The coordinate origin is mapped with the wrist serving as the primary anchor point.

Operators can selectively enable/disable any of these gestures in the **Gestures** configuration tab.

### A. Raised Open Palm (Pause / Resume)

*   **Action**: Pauses current recording (stops depth/RGB frames and stroke logs, pauses audio recording) if active. Resumes recording if paused.
*   **Trigger Condition**: The user holds their hand open and relatively still, facing the camera.
*   **State Detection**:
    *   Fingers (Index, Middle, Ring, Little) are determined to be *extended* if:
        $$\text{distance}(\text{FingerTip}, \text{Wrist}) > \text{distance}(\text{FingerMCP}, \text{Wrist}) \times 1.2$$
    *   Thumb is *extended* if:
        $$\text{distance}(\text{ThumbTip}, \text{Wrist}) > \text{distance}(\text{ThumbIP}, \text{Wrist}) \times 1.1$$
    *   All 5 fingers must meet the extension requirement simultaneously.
    *   **Still-Hand Check**: To prevent other gestures like waving from accidentally triggering a pause, the normalized displacement of the wrist over the 90-frame window must be small on both axes:
        $$X_{\text{max}} - X_{\text{min}} < 0.08 \quad \text{and} \quad Y_{\text{max}} - Y_{\text{min}} < 0.08$$
*   **Debounce/Hold**: Must be detected continuously for 90 frames ($\approx 3.0$ seconds) with the Still-Hand Check satisfied. Once triggered, it activates a 60-frame (2-second) cooldown to prevent double-triggering.

### B. Open Hand Wave (Stop Session)

*   **Action**: Stops and finalizes the active recording session if recording (paused or active). Waving does not start sessions.
*   **Trigger Condition**: The user waves their open hand back and forth horizontally at least 3 times within a 4-second period.
*   **State Detection**:
    *   Hand must be detected as an Open Palm (see above).
    *   The horizontal ($X$) coordinate of the wrist is stored in a 30-frame sliding history window.
    *   The maximum displacement in the window must exceed the threshold:
        $$X_{\text{max}} - X_{\text{min}} > 0.18$$
    *   The direction of movement must reverse at least 3 times within the 30-frame history window (counting transitions of $\Delta X$ sign exceeding a minimal noise gate of $0.005$).
    *   Upon detection of a wave event, the history window is cleared to prevent a continuous wave from registering multiple wave counts in the same window.
    *   **Wave Counting**: If 3 wave events are detected within 4.0 seconds, the `.stop` command is emitted.
*   **Cooldown**: Triggers the `.stop` command immediately upon the third wave event, clearing the timestamps window and activating a 60-frame (2-second) cooldown.

### C. One-Finger Triple Tap (Mark Segment)

*   **Action**: Appends a segment marker containing the current monotonic and Unix timestamp to `segments` in the session manifest.
*   **Trigger Condition**: The user pinches their index fingertip to their thumb fingertip 3 times in quick succession (within 2.0 seconds), with middle, ring, and little fingers curled.
*   **State Detection**:
    *   Only the index finger is extended. Middle, ring, and little fingers must be curled:
        $$\text{distance}(\text{FingerTip}, \text{Wrist}) < \text{distance}(\text{FingerMCP}, \text{Wrist}) \times 1.1$$
    *   A pinch is *active* when the index tip is close to the thumb tip:
        $$\text{distance}(\text{IndexTip}, \text{ThumbTip}) < 0.05$$
*   **Triple Tap Counting**:
    *   Monitors transitions from `pinchActive = false` to `pinchActive = true`.
    *   If 3 transitions occur within a window of $2.0$ seconds, a `.markSegment` command is emitted.
    *   Activates a 60-frame (2-second) cooldown.

---

## 3. Developer Configuration & Tuning

To tune these thresholds on a new device configuration or distance layout:
1.  **Pinch Thresholds**: If pinch detection is failing, increase the fingertip‑to‑thumbtip threshold from `0.05` to `0.07` in `HandPoseVisionProcessor.processFrameForFingertipAndGestures`.
2.  **Wave Amplitude**: For wider lens cameras or further mounting setups, lower the wave horizontal displacement from `0.18` to `0.12` to increase sensitivity.
3.  **Frame Rates**: The consecutive frame counts assume a standard 30 fps capture pipeline. If running at 60 fps, double the consecutive frames threshold (e.g., set open palm frame check to `180` instead of `90`).
