"""Disk-backed local session/document catalog for the main application flow.

Two kinds of files hold the catalog:

* ``sessions.json`` holds the small session, document and message metadata.
  It is rewritten on every save.
* ``number-state/<document id>.json`` holds one document's number state: its
  per-number revision records (``evidence_state``) and its chart reads
  (``chart_extractions``). Every saved document has one; it is rewritten only
  when that document's state changed.

In memory each document dictionary still carries its number state, so
callers read and change ``document["evidence_state"]`` as before.

Number state only grows while a reading is current: numbers are added and
revisions and chart reads are appended, never edited in place. A new reading
replaces it under a new ``extraction_run_id``. So the state changed exactly
when its mark (reading id and those counts) changed.
"""

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
NUMBER_STATE_FIELDS = ("evidence_state", "chart_extractions")

# Sync endpoints run in a thread pool and extraction runs as a background
# task, so the in-memory catalog is shared across threads. Hold this lock
# while mutating the catalog and while serializing it; never hold it across
# slow work (PDF extraction, AI/provider calls).
catalog_lock = threading.RLock()
logger = logging.getLogger(__name__)
# Mark of the number state last written to each number-state file.
_written_marks: dict[str, tuple[Any, ...]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def number_state_root() -> Path:
    return RUNTIME_ROOT / "number-state"


def number_state_path(name: str) -> Path:
    root = number_state_root().resolve()
    path = (root / f"{name}.json").resolve()
    if path.parent != root:
        raise ValueError("invalid number state name")
    return path


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
    embedded = False
    for document in _documents(value):
        path = number_state_path(document["id"])
        if any(field in document for field in NUMBER_STATE_FIELDS):
            # A catalog from before the split: the number state is still
            # inside sessions.json. save_catalog below moves it out.
            embedded = True
        elif path.exists():
            document.update(json.loads(path.read_text(encoding="utf-8")))
            _written_marks[str(path)] = number_state_mark(document)
    if embedded:
        save_catalog(value)
    return value


def _set_aside_damaged_catalog() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    damaged = CATALOG_FILE.with_name(f"{CATALOG_FILE.name}.corrupt-{stamp}")
    os.replace(CATALOG_FILE, damaged)
    logger.critical("Session catalog %s is not valid; moved it to %s and started with an empty catalog", CATALOG_FILE, damaged)


def _documents(catalog: dict[str, Any]):
    for session in catalog.get("sessions", {}).values():
        yield from session.get("documents", [])


def number_state(document: dict[str, Any]) -> dict[str, Any]:
    return {field: document[field] for field in NUMBER_STATE_FIELDS if field in document}


def number_state_mark(document: dict[str, Any]) -> tuple[Any, ...]:
    state = document.get("evidence_state") or {}
    items = state.get("items") or {}
    return (
        state.get("extraction_run_id"),
        len(items),
        sum(len(item.get("revisions", ())) for item in items.values()),
        len(document.get("chart_extractions") or ()),
    )


def write_json_atomically(path: Path, value: Any, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=True)
    # A per-writer temporary name: a shared "sessions.tmp" let two
    # concurrent saves replace each other's half-written file.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_catalog(catalog: dict[str, Any]) -> None:
    with catalog_lock:
        metadata = {"sessions": {}}
        for session_id, session in catalog.get("sessions", {}).items():
            documents = []
            for document in session.get("documents", []):
                _save_number_state(document)
                documents.append({key: value for key, value in document.items() if key not in NUMBER_STATE_FIELDS})
            metadata["sessions"][session_id] = {**session, "documents": documents} if "documents" in session else session
        # Number state is written first: a crash between the two writes
        # leaves the new state with the old metadata, never metadata that
        # points at state that was not written.
        write_json_atomically(CATALOG_FILE, metadata, indent=2)


def _save_number_state(document: dict[str, Any]) -> None:
    path = number_state_path(document["id"])
    mark = number_state_mark(document)
    if _written_marks.get(str(path)) == mark and path.exists():
        return
    write_json_atomically(path, number_state(document))
    _written_marks[str(path)] = mark


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
