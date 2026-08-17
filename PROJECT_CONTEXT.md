# SandStories Project Context

This file is the shared project memory for Codex / Antigravity chats working in this repo.
Read it before making product or implementation decisions, and update it when
new durable decisions are made.

## Current Product Direction

- SandStories is an iOS app focused on camera capture, LiDAR/depth capture, and session export.
- The app should feel close to Apple's Camera app: quiet UI, visible record control, native-feeling bottom navigation, and no unnecessary overlays during capture.
- Performance matters on device. Prefer smooth capture and lower heat over heavy visual effects.
- Avoid expensive real-time effects unless they are essential to the capture flow.

## Camera And Zoom Decisions

- iPhone-style zoom buttons were explored: 0.5x, 1x, 2x, 3x.
- Reliable lens switching during LiDAR/depth capture is not guaranteed in the current app flow.
- 0.5x ultra-wide RGB can be useful for preview, but it does not match LiDAR/depth capture in the way the user needs.
- Because mismatched RGB + LiDAR is misleading, unsupported zoom controls should stay removed unless the capture pipeline is redesigned to handle lens/device switching correctly.
- If zoom returns later, it must switch actual camera feeds on screen, not only scale/crop the preview.

## UI Decisions

- Keep the top bar visible.
- Keep the native tab bar.
- The Capture screen needs an obvious Record button at the bottom.
- Pause should behave like a real capture control, not show a blocking overlay while recording continues in the background.
- The bottom controls should be readable over the camera feed; avoid being too transparent.
- The design target is Apple Camera-inspired and iOS 26/liquid-glass inspired, but implementation should prefer stable APIs over flashy effects that hurt reliability.

## Export Flow

- Export Session previously showed a blank grey screen on first open, then worked after going back and opening again.
- Future export changes should verify first-open behavior, not only second-open behavior.

## Build And Distribution

- IPA builds happen through GitHub Actions.
- The latest direct IPA release URL is:
  https://github.com/VijitPugalia/SandStories/releases/download/latest-ipa/SandStories.ipa
- The repo is private, so the direct IPA link requires GitHub access/login.
- Keep main updated when the user needs a new IPA from GitHub Actions.

## Repository Notes

- The repo uses code-review-graph. Use the graph tools before normal file searching or reading when exploring code.
- Generated local artifacts and model weights should stay ignored and out of Git:
  - weights/
  - *.pt
  - sandstories_session_contact_sheet.png
  - NUL/
- Do not commit large downloaded ML weights.

## Maintenance Rule

When a chat makes a durable project decision, fixes an important behavior, changes build/distribution flow, or discovers a device-specific limitation, update this file in the same PR/commit. If you cannot update it, tell Vijit exactly what should be added.
