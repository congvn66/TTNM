import json

import pytest
from report_qa.api import main
from report_qa.application.text_safety import storable


def test_storable_removes_nul_and_lone_surrogates_everywhere():
    value = {"a\x00": ["x\x00y", {"b": "\ud800z"}], "n": 1, "none": None, "vi": "Doanh thu quý 😀"}
    cleaned = storable(value)
    assert cleaned == {"a": ["xy", {"b": "z"}], "n": 1, "none": None, "vi": "Doanh thu quý 😀"}
    json.dumps(cleaned, ensure_ascii=False).encode("utf-8")


def test_requests_are_cleaned_before_validation():
    assert main.SessionQuestionRequest(document_id="d", question="a\x00b").question == "ab"
    with pytest.raises(ValueError):
        main.SessionQuestionRequest(document_id="d", question="\x00")


def test_an_exchange_that_cannot_be_saved_does_not_stay_in_the_session(monkeypatch):
    session = {"messages": [], "owner_id": main.LOCAL_OWNER_ID}
    monkeypatch.setattr(main, "save_catalog", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        main._append_exchange(session, {"body": "q"}, {"body": "a"}, "now")
    assert session["messages"] == []


def test_a_refused_postgres_save_drops_only_that_owners_cached_sessions(monkeypatch):
    class Store:
        def sync_catalog(self, *args, **kwargs):
            raise ValueError("refused")

    monkeypatch.setattr(main, "postgres_runtime", object())
    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: Store())
    cache = {"sessions": {"1": {"owner_id": "a"}, "2": {"owner_id": "b"}}}
    with pytest.raises(ValueError):
        main.save_catalog(cache, "a")
    assert list(cache["sessions"]) == ["2"]
