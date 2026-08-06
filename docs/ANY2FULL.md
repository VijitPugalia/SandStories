# Optional Any2Full depth completion

SandStories can use [Any2Full](https://github.com/zhiyuandaily/Any2Full) as an
**offline, optional derived-data step**. It is not part of the iOS capture path.
The original LiDAR streams remain the authoritative measurements.

For automatic processing immediately after field-console upload, see
[AUTOMATIC_ANY2FULL.md](AUTOMATIC_ANY2FULL.md).

Any2Full is most useful when RGB is clear but valid LiDAR coverage is incomplete.
It should not be used to hide a failed capture, replace raw data, or claim that
model-filled pixels were physically measured.

## Output layout

By default the adapter writes:

```text
session_UUID/
  streams/                         # unchanged raw capture
  v2_frames.jsonl                  # unchanged raw metadata
  derived/any2full/
    completion_manifest.json       # provenance and source-frame mapping
    quality_report.json            # agreement at valid LiDAR anchors
    inputs/
      rgb/frame_000001.png
      depth/frame_000001.npy
    predictions/
      frame_000001.npy             # model-derived metric depth
      frame_000001.png             # Any2Full visualization
```

`quality_report.json` only measures agreement where the source LiDAR already had
valid depth. There is no ground truth for newly completed pixels, so those values
remain unvalidated estimates.

## Install Any2Full separately

Any2Full currently specifies Python 3.9, PyTorch 2.1, torchvision 0.16, and
NumPy below 2. Keep it in a separate environment from the SandStories analysis
environment.

```bash
git clone https://github.com/zhiyuandaily/Any2Full.git
cd Any2Full
python3.9 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install torch==2.1.0 torchvision==0.16.0 "numpy<2" \
  pillow matplotlib scipy opencv-python-headless==4.11.0.86
```

Download a matching `vits`, `vitb`, or `vitl` checkpoint from the
[official checkpoint repository](https://huggingface.co/zhiyuandaily/Any2Full/tree/main/checkpoints).
Start with `vits` for the smallest model and fastest pilot.

## Prepare a small pilot

This extracts ten synchronized pairs without running the model:

```bash
python scripts/complete_depth_any2full.py "/path/to/session_UUID" \
  --prepare-only \
  --stride 10 \
  --max-frames 10
```

RGB is resized to the captured depth resolution by default. This preserves the
LiDAR grid and reduces GPU memory use. `--target-resolution rgb` instead
upsamples sparse depth to the RGB grid and can be substantially more expensive.

## Run completion

```bash
python scripts/complete_depth_any2full.py "/path/to/session_UUID" \
  --any2full-dir "/path/to/Any2Full" \
  --checkpoint "/path/to/Any2Full_vits.pth.tar" \
  --python "/path/to/Any2Full/.venv/bin/python" \
  --stride 10 \
  --max-frames 10
```

On Windows, `--python` will usually resemble:

```text
C:\path\to\Any2Full\.venv\Scripts\python.exe
```

The encoder is inferred from the official checkpoint filename. Use
`--encoder vits`, `vitb`, or `vitl` if a renamed checkpoint cannot be inferred.

Use `--denoise` only after comparing results without it. Denoising can remove
LiDAR outliers, but it may also erase legitimate sharp sand edges.

## Acceptance checks

Before using completed depth downstream:

1. Inspect raw and completed maps side by side over flat sand, grooves, hands,
   tray edges, and occlusions.
2. Confirm low anchor MAE/RMSE in `quality_report.json`.
3. Check several consecutive frames for temporal flicker.
4. Keep completed files under `derived/`; never replace `streams/depth.f32`.
5. Describe Any2Full output as estimated or completed depth in reports.

If the app diagnostic reports almost no source depth, fix capture hardware,
permissions, distance, or lighting first. Depth completion still needs valid
metric anchors.
