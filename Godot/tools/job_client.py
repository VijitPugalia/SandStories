#!/usr/bin/env python3
"""Submit, resume, and inspect SandStories jobs through an HTTPS endpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib import error, request


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def call(
    url: str,
    method: str,
    token: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict, dict[str, str]]:
    outgoing = request.Request(
        url,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", **(headers or {})},
    )
    try:
        with request.urlopen(outgoing, timeout=180) as response:
            raw = response.read()
            payload = json.loads(raw) if raw else {}
            return response.status, payload, dict(response.headers)
    except error.HTTPError as exc:
        raw = exc.read()
        message = raw.decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc


def save_state(path: Path, state: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    if os.name != "nt":
        path.chmod(0o600)


def upload_offset(base: str, job_id: str, token: str) -> int:
    _, _, headers = call(f"{base}/v1/jobs/{job_id}/input", "HEAD", token)
    return int(headers["Upload-Offset"])


def submit(args: argparse.Namespace) -> None:
    source = Path(args.archive).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    base = args.endpoint.rstrip("/")
    state_path = Path(args.state or (str(source) + ".sandstories-job.json"))
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["source"] != str(source) or state["size_bytes"] != source.stat().st_size:
            raise RuntimeError("resume state belongs to a different archive")
        requested = {
            "input_format": args.input_format,
            "output_format": args.output_format,
            "rgb_resolution": args.rgb_resolution,
            "fallback_fps": args.fallback_fps,
        }
        if state.get("options", requested) != requested:
            raise RuntimeError("resume state was created with different format options")
    else:
        sha = digest(source)
        body = {
            "filename": source.name,
            "size_bytes": source.stat().st_size,
            "sha256": sha,
            "profile": "azure-hand-free-v12",
            "input_format": args.input_format,
            "output_format": args.output_format,
            "rgb_resolution": args.rgb_resolution,
            "fallback_fps": args.fallback_fps,
        }
        if args.webhook:
            body["webhook_url"] = args.webhook
        _, created, _ = call(
            f"{base}/v1/jobs",
            "POST",
            args.submit_token,
            json.dumps(body).encode(),
            {"Content-Type": "application/json"},
        )
        state = {
            "endpoint": base,
            "source": str(source),
            "size_bytes": source.stat().st_size,
            "sha256": sha,
            "job_id": created["job"]["id"],
            "job_token": created["job_token"],
            "webhook_secret": created.get("webhook_secret"),
            "options": {
                "input_format": args.input_format,
                "output_format": args.output_format,
                "rgb_resolution": args.rgb_resolution,
                "fallback_fps": args.fallback_fps,
            },
        }
        save_state(state_path, state)
        print(f"created {state['job_id']}; resume credentials saved to {state_path}")

    offset = upload_offset(base, state["job_id"], state["job_token"])
    chunk_size = args.chunk_mib * 1024 * 1024
    attempts = 0
    with source.open("rb") as stream:
        while offset < state["size_bytes"]:
            stream.seek(offset)
            block = stream.read(min(chunk_size, state["size_bytes"] - offset))
            try:
                _, _, headers = call(
                    f"{base}/v1/jobs/{state['job_id']}/input",
                    "PATCH",
                    state["job_token"],
                    block,
                    {
                        "Content-Type": "application/offset+octet-stream",
                        "Upload-Offset": str(offset),
                    },
                )
                offset = int(headers.get("Upload-Offset", offset + len(block)))
                attempts = 0
                print(f"{offset}/{state['size_bytes']} bytes ({offset / state['size_bytes']:.1%})", flush=True)
            except (OSError, RuntimeError) as exc:
                attempts += 1
                if attempts > args.retries:
                    raise
                delay = min(60, 2**attempts)
                print(f"upload interrupted ({exc}); reconciling in {delay}s", file=sys.stderr)
                time.sleep(delay)
                offset = upload_offset(base, state["job_id"], state["job_token"])
    _, committed, _ = call(
        f"{base}/v1/jobs/{state['job_id']}/commit", "POST", state["job_token"], b""
    )
    print(json.dumps(committed, indent=2))


def status(args: argparse.Namespace) -> None:
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    _, payload, _ = call(
        f"{state['endpoint']}/v1/jobs/{state['job_id']}", "GET", state["job_token"]
    )
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    upload = sub.add_parser("submit")
    upload.add_argument("archive")
    upload.add_argument("--endpoint", required=True)
    upload.add_argument("--submit-token", default=os.environ.get("SANDSTORIES_SUBMIT_TOKEN", ""))
    upload.add_argument("--webhook")
    upload.add_argument("--input-format", choices=("auto", "azure-mkv", "frame-archive", "stream-bundle"), default="auto")
    upload.add_argument("--output-format", choices=("png-sequence", "lossless-streams", "compact-streams", "both"), default="compact-streams")
    upload.add_argument("--rgb-resolution", choices=("native", "75-percent", "50-percent"), default="native")
    upload.add_argument("--fallback-fps", type=float, default=30.0)
    upload.add_argument("--state")
    upload.add_argument("--chunk-mib", type=int, default=1)
    upload.add_argument("--retries", type=int, default=12)
    inspect = sub.add_parser("status")
    inspect.add_argument("--state", required=True)
    args = parser.parse_args()
    if args.command == "submit":
        if not args.submit_token:
            parser.error("--submit-token or SANDSTORIES_SUBMIT_TOKEN is required")
        submit(args)
    else:
        status(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
