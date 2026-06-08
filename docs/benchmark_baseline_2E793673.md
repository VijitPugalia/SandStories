# Benchmark baseline — session `2E793673-AB62-40B3-A27D-6AFBF839C16E`

**Folder (Windows):**  
`C:\Users\vijit\Downloads\Benchmark_session_2E793673-AB62-40B3-A27D-6AFBF839C16E\F839C16E`

> Note: Data lives in the inner `F839C16E` folder (where `manifest.json` is), not the outer Downloads folder.

## Package check

| Item | Status |
|------|--------|
| `manifest.json` | Present |
| `depth/` | 54 × `d_*.png` |
| `rgb/` | 54 × `r_*.jpg` |
| `audio.m4a` | None (benchmark skips audio) |
| `strokes.json` | Present |
| Total size | ~21 MB |

## Performance (from manifest)

| Metric | Value |
|--------|-------|
| Wall-clock duration | 15.08 s |
| Depth frames saved | 54 |
| RGB frames saved | 54 |
| **Saved fps** | **3.58** (54 ÷ 15.08) |
| Depth encoding | 16-bit PNG, max 8.0 m |
| Motion threshold | deltaMeanAbsThresholdU16 = 400 |

## Visualization

Saved frame 0 (depth colormap + RGB):

`C:\Users\vijit\Downloads\benchmark_frame_0.png`

Regenerate:

```powershell
py C:\Users\vijitpugalia\SandStories\scripts\visualize_sandstories_session.py `
  "C:\Users\vijit\Downloads\Benchmark_session_2E793673-AB62-40B3-A27D-6AFBF839C16E\F839C16E" `
  --frame 0 --save C:\Users\vijit\Downloads\benchmark_frame_0.png
```

## Interpretation

- **~3.6 saved fps** for PNG depth + JPEG RGB on this run — useful baseline before testing compressed depth or video.
- **~21 MB / 15 s** ≈ **1.4 MB/s** of stored depth+RGB (motion-gated).
- For storytelling research, use a full **Record** session (with audio), not this benchmark folder.
