from report_qa.api.main import _database_evidence_state
from report_qa.api.number_state import apply_event, edit_event


def test_an_edit_applies_to_the_state_loaded_from_postgres():
    # The database loader returns no event_count; an edit used to crash with KeyError.
    document = {"evidence_state": {"data_revision": 0, "items": {}}}
    extraction = {"evidence_batch": {"evidences": [{"evidence_key": "ev-1", "numeric_value": "8120"}]}}
    state = _database_evidence_state(document, extraction)
    first = state["items"]["ev-1"]["revisions"][-1]
    revision = {"id": "r2", "revision_no": 2, "action": "edit", "created_at": "2026-11-28T00:00:00Z",
                "numeric_value": "8210", "old_numeric_value": "8120", "previous_revision_id": first["id"], "reason": "test"}
    apply_event(state, edit_event("ev-1", revision))
    assert state["items"]["ev-1"]["revisions"][-1]["numeric_value"] == "8210"
