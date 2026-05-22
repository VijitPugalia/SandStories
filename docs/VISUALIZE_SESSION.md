# Visualizing SandStories session data (Windows / macOS / Linux)

## Your folder layout

Use the directory that contains **`manifest.json`** (usually `session_<UUID>/`).  
If you see a path like `...\session_7C46D4A2-...\77A43D02`, open the parent until you find `manifest.json`.

Typical contents:

| Item | Purpose |
|------|---------|
| `manifest.json` | Session metadata, list of depth/RGB files, timestamps |
| `depth/*.png` | 16-bit grayscale depth (lossless PNG) |
| `rgb/*.jpg` | RGB frames paired with saved depth frames |
| `audio.m4a` | Session audio |
| `strokes.json` | Hand stroke polylines in AR coordinates |
| `objects.jsonl` | Object detection lines (may be empty) |

## Depth encoding

From `manifest.json` → `depthEncoding.maxDepthMeters` (typically **8.0**).

Each depth pixel is **UInt16** stored in the PNG:

- **Invalid / no depth** (ARKit): stored as **0**.
- **Valid depth** in meters:

```text
meters = (uint16_value / 65535.0) * maxDepthMeters
```

This matches the app’s encoder: `normalized = clamp(meters, 0, max) / maxDepthMeters` → `uint16 = normalized * 65535`.

## Quick options

### A) Python script (recommended)

From the repo:

```bash
pip install numpy pillow matplotlib
python scripts/visualize_sandstories_session.py "C:/Users/vijit/Downloads/session_7C46D4A2-EE78-4DD8-BD97-D5DC77A43D02"
```

Opens a figure with depth (colormap) + RGB side-by-side for the first frame, and can save PNGs. Use `--frame N` to pick another index.

### B) ImageJ / Fiji

1. **File → Import → PNG…** — Fiji reads 16-bit grayscale.
2. **Image → Adjust → Brightness/Contrast** — Auto.
3. For **physical depth**: **Process → Math → Multiply** by `(maxDepthMeters / 65535)` — get `maxDepthMeters` from `manifest.json`.

### C) MATLAB

```matlab
info = imfinfo('depth/d_000001.png');
img = imread('depth/d_000001.png');  % uint16
maxM = 8.0;  % from manifest depthEncoding.maxDepthMeters
meters = double(img) / 65535 * maxM;
meters(img == 0) = NaN;  % optional: mask invalid
imagesc(meters); colorbar;
```

### D) OpenCV (Python)

```python
import cv2, json
with open("manifest.json") as f:
    m = json.load(f)
max_m = m["depthEncoding"]["maxDepthMeters"]
d = cv2.imread("depth/d_000001.png", cv2.IMREAD_UNCHANGED)  # uint16
meters = d.astype("float32") / 65535.0 * max_m
```

## Aligning RGB and depth

`manifest.json` lists `depthFrames[i]` and `rgbFrames[i]` with the same logical index; `relativePath` gives paths from the session root. Filenames are paired (`d_000001.png` / `r_000001.jpg`) when both are saved together.

## Audio + strokes

- **Audio**: any player for `audio.m4a`.
- **Strokes**: `strokes.json` is JSON array of strokes with 3D points (`x,y,z`) and ARKit-style timestamps — visualize in a 3D tool or custom script, not in the depth PNG viewer.
