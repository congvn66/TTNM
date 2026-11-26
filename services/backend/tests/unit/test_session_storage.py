import json

import pytest

from report_qa.api import session_storage


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(session_storage, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(session_storage, "CATALOG_FILE", tmp_path / "sessions.json")
    return tmp_path


def _state(values):
    return {"data_revision": 0, "items": {
        key: {"evidence_key": key, "original_numeric_value": value, "current_revision_id": f"r-{key}",
              "revisions": [{"id": f"r-{key}", "action": "initialize", "numeric_value": value}]}
        for key, value in values.items()
    }}


def _catalog():
    document = {"id": "doc-1", "file_name": "a.pdf", "extraction_status": "ready",
                "evidence_state": _state({"a": "1", "b": "2"}), "chart_extractions": [{"chart_region_key": "c"}]}
    return {"sessions": {"s1": {"id": "s1", "title": "t", "documents": [document], "messages": []}}}


def test_number_state_lives_outside_sessions_json_and_is_written_only_when_it_changes(runtime, monkeypatch):
    catalog = _catalog()
    writes = []
    real_write = session_storage.write_json_atomically
    monkeypatch.setattr(session_storage, "write_json_atomically", lambda path, *a, **k: (writes.append(path.name), real_write(path, *a, **k))[1])

    session_storage.save_catalog(catalog)
    stored = json.loads((runtime / "sessions.json").read_text(encoding="utf-8"))
    assert "evidence_state" not in stored["sessions"]["s1"]["documents"][0]
    assert "chart_extractions" not in stored["sessions"]["s1"]["documents"][0]
    state_file = runtime / "number-state" / "doc-1.json"
    assert json.loads(state_file.read_text(encoding="utf-8"))["evidence_state"]["items"]["a"]["original_numeric_value"] == "1"

    writes.clear()
    catalog["sessions"]["s1"]["messages"].append({"id": "m1", "role": "user", "body": "q"})
    session_storage.save_catalog(catalog)
    assert writes == ["sessions.json"]

    item = catalog["sessions"]["s1"]["documents"][0]["evidence_state"]["items"]["a"]
    item["revisions"].append({"id": "r2", "action": "edit", "numeric_value": "5"})
    item["current_revision_id"] = "r2"
    writes.clear()
    session_storage.save_catalog(catalog)
    assert writes == ["doc-1.json", "sessions.json"]
    assert session_storage.load_catalog() == catalog


def test_old_catalog_with_embedded_number_state_is_moved_out_without_loss(runtime):
    catalog = _catalog()
    (runtime / "sessions.json").write_text(json.dumps(catalog), encoding="utf-8")

    loaded = session_storage.load_catalog()

    assert loaded == catalog
    stored = json.loads((runtime / "sessions.json").read_text(encoding="utf-8"))
    assert "evidence_state" not in stored["sessions"]["s1"]["documents"][0]
    moved = json.loads((runtime / "number-state" / "doc-1.json").read_text(encoding="utf-8"))
    assert moved == {key: catalog["sessions"]["s1"]["documents"][0][key] for key in ("evidence_state", "chart_extractions")}
    assert session_storage.load_catalog() == catalog


def test_cleared_number_state_is_not_brought_back_by_the_old_file(runtime):
    catalog = _catalog()
    session_storage.save_catalog(catalog)
    document = catalog["sessions"]["s1"]["documents"][0]
    document.pop("evidence_state")
    document["chart_extractions"] = []
    session_storage.save_catalog(catalog)

    reloaded = session_storage.load_catalog()["sessions"]["s1"]["documents"][0]
    assert "evidence_state" not in reloaded and reloaded["chart_extractions"] == []
