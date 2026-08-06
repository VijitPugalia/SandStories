# Automatic local-GPU depth completion

The field console can automatically queue Any2Full after a valid SandStories
session ZIP is uploaded. Validation and raw archival happen first. Model output
is derived data and never replaces the uploaded ZIP or extracted raw streams.

```text
iPhone upload
  -> ZIP archive
  -> validation + extraction
  -> SQLite-backed completion queue
  -> Any2Full GPU subprocess
  -> derived output ZIP + quality report
  -> field-console status/download
```

Jobs are claimed through SQLite, run one at a time, and return to `queued` if
the server restarts while processing. Invalid packages are never queued.

The default pilot processes every tenth saved frame, up to 60 frames, at the
LiDAR grid resolution. Change those limits only after checking quality and GPU
memory use.

## Option A: NVIDIA Docker pipeline

Requirements:

- NVIDIA GPU with a working host driver.
- Docker Engine or Docker Desktop with NVIDIA container GPU support.
- A local Any2Full checkout.
- A downloaded Any2Full checkpoint.

Copy `deploy/env.lan.example` to `deploy/.env` and set:

```text
ANY2FULL_HOST_DIR=C:/Users/vijit/Any2Full
ANY2FULL_CHECKPOINT_HOST_DIR=C:/Users/vijit/Any2Full/checkpoints
ANY2FULL_CHECKPOINT_FILE=Any2Full_vits.pth.tar
```

Linux paths work as well. Then start the base LAN stack with the GPU override:

```bash
cd deploy
docker compose \
  -f docker-compose.lan.yml \
  -f docker-compose.any2full.yml \
  up --build
```

The override creates a Python 3.9 environment with PyTorch 2.1,
torchvision 0.16, and CUDA 12.1 support. It mounts the model checkout
and checkpoint read-only. The existing `server_data` volume stores uploads,
extracted sessions, job state, reports, and derived ZIPs.

## Option B: native field console

Run the field console normally, but point it at the Python executable inside
the Any2Full environment:

```powershell
$env:SANDSTORIES_ANY2FULL_ENABLED = "true"
$env:SANDSTORIES_ANY2FULL_PYTHON = "C:\Users\vijit\Any2Full\.venv\Scripts\python.exe"
$env:SANDSTORIES_ANY2FULL_DIR = "C:\Users\vijit\Any2Full"
$env:SANDSTORIES_ANY2FULL_CHECKPOINT = "C:\Users\vijit\Any2Full\checkpoints\Any2Full_vits.pth.tar"
$env:SANDSTORIES_ANY2FULL_STRIDE = "10"
$env:SANDSTORIES_ANY2FULL_MAX_FRAMES = "60"

uvicorn server.app:app --host 0.0.0.0 --port 8080
```

The field console needs `server/requirements.txt` in its own environment.
The configured Any2Full executable only needs Any2Full's model dependencies;
it is launched as a separate subprocess.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SANDSTORIES_ANY2FULL_ENABLED` | `false` | Enables automatic queueing |
| `SANDSTORIES_ANY2FULL_PYTHON` | server Python | Any2Full environment executable |
| `SANDSTORIES_ANY2FULL_DIR` | empty | Checkout containing `run_any2full.py` |
| `SANDSTORIES_ANY2FULL_CHECKPOINT` | empty | Model checkpoint |
| `SANDSTORIES_ANY2FULL_ENCODER` | `auto` | `auto`, `vits`, `vitb`, or `vitl` |
| `SANDSTORIES_ANY2FULL_DEPTH_SOURCE` | `selected` | `selected` or `smoothed` |
| `SANDSTORIES_ANY2FULL_TARGET_RESOLUTION` | `depth` | `depth` or `rgb` |
| `SANDSTORIES_ANY2FULL_STRIDE` | `10` | Process every Nth saved frame |
| `SANDSTORIES_ANY2FULL_MAX_FRAMES` | `60` | Per-job cap; `0` means all |
| `SANDSTORIES_ANY2FULL_DENOISE` | `false` | Enables model input denoising |
| `SANDSTORIES_ANY2FULL_TIMEOUT_SECONDS` | `3600` | Per-job timeout |

`GET /api/health` reports whether configuration is enabled and ready without
exposing local model paths.

## Field-console behavior

The Session Packages table displays one of:

- `DISABLED`: automatic completion is off.
- `UNAVAILABLE`: enabled but model configuration is incomplete.
- `QUEUED`: waiting for the GPU worker.
- `RUNNING`: model inference is active.
- `COMPLETED`: report and derived ZIP are available.
- `FAILED`: the job failed; inspect the error and retry from the dashboard.

Completed output contains `completion_manifest.json`, `quality_report.json`,
paired inputs, model predictions, and `worker.log`. Anchor metrics only measure
agreement at pixels where LiDAR supplied valid depth; model-filled holes still
lack physical ground truth.
