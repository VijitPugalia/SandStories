#!/usr/bin/env python3
"""Resumable, single-worker job gateway for the SandStories v12 pipeline.

TLS and public exposure belong on a reverse proxy. This process should listen
only on loopback or a trusted private interface.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import hmac
import html
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error as urlerror
from urllib import parse, request
import uuid


TERMINAL_STATES = {"completed", "failed", "rejected", "cancelled"}
ACTIVE_STATES = {"validating", "running"}
JOB_ID_PREFIX = "sj_"
INPUT_FORMATS = {"auto", "azure-mkv", "frame-archive", "stream-bundle"}
OUTPUT_FORMATS = {"png-sequence", "lossless-streams", "compact-streams", "both"}
RGB_RESOLUTIONS = {"native", "75-percent", "50-percent"}
_UPLOAD_LOCKS: dict[str, threading.Lock] = {}
_UPLOAD_LOCKS_GUARD = threading.Lock()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_secret(path: str | os.PathLike[str]) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if len(value) < 24:
        raise ValueError(f"secret in {path} must contain at least 24 characters")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    config_path = Path(path).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    required = (
        "database_path",
        "storage_root",
        "scratch_root",
        "submit_token_file",
        "admin_token_file",
        "pipeline_command",
    )
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"missing gateway config keys: {', '.join(missing)}")
    if not isinstance(data["pipeline_command"], list) or not data["pipeline_command"]:
        raise ValueError("pipeline_command must be a non-empty JSON array")
    data.setdefault("listen_host", "127.0.0.1")
    data.setdefault("listen_port", 8787)
    data.setdefault("max_upload_bytes", 200 * 1024**3)
    data.setdefault("max_chunk_bytes", 64 * 1024**2)
    data.setdefault("poll_seconds", 3)
    data.setdefault("manual_review_required", False)
    data.setdefault("webhook_allowed_hosts", [])
    data.setdefault("webhook_proxy", "")
    data.setdefault("webhook_max_attempts", 8)
    data.setdefault("max_open_jobs_per_user", 5)
    data.setdefault("max_open_jobs", 50)
    data.setdefault("web_auth_enabled", False)
    data.setdefault("session_hours", 12)
    data.setdefault("oauth_proxy", data.get("webhook_proxy", ""))
    if data["web_auth_enabled"]:
        oauth_required = (
            "public_base_url",
            "github_oauth_client_id",
            "github_oauth_client_secret_file",
            "bootstrap_admin_emails",
        )
        oauth_missing = [key for key in oauth_required if not data.get(key)]
        if oauth_missing:
            raise ValueError(f"missing web auth config keys: {', '.join(oauth_missing)}")
        public = parse.urlparse(data["public_base_url"])
        if public.scheme != "https" or not public.hostname:
            raise ValueError("public_base_url must be an absolute HTTPS URL")
        data["public_base_url"] = data["public_base_url"].rstrip("/")
        data["cookie_path"] = (public.path.rstrip("/") or "") + "/"
    data["_config_path"] = str(config_path)
    return data


class Store:
    def __init__(self, database_path: str | os.PathLike[str]):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextlib.contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    upload_offset INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    profile TEXT NOT NULL,
                    job_token_hash TEXT NOT NULL,
                    webhook_url TEXT,
                    webhook_secret TEXT,
                    output_path TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    worker_id TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress REAL NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    next_attempt_epoch REAL NOT NULL,
                    delivered_at TEXT,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    github_id INTEGER NOT NULL UNIQUE,
                    github_login TEXT NOT NULL,
                    email TEXT NOT NULL,
                    avatar_url TEXT,
                    role TEXT NOT NULL CHECK(role IN ('pending','uploader','admin','disabled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL,
                    approved_by INTEGER REFERENCES users(id),
                    approved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS web_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_epoch REAL NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_flows (
                    state_hash TEXT PRIMARY KEY,
                    code_verifier TEXT NOT NULL,
                    expires_epoch REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_role_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    actor_user_id INTEGER NOT NULL REFERENCES users(id),
                    target_user_id INTEGER NOT NULL REFERENCES users(id),
                    old_role TEXT NOT NULL,
                    new_role TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job
                ON jobs ((1)) WHERE state IN ('validating', 'running');
                CREATE INDEX IF NOT EXISTS jobs_queue
                ON jobs (state, created_at);
                CREATE INDEX IF NOT EXISTS webhook_due
                ON webhook_deliveries (delivered_at, next_attempt_epoch);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "owner_user_id" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN owner_user_id INTEGER REFERENCES users(id)")
            migrations = {
                "input_format": "TEXT NOT NULL DEFAULT 'auto'",
                # Legacy rows only ever published the PNG session archive.
                # New API-created jobs always store their explicit selection.
                "output_format": "TEXT NOT NULL DEFAULT 'png-sequence'",
                "rgb_resolution": "TEXT NOT NULL DEFAULT 'native'",
                "fallback_fps": "REAL NOT NULL DEFAULT 30.0",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
            db.execute("DELETE FROM web_sessions WHERE expires_epoch < ?", (time.time(),))
            db.execute("DELETE FROM oauth_flows WHERE expires_epoch < ?", (time.time(),))

    def event(
        self,
        db: sqlite3.Connection,
        job_id: str,
        state: str,
        stage: str,
        progress: float,
        message: str,
    ) -> None:
        db.execute(
            "INSERT INTO events(job_id, created_at, state, stage, progress, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, utc_now(), state, stage, progress, message),
        )

    def update_state(
        self,
        job_id: str,
        *,
        state: str,
        stage: str,
        progress: float,
        message: str,
        error: str | None = None,
        output_path: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        now = utc_now()
        started = now if state == "running" else None
        finished = now if state in TERMINAL_STATES or state == "review_required" else None
        with self.connect() as db:
            db.execute(
                """
                UPDATE jobs SET updated_at=?, state=?, stage=?, progress=?, message=?,
                    error=COALESCE(?, error), output_path=COALESCE(?, output_path),
                    worker_id=COALESCE(?, worker_id),
                    started_at=COALESCE(started_at, ?),
                    finished_at=CASE WHEN ? IS NOT NULL THEN ? ELSE finished_at END
                WHERE id=?
                """,
                (
                    now,
                    state,
                    stage,
                    max(0.0, min(1.0, float(progress))),
                    message,
                    error,
                    output_path,
                    worker_id,
                    started,
                    finished,
                    finished,
                    job_id,
                ),
            )
            self.event(db, job_id, state, stage, progress, message)

    def get(self, job_id: str) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT j.*,u.github_login AS owner_login FROM jobs j "
                "LEFT JOIN users u ON u.id=j.owner_user_id WHERE j.id=?",
                (job_id,),
            ).fetchone()

    def claim(self, worker_id: str) -> sqlite3.Row | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                "SELECT 1 FROM jobs WHERE state IN ('validating', 'running') LIMIT 1"
            ).fetchone()
            if active:
                db.rollback()
                return None
            row = db.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                db.rollback()
                return None
            now = utc_now()
            db.execute(
                "UPDATE jobs SET state='validating', stage='sha256', progress=0.01, "
                "message='verifying uploaded archive', worker_id=?, updated_at=? WHERE id=?",
                (worker_id, now, row["id"]),
            )
            self.event(
                db,
                row["id"],
                "validating",
                "sha256",
                0.01,
                "verifying uploaded archive",
            )
            db.commit()
            return self.get(row["id"])

    def enqueue_webhook(self, job_id: str, event_type: str) -> None:
        row = self.get(job_id)
        if not row or not row["webhook_url"]:
            return
        payload = json.dumps(
            {"event": event_type, "job": public_job(row)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO webhook_deliveries"
                "(job_id,event_type,payload_json,next_attempt_epoch) VALUES(?,?,?,?)",
                (job_id, event_type, payload, time.time()),
            )


def public_job(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "created_at",
        "updated_at",
        "filename",
        "size_bytes",
        "sha256",
        "upload_offset",
        "state",
        "stage",
        "progress",
        "message",
        "profile",
        "input_format",
        "output_format",
        "rgb_resolution",
        "fallback_fps",
        "output_path",
        "error",
        "started_at",
        "finished_at",
    )
    payload = {key: row[key] for key in keys}
    payload["log_url"] = f"/v1/jobs/{row['id']}/log"
    payload["failure_url"] = f"/v1/jobs/{row['id']}/failure"
    available = row.keys() if hasattr(row, "keys") else row
    if "owner_login" in available:
        payload["owner_login"] = row["owner_login"]
    return payload


def valid_webhook_url(value: str, allowed_hosts: list[str]) -> bool:
    if not value:
        return True
    parsed = parse.urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() in {host.lower() for host in allowed_hosts}
        and not parsed.username
        and not parsed.password
    )


def upload_lock(job_id: str) -> threading.Lock:
    with _UPLOAD_LOCKS_GUARD:
        return _UPLOAD_LOCKS.setdefault(job_id, threading.Lock())


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "SandStoriesJobGateway/1"
    sys_version = ""

    @property
    def app(self) -> "GatewayServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        message = fmt % args
        message = re.sub(
            r"(/auth/github/callback)\?[^ ]+", r"\1?<redacted>", message
        )
        sys.stderr.write(f"{utc_now()} {self.client_address[0]} {message}\n")

    def json_response(
        self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def html_response(self, status: int, body: str, nonce: str = "") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            "img-src https://avatars.githubusercontent.com data:; "
            "connect-src 'self'; form-action 'self' https://github.com",
        )
        self.end_headers()
        self.wfile.write(encoded)

    def file_response(
        self,
        path: Path,
        download_name: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        if not path.is_file():
            self.json_response(404, {"error": "file not found"})
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range", "").strip()
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:
                suffix = int(match.group(2))
                start = max(0, size - suffix)
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    try:
                        self.wfile.write(block)
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    remaining -= len(block)

    def artifact_path(self, row: sqlite3.Row, kind: str = "tar.zst") -> Path | None:
        if row["state"] != "completed" or not row["output_path"]:
            return None
        job_root = self.app.job_root(row["id"]).resolve()
        output = Path(row["output_path"]).resolve()
        if not output.is_relative_to(job_root):
            return None
        names = {
            "zip": f"{row['id']}-final-v12.zip",
            "streams.zip": f"{row['id']}-final-v12-streams.zip",
            "tar.zst": f"{row['id']}-final-v12.tar.zst",
        }
        name = names.get(kind)
        if name is None:
            return None
        artifact = job_root / "artifacts" / name
        return artifact if artifact.is_file() else None

    def redirect(self, location: str, cookies: list[str] | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.send_header("Referrer-Policy", "no-referrer")
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def cookie_value(self, name: str, value: str, max_age: int) -> str:
        path = self.app.config.get("cookie_path", "/")
        return (
            f"{name}={value}; Path={path}; Max-Age={max_age}; "
            "Secure; HttpOnly; SameSite=Lax"
        )

    def public_url(self, suffix: str = "") -> str:
        return self.app.config["public_base_url"] + suffix

    def read_form(self, maximum: int = 16 * 1024) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError("invalid form body length")
        values = parse.parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        form = {key: value[-1] for key, value in values.items()}
        self._form_csrf = form.get("csrf", "")
        return form

    def github_json(self, url: str, token: str) -> Any:
        outgoing = request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "SandStories-Job-Gateway/1",
            },
        )
        with self.app.oauth_opener.open(outgoing, timeout=20) as response:
            return json.loads(response.read())

    def oauth_start(self) -> None:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        with self.app.store.connect() as db:
            db.execute("DELETE FROM oauth_flows WHERE expires_epoch < ?", (time.time(),))
            if db.execute("SELECT COUNT(*) FROM oauth_flows").fetchone()[0] >= 1000:
                raise ValueError("too many pending OAuth flows; retry later")
            db.execute(
                "INSERT INTO oauth_flows(state_hash,code_verifier,expires_epoch) VALUES(?,?,?)",
                (token_hash(state), verifier, time.time() + 600),
            )
        callback = self.public_url("/auth/github/callback")
        query = parse.urlencode(
            {
                "client_id": self.app.config["github_oauth_client_id"],
                "redirect_uri": callback,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "allow_signup": "false",
            }
        )
        self.redirect(
            "https://github.com/login/oauth/authorize?" + query,
            [self.cookie_value("sandstories_oauth_state", state, 600)],
        )

    def oauth_callback(self, query: str) -> None:
        values = parse.parse_qs(query)
        state = values.get("state", [""])[0]
        code = values.get("code", [""])[0]
        cookie = self.cookies().get("sandstories_oauth_state")
        if not state or not code or not cookie or not hmac.compare_digest(state, cookie.value):
            raise ValueError("OAuth state validation failed")
        with self.app.store.connect() as db:
            flow = db.execute(
                "SELECT * FROM oauth_flows WHERE state_hash=? AND expires_epoch>?",
                (token_hash(state), time.time()),
            ).fetchone()
            db.execute("DELETE FROM oauth_flows WHERE state_hash=?", (token_hash(state),))
        if not flow:
            raise ValueError("OAuth flow expired or was already used")
        callback = self.public_url("/auth/github/callback")
        body = parse.urlencode(
            {
                "client_id": self.app.config["github_oauth_client_id"],
                "client_secret": self.app.github_client_secret,
                "code": code,
                "redirect_uri": callback,
                "code_verifier": flow["code_verifier"],
            }
        ).encode()
        outgoing = request.Request(
            "https://github.com/login/oauth/access_token",
            data=body,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.app.oauth_opener.open(outgoing, timeout=20) as response:
            token_response = json.loads(response.read())
        access_token = token_response.get("access_token", "")
        if not access_token:
            detail = str(
                token_response.get("error_description")
                or token_response.get("error")
                or "unknown error"
            )
            raise RuntimeError(f"GitHub token exchange failed: {detail}")
        identity = self.github_json("https://api.github.com/user", access_token)
        try:
            emails = self.github_json(
                "https://api.github.com/user/emails?per_page=100", access_token
            )
        except urlerror.HTTPError as exc:
            if exc.code in {401, 403}:
                raise RuntimeError("GitHub did not grant usable user:email access") from exc
            raise
        verified = [item for item in emails if item.get("verified") and item.get("email")]
        if not verified:
            raise RuntimeError("GitHub account has no verified email address")
        primary = next((item["email"] for item in verified if item.get("primary")), verified[0]["email"])
        bootstrap = {email.lower() for email in self.app.config["bootstrap_admin_emails"]}
        matching_admin = next((item["email"] for item in verified if item["email"].lower() in bootstrap), None)
        github_id = int(identity["id"])
        now = utc_now()
        with self.app.store.connect() as db:
            existing = db.execute("SELECT * FROM users WHERE github_id=?", (github_id,)).fetchone()
            if existing:
                role = existing["role"]
                if matching_admin and role == "pending":
                    has_admin = db.execute(
                        "SELECT 1 FROM users WHERE role='admin' LIMIT 1"
                    ).fetchone()
                    if not has_admin:
                        role = "admin"
                db.execute(
                    "UPDATE users SET github_login=?,email=?,avatar_url=?,role=?,updated_at=?,last_login_at=? WHERE id=?",
                    (identity["login"], matching_admin or primary, identity.get("avatar_url"), role, now, now, existing["id"]),
                )
                user_id = existing["id"]
            else:
                role = "admin" if matching_admin else "pending"
                cursor = db.execute(
                    "INSERT INTO users(github_id,github_login,email,avatar_url,role,created_at,updated_at,last_login_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (github_id, identity["login"], matching_admin or primary, identity.get("avatar_url"), role, now, now, now),
                )
                user_id = cursor.lastrowid
            session_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            lifetime = int(float(self.app.config["session_hours"]) * 3600)
            db.execute(
                "INSERT INTO web_sessions(token_hash,user_id,csrf_token,created_at,expires_epoch,last_seen_at) "
                "VALUES(?,?,?,?,?,?)",
                (token_hash(session_token), user_id, csrf_token, now, time.time() + lifetime, now),
            )
        self.redirect(
            self.public_url("/ui"),
            [
                self.cookie_value("sandstories_session", session_token, lifetime),
                self.cookie_value("sandstories_oauth_state", "", 0),
            ],
        )

    def page_shell(self, title: str, content: str, user: sqlite3.Row | None, nonce: str) -> str:
        nav = ""
        if user:
            current_session = self.web_session()
            csrf = html.escape(current_session[0]["csrf_token"] if current_session else "")
            admin = f'<a href="{self.public_url("/ui/admin/users")}">Users</a>' if user["role"] == "admin" else ""
            nav = (
                f'<nav><a href="{self.public_url("/ui")}">Jobs</a>{admin}'
                f'<span>@{html.escape(user["github_login"])}</span>'
                f'<form method="post" action="{self.public_url("/logout")}"><input type="hidden" name="csrf" value="{csrf}"><button>Sign out</button></form></nav>'
            )
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style nonce="{nonce}">
:root{{--ink:#151515;--muted:#666;--line:#ddd;--paper:#faf9f5;--accent:#2357d9;--bad:#a32222}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main,nav{{max-width:1120px;margin:auto;padding:20px}}nav{{display:flex;gap:18px;align-items:center;border-bottom:1px solid var(--line)}}
nav span{{margin-left:auto}}nav form{{margin:0}}h1{{font-size:28px}}h2{{margin-top:30px}}a{{color:var(--accent)}}
button,.button{{border:0;border-radius:7px;background:var(--accent);color:white;padding:9px 14px;cursor:pointer;text-decoration:none}}
input,select{{padding:9px;border:1px solid #bbb;border-radius:6px;max-width:100%}}label{{display:block;margin:12px 0}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{text-align:left;padding:9px;border-bottom:1px solid var(--line)}}
.muted{{color:var(--muted)}}.error{{color:var(--bad)}}progress{{width:min(620px,100%);height:18px}}
.card{{background:white;border:1px solid var(--line);border-radius:10px;padding:18px;margin:16px 0}}code{{overflow-wrap:anywhere}}
</style></head><body>{nav}<main>{content}</main></body></html>"""

    def web_ui(self) -> None:
        nonce = secrets.token_urlsafe(18)
        session = self.web_session()
        if not session:
            content = (
                "<h1>SandStories processing</h1><p>Upload an aligned Azure RGB-D capture and follow its v12 processing job.</p>"
                f'<p><a class="button" href="{self.public_url("/auth/github")}">Sign in with GitHub</a></p>'
            )
            self.html_response(200, self.page_shell("SandStories jobs", content, None, nonce), nonce)
            return
        session_row, user = session
        if user["role"] == "pending":
            content = "<h1>Access pending</h1><p>Your GitHub identity is verified. An administrator must approve upload access.</p>"
            self.html_response(403, self.page_shell("Access pending", content, user, nonce), nonce)
            return
        if user["role"] == "disabled":
            content = "<h1>Access disabled</h1><p>Contact the service administrator.</p>"
            self.html_response(403, self.page_shell("Access disabled", content, user, nonce), nonce)
            return
        csrf = session_row["csrf_token"]
        content = """<h1>SandStories jobs</h1>
<div class="card"><h2>Submit capture</h2>
<p class="muted">Input may be an Azure Kinect MKV, an aligned RGB/depth frame archive, or a SandStories stream bundle. Timing metadata is used when present; the fallback frame rate is only for old archives without timestamps.</p>
<form id="upload"><label>Capture <input id="archive" type="file" required accept=".mkv,.tar,.gz,.tgz,.zip"></label>
<label>Input format <select id="inputFormat"><option value="auto">Auto-detect</option><option value="azure-mkv">Azure Kinect MKV</option><option value="frame-archive">RGB/depth frame archive</option><option value="stream-bundle">SandStories stream bundle</option></select></label>
<label>Output format <select id="outputFormat"><option value="compact-streams">Compact streams (H.264 RGB + lossless depth)</option><option value="lossless-streams">Lossless streams (FFV1 RGB + depth)</option><option value="png-sequence">PNG sequence package</option><option value="both">PNG package and compact streams</option></select></label>
<label>RGB export resolution <select id="rgbResolution"><option value="native">Native processed size</option><option value="75-percent">75% linear size</option><option value="50-percent">50% linear size</option></select></label>
<label>Fallback FPS <input id="fallbackFps" type="number" min="0.1" max="240" step="0.001" value="30"></label>
<label>Webhook (optional) <input id="webhook" type="url" placeholder="https://allowed.example/hook" size="56"></label>
<button type="submit">Upload and queue</button></form><p id="uploadText" class="muted"></p>
<p id="webhookCredential" class="muted"></p><progress id="uploadProgress" value="0" max="1"></progress></div>
<h2>Jobs</h2><table><thead><tr><th>Job</th><th>Owner</th><th>State</th><th>Stage</th><th>Progress</th><th>Updated</th></tr></thead><tbody id="jobs"></tbody></table>
"""
        script = f"""<script nonce="{nonce}">
const csrf={json.dumps(csrf)}; const prefix='../'; const chunkBytes=1024*1024;
const text=document.querySelector('#uploadText'), credential=document.querySelector('#webhookCredential'), bar=document.querySelector('#uploadProgress');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function api(path,options={{}}){{options.credentials='same-origin';options.headers={{...(options.headers||{{}}),'X-CSRF-Token':csrf}};const r=await fetch(prefix+path,options);if(!r.ok)throw new Error(await r.text());return r;}}
async function refresh(){{const r=await api('v1/jobs?limit=50');const data=await r.json();const body=document.querySelector('#jobs');body.replaceChildren();for(const j of data.jobs){{const tr=document.createElement('tr');const first=document.createElement('td'),link=document.createElement('a');link.href='/ui/jobs/'+encodeURIComponent(j.id);link.textContent=j.id;first.append(link);tr.append(first);for(const value of [j.owner_login,j.state,j.stage,Math.round(j.progress*100)+'%',j.updated_at]){{const td=document.createElement('td');td.textContent=value??'';tr.append(td)}}body.append(tr)}}}}
document.querySelector('#upload').addEventListener('submit',async e=>{{e.preventDefault();const file=document.querySelector('#archive').files[0];if(!file)return;bar.max=file.size;credential.textContent='';const jobOptions={{input_format:document.querySelector('#inputFormat').value,output_format:document.querySelector('#outputFormat').value,rgb_resolution:document.querySelector('#rgbResolution').value,fallback_fps:Number(document.querySelector('#fallbackFps').value)}};const optionKey=JSON.stringify(jobOptions);let saved;try{{saved=JSON.parse(localStorage.getItem('sandstoriesUpload')||'null')}}catch{{saved=null}}try{{if(!saved||saved.name!==file.name||saved.size!==file.size||saved.optionKey!==optionKey){{text.textContent='Creating job…';const r=await api('v1/jobs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{filename:file.name,size_bytes:file.size,sha256:'auto',profile:'azure-hand-free-v12',webhook_url:document.querySelector('#webhook').value,...jobOptions}})}});const d=await r.json();saved={{id:d.job.id,name:file.name,size:file.size,optionKey}};localStorage.setItem('sandstoriesUpload',JSON.stringify(saved));if(d.webhook_secret)credential.textContent='Copy this webhook signing secret now; it is shown only once: '+d.webhook_secret}}let head=await api(`v1/jobs/${{saved.id}}/input`,{{method:'HEAD'}});let offset=Number(head.headers.get('Upload-Offset'));bar.value=offset;while(offset<file.size){{const chunk=file.slice(offset,Math.min(file.size,offset+chunkBytes));let sent=false;for(let attempt=1;attempt<=12&&!sent;attempt++){{try{{const r=await api(`v1/jobs/${{saved.id}}/input`,{{method:'PATCH',headers:{{'Content-Type':'application/offset+octet-stream','Upload-Offset':String(offset)}},body:chunk}});offset=Number(r.headers.get('Upload-Offset'));bar.value=offset;text.textContent=`${{offset}} / ${{file.size}} bytes`;sent=true}}catch(err){{text.textContent=`Connection interrupted; retry ${{attempt}}/12`;await sleep(Math.min(60000,1000*2**attempt));head=await api(`v1/jobs/${{saved.id}}/input`,{{method:'HEAD'}});offset=Number(head.headers.get('Upload-Offset'))}}}}if(!sent)throw new Error('Upload retry limit reached')}}await api(`v1/jobs/${{saved.id}}/commit`,{{method:'POST'}});localStorage.removeItem('sandstoriesUpload');text.textContent='Upload committed and queued.';await refresh()}}catch(err){{text.textContent=String(err);text.className='error'}}}});
refresh();setInterval(refresh,5000);
</script>"""
        self.html_response(200, self.page_shell("SandStories jobs", content + script, user, nonce), nonce)

    def job_detail_page(self, job_id: str) -> None:
        nonce = secrets.token_urlsafe(18)
        session = self.web_session()
        row = self.app.store.get(job_id)
        if not session or not row or not self.authorize_job(row):
            self.html_response(404, self.page_shell("Not found", "<h1>Job not found</h1>", session[1] if session else None, nonce), nonce)
            return
        with self.app.store.connect() as db:
            events = db.execute(
                "SELECT created_at,state,stage,progress,message FROM events WHERE job_id=? ORDER BY id DESC LIMIT 100",
                (job_id,),
            ).fetchall()
        event_rows = "".join(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (event["created_at"], event["state"], event["stage"], f"{event['progress']:.0%}", event["message"])
            ) + "</tr>"
            for event in events
        )
        log_path = self.app.job_root(job_id) / "pipeline.log"
        tail = ""
        if log_path.is_file():
            with log_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 64 * 1024))
                tail = stream.read().decode("utf-8", "replace")
        zip_artifact = self.artifact_path(row, "zip")
        stream_artifact = self.artifact_path(row, "streams.zip")
        tar_artifact = self.artifact_path(row, "tar.zst")
        artifact_links = (
            f'<a class="button" href="{self.public_url(f"/v1/jobs/{job_id}/artifact.zip")}">Download final v12 (.zip)</a> '
            if zip_artifact
            else (
                '<span class="muted">Final download package is being prepared.</span> '
                if row["state"] == "completed"
                else ""
            )
        )
        if tar_artifact:
            artifact_links += (
                f'<a href="{self.public_url(f"/v1/jobs/{job_id}/artifact.tar.zst")}">'
                "Advanced: download .tar.zst</a> "
            )
        if stream_artifact:
            artifact_links += (
                f'<a href="{self.public_url(f"/v1/jobs/{job_id}/artifact.streams.zip")}">'
                "Download compact RGB-D streams</a> "
            )
        content = (
            f"<h1>{html.escape(job_id)}</h1><div class=\"card\"><p><b>State:</b> {html.escape(row['state'])} · "
            f"<b>Stage:</b> {html.escape(row['stage'])} · <b>Progress:</b> {row['progress']:.0%}</p>"
            f"<p>{html.escape(row['message'])}</p><p><b>SHA-256:</b> <code>{html.escape(row['sha256'])}</code></p>"
            f"<p><b>Input:</b> {html.escape(row['input_format'])} · <b>Output:</b> {html.escape(row['output_format'])} · "
            f"<b>RGB:</b> {html.escape(row['rgb_resolution'])} · <b>Fallback FPS:</b> {row['fallback_fps']:g}</p>"
            f"<p><b>Output:</b> <code>{html.escape(row['output_path'] or '')}</code></p>"
            f'<p>{artifact_links}<a class="button" href="{self.public_url(f"/v1/jobs/{job_id}/log")}">Download complete pipeline.log</a></p></div>'
            "<h2>Events</h2><table><thead><tr><th>Time</th><th>State</th><th>Stage</th><th>Progress</th><th>Message</th></tr></thead>"
            f"<tbody>{event_rows}</tbody></table><h2>Pipeline log tail (last 64 KiB)</h2><pre class=\"card\">{html.escape(tail)}</pre>"
        )
        self.html_response(200, self.page_shell(f"Job {job_id}", content, session[1], nonce), nonce)

    def admin_users_page(self) -> None:
        nonce = secrets.token_urlsafe(18)
        session = self.web_session()
        if not session or session[1]["role"] != "admin":
            self.html_response(403, self.page_shell("Forbidden", "<h1>Forbidden</h1>", session[1] if session else None, nonce), nonce)
            return
        session_row, current = session
        with self.app.store.connect() as db:
            users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        rows = []
        for user in users:
            options = "".join(
                f'<option value="{role}"{" selected" if role == user["role"] else ""}>{role}</option>'
                for role in ("pending", "uploader", "admin", "disabled")
            )
            disabled = " disabled" if user["id"] == current["id"] else ""
            rows.append(
                "<tr>"
                f"<td>@{html.escape(user['github_login'])}</td><td>{html.escape(user['email'])}</td>"
                f"<td><form method=\"post\" action=\"users/{user['id']}\">"
                f"<input type=\"hidden\" name=\"csrf\" value=\"{html.escape(session_row['csrf_token'])}\">"
                f"<select name=\"role\"{disabled}>{options}</select> <button{disabled}>Save</button></form></td>"
                f"<td>{html.escape(user['last_login_at'])}</td></tr>"
            )
        content = "<h1>User access</h1><p>New GitHub users remain pending until approved.</p><table><thead><tr><th>GitHub</th><th>Verified email</th><th>Role</th><th>Last login</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        self.html_response(200, self.page_shell("User access", content, current, nonce), nonce)

    def update_user_role(self, user_id: int) -> None:
        form = self.read_form()
        session = self.web_session()
        if not session or session[1]["role"] != "admin" or not self.csrf_valid():
            self.json_response(403, {"error": "admin and CSRF authorization required"})
            return
        role = form.get("role", "")
        if role not in {"pending", "uploader", "admin", "disabled"}:
            raise ValueError("invalid role")
        if user_id == session[1]["id"]:
            raise ValueError("the current administrator cannot change their own role")
        with self.app.store.connect() as db:
            target = db.execute("SELECT id,role FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise ValueError("user not found")
            db.execute(
                "UPDATE users SET role=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?",
                (role, session[1]["id"], utc_now(), utc_now(), user_id),
            )
            if role != target["role"]:
                db.execute(
                    "INSERT INTO user_role_events(created_at,actor_user_id,target_user_id,old_role,new_role) "
                    "VALUES(?,?,?,?,?)",
                    (utc_now(), session[1]["id"], user_id, target["role"], role),
                )
            if role == "disabled":
                db.execute("DELETE FROM web_sessions WHERE user_id=?", (user_id,))
        self.redirect(self.public_url("/ui/admin/users"))

    def logout(self) -> None:
        form = self.read_form()
        if not self.csrf_valid():
            self.json_response(403, {"error": "CSRF validation failed"})
            return
        morsel = self.cookies().get("sandstories_session")
        if morsel:
            with self.app.store.connect() as db:
                db.execute("DELETE FROM web_sessions WHERE token_hash=?", (token_hash(morsel.value),))
        self.redirect(
            self.public_url("/ui"),
            [self.cookie_value("sandstories_session", "", 0)],
        )

    def read_json(self, maximum: int = 64 * 1024) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError("invalid JSON body length")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def bearer(self) -> str:
        value = self.headers.get("Authorization", "")
        return value[7:] if value.startswith("Bearer ") else ""

    def cookies(self) -> SimpleCookie:
        result = SimpleCookie()
        with contextlib.suppress(Exception):
            result.load(self.headers.get("Cookie", ""))
        return result

    def web_session(self) -> tuple[sqlite3.Row, sqlite3.Row] | None:
        if not self.app.config.get("web_auth_enabled"):
            return None
        morsel = self.cookies().get("sandstories_session")
        if not morsel or not morsel.value:
            return None
        digest = token_hash(morsel.value)
        with self.app.store.connect() as db:
            row = db.execute(
                """
                SELECT s.token_hash,s.user_id,s.csrf_token,s.expires_epoch,
                       u.github_id,u.github_login,u.email,u.avatar_url,u.role
                FROM web_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_epoch>?
                """,
                (digest, time.time()),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE web_sessions SET last_seen_at=? WHERE token_hash=?",
                (utc_now(), digest),
            )
            user = db.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
        return row, user

    def session_user(self) -> sqlite3.Row | None:
        session = self.web_session()
        return session[1] if session else None

    def csrf_valid(self) -> bool:
        session = self.web_session()
        if not session:
            return False
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied and self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            supplied = getattr(self, "_form_csrf", "")
        return bool(supplied) and hmac.compare_digest(supplied, session[0]["csrf_token"])

    def mutation_authorized(
        self,
        row: sqlite3.Row | None = None,
        *,
        submitter: bool = False,
        admin_only: bool = False,
    ) -> bool:
        value = self.bearer()
        if value:
            if hmac.compare_digest(value, self.app.admin_token):
                return True
            if submitter and hmac.compare_digest(value, self.app.submit_token):
                return True
            if row is not None and hmac.compare_digest(token_hash(value), row["job_token_hash"]):
                return not admin_only
            return False
        return self.csrf_valid()

    def is_admin(self) -> bool:
        value = self.bearer()
        if value and hmac.compare_digest(value, self.app.admin_token):
            return True
        user = self.session_user()
        return bool(user and user["role"] == "admin")

    def is_submitter(self) -> bool:
        value = self.bearer()
        if value and (
            hmac.compare_digest(value, self.app.submit_token)
            or hmac.compare_digest(value, self.app.admin_token)
        ):
            return True
        user = self.session_user()
        return bool(user and user["role"] in {"uploader", "admin"})

    def authorize_job(self, row: sqlite3.Row) -> bool:
        value = self.bearer()
        if value and (
            hmac.compare_digest(value, self.app.admin_token)
            or hmac.compare_digest(token_hash(value), row["job_token_hash"])
        ):
            return True
        user = self.session_user()
        return bool(
            user
            and user["role"] in {"uploader", "admin"}
            and (user["role"] == "admin" or row["owner_user_id"] == user["id"])
        )

    def route(self) -> tuple[list[str], str]:
        parsed = parse.urlparse(self.path)
        return [part for part in parsed.path.split("/") if part], parsed.query

    def do_GET(self) -> None:
        try:
            parts, query = self.route()
            if parts == ["healthz"]:
                self.json_response(200, {"ok": True, "time": utc_now()})
                return
            if self.app.config.get("web_auth_enabled"):
                if not parts:
                    self.redirect(self.public_url("/ui"))
                    return
                if parts == ["auth", "github"]:
                    self.oauth_start()
                    return
                if parts == ["auth", "github", "callback"]:
                    self.oauth_callback(query)
                    return
                if parts == ["ui"]:
                    self.web_ui()
                    return
                if len(parts) == 3 and parts[:2] == ["ui", "jobs"]:
                    self.job_detail_page(parts[2])
                    return
                if parts == ["ui", "admin", "users"]:
                    self.admin_users_page()
                    return
            if parts == ["v1", "jobs"]:
                user = self.session_user()
                if not self.is_admin() and not (user and user["role"] == "uploader"):
                    self.json_response(401, {"error": "authorization required"})
                    return
                limit = min(100, max(1, int(parse.parse_qs(query).get("limit", [20])[0])))
                with self.app.store.connect() as db:
                    if self.is_admin():
                        rows = db.execute(
                            "SELECT j.*,u.github_login AS owner_login FROM jobs j "
                            "LEFT JOIN users u ON u.id=j.owner_user_id "
                            "ORDER BY j.created_at DESC LIMIT ?", (limit,)
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT j.*,u.github_login AS owner_login FROM jobs j "
                            "LEFT JOIN users u ON u.id=j.owner_user_id "
                            "WHERE j.owner_user_id=? ORDER BY j.created_at DESC LIMIT ?",
                            (user["id"], limit),
                        ).fetchall()
                self.json_response(200, {"jobs": [public_job(row) for row in rows]})
                return
            if len(parts) >= 3 and parts[:2] == ["v1", "jobs"]:
                row = self.app.store.get(parts[2])
                if not row:
                    self.json_response(404, {"error": "job not found"})
                    return
                if not self.authorize_job(row):
                    self.json_response(401, {"error": "job authorization required"})
                    return
                if len(parts) == 3:
                    payload = public_job(row)
                    progress_path = self.app.job_root(row["id"]) / "progress.json"
                    if progress_path.is_file():
                        with contextlib.suppress(Exception):
                            payload["live_progress"] = json.loads(
                                progress_path.read_text(encoding="utf-8")
                            )
                    self.json_response(200, {"job": payload})
                    return
                if len(parts) == 4 and parts[3] == "events":
                    with self.app.store.connect() as db:
                        events = db.execute(
                            "SELECT created_at,state,stage,progress,message FROM events "
                            "WHERE job_id=? ORDER BY id", (row["id"],)
                        ).fetchall()
                    self.json_response(200, {"events": [dict(event) for event in events]})
                    return
                if len(parts) == 4 and parts[3] == "log":
                    log_path = self.app.job_root(row["id"]) / "pipeline.log"
                    self.file_response(
                        log_path,
                        f"{row['id']}-pipeline.log",
                        "text/plain; charset=utf-8",
                    )
                    return
                if len(parts) == 4 and parts[3] in {"artifact", "artifact.zip", "artifact.streams.zip", "artifact.tar.zst"}:
                    kind = "zip" if parts[3] == "artifact.zip" else ("streams.zip" if parts[3] == "artifact.streams.zip" else "tar.zst")
                    artifact = self.artifact_path(row, kind)
                    if artifact is None:
                        self.json_response(404, {"error": "final download package is not ready"})
                        return
                    self.file_response(
                        artifact,
                        artifact.name,
                        "application/zip" if kind in {"zip", "streams.zip"} else "application/zstd",
                    )
                    return
                if len(parts) == 4 and parts[3] == "failure":
                    failure_path = self.app.job_root(row["id"]) / "failure.json"
                    if not failure_path.is_file():
                        self.json_response(404, {"error": "failure report not found"})
                        return
                    self.json_response(200, json.loads(failure_path.read_text(encoding="utf-8")))
                    return
            self.json_response(404, {"error": "not found"})
        except Exception as exc:
            self.fail(exc)

    def do_HEAD(self) -> None:
        try:
            parts, _ = self.route()
            if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "input":
                row = self.app.store.get(parts[2])
                if not row:
                    self.json_response(404, {"error": "job not found"})
                    return
                if not self.authorize_job(row):
                    self.json_response(401, {"error": "job authorization required"})
                    return
                offset = self.app.reconcile_offset(row)
                self.json_response(
                    200,
                    {},
                    {"Upload-Offset": str(offset), "Upload-Length": str(row["size_bytes"])},
                )
                return
            if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] in {"artifact", "artifact.zip", "artifact.streams.zip", "artifact.tar.zst", "log"}:
                row = self.app.store.get(parts[2])
                if not row or not self.authorize_job(row):
                    self.json_response(404, {"error": "job not found"})
                    return
                if parts[3] in {"artifact", "artifact.zip", "artifact.streams.zip", "artifact.tar.zst"}:
                    kind = "zip" if parts[3] == "artifact.zip" else ("streams.zip" if parts[3] == "artifact.streams.zip" else "tar.zst")
                    artifact = self.artifact_path(row, kind)
                    if artifact is None:
                        self.json_response(404, {"error": "final download package is not ready"})
                        return
                    self.file_response(
                        artifact,
                        artifact.name,
                        "application/zip" if kind in {"zip", "streams.zip"} else "application/zstd",
                    )
                else:
                    self.file_response(
                        self.app.job_root(row["id"]) / "pipeline.log",
                        f"{row['id']}-pipeline.log",
                        "text/plain; charset=utf-8",
                    )
                return
            self.json_response(404, {"error": "not found"})
        except Exception as exc:
            self.fail(exc)

    def do_POST(self) -> None:
        try:
            parts, _ = self.route()
            if self.app.config.get("web_auth_enabled"):
                if parts == ["logout"]:
                    self.logout()
                    return
                if len(parts) == 4 and parts[:3] == ["ui", "admin", "users"]:
                    self.update_user_role(int(parts[3]))
                    return
            if parts == ["v1", "jobs"]:
                self.create_job()
                return
            if len(parts) == 4 and parts[:2] == ["v1", "jobs"]:
                row = self.app.store.get(parts[2])
                if not row:
                    self.json_response(404, {"error": "job not found"})
                    return
                action = parts[3]
                if action == "review":
                    if not self.is_admin() or not self.mutation_authorized(row, admin_only=True):
                        self.json_response(401, {"error": "admin authorization required"})
                        return
                    self.review_job(row)
                    return
                if not self.authorize_job(row):
                    self.json_response(401, {"error": "job authorization required"})
                    return
                if not self.mutation_authorized(row):
                    self.json_response(403, {"error": "CSRF validation failed"})
                    return
                if action == "commit":
                    self.commit_job(row)
                    return
                if action == "cancel":
                    self.cancel_job(row)
                    return
            self.json_response(404, {"error": "not found"})
        except Exception as exc:
            self.fail(exc)

    def do_PATCH(self) -> None:
        try:
            parts, _ = self.route()
            if len(parts) != 4 or parts[:2] != ["v1", "jobs"] or parts[3] != "input":
                self.json_response(404, {"error": "not found"})
                return
            row = self.app.store.get(parts[2])
            if not row:
                self.json_response(404, {"error": "job not found"})
                return
            if not self.authorize_job(row):
                self.json_response(401, {"error": "job authorization required"})
                return
            if not self.mutation_authorized(row):
                self.json_response(403, {"error": "CSRF validation failed"})
                return
            self.patch_upload(row)
        except Exception as exc:
            self.fail(exc)

    def create_job(self) -> None:
        if not self.is_submitter():
            self.json_response(401, {"error": "submit authorization required"})
            return
        if not self.mutation_authorized(submitter=True):
            self.json_response(403, {"error": "CSRF validation failed"})
            return
        body = self.read_json()
        filename = str(body.get("filename", ""))
        accepted_suffixes = (".mkv", ".tar", ".tar.gz", ".tgz", ".zip")
        if Path(filename).name != filename or not filename.lower().endswith(accepted_suffixes):
            raise ValueError("filename must be a plain .mkv, .tar, .tar.gz, .tgz, or .zip name")
        size = int(body.get("size_bytes", 0))
        if size <= 0 or size > int(self.app.config["max_upload_bytes"]):
            raise ValueError("size_bytes is outside the configured upload limit")
        digest = str(body.get("sha256", "")).lower()
        web_user = self.session_user()
        if digest == "auto" and not web_user:
            raise ValueError("automatic server-side hashing is available only in the web portal")
        if digest != "auto" and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")
        profile = str(body.get("profile", "azure-hand-free-v12"))
        if profile not in {"azure-hand-free-v12", "azure-hand-free-v12-2275"}:
            raise ValueError("unsupported pipeline profile")
        profile = "azure-hand-free-v12"
        input_format = str(body.get("input_format", "auto"))
        output_format = str(body.get("output_format", "compact-streams"))
        rgb_resolution = str(body.get("rgb_resolution", "native"))
        fallback_fps = float(body.get("fallback_fps", 30.0))
        if input_format not in INPUT_FORMATS:
            raise ValueError("unsupported input_format")
        if output_format not in OUTPUT_FORMATS:
            raise ValueError("unsupported output_format")
        if rgb_resolution not in RGB_RESOLUTIONS:
            raise ValueError("unsupported rgb_resolution")
        if not 0.1 <= fallback_fps <= 240.0:
            raise ValueError("fallback_fps must be between 0.1 and 240")
        lower_name = filename.lower()
        if input_format == "azure-mkv" and not lower_name.endswith(".mkv"):
            raise ValueError("azure-mkv input_format requires an .mkv file")
        if input_format == "frame-archive" and not lower_name.endswith((".tar", ".tar.gz", ".tgz", ".zip")):
            raise ValueError("frame-archive input_format requires a tar or zip archive")
        if input_format == "stream-bundle" and not lower_name.endswith(".zip"):
            raise ValueError("stream-bundle input_format requires a .zip file")
        webhook_url = str(body.get("webhook_url", ""))
        if not valid_webhook_url(webhook_url, self.app.config["webhook_allowed_hosts"]):
            raise ValueError("webhook_url must be HTTPS and use an allowed host")

        with self.app.store.connect() as db:
            open_count = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE state NOT IN ('completed','failed','rejected','cancelled')"
            ).fetchone()[0]
            if open_count >= int(self.app.config["max_open_jobs"]):
                raise ValueError("the service has reached its open-job limit")
            if web_user:
                user_open = db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE owner_user_id=? "
                    "AND state NOT IN ('completed','failed','rejected','cancelled')",
                    (web_user["id"],),
                ).fetchone()[0]
                if user_open >= int(self.app.config["max_open_jobs_per_user"]):
                    raise ValueError("this user has reached the open-job limit")

        job_id = JOB_ID_PREFIX + uuid.uuid4().hex
        job_token = secrets.token_urlsafe(32)
        webhook_secret = secrets.token_urlsafe(32) if webhook_url else None
        now = utc_now()
        root = self.app.job_root(job_id)
        (root / "input").mkdir(parents=True)
        with self.app.store.connect() as db:
            db.execute(
                """
                INSERT INTO jobs(
                    id,created_at,updated_at,filename,size_bytes,sha256,state,stage,
                    progress,message,profile,job_token_hash,webhook_url,webhook_secret,owner_user_id,
                    input_format,output_format,rgb_resolution,fallback_fps
                ) VALUES(?,?,?,?,?,?, 'uploading','upload',0,'awaiting upload',?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    now,
                    now,
                    filename,
                    size,
                    digest,
                    profile,
                    token_hash(job_token),
                    webhook_url or None,
                    webhook_secret,
                    web_user["id"] if web_user else None,
                    input_format,
                    output_format,
                    rgb_resolution,
                    fallback_fps,
                ),
            )
            self.app.store.event(db, job_id, "uploading", "upload", 0, "awaiting upload")
        response = {
            "job": public_job(self.app.store.get(job_id)),
            "job_token": job_token,
            "upload_url": f"/v1/jobs/{job_id}/input",
            "commit_url": f"/v1/jobs/{job_id}/commit",
        }
        if webhook_secret:
            response["webhook_secret"] = webhook_secret
        self.json_response(201, response)

    def patch_upload(self, row: sqlite3.Row) -> None:
        if row["state"] != "uploading":
            self.json_response(409, {"error": f"job is {row['state']}, not uploading"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > int(self.app.config["max_chunk_bytes"]):
            raise ValueError("chunk length is outside the configured limit")
        supplied_offset = int(self.headers.get("Upload-Offset", "-1"))
        with upload_lock(row["id"]):
            current = self.app.reconcile_offset(row)
            if supplied_offset != current:
                self.json_response(409, {"error": "offset mismatch", "upload_offset": current})
                return
            if current + length > row["size_bytes"]:
                raise ValueError("chunk exceeds declared upload size")
            target = self.app.partial_path(row)
            with target.open("ab") as stream:
                remaining = length
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ConnectionError("upload body ended before Content-Length")
                    stream.write(block)
                    remaining -= len(block)
                stream.flush()
                os.fsync(stream.fileno())
            offset = current + length
            with self.app.store.connect() as db:
                db.execute(
                    "UPDATE jobs SET upload_offset=?, updated_at=?, progress=?, message=? WHERE id=?",
                    (
                        offset,
                        utc_now(),
                        offset / row["size_bytes"],
                        f"uploaded {offset} of {row['size_bytes']} bytes",
                        row["id"],
                    ),
                )
        self.json_response(200, {}, {"Upload-Offset": str(offset)})

    def commit_job(self, row: sqlite3.Row) -> None:
        with upload_lock(row["id"]):
            offset = self.app.reconcile_offset(row)
            if row["state"] != "uploading" or offset != row["size_bytes"]:
                self.json_response(
                    409,
                    {"error": "upload is incomplete or already committed", "upload_offset": offset},
                )
                return
            os.replace(self.app.partial_path(row), self.app.input_path(row))
            self.app.store.update_state(
                row["id"],
                state="queued",
                stage="queued",
                progress=0,
                message="upload committed; waiting for the single worker",
            )
        self.app.store.enqueue_webhook(row["id"], "job.queued")
        self.json_response(202, {"job": public_job(self.app.store.get(row["id"]))})

    def cancel_job(self, row: sqlite3.Row) -> None:
        if row["state"] not in {"uploading", "queued"}:
            self.json_response(409, {"error": "only uploading or queued jobs can be cancelled"})
            return
        self.app.store.update_state(
            row["id"], state="cancelled", stage="cancelled", progress=row["progress"],
            message="cancelled by submitter",
        )
        self.app.store.enqueue_webhook(row["id"], "job.cancelled")
        self.json_response(200, {"job": public_job(self.app.store.get(row["id"]))})

    def review_job(self, row: sqlite3.Row) -> None:
        if row["state"] != "review_required":
            self.json_response(409, {"error": "job is not awaiting review"})
            return
        body = self.read_json()
        outcome = body.get("outcome")
        notes = str(body.get("notes", "")).strip()[:4000]
        if outcome not in {"approve", "reject"}:
            raise ValueError("review outcome must be approve or reject")
        if outcome == "approve" and row["stage"] == "mask_review":
            approval = self.app.job_root(row["id"]) / "stages" / "mask_review_approved.done"
            atomic_json(approval, {"approved_at": utc_now(), "notes": notes})
            self.app.store.update_state(
                row["id"],
                state="queued",
                stage="queued",
                progress=row["progress"],
                message="mask review approved; waiting to resume the single pipeline worker",
            )
            self.app.store.enqueue_webhook(row["id"], "job.queued")
            self.json_response(202, {"job": public_job(self.app.store.get(row["id"]))})
            return
        state = "completed" if outcome == "approve" else "rejected"
        message = "visual review approved" if outcome == "approve" else "visual review rejected"
        if notes:
            message += f": {notes}"
        self.app.store.update_state(
            row["id"], state=state, stage=state, progress=1, message=message
        )
        self.app.store.enqueue_webhook(row["id"], f"job.{state}")
        self.json_response(200, {"job": public_job(self.app.store.get(row["id"]))})

    def fail(self, exc: Exception) -> None:
        status = HTTPStatus.BAD_REQUEST if isinstance(exc, (ValueError, json.JSONDecodeError)) else 500
        if status == 500:
            traceback.print_exc()
        with contextlib.suppress(BrokenPipeError):
            self.json_response(int(status), {"error": str(exc) if status == 400 else "internal error"})


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: dict[str, Any]):
        # Tests and embedded callers may construct a config directly instead of
        # going through load_config().  Keep operational limits fail-safe here
        # as well so that the server never relies on a KeyError for admission.
        config.setdefault("max_open_jobs_per_user", 5)
        config.setdefault("max_open_jobs", 50)
        config.setdefault("web_auth_enabled", False)
        config.setdefault("session_hours", 12)
        config.setdefault("oauth_proxy", config.get("webhook_proxy", ""))
        self.config = config
        self.store = Store(config["database_path"])
        self.storage_root = Path(config["storage_root"]).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.submit_token = read_secret(config["submit_token_file"])
        self.admin_token = read_secret(config["admin_token_file"])
        self.github_client_secret = ""
        if config.get("web_auth_enabled"):
            self.github_client_secret = read_secret(config["github_oauth_client_secret_file"])
        proxy_url = str(config.get("oauth_proxy", ""))
        self.oauth_opener = request.build_opener(
            request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            if proxy_url
            else request.ProxyHandler({})
        )
        super().__init__((config["listen_host"], int(config["listen_port"])), GatewayHandler)

    def job_root(self, job_id: str) -> Path:
        if not job_id.startswith(JOB_ID_PREFIX) or not job_id[len(JOB_ID_PREFIX):].isalnum():
            raise ValueError("invalid job id")
        return self.storage_root / "jobs" / job_id

    def partial_path(self, row: sqlite3.Row) -> Path:
        return self.job_root(row["id"]) / "input" / "payload.part"

    def input_path(self, row: sqlite3.Row) -> Path:
        return self.job_root(row["id"]) / "input" / row["filename"]

    def reconcile_offset(self, row: sqlite3.Row) -> int:
        path = self.partial_path(row)
        actual = path.stat().st_size if path.exists() else 0
        if actual > row["size_bytes"]:
            raise RuntimeError("partial upload exceeds declared size")
        if actual != row["upload_offset"] and row["state"] == "uploading":
            with self.store.connect() as db:
                db.execute(
                    "UPDATE jobs SET upload_offset=?, updated_at=? WHERE id=?",
                    (actual, utc_now(), row["id"]),
                )
        return actual


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_progress(path: Path) -> dict[str, Any] | None:
    with contextlib.suppress(FileNotFoundError, json.JSONDecodeError, OSError):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    return None


def format_pipeline_command(config: dict[str, Any], row: sqlite3.Row) -> list[str]:
    job_root = Path(config["storage_root"]).resolve() / "jobs" / row["id"]
    context = {
        "job_id": row["id"],
        "job_root": str(job_root),
        "input_path": str(job_root / "input" / row["filename"]),
        "scratch_root": str(Path(config["scratch_root"]).resolve()),
    }
    return [str(part).format_map(context) for part in config["pipeline_command"]]


def queue_terminal_webhook(store: Store, job_id: str, state: str) -> None:
    store.enqueue_webhook(job_id, f"job.{state}")


def recover_orphaned_jobs(store: Store, worker_id: str) -> None:
    """Fail active jobs whose recorded local worker process no longer exists."""
    current_host, _ = worker_id.rsplit(":", 1)
    with store.connect() as db:
        rows = db.execute(
            "SELECT id,worker_id,progress,stage FROM jobs WHERE state IN ('validating','running')"
        ).fetchall()
    for row in rows:
        recorded = str(row["worker_id"] or "")
        alive = False
        if ":" in recorded:
            host, raw_pid = recorded.rsplit(":", 1)
            if host == current_host:
                try:
                    os.kill(int(raw_pid), 0)
                    alive = True
                except (OSError, ValueError):
                    pass
        if alive:
            continue
        store.update_state(
            row["id"],
            state="failed",
            stage=str(row["stage"] or "worker"),
            progress=float(row["progress"]),
            message=f"failed in {row['stage'] or 'worker'}: worker process ended before completion; download pipeline.log",
            error=f"orphaned active job recovered at {utc_now()}; previous worker={recorded or 'unknown'}",
        )
        job_root = store.path.parent / "jobs" / row["id"]
        job_root.mkdir(parents=True, exist_ok=True)
        failure = {
            "stage": str(row["stage"] or "worker"),
            "message": "worker process ended before the pipeline completed",
            "pipelineLog": str(job_root / "pipeline.log"),
            "logUrl": f"/v1/jobs/{row['id']}/log",
        }
        (job_root / "failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        queue_terminal_webhook(store, row["id"], "failed")


def run_job(config: dict[str, Any], store: Store, row: sqlite3.Row, worker_id: str) -> None:
    job_id = row["id"]
    job_root = Path(config["storage_root"]).resolve() / "jobs" / job_id
    input_path = job_root / "input" / row["filename"]
    progress_path = job_root / "progress.json"
    result_path = job_root / "result.json"
    log_path = job_root / "pipeline.log"
    failure_path = job_root / "failure.json"
    try:
        actual = hash_file(input_path)
        if row["sha256"] == "auto":
            with store.connect() as db:
                db.execute(
                    "UPDATE jobs SET sha256=?, updated_at=?, message=? WHERE id=?",
                    (actual, utc_now(), "server-side SHA-256 recorded", job_id),
                )
            row = store.get(job_id)
        elif not hmac.compare_digest(actual, row["sha256"]):
            raise RuntimeError(f"SHA-256 mismatch: expected {row['sha256']}, got {actual}")
        command = format_pipeline_command(config, row)
        store.update_state(
            job_id,
            state="running",
            stage="starting",
            progress=0.02,
            message="starting v12 pipeline",
            worker_id=worker_id,
        )
        store.enqueue_webhook(job_id, "job.started")
        environment = os.environ.copy()
        environment.update(
            {
                "SANDSTORIES_JOB_ID": job_id,
                "SANDSTORIES_JOB_ROOT": str(job_root),
                "SANDSTORIES_PROGRESS_FILE": str(progress_path),
                "SANDSTORIES_RESULT_FILE": str(result_path),
                "SANDSTORIES_INPUT_FORMAT": str(row["input_format"]),
                "SANDSTORIES_OUTPUT_FORMAT": str(row["output_format"]),
                "SANDSTORIES_RGB_RESOLUTION": str(row["rgb_resolution"]),
                "SANDSTORIES_FALLBACK_FPS": str(row["fallback_fps"]),
            }
        )
        with log_path.open("ab", buffering=0) as log:
            log.write((f"{utc_now()} command: {shlex.join(command)}\n").encode())
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            )
            last_progress: tuple[Any, ...] | None = None
            while process.poll() is None:
                progress = read_progress(progress_path)
                if progress:
                    snapshot = (
                        progress.get("stage"),
                        progress.get("progress"),
                        progress.get("message"),
                    )
                    if snapshot != last_progress:
                        store.update_state(
                            job_id,
                            state="running",
                            stage=str(snapshot[0] or "running"),
                            progress=float(snapshot[1] or 0),
                            message=str(snapshot[2] or "pipeline running"),
                            worker_id=worker_id,
                        )
                        last_progress = snapshot
                time.sleep(float(config["poll_seconds"]))
            return_code = process.returncode
        if return_code != 0:
            raise RuntimeError(f"pipeline exited with status {return_code}; inspect pipeline.log")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        output_path = str(result["output_path"])
        review_stage = str(result.get("review_stage", "visual_review"))
        result_progress = float(result.get("progress", 1.0))
        if result.get("review_required", config["manual_review_required"]):
            store.update_state(
                job_id,
                state="review_required",
                stage=review_stage,
                progress=result_progress,
                message=(
                    "mask review is required before the remaining v12 stages"
                    if review_stage == "mask_review"
                    else "automated v12 stages passed; manual Godot review is required"
                ),
                output_path=output_path,
            )
            store.enqueue_webhook(job_id, "job.review_required")
        else:
            store.update_state(
                job_id,
                state="completed",
                stage="completed",
                progress=1,
                message="pipeline completed",
                output_path=output_path,
            )
            queue_terminal_webhook(store, job_id, "completed")
    except Exception as exc:
        worker_trace = traceback.format_exc()
        latest = read_progress(progress_path) or {}
        current = store.get(job_id)
        failure_stage = str(latest.get("stage") or current["stage"] or "worker")
        detail = str(latest.get("message") or exc)
        message = f"failed in {failure_stage}: {detail}; download complete pipeline.log"
        with log_path.open("ab", buffering=0) as log:
            log.write((f"\n{utc_now()} worker failure in stage {failure_stage}\n{worker_trace}\n").encode())
        failure: dict[str, Any] = {}
        if failure_path.is_file():
            with contextlib.suppress(Exception):
                failure = json.loads(failure_path.read_text(encoding="utf-8"))
        failure.update(
            {
                "stage": failure_stage,
                "message": detail,
                "workerError": str(exc),
                "pipelineLog": str(log_path),
                "logUrl": f"/v1/jobs/{job_id}/log",
            }
        )
        failure_path.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        store.update_state(
            job_id,
            state="failed",
            stage=failure_stage,
            progress=current["progress"],
            message=message,
            error=worker_trace,
        )
        queue_terminal_webhook(store, job_id, "failed")


def deliver_due_webhooks(config: dict[str, Any], store: Store) -> None:
    with store.connect() as db:
        deliveries = db.execute(
            """
            SELECT d.*, j.webhook_url, j.webhook_secret
            FROM webhook_deliveries d JOIN jobs j ON j.id=d.job_id
            WHERE d.delivered_at IS NULL AND d.next_attempt_epoch <= ?
              AND d.attempt < ? ORDER BY d.id LIMIT 20
            """,
            (time.time(), int(config["webhook_max_attempts"])),
        ).fetchall()
    proxy_url = str(config.get("webhook_proxy", ""))
    opener = request.build_opener(
        request.ProxyHandler({"http": proxy_url, "https": proxy_url}) if proxy_url
        else request.ProxyHandler({})
    )
    delays = (10, 60, 300, 1800, 7200, 43200, 86400, 86400)
    for delivery in deliveries:
        payload = delivery["payload_json"].encode("utf-8")
        signature = hmac.new(
            delivery["webhook_secret"].encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        outgoing = request.Request(
            delivery["webhook_url"],
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "SandStories-Webhook/1",
                "X-SandStories-Event": delivery["event_type"],
                "X-SandStories-Delivery": str(delivery["id"]),
                "X-SandStories-Signature-256": "sha256=" + signature,
            },
        )
        try:
            with opener.open(outgoing, timeout=20) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"webhook returned HTTP {response.status}")
            with store.connect() as db:
                db.execute(
                    "UPDATE webhook_deliveries SET delivered_at=?, attempt=attempt+1, "
                    "last_error=NULL WHERE id=?", (utc_now(), delivery["id"])
                )
        except (OSError, urlerror.URLError, RuntimeError) as exc:
            attempt = delivery["attempt"] + 1
            delay = delays[min(attempt - 1, len(delays) - 1)]
            with store.connect() as db:
                db.execute(
                    "UPDATE webhook_deliveries SET attempt=?, next_attempt_epoch=?, "
                    "last_error=? WHERE id=?",
                    (attempt, time.time() + delay, str(exc)[:2000], delivery["id"]),
                )


def worker_loop(config: dict[str, Any], once: bool) -> None:
    store = Store(config["database_path"])
    worker_id = f"{os.uname().nodename if hasattr(os, 'uname') else os.getenv('COMPUTERNAME', 'worker')}:{os.getpid()}"
    recover_orphaned_jobs(store, worker_id)
    while True:
        deliver_due_webhooks(config, store)
        row = store.claim(worker_id)
        if row:
            run_job(config, store, row, worker_id)
            deliver_due_webhooks(config, store)
        if once:
            return
        time.sleep(float(config["poll_seconds"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db")
    subparsers.add_parser("serve")
    worker = subparsers.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "init-db":
        Store(config["database_path"])
        return 0
    if args.command == "serve":
        server = GatewayServer(config)
        print(f"listening on http://{config['listen_host']}:{config['listen_port']}")
        server.serve_forever()
        return 0
    if args.command == "worker":
        worker_loop(config, args.once)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
