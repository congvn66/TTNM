"""Disk-backed local session/document catalog for the main application flow.

Three kinds of files hold the catalog:

* ``sessions.json`` is the index: every session and its documents, without
  their messages. It is small and rewritten on every save.
* ``sessions/<session id>.json`` holds one session's messages and stored
  idempotent responses. It is rewritten only when its content changed.
* ``number-state/<document id>.<extraction run id>.jsonl`` is the append-only
  log of one reading's number events (chart reads and user edits; see
  number_state). A line is appended and synced for each event; nothing is
  ever rewritten. The base numbers are in the reading's extraction artifact.

In memory each document also carries its log (``number_log``), its chart
reads (``chart_extractions``) and, once built, its number state
(``evidence_state``). These are never written to sessions.json.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import number_state as numbers

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
# Held in memory only: the number log file is their storage.
MEMORY_ONLY_FIELDS = ("evidence_state", "chart_extractions", "number_log")
# Session fields kept in the session's own file, not in the index.
SESSION_FILE_FIELDS = ("messages", "request_keys")

# Sync endpoints run in a thread pool and extraction runs as a background
# task, so the in-memory catalog is shared across threads. Hold this lock
# while mutating the catalog and while serializing it; never hold it across
# slow work (PDF extraction, AI/provider calls).
catalog_lock = threading.RLock()
logger = logging.getLogger(__name__)
# Digest of the text each session file holds, by path: what was last read or written.
_session_file_digests: dict[str, str] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def number_state_root() -> Path:
    return RUNTIME_ROOT / "number-state"


def number_state_path(name: str) -> Path:
    """A file in number-state/ by name (old snapshots are "<name>.json")."""
    root = number_state_root().resolve()
    path = (root / (name if name.endswith(".jsonl") else f"{name}.json")).resolve()
    if path.parent != root:
        raise ValueError("invalid number state name")
    return path


def number_log_name(document_id: str, run_id: str) -> str:
    return f"{document_id}.{run_id}.jsonl"


def session_file_path(session_id: str) -> Path:
    root = (RUNTIME_ROOT / "sessions").resolve()
    path = (root / f"{session_id}.json").resolve()
    if path.parent != root:
        raise ValueError("invalid session id")
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
        _set_aside(CATALOG_FILE, "Session catalog")
        return {"sessions": {}}
    _remove_stale_temporary_files()
    renamed_ids: dict[str, str] = {}
    changed = False
    for session_id, session in value["sessions"].items():
        if any(field in session for field in SESSION_FILE_FIELDS):
            changed = True  # a catalog from before session files: save moves them out
        else:
            changed |= _load_session_file(session_id, session)
    for document in _documents(value):
        if "number_event_count" not in document:
            renamed_ids.update(_migrate_number_state(document))
            changed = True
        expected = document["number_event_count"]
        document["number_log"] = _read_number_log(document)
        document["chart_extractions"] = [event["record"] for event in document["number_log"] if event["kind"] == "chart_read"]
        changed |= document["number_event_count"] != expected
    if changed:
        # Answers and edits named the old random initial revision ids.
        _rename_ids(value, renamed_ids)
        save_catalog(value)
    for document in _documents(value):
        _retire_old_number_state(document)
    return value


def _set_aside(path: Path, what: str) -> None:
    """Keep a damaged file for recovery under a new name; the catalog goes on without it."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    damaged = path.with_name(f"{path.name}.corrupt-{stamp}")
    os.replace(path, damaged)
    logger.critical("%s %s is not valid; moved it to %s and went on without it", what, path, damaged)


# Suffixes of files a writer renames into place when it finishes.
_TEMPORARY_SUFFIXES = (".tmp", ".uploading")


def _remove_stale_temporary_files() -> None:
    """Remove the temporary files of writes that never finished: the process was killed before its rename."""
    for directory in (RUNTIME_ROOT, RUNTIME_ROOT / "sessions", number_state_root(), EXTRACTION_ROOT, UPLOAD_ROOT):
        if directory.is_dir():
            for path in directory.iterdir():
                if path.is_file() and path.suffix in _TEMPORARY_SUFFIXES:
                    path.unlink()
                    logger.warning("Removed %s, left by a write that did not finish", path)


def _documents(catalog: dict[str, Any]):
    for session in catalog.get("sessions", {}).values():
        yield from session.get("documents", [])


def write_json_atomically(path: Path, value: Any, *, indent: int | None = None) -> None:
    write_text_atomically(path, json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=True))


