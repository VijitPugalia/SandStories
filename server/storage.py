from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("SANDSTORIES_DATA_DIR", "server_data")).resolve()


def uploads_dir() -> Path:
    path = data_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def extracted_dir() -> Path:
    path = data_dir() / "extracted"
    path.mkdir(parents=True, exist_ok=True)
    return path


def derived_dir() -> Path:
    path = data_dir() / "derived"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    path = data_dir() / "sandstories.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned.strip("._") or "sandstories_session"
