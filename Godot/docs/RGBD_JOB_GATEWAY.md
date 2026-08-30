# RGB-D Job Gateway: Web Inputs, Outputs, and Wire Formats

This document defines the public contract of the SandStories web job gateway.
It describes what a submitter uploads, which job-level choices are available,
what the pipeline stores and returns, and how timing and metric depth are
preserved. Site-specific hostnames, credentials, routes, and mount points are
deployment configuration and are intentionally not part of this contract.

## 1. Processing model

The gateway exposes a resumable HTTPS upload API and a browser interface in
front of the Azure hand-free v12 pipeline. The API and worker share a SQLite
queue. Exactly one job may be in `validating` or `running` state; additional
committed jobs remain FIFO queued.

The worker uses local scratch for high-I/O model stages. The canonical final
session is written to configured durable storage. Download artifacts are
created only after the final session and automated audits complete.

```text
browser or API client
        |
        | resumable HTTPS upload
        v
job gateway + SQLite queue
        |
        | one claimed job
        v
Azure hand-free v12 worker
        |
        +--> canonical PNG session on durable storage
        +--> selected downloadable artifact(s)
```

## 2. Web submission fields

The browser form sends these immutable fields when it creates a job:

| Field | Values | Default | Meaning |
| --- | --- | --- | --- |
| `input_format` | `auto`, `azure-mkv`, `frame-archive`, `stream-bundle` | `auto` | Declares or detects the uploaded representation. |
| `output_format` | `png-sequence`, `lossless-streams`, `compact-streams`, `both` | `compact-streams` | Selects downloadable artifact encoding. |
| `rgb_resolution` | `native`, `75-percent`, `50-percent` | `native` | Selects RGB size in stream artifacts. It does not change the canonical processing session. |
| `fallback_fps` | `0.1` through `240` | `30` | Used only when the input has no per-frame timestamps. |
| `webhook_url` | allowlisted HTTPS URL or empty | empty | Optional signed job-event callback. |

Selections are part of resumable-upload identity. Changing an option creates a
new job rather than silently resuming data into a job with different output
semantics.

## 3. Accepted inputs

### 3.1 Azure Kinect MKV

Use `input_format: azure-mkv`, or `auto` with a `.mkv` filename.

The decoder reads to end-of-file and does not assume a recording length. It:

1. decodes color and native `DEPTH16` captures;
2. registers color into depth-camera geometry with the calibration embedded in
   the recording;
3. writes the internal RGB and depth frame directories used by v12;
4. writes the raw calibration JSON; and
5. records the color timestamp, depth timestamp, pair delta, and presentation
   time for every emitted pair in `capture_frames.jsonl`.

Color and depth are queued independently and paired in stream order. Stream
surplus and timestamp-delta statistics are recorded in
`capture_manifest.json`.

### 3.2 Aligned frame archive

Use `input_format: frame-archive`, or `auto` with a tar/ZIP that is not a stream
bundle. Accepted filename suffixes are `.tar`, `.tar.gz`, `.tgz`, and `.zip`.

The archive contains `rgb/` and `depth/` either at its root or below one wrapper
directory:

```text
capture/
  rgb/
    frame_000001.jpg       # .jpeg and .png are also accepted
    frame_000002.jpg
  depth/
    depth_000001.png       # uint16 millimetres
    depth_000002.png
  capture_frames.jsonl     # optional per-frame timing
  capture_manifest.json    # optional source metadata
```

Requirements:

- numbering starts at one, is six-digit, and is continuous;
- RGB and depth counts are equal and non-zero;
- every RGB frame is three-channel decodable color;
- every depth frame is single-channel `uint16` in millimetres;
- value zero means invalid depth;
- RGB and depth dimensions match and remain constant; and
- the capture passes the configured tray/depth-envelope checks.

PNG RGB is accepted at the boundary and normalized to the existing v12 staging
representation. This normalization is not the archival output policy.

If `capture_frames.jsonl` is absent, presentation times are synthesized from
the job's explicit `fallback_fps` and the final manifest identifies them as
fallback timing.

### 3.3 SandStories stream bundle

Use `input_format: stream-bundle`, or `auto` with a ZIP whose root contains
`bundle_manifest.json`.

```text
bundle.zip
  bundle_manifest.json
  frames.jsonl
  processed_manifest.json
  streams/
    rgb.mkv
    depth.mkv
```

The bundle must declare format `sandstories_rgbd_stream_bundle_v1`. The gateway
validates both stream frame counts and the JSONL record count before decoding.
Depth is restored exactly. If RGB was exported at 75% or 50%, it is resized
back to the native depth dimensions for compatibility with the current v12
pipeline.

ZIP and tar extraction reject path traversal, links/devices, and excessive
entry counts.

## 4. Timing semantics

Per-frame timestamps are authoritative whenever present. A frame record uses:

```json
{"frameIndex":1,"timeSeconds":0.0,"sourceFrameIndex":1}
```

Azure MKV records additionally contain `colorTimestampUsec`,
`depthTimestampUsec`, `colorTimeSeconds`, and `pairDeltaUsec`.

Some existing v12 algorithms express temporal windows in frames and accept one
nominal rate. For timestamped input, the runner derives that nominal value from
the median positive timestamp interval. It then writes the authoritative
per-frame times back into downstream manifests. The nominal value is therefore
an algorithm parameter, not a replacement for capture timing.

The pipeline never assumes a fixed frame count. `fallback_fps` is consulted
only for legacy frame archives without timing metadata.

## 5. Canonical output and download choices

The canonical result remains the normal v12 directory with PNG RGB, metric
depth, normal maps, confidence, masks, manifests, session metadata, and audit
receipts. It remains at processing-native resolution regardless of download
choice so existing Godot and analysis tools continue to work.

