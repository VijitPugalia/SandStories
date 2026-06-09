#!/usr/bin/env python3
"""Small standalone receiver for SandStories session ZIP uploads."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zipfile import BadZipFile, ZipFile


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned.strip("._") or "sandstories_session.zip"


def safe_extract_zip(zf: ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in zf.infolist():
        target = (root / member.filename).resolve()
        if root != target and root not in target.parents:
            raise BadZipFile(f"unsafe member path: {member.filename}")
    zf.extractall(root)


class UploadHandler(BaseHTTPRequestHandler):
    server_version = "SandStoriesUpload/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_error(404, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/upload":
            self.send_error(404, "not found")
            return

        token = getattr(self.server, "upload_token", "")
        if token:
            query_token = parse_qs(parsed.query).get("token", [""])[0]
            header_token = self.headers.get("X-SandStories-Token", "")
            if token not in (query_token, header_token):
                self.send_error(401, "invalid token")
                return

        length_header = self.headers.get("Content-Length")
        if not length_header:
            self.send_error(411, "content-length required")
            return

        try:
            content_length = int(length_header)
        except ValueError:
            self.send_error(400, "invalid content-length")
            return

        max_bytes = getattr(self.server, "max_bytes", 0)
        if max_bytes and content_length > max_bytes:
            self.send_error(413, "upload too large")
            return

        upload_dir: Path = getattr(self.server, "upload_dir")
        upload_dir.mkdir(parents=True, exist_ok=True)

        requested_name = self.headers.get("X-SandStories-Filename", "sandstories_session.zip")
        stem = Path(safe_filename(requested_name)).stem
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        zip_path = upload_dir / f"{timestamp}_{stem}.zip"

        remaining = content_length
        with zip_path.open("wb") as out:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    self.send_error(400, "incomplete upload")
                    return
                out.write(chunk)
                remaining -= len(chunk)

        try:
            with ZipFile(zip_path) as zf:
                bad_member = zf.testzip()
                if bad_member is not None:
                    raise BadZipFile(f"bad member: {bad_member}")
                if getattr(self.server, "extract", False):
                    extract_dir = upload_dir / zip_path.stem
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    safe_extract_zip(zf, extract_dir)
        except BadZipFile as exc:
            try:
                zip_path.unlink()
            except OSError:
                pass
            self.send_error(400, f"invalid zip: {exc}")
            return

        self.send_response(201)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        body = f'{{"ok":true,"file":"{zip_path.name}","bytes":{content_length}}}\n'
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive SandStories session ZIP uploads.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host. Use 0.0.0.0 for LAN access.")
    parser.add_argument("--port", type=int, default=8080, help="Bind port.")
    parser.add_argument("--dir", default="uploads", help="Directory for received ZIP files.")
    parser.add_argument("--extract", action="store_true", help="Also extract each valid ZIP into a folder.")
    parser.add_argument("--token", default=os.environ.get("SANDSTORIES_UPLOAD_TOKEN", ""), help="Optional shared token.")
    parser.add_argument("--max-mb", type=int, default=4096, help="Maximum upload size in MB. Use 0 for unlimited.")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), UploadHandler)
    server.upload_dir = Path(args.dir).resolve()
    server.upload_token = args.token
    server.extract = args.extract
    server.max_bytes = args.max_mb * 1024 * 1024 if args.max_mb else 0

    print(f"SandStories upload server listening on http://{args.host}:{args.port}/upload")
    print(f"Saving uploads to {server.upload_dir}")
    if args.token:
        print("Token required: append ?token=... to the upload URL or send X-SandStories-Token")
    server.serve_forever()


if __name__ == "__main__":
    main()
