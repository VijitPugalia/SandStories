from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .storage import db_path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'offline',
                current_session_id TEXT,
                last_seen_at REAL,
                last_status_json TEXT
            );

            CREATE TABLE IF NOT EXISTS packages (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                device_id TEXT,
                filename TEXT NOT NULL,
                zip_path TEXT NOT NULL,
                extracted_path TEXT,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                uploaded_at REAL NOT NULL,
                validation_status TEXT NOT NULL,
                validation_report_path TEXT,
                frame_count INTEGER,
                duration_seconds REAL,
                completion_status TEXT NOT NULL DEFAULT 'disabled',
                completion_started_at REAL,
                completion_finished_at REAL,
                completion_output_path TEXT,
                completion_report_path TEXT,
                completion_artifact_path TEXT,
                completion_error TEXT
            );

            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                acked_at REAL,
                completed_at REAL,
                error TEXT
            );
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(packages)")
        }
        migrations = {
            "completion_status": "TEXT NOT NULL DEFAULT 'disabled'",
            "completion_started_at": "REAL",
            "completion_finished_at": "REAL",
            "completion_output_path": "TEXT",
            "completion_report_path": "TEXT",
            "completion_artifact_path": "TEXT",
            "completion_error": "TEXT",
        }
        for name, declaration in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE packages ADD COLUMN {name} {declaration}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def upsert_device(device_id: str, name: str, status: str = "online", status_json: str | None = None) -> None:
    now = time.time()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO devices(id, name, status, last_seen_at, last_status_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                status=excluded.status,
                last_seen_at=excluded.last_seen_at,
                last_status_json=COALESCE(excluded.last_status_json, devices.last_status_json)
            """,
            (device_id, name, status, now, status_json),
        )


def list_devices() -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM devices ORDER BY last_seen_at DESC NULLS LAST")]


def insert_package(package: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO packages(
                id, session_id, device_id, filename, zip_path, extracted_path, size_bytes,
                sha256, uploaded_at, validation_status, validation_report_path,
                frame_count, duration_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package["id"],
                package.get("session_id"),
                package.get("device_id"),
                package["filename"],
                package["zip_path"],
                package.get("extracted_path"),
                package["size_bytes"],
                package["sha256"],
                package["uploaded_at"],
                package["validation_status"],
                package.get("validation_report_path"),
                package.get("frame_count"),
                package.get("duration_seconds"),
            ),
        )


def update_package_validation(package_id: str, status: str, report_path: Path, extracted_path: Path | None, frame_count: int | None, duration_seconds: float | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE packages
            SET validation_status=?, validation_report_path=?, extracted_path=?, frame_count=?, duration_seconds=?
            WHERE id=?
            """,
            (status, str(report_path), str(extracted_path) if extracted_path else None, frame_count, duration_seconds, package_id),
        )


def list_packages() -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM packages ORDER BY uploaded_at DESC")]


def get_package(package_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(conn.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone())


def queue_package_completion(package_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE packages
            SET completion_status='queued',
                completion_started_at=NULL,
                completion_finished_at=NULL,
                completion_output_path=NULL,
                completion_report_path=NULL,
                completion_artifact_path=NULL,
                completion_error=NULL
            WHERE id=?
            """,
            (package_id,),
        )


def mark_package_completion_unavailable(package_id: str, error: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE packages
            SET completion_status='unavailable',
                completion_finished_at=?,
                completion_error=?
            WHERE id=?
            """,
            (time.time(), error, package_id),
        )


def reset_running_completion_jobs() -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE packages
            SET completion_status='queued',
                completion_started_at=NULL,
                completion_error='Field console restarted while this job was running'
            WHERE completion_status='running'
            """
        )


def claim_next_completion_package() -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM packages
            WHERE completion_status='queued'
            ORDER BY uploaded_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        package_id = row["id"]
        conn.execute(
            """
            UPDATE packages
            SET completion_status='running',
                completion_started_at=?,
                completion_finished_at=NULL,
                completion_error=NULL
            WHERE id=? AND completion_status='queued'
            """,
            (time.time(), package_id),
        )
        claimed = conn.execute(
            "SELECT * FROM packages WHERE id=?", (package_id,)
        ).fetchone()
        return row_to_dict(claimed)


def finish_package_completion(
    package_id: str,
    *,
    output_path: Path,
    report_path: Path,
    artifact_path: Path,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE packages
            SET completion_status='completed',
                completion_finished_at=?,
                completion_output_path=?,
                completion_report_path=?,
                completion_artifact_path=?,
                completion_error=NULL
            WHERE id=?
            """,
            (
                time.time(),
                str(output_path),
                str(report_path),
                str(artifact_path),
                package_id,
            ),
        )


def fail_package_completion(package_id: str, error: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE packages
            SET completion_status='failed',
                completion_finished_at=?,
                completion_error=?
            WHERE id=?
            """,
            (time.time(), error, package_id),
        )
