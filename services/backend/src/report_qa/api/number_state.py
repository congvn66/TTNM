"""The numbers of a document's current reading, with every change made to them.

A reading is one extraction run. Its base values are in its extraction
artifact and never change. Everything added later is one event in the
reading's append-only log (see session_storage.append_number_events):

* ``{"kind": "chart_read", "record": {...}}``: a chart read on demand. Its
  numbers that the reading does not have yet are added; a number whose earlier
  read gave no value gets this read's value.
* ``{"kind": "edit", "evidence_key": ..., "revision": {...}, "location": ...}``:
  a value a user typed, or a user's edit carried over from an earlier reading.

The number state is a replay: an initial revision for every base number, then
each event in log order. Revisions the replay makes have ids derived from the
run id, the evidence key and the event number, so the same artifact and log
always give the same state and the same ids. Only edits store their own id.
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID, uuid5


_IDS = UUID("6f2b8f0e-2d43-4c4e-9a59-2b1e8f3c7a10")
INITIAL_REASON = "Giá trị trích xuất gốc, không thể sửa trực tiếp."
REREAD_REASON = "Giá trị được đọc lại và xác minh."


class ReadingNotCurrent(Exception):
    """Numbers were asked for a reading that is not the document's current ready reading."""

    def __init__(self, document_id: str | None, run_id: str | None) -> None:
        super().__init__(f"reading {run_id} is not the current reading of document {document_id}")
        self.document_id = document_id
        self.run_id = run_id


def initial_revision_id(run_id: str, evidence_key: str) -> str:
    return str(uuid5(_IDS, f"{run_id}/{evidence_key}/initialize"))


def reread_revision_id(run_id: str, evidence_key: str, event_no: int) -> str:
    return str(uuid5(_IDS, f"{run_id}/{evidence_key}/reread/{event_no}"))


def run_id_of(artifact: dict[str, Any]) -> str:
    return str(artifact["evidence_batch"]["extraction_run_id"])


def replay(artifact: dict[str, Any], events: Iterable[dict[str, Any]], *, read_at: str | None) -> dict[str, Any]:
    """The number state of the artifact's reading after ``events``; ``read_at`` dates the initial revisions."""
    state = {"extraction_run_id": run_id_of(artifact), "data_revision": 0, "items": {}, "event_count": 0}
    for evidence in artifact["evidence_batch"]["evidences"]:
        _add_number(state, evidence, read_at)
    for event in events:
        apply_event(state, event)
    return state


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    event_no = state["event_count"]
    state["event_count"] += 1
    if event["kind"] == "chart_read":
        record = event["record"]
        for evidence in record["evidence_batch"]["evidences"]:
            item = state["items"].get(evidence["evidence_key"])
            if item is None:
                _add_number(state, evidence, record.get("created_at"))
            else:
                _fill_withheld_value(state, item, evidence.get("numeric_value"), event_no, record.get("created_at"))
    elif event["kind"] == "edit":
        item = state["items"][event["evidence_key"]]
        _append(state, item, dict(event["revision"]))
    else:
        raise ValueError(f"unknown number event {event['kind']!r}")


def edit_event(evidence_key: str, revision: dict[str, Any], location: dict[str, Any] | None) -> dict[str, Any]:
    return {"kind": "edit", "evidence_key": evidence_key, "revision": revision, "location": location}


def chart_read_event(record: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "chart_read", "record": record}


def _add_number(state: dict[str, Any], evidence: dict[str, Any], created_at: str | None) -> None:
    key = evidence["evidence_key"]
    initial = {
        "id": initial_revision_id(state["extraction_run_id"], key), "revision_no": 1, "action": "initialize", "created_at": created_at,
        "numeric_value": evidence.get("numeric_value"), "old_numeric_value": None, "previous_revision_id": None, "reason": INITIAL_REASON,
    }
    state["items"][key] = {"evidence_key": key, "original_numeric_value": evidence.get("numeric_value"), "current_revision_id": initial["id"], "revisions": [initial]}


def _fill_withheld_value(state: dict[str, Any], item: dict[str, Any], value: str | None, event_no: int, created_at: str | None) -> None:
    """A later chart read gives the value an earlier read withheld (e.g. its visual check failed). User edits win."""
    current = item["revisions"][-1]
    if value is None or current.get("numeric_value") is not None or current.get("action") == "edit":
        return
    _append(state, item, {
        "id": reread_revision_id(state["extraction_run_id"], item["evidence_key"], event_no), "revision_no": len(item["revisions"]) + 1,
        "action": "reread", "created_at": created_at, "numeric_value": value, "old_numeric_value": None,
        "previous_revision_id": current["id"], "reason": REREAD_REASON,
    })


def _append(state: dict[str, Any], item: dict[str, Any], revision: dict[str, Any]) -> None:
    item["revisions"].append(revision)
    item["current_revision_id"] = revision["id"]
    state["data_revision"] += 1
