"""Disk-backed local session/document catalog for the main application flow."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_RUNTIME_ROOT = Path(__file__).resolve().parents[5] / "runtime"
# Tests and side-by-side runs can use their own storage instead of overwriting
# the developer's runtime/sessions.json. SOURCELENS_RUNTIME_ROOT wins when both
# names are set.
RUNTIME_ROOT = Path(
    os.getenv("SOURCELENS_RUNTIME_ROOT") or os.getenv("REPORT_QA_RUNTIME_DIR") or _DEFAULT_RUNTIME_ROOT
).resolve()
CATALOG_FILE = RUNTIME_ROOT / "sessions.json"
UPLOAD_ROOT = RUNTIME_ROOT / "uploads"
EXTRACTION_ROOT = RUNTIME_ROOT / "extracted"

# Sync endpoints run in a thread pool and extraction runs as a background
# task, so the in-memory catalog is shared across threads. Hold this lock
# while mutating the catalog and while serializing it; never hold it across
# slow work (PDF extraction, AI/provider calls).
catalog_lock = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_catalog() -> dict[str, Any]:
    if not CATALOG_FILE.exists():
        return {"sessions": {}}
    try:
        value = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}
    if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
        return {"sessions": {}}
    return value


def save_catalog(catalog: dict[str, Any]) -> None:
    with catalog_lock:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        data = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True)
        # A per-writer temporary name: a shared "sessions.tmp" let two
        # concurrent saves replace each other's half-written file.
        temporary = CATALOG_FILE.with_name(f"{CATALOG_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, CATALOG_FILE)


def document_path(storage_name: str) -> Path:
    path = (UPLOAD_ROOT / storage_name).resolve()
    if UPLOAD_ROOT.resolve() not in path.parents:
        raise ValueError("invalid storage name")
    return path


def extraction_path(storage_name: str) -> Path:
    path = (EXTRACTION_ROOT / storage_name).resolve()
    if EXTRACTION_ROOT.resolve() not in path.parents:
        raise ValueError("invalid extraction storage name")
    return path
