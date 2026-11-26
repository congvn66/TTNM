"""Disk-backed local session/document catalog for the main application flow."""

from __future__ import annotations

import json
import logging
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
logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_catalog() -> dict[str, Any]:
    if not CATALOG_FILE.exists():
        return {"sessions": {}}
    # A read error propagates: starting empty would let the next save
    # overwrite a catalog that is only unreadable for now.
    text = CATALOG_FILE.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
        _set_aside_damaged_catalog()
        return {"sessions": {}}
    return value


def _set_aside_damaged_catalog() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    damaged = CATALOG_FILE.with_name(f"{CATALOG_FILE.name}.corrupt-{stamp}")
    os.replace(CATALOG_FILE, damaged)
    logger.critical("Session catalog %s is not valid; moved it to %s and started with an empty catalog", CATALOG_FILE, damaged)


def save_catalog(catalog: dict[str, Any]) -> None:
    with catalog_lock:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        data = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True)
        # A per-writer temporary name: a shared "sessions.tmp" let two
        # concurrent saves replace each other's half-written file.
        temporary = CATALOG_FILE.with_name(f"{CATALOG_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
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
