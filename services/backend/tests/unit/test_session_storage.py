import json

import pytest

from report_qa.api import number_state, session_storage


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(session_storage, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(session_storage, "CATALOG_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(session_storage, "EXTRACTION_ROOT", tmp_path / "extracted")
    return tmp_path


def _artifact(run_id="run-1", values=(("a", "1"), ("b", "2"))):
    return {"pages": [], "evidence_batch": {"extraction_run_id": run_id, "evidences": [
        {"evidence_key": key, "numeric_value": value, "raw_text": value, "page_number": 1} for key, value in values]}}


def _write_artifact(runtime, artifact, name="doc-1.json"):
    (runtime / "extracted").mkdir(exist_ok=True)
    (runtime / "extracted" / name).write_text(json.dumps(artifact), encoding="utf-8")


def _ready_catalog():
    document = {"id": "doc-1", "file_name": "a.pdf", "extraction_name": "doc-1.json", "extraction_status": "ready",
                "extraction_run_id": "run-1", "extracted_at": "2026-01-01T00:00:00+00:00", "number_event_count": 0}
    return {"sessions": {"s1": {"id": "s1", "title": "t", "documents": [document], "messages": []}}}


def _edit(key, value, revision_id, previous):
    return number_state.edit_event(key, {"id": revision_id, "revision_no": 2, "action": "edit", "numeric_value": value, "previous_revision_id": previous}, None)


def test_number_events_are_appended_to_the_reading_log_and_never_rewritten(runtime, monkeypatch):
    catalog = _ready_catalog()
    document = catalog["sessions"]["s1"]["documents"][0]
    with session_storage.catalog_lock:
        session_storage.record_number_events(document, [_edit("a", "5", "r2", number_state.initial_revision_id("run-1", "a"))])
        document["chart_extractions"] = [{"chart_region_key": "c", "created_at": "t", "document_run_id": "run-1", "evidence_batch": {"evidences": []}}]
    session_storage.save_catalog(catalog)

    stored = json.loads((runtime / "sessions.json").read_text(encoding="utf-8"))
    assert not set(session_storage.MEMORY_ONLY_FIELDS) & set(stored["sessions"]["s1"]["documents"][0])
    log = runtime / "number-state" / "doc-1.run-1.jsonl"
    assert [json.loads(line)["kind"] for line in log.read_text(encoding="utf-8").splitlines()] == ["edit", "chart_read"]
    before = log.read_bytes()

    catalog["sessions"]["s1"]["messages"].append({"id": "m1", "role": "user", "body": "q"})
    session_storage.save_catalog(catalog)
    assert log.read_bytes() == before

    loaded = session_storage.load_catalog()["sessions"]["s1"]["documents"][0]
    assert loaded["number_log"] == document["number_log"]
    assert loaded["chart_extractions"] == document["chart_extractions"]
    state = number_state.replay(_artifact(), loaded["number_log"], read_at=loaded["extracted_at"])
    assert state["items"]["a"]["revisions"][-1]["numeric_value"] == "5"


def test_the_state_of_a_number_is_its_base_value_with_its_log_replayed():
    artifact = _artifact()
    chart = {"created_at": "t1", "evidence_batch": {"evidences": [{"evidence_key": "c", "numeric_value": None}]}}
    reread = {"created_at": "t2", "evidence_batch": {"evidences": [{"evidence_key": "c", "numeric_value": "7"}]}}
    events = [number_state.chart_read_event(chart), _edit("a", "5", "r-edit", number_state.initial_revision_id("run-1", "a")), number_state.chart_read_event(reread)]

    first = number_state.replay(artifact, events, read_at="t0")
    second = number_state.replay(artifact, events, read_at="t0")

    assert first == second
    assert [(r["action"], r["numeric_value"]) for r in first["items"]["c"]["revisions"]] == [("initialize", None), ("reread", "7")]
    assert [r["id"] for r in first["items"]["a"]["revisions"]] == [number_state.initial_revision_id("run-1", "a"), "r-edit"]
    assert first["items"]["b"]["revisions"][0]["created_at"] == "t0"
    assert first["data_revision"] == 2


def _old_state(initial_ids):
    def item(key, value, revisions=()):
        initial = {"id": initial_ids[key], "revision_no": 1, "action": "initialize", "created_at": "2025-01-01T00:00:00+00:00", "numeric_value": value}
        return {"evidence_key": key, "original_numeric_value": value, "current_revision_id": (list(revisions) or [initial])[-1]["id"], "revisions": [initial, *revisions]}
    edit = {"id": "old-edit", "revision_no": 2, "action": "edit", "created_at": "2025-01-03T00:00:00+00:00", "numeric_value": "5",
            "old_numeric_value": "1", "previous_revision_id": initial_ids["a"], "reason": "x"}
    reread = {"id": "old-reread", "revision_no": 2, "action": "reread", "created_at": "2025-01-02T00:00:00+00:00", "numeric_value": "7",
              "previous_revision_id": initial_ids["c"]}
    charts = [{"chart_region_key": "r", "created_at": "2025-01-01T12:00:00+00:00", "evidence_batch": {"evidences": [{"evidence_key": "c", "numeric_value": None}]}},
              {"chart_region_key": "r", "created_at": "2025-01-02T00:00:00+00:00", "evidence_batch": {"evidences": [{"evidence_key": "c", "numeric_value": "7"}]}}]
    state = {"data_revision": 2, "extraction_run_id": "run-1", "items": {"a": item("a", "1", [edit]), "b": item("b", "2"), "c": item("c", None, [reread])}}
    return {"evidence_state": state, "chart_extractions": charts}


@pytest.mark.parametrize("where", ["embedded", "file"])
def test_a_number_state_snapshot_is_migrated_into_a_log_without_loss(runtime, where):
    _write_artifact(runtime, _artifact())
    old_ids = {"a": "old-a", "b": "old-b", "c": "old-c"}
    snapshot = _old_state(old_ids)
    document = {"id": "doc-1", "file_name": "a.pdf", "extraction_name": "doc-1.json", "extraction_status": "ready"}
    answer = {"id": "m1", "role": "assistant", "answer_inputs": [{"evidence_key": "b", "evidence_revision_id": "old-b"}]}
    if where == "embedded":
        document.update(snapshot)
    else:
        (runtime / "number-state").mkdir()
        (runtime / "number-state" / "doc-1.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (runtime / "sessions.json").write_text(json.dumps({"sessions": {"s1": {"id": "s1", "documents": [document], "messages": [answer]}}}), encoding="utf-8")

    loaded = session_storage.load_catalog()

    document = loaded["sessions"]["s1"]["documents"][0]
    state = number_state.replay(_artifact(), document["number_log"], read_at=document["extracted_at"])
    old_items = snapshot["evidence_state"]["items"]
    for key, item in state["items"].items():
        assert [(r["action"], r["numeric_value"]) for r in item["revisions"]] == [(r["action"], r["numeric_value"]) for r in old_items[key]["revisions"]]
    assert state["items"]["a"]["revisions"][1]["previous_revision_id"] == number_state.initial_revision_id("run-1", "a")
    assert loaded["sessions"]["s1"]["messages"][0]["answer_inputs"][0]["evidence_revision_id"] == number_state.initial_revision_id("run-1", "b")
    assert document["chart_extractions"] == snapshot["chart_extractions"]
    assert document["extracted_at"] == "2025-01-01T00:00:00+00:00"
    stored = json.loads((runtime / "sessions.json").read_text(encoding="utf-8"))["sessions"]["s1"]["documents"][0]
    assert "evidence_state" not in stored and stored["number_event_count"] == 3
    if where == "file":
        assert not (runtime / "number-state" / "doc-1.json").exists()
        assert json.loads((runtime / "number-state" / "doc-1.json.migrated").read_text(encoding="utf-8")) == snapshot
    assert session_storage.load_catalog() == loaded


def test_a_replaced_reading_does_not_bring_its_log_back(runtime):
    catalog = _ready_catalog()
    document = catalog["sessions"]["s1"]["documents"][0]
    with session_storage.catalog_lock:
        session_storage.record_number_events(document, [_edit("a", "5", "r2", "x")])
    document.update({"extraction_run_id": None, "number_log": [], "chart_extractions": [], "number_event_count": 0, "extraction_status": "queued"})
    session_storage.save_catalog(catalog)

    reloaded = session_storage.load_catalog()["sessions"]["s1"]["documents"][0]
    assert reloaded["number_log"] == [] and reloaded["chart_extractions"] == []
    assert (session_storage.number_state_root() / "doc-1.run-1.jsonl").exists()