def write_text_atomically(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A per-writer temporary name: a shared "sessions.tmp" let two
    # concurrent saves replace each other's half-written file.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_catalog(catalog: dict[str, Any]) -> None:
    # Session files and number logs are written before the index: a crash in
    # between leaves an index that names only data already on disk.
    with catalog_lock:
        index = {"sessions": {}}
        for session_id, session in catalog.get("sessions", {}).items():
            _save_session_file(session_id, session)
            entry = {key: value for key, value in session.items() if key not in SESSION_FILE_FIELDS}
            if "documents" in session:
                for document in session["documents"]:
                    record_chart_reads(document)
                entry["documents"] = [{key: value for key, value in document.items() if key not in MEMORY_ONLY_FIELDS} for document in session["documents"]]
            entry["message_count"] = len(session.get("messages") or ())
            index["sessions"][session_id] = entry
        write_json_atomically(CATALOG_FILE, index, indent=2)


def _save_session_file(session_id: str, session: dict[str, Any]) -> None:
    text = json.dumps({field: session[field] for field in SESSION_FILE_FIELDS if field in session}, ensure_ascii=False, sort_keys=True)
    path = session_file_path(session_id)
    digest = sha256(text.encode("utf-8")).hexdigest()
    if _session_file_digests.get(str(path)) == digest:
        return
    write_text_atomically(path, text)
    _session_file_digests[str(path)] = digest


def _load_session_file(session_id: str, session: dict[str, Any]) -> bool:
    """Read a session's messages; True when the file was missing or damaged (the index must be saved).

    A session whose file is missing or damaged loads with no messages.
    """
    count = session.pop("message_count", 0)
    session["messages"] = []
    path = session_file_path(session_id)
    if not path.exists():
        if count:
            logger.critical("Session file %s is missing; the index says it held %d messages", path, count)
        return bool(count)
    text = path.read_text(encoding="utf-8")
    try:
        content = json.loads(text)
    except ValueError:
        content = None
    if not isinstance(content, dict) or not all(isinstance(content.get(field, []), (list, dict)) for field in SESSION_FILE_FIELDS):
        _set_aside(path, "Session file")
        return True
    session.update(content)
    _session_file_digests[str(path)] = sha256(text.encode("utf-8")).hexdigest()
    return False


def record_number_events(document: dict[str, Any], events: list[dict[str, Any]]) -> None:
    """Append events to the current reading's log, then to its state in memory. Call under catalog_lock.

    The events are synced to disk before they count anywhere, so an event a
    caller acknowledged is never lost.
    """
    run_id = document["extraction_run_id"]
    path = number_state_path(number_log_name(document["id"], run_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    document.setdefault("number_log", []).extend(events)
    document["number_event_count"] = len(document["number_log"])
    state = document.get("evidence_state")
    if state is not None and state.get("extraction_run_id") == run_id:
        for event in events:
            numbers.apply_event(state, event)


def record_chart_reads(document: dict[str, Any]) -> None:
    """Log the chart reads appended to ``chart_extractions`` since the last call. Call under catalog_lock.

    A chart read belongs to the reading it was made on (its
    ``document_run_id``). One made on another reading, e.g. by an answer that
    started before a re-extraction, is dropped.
    """
    records = document.get("chart_extractions") or []
    logged = sum(1 for event in document.get("number_log", []) if event["kind"] == "chart_read")
    run_id = document.get("extraction_run_id")
    new = records[logged:]
    kept = [record for record in new if run_id and record.get("document_run_id") == run_id]
    if len(kept) != len(new):
        logger.warning("Dropped %d chart reads of document %s made on another reading", len(new) - len(kept), document.get("id"))
        records[logged:] = kept
    if kept:
        record_number_events(document, [numbers.chart_read_event(record) for record in kept])


def _read_number_log(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The current reading's events; sets ``number_event_count`` to what was read.

    The index counts the events each document's log holds, so a missing or
    shorter log is reported. A last line without its newline is a write that
    was never acknowledged (the process was killed during it) and is cut off.
    A log with a line that is not an event is set aside.
    """
    expected = document.get("number_event_count") or 0
    run_id = document.get("extraction_run_id")
    path = number_state_path(number_log_name(document["id"], run_id)) if run_id else None
    events: list[dict[str, Any]] = []
    if path is None or not path.exists():
        if expected:
            logger.critical("Number log %s of document %s is missing; the index says it held %d events", path, document["id"], expected)
    else:
        data = path.read_bytes()
        complete = data[: data.rfind(b"\n") + 1]
        if len(complete) != len(data):
            with open(path, "r+b") as handle:
                handle.truncate(len(complete))
                os.fsync(handle.fileno())
            logger.warning("Cut an unfinished last line off number log %s", path)
        try:
            events = [json.loads(line) for line in complete.decode("utf-8").splitlines() if line]
            if not all(_is_number_event(event) for event in events):
                raise ValueError("not a number event")
        except ValueError:
            _set_aside(path, "Number log")
            events = []
        else:
            if len(events) < expected:
                logger.critical("Number log %s holds %d events; the index says %d", path, len(events), expected)
    document["number_event_count"] = len(events)
    return events


def _is_number_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("kind") == "edit":
        return isinstance(event.get("evidence_key"), str) and isinstance(event.get("revision"), dict) and "id" in event["revision"]
    if event.get("kind") == "chart_read":
        return isinstance(((event.get("record") or {}).get("evidence_batch") or {}).get("evidences"), list)
    return False


def _migrate_number_state(document: dict[str, Any]) -> dict[str, str]:
    """Move a document's number state from before the log (a full snapshot) into a log.

    The snapshot is inside the document (oldest catalogs) or in
    number-state/<document id>.json. Its edits and chart reads become events;
    its initial and re-read revisions are derived again, and the returned map
    renames their old random ids to the derived ones. A snapshot the replay
    does not reproduce is kept and logged.
    """
    snapshot = {field: document.pop(field) for field in ("evidence_state", "chart_extractions") if field in document}
    old_file = number_state_path(document["id"])
    if not snapshot and old_file.exists():
        try:
            snapshot = json.loads(old_file.read_text(encoding="utf-8"))
        except ValueError:
            _set_aside(old_file, "Number state file")
        if not isinstance(snapshot, dict):
            snapshot = {}
    artifact = _read_artifact(document)
    state = snapshot.get("evidence_state") or {}
    items = state.get("items") or {}
    run_id = numbers.run_id_of(artifact) if artifact else state.get("extraction_run_id")
    initial_times = [item["revisions"][0].get("created_at") for item in items.values() if item.get("revisions")]
    document.setdefault("extracted_at", min(filter(None, initial_times), default=None) or document.get("created_at"))
    document["number_event_count"] = 0
    if document.get("extraction_status") == "ready" and run_id:
        document["extraction_run_id"] = run_id
    if not items and not snapshot.get("chart_extractions"):
        return {}
    if run_id is None:
        logger.critical("Number state of document %s names no reading; kept it in %s", document["id"], old_file)
        document["number_state_unmigrated"] = True
        return {}
    events = _snapshot_events(items, snapshot.get("chart_extractions") or [])
    renamed: dict[str, str] = {}
    if artifact is not None:
        replayed = numbers.replay(artifact, events, read_at=document["extracted_at"])
        mismatched = []
        for key, item in items.items():
            old = item.get("revisions") or []
            new = (replayed["items"].get(key) or {}).get("revisions") or []
            if [(r.get("action"), r.get("numeric_value")) for r in old] != [(r.get("action"), r.get("numeric_value")) for r in new]:
                mismatched.append(key)
                continue
            renamed.update({o["id"]: n["id"] for o, n in zip(old, new) if o["id"] != n["id"]})
        if mismatched:
            document["number_state_unmigrated"] = True
            logger.critical("Number state of document %s: %d numbers differ from their replay (%s); the old snapshot is kept", document["id"], len(mismatched), mismatched[:5])
    else:
        document["number_state_unmigrated"] = True
        logger.critical("Number state of document %s: its extraction artifact is unreadable, so initial revision ids are not renamed", document["id"])
    _rename_ids(events, renamed)
    write_text_atomically(
        number_state_path(number_log_name(document["id"], run_id)),
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
    )
    if document.get("extraction_run_id") == run_id:
        document["number_event_count"] = len(events)
    return renamed


def _snapshot_events(items: dict[str, Any], chart_reads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A snapshot's chart reads and edits as events, in the order they were made."""
    timed = [((record.get("created_at") or ""), 0, numbers.chart_read_event(record)) for record in chart_reads]
    for key, item in items.items():
        for revision in item.get("revisions") or []:
            if revision.get("action") == "edit":
                timed.append(((revision.get("created_at") or ""), 1, numbers.edit_event(key, revision)))
    return [event for _, _, event in sorted(timed, key=lambda entry: (entry[0], entry[1]))]


def _read_artifact(document: dict[str, Any]) -> dict[str, Any] | None:
    """The document's extraction artifact when it is a reading with numbers, else None.

    An artifact from before numbers were extracted holds pages only.
    """
    try:
        artifact = json.loads(extraction_path(document["extraction_name"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        return None
    return artifact if isinstance(artifact, dict) and "extraction_run_id" in (artifact.get("evidence_batch") or {}) else None


def _retire_old_number_state(document: dict[str, Any]) -> None:
    old_file = number_state_path(document["id"])
    if old_file.exists() and not document.get("number_state_unmigrated"):
        os.replace(old_file, old_file.with_name(f"{old_file.name}.migrated"))


def _rename_ids(value: Any, renamed: dict[str, str]) -> Any:
    """Replace, in place, every string in ``value`` that is a key of ``renamed``."""
    if not renamed:
        return value
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, item in list(items):
        if isinstance(item, str) and item in renamed:
            value[key] = renamed[item]
        else:
            _rename_ids(item, renamed)
    return value


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