### `png-sequence`

Creates a broadly compatible ZIP of the complete canonical session and a
`.tar.zst` automation artifact. Individual processed images remain available
as PNG files.

### `lossless-streams`

Creates one stream-bundle ZIP:

- RGB: FFV1 level 3 in Matroska, `bgr0`, intra-only GOP, slice CRC;
- depth: FFV1 level 3 in Matroska, `gray16le`, intra-only GOP, slice CRC;
- timing: `frames.jsonl`; and
- metadata: bundle and processed manifests.

Both RGB and depth are pixel-lossless relative to the processed PNG sequence.

### `compact-streams`

Creates one stream-bundle ZIP:

- RGB: H.264 (`libx264`, CRF 18, medium preset, `yuv420p`); and
- depth: the same lossless FFV1 `gray16le` stream as lossless mode.

This is the default because RGB tolerates ordinary delivery compression while
metric depth does not. “Compact” never means lossy depth.

### `both`

Creates the PNG ZIP and `.tar.zst`, plus a compact stream bundle available as
`artifact.streams.zip`.

The `rgb_resolution` scale is applied only to RGB in stream bundles. Dimensions
are rounded to even numbers for H.264 compatibility. Depth is never resized.

## 6. Artifact validation

Before a stream bundle is published, the packer asks `ffprobe` to count decoded
frames in both Matroska streams and compares them with the processed manifest.
Files are written to temporary paths and atomically renamed after success.
SHA-256 sidecar receipts record artifact size and digest.

The automated test suite covers:

- resumable upload and queue completion;
- option validation, persistence, and worker environment propagation;
- browser CSRF and per-user job ownership;
- ranged artifact downloads;
- HMAC-signed webhooks;
- exact failure-stage and complete-log retention; and
- PNG -> FFV1 -> PNG depth equality with non-uniform frame timestamps.

## 7. API summary

Job creation uses `POST /v1/jobs` with JSON:

```json
{
  "filename": "capture.mkv",
  "size_bytes": 123456789,
  "sha256": "auto",
  "profile": "azure-hand-free-v12",
  "input_format": "azure-mkv",
  "output_format": "compact-streams",
  "rgb_resolution": "native",
  "fallback_fps": 30.0,
  "webhook_url": ""
}
```

The browser may request server-side SHA-256 with `auto`; token clients provide
a lowercase 64-character digest. Upload proceeds with offset-checked `PATCH`
requests and may resume by reading `Upload-Offset` with `HEAD`.

Relevant download endpoints are:

| Endpoint | Result |
| --- | --- |
| `/v1/jobs/{id}/artifact.zip` | Primary selected ZIP. |
| `/v1/jobs/{id}/artifact.streams.zip` | Additional stream bundle for `both`. |
| `/v1/jobs/{id}/artifact.tar.zst` | PNG session tarball when requested. |
| `/v1/jobs/{id}/log` | Complete pipeline log. |
| `/v1/jobs/{id}/failure` | Structured failure stage and log location. |

All artifact responses support HTTP byte ranges for resumable downloads.

## 8. Authentication and operational security

The web UI supports GitHub OAuth authorization code flow with PKCE. The server
trusts verified email addresses only for initial administrator bootstrap,
stores sessions as hashes, sets secure HTTP-only cookies, and requires a CSRF
token for browser mutations. Roles are `pending`, `uploader`, `admin`, and
`disabled`.

Bearer-token automation remains available. Submit, administrator, GitHub
client-secret, and webhook-signing secrets must never be committed. Webhook
destinations are HTTPS and host-allowlisted to avoid server-side request
forgery. Callbacks are signed with HMAC-SHA256.

The public reverse proxy terminates TLS. The gateway itself should listen only
on a private address, and the worker should run as an unprivileged service
account with write access limited to its database, scratch, and durable output
roots. See `deploy/job_gateway/` for sanitized examples.

## 9. Webhook contract

When a job has a `webhook_url`, the create response returns a randomly generated
`webhook_secret` once. The gateway sends JSON containing the event name and the
same public job object returned by the status API:

```json
{"event":"job.completed","job":{"id":"sj_...","state":"completed","stage":"completed","progress":1.0}}
```

Possible events are `job.queued`, `job.started`, `job.review_required` when a
deployment enables manual review, `job.completed`, `job.failed`, and
`job.cancelled`. Receivers should treat the `X-SandStories-Delivery` value as
an idempotency key. `X-SandStories-Event` repeats the event name, and
`X-SandStories-Signature-256` is `sha256=` followed by the hexadecimal
HMAC-SHA256 of the exact request body. Delivery succeeds only on a 2xx response
and otherwise retries with bounded exponential backoff.

## 10. Deployment examples

`deploy/job_gateway/` contains deliberately generic examples:

- `gateway.example.json` defines queue, storage, OAuth, upload, webhook, and
  pipeline-command settings;
- `pipeline.example.env` names the isolated Python/model environments and the
  durable output root;
- `sandstories-job-api.service` and `sandstories-job-worker.service` separate
  the network-facing process from the single worker; and
- `Caddyfile.snippet` shows HTTPS termination and a request-size guard suitable
  for the default 1 MiB resumable chunks.

Replace every example host and path. Generate secret files on the deployment
host with restrictive permissions; do not place secret values in the JSON or
environment file.

## 11. Dependencies

The gateway uses the Python standard library and SQLite. Processing additionally
requires the dependencies of the v12 pipeline. Stream transport requires
`ffmpeg`/`ffprobe` with `ffv1` and `libx264`; PNG packaging uses `7z` and
`.tar.zst` publishing requires GNU tar with zstd support.

Azure MKV ingestion requires a Python environment containing `pyk4a`, OpenCV,
NumPy, and the Azure Kinect Sensor SDK runtime.
