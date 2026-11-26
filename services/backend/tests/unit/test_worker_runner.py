from types import SimpleNamespace


def test_worker_uses_stable_environment_identity(monkeypatch):
    from report_qa.worker import runner

    calls = []

    class FakeQueue:
        def __init__(self, database_url):
            self.database_url = database_url

        def claim(self, *, worker_id):
            calls.append(worker_id)
            return None

    monkeypatch.setattr(runner, "PostgresJobQueue", FakeQueue)
    monkeypatch.setattr(runner, "settings", SimpleNamespace(persistence_backend="postgres", database_url="test"))
    monkeypatch.setenv("SOURCELENS_WORKER_ID", "deployment-worker-a")

    runner.run(once=True)

    assert calls == ["deployment-worker-a"]


def _extraction_setup(monkeypatch, *, result, persistence_error=False):
    from report_qa.api import main
    from uuid import uuid4
    sid, did = str(uuid4()), str(uuid4())
    document = {"id": did, "storage_name": "file.pdf", "extraction_name": "file.json", "extraction_status": "queued"}
    fresh = {"id": sid, "owner_id": str(uuid4()), "documents": [document]}
    loads, writes = [], []
    class Store:
        def load_session(self, identifier):
            loads.append(identifier)
            return fresh
    monkeypatch.setattr(main, "postgres_runtime", True)
    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: Store())
    monkeypatch.setattr(main, "catalog", {"sessions": {sid: {"documents": []}}})
    monkeypatch.setattr(main, "cache_pdf", lambda key: key)
    monkeypatch.setattr(main, "extract_pdf_pages", lambda *args: result)
    monkeypatch.setattr(main, "cache_extraction", lambda key: SimpleNamespace(read_text=lambda **kwargs: "{}"))
    monkeypatch.setattr(main, "ensure_document_evidence_state", lambda *args: None)
    def save(*args):
        writes.append(document["extraction_status"])
        if persistence_error and document["extraction_status"] == "ready":
            raise ValueError("invalid evidence")
    monkeypatch.setattr(main, "save_catalog", save)
    return main, sid, did, fresh["owner_id"], loads, writes


def test_extraction_reloads_session_for_second_upload(monkeypatch):
    result = {"status": "ready", "page_count": 2, "numeric_evidence_count": 3, "error": None}
    main, sid, did, owner, loads, writes = _extraction_setup(monkeypatch, result=result)
    main.complete_document_extraction(sid, did, owner_id=owner)
    assert len(loads) == 1
    assert writes == ["processing", "ready"]


def test_failed_extraction_is_not_acknowledged_as_success(monkeypatch):
    import pytest
    result = {"status": "failed", "page_count": None, "numeric_evidence_count": 0, "error": "MODEL_FAILED"}
    main, sid, did, owner, _, writes = _extraction_setup(monkeypatch, result=result)
    with pytest.raises(RuntimeError, match="EXTRACTION_FAILED"):
        main.complete_document_extraction(sid, did, owner_id=owner)
    assert writes == ["processing", "failed"]


def test_publish_error_leaves_visible_failed_state(monkeypatch):
    import pytest
    result = {"status": "ready", "page_count": 2, "numeric_evidence_count": 3, "error": None}
    main, sid, did, owner, _, writes = _extraction_setup(monkeypatch, result=result, persistence_error=True)
    with pytest.raises(ValueError, match="invalid evidence"):
        main.complete_document_extraction(sid, did, owner_id=owner)
    assert writes == ["processing", "ready", "failed"]



def test_answer_job_marks_its_request_as_the_worker(monkeypatch):
    from report_qa.worker import runner

    session = {"messages": [{"id": "placeholder", "status": "processing"}]}
    seen = []

    def ask(session_id, payload, request, response):
        seen.append(getattr(request.state, "worker_job", False))
        return {"user_message": {"id": "u"}, "assistant_message": {"id": "a", "body": "ok"}}

    monkeypatch.setattr(runner, "get_session", lambda *args: session)
    monkeypatch.setattr(runner, "ask_session_document", ask)
    monkeypatch.setattr(runner, "save_catalog", lambda *args: None)

    runner.complete_answer_job({"session_id": "s", "assistant_message_id": "placeholder", "owner_id": "o", "document_id": "d", "question": "q"})

    assert seen == [True]
