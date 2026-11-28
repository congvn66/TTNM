"""Errors the reader can act on, jobs that end instead of hanging, and answers before readings."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


# --- A 500 still reaches the browser as itself ---------------------------------------------

def test_an_unhandled_error_keeps_the_cors_headers_so_the_browser_sees_it():
    from report_qa.api import main

    def broken() -> None:
        raise RuntimeError("boom")

    main.app.add_api_route("/__test_broken", broken, include_in_schema=False)
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.get("/__test_broken", headers={"Origin": "http://127.0.0.1:4173"})
        foreign = client.get("/__test_broken", headers={"Origin": "https://evil.example"})
    finally:
        main.app.router.routes = [route for route in main.app.router.routes if getattr(route, "path", "") != "/__test_broken"]
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "INTERNAL_ERROR"
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in foreign.headers


# --- Account errors that say what is wrong ---------------------------------------------------

@pytest.mark.parametrize("token", ["abc", "", "x" * 300])
def test_a_reset_code_of_the_wrong_length_is_an_invalid_link_not_a_vague_422(monkeypatch, token):
    from report_qa.api import auth, main

    monkeypatch.setattr(auth, "_require_postgres", lambda: None)
    monkeypatch.setattr(auth, "_connection", lambda **_: pytest.fail("no database call for a malformed code"))
    response = TestClient(main.app).post("/api/v1/auth/reset-password", json={"token": token, "password": "matkhau-moi-123"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "RESET_TOKEN_INVALID"


def test_a_deleted_guest_report_frees_its_daily_slot_but_still_counts_in_the_overall_cap():
    from report_qa.api import auth

    log = []

    class Connection:
        def execute(self, sql, params=()):
            log.append(" ".join(sql.split()))
            row = {"is_guest": True, "gone": False} if "FOR NO KEY UPDATE" in sql else {"n": 0}
            return SimpleNamespace(fetchone=lambda: row)

    auth._guest_uploads_left(Connection(), uuid4())
    own, everyone = log[1], log[2]
    assert "deleted_at IS NULL" in own
    assert "deleted_at" not in everyone


def test_renaming_with_a_slash_says_the_slash_is_the_problem(monkeypatch):
    from report_qa.api import main

    session = {"id": "s", "owner_id": main.LOCAL_OWNER_ID, "documents": [{"id": "d", "file_name": "a.pdf"}], "messages": []}
    monkeypatch.setattr(main, "get_session", lambda *_: session)
    client = TestClient(main.app)
    slash = client.patch("/api/v1/sessions/s/documents/d", json={"file_name": "Q3/2025"})
    blank = client.patch("/api/v1/sessions/s/documents/d", json={"file_name": "‎"})
    assert slash.status_code == 422 and slash.json()["detail"]["code"] == "DOCUMENT_NAME_SLASH"
    assert "/" in slash.json()["detail"]["message"]
    assert blank.json()["detail"]["code"] == "DOCUMENT_NAME_INVALID"


# --- The AI provider's rate limit is its own error ------------------------------------------

def test_http_429_from_the_provider_is_a_rate_limit_with_its_own_message(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError

    from report_qa.api import ai_provider
    from report_qa.api.user_messages import MESSAGES

    monkeypatch.setattr(ai_provider, "_load_local_env", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("REPORT_QA_AI_RETRIES", "0")
    client = ai_provider.PlannerChatClient("gemini")

    def limited(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, BytesIO(b"{}"))

    monkeypatch.setattr(ai_provider, "urlopen", limited)
    with pytest.raises(ai_provider.ProviderError) as error:
        client.complete("system", "user")
    assert error.value.code == "AI_RATE_LIMITED" and error.value.http_status == 429
    # The reader's friendlyError replaces any text with "AI" in it by a generic one.
    assert "ai" not in MESSAGES["AI_RATE_LIMITED"].casefold().replace("ại", "")


def test_a_brief_that_runs_out_of_time_says_so(monkeypatch):
    from report_qa.api import main
    from report_qa.api.ai_provider import ProviderError

    document = {"id": "d", "extraction_status": "ready"}
    monkeypatch.setattr(main, "get_session", lambda *_: {"id": "s", "owner_id": main.LOCAL_OWNER_ID, "documents": [document], "messages": []})
    monkeypatch.setattr(main, "_ready_document", lambda session, document_id: (document, {}))
    monkeypatch.setattr(main, "assistant_mode", lambda: "tools")
    monkeypatch.setattr(main, "extraction_marker", lambda document: 1)

    def slow(*args, **kwargs):
        raise ProviderError("AI_ANSWER_TIMEOUT", "budget")

    monkeypatch.setattr(main, "answer_document", slow)
    response = TestClient(main.app).post("/api/v1/sessions/s/documents/d/brief")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "BRIEF_TIMEOUT"
    assert response.json()["detail"]["message"] == "Tóm tắt mất quá lâu. Thử lại sau."


# --- A failed answer stays in the chat, with its reason, and is not retried behind its back ---

def _answer_job(monkeypatch, *, ask, messages):
    from report_qa.worker import runner

    session = {"id": "s", "messages": messages}
    saved = []
    monkeypatch.setattr(runner, "get_session", lambda *args: session)
    monkeypatch.setattr(runner, "ask_session_document", ask)
    monkeypatch.setattr(runner, "save_session", lambda value, owner: saved.append(json.loads(json.dumps(value))))
    payload = {"session_id": "s", "assistant_message_id": "a1", "owner_id": "o", "document_id": "d", "question": "q"}
    return runner, payload, saved


def test_a_rate_limited_answer_is_saved_as_failed_with_its_code_and_message(monkeypatch):
    def ask(*args):
        raise HTTPException(502, {"code": "AI_RATE_LIMITED", "message": "x", "provider_http_status": 429})

    runner, payload, saved = _answer_job(monkeypatch, ask=ask, messages=[{"id": "u1", "role": "user"}, {"id": "a1", "role": "assistant", "status": "processing"}])
    with pytest.raises(runner.AnswerFailed) as failed:
        runner.complete_answer_job(payload)
    assert failed.value.code == "AI_RATE_LIMITED"
    card = saved[-1]["messages"][1]
    assert card["status"] == "failed" and card["body"] == "Trợ lý đang quá tải. Thử lại sau một phút."
    assert card["structured_answer"]["error_code"] == "AI_RATE_LIMITED"
    assert [item["id"] for item in saved[-1]["messages"]] == ["u1", "a1"]


def test_an_unexpected_answer_error_gets_the_generic_failure(monkeypatch):
    def ask(*args):
        raise KeyError("planner")

    runner, payload, saved = _answer_job(monkeypatch, ask=ask, messages=[{"id": "u1", "role": "user"}, {"id": "a1", "role": "assistant", "status": "processing"}])
    with pytest.raises(runner.AnswerFailed) as failed:
        runner.complete_answer_job(payload)
    assert failed.value.code == "ANSWER_FAILED"
    assert saved[-1]["messages"][1]["body"] == "Không thể tạo câu trả lời. Hãy thử lại."


def test_a_question_before_its_report_is_read_waits_and_fails_only_on_the_last_try(monkeypatch):
    def ask(*args):
        raise HTTPException(409, {"code": "EXTRACTION_NOT_READY", "message": "x"})

    messages = [{"id": "u1", "role": "user"}, {"id": "a1", "role": "assistant", "status": "processing"}]
    runner, payload, saved = _answer_job(monkeypatch, ask=ask, messages=messages)
    with pytest.raises(runner.RetryLater):
        runner.complete_answer_job(payload, last_try=False)
    assert saved == [] and messages[1]["status"] == "processing"
    with pytest.raises(runner.AnswerFailed):
        runner.complete_answer_job(payload, last_try=True)
    assert saved[-1]["messages"][1]["body"] == "Báo cáo chưa đọc xong. Thử lại sau."


def test_an_answer_job_without_its_stored_question_is_skipped(monkeypatch):
    runner, payload, saved = _answer_job(monkeypatch, ask=lambda *args: pytest.fail("nothing to answer into"), messages=[])
    runner.complete_answer_job(payload)
    assert saved == []


def test_a_failed_answer_ends_its_job_without_a_retry(monkeypatch):
    from report_qa.worker import runner

    calls = []

    class Queue:
        def __init__(self, url):
            pass

        def claim(self, **kwargs):
            calls.append(("claim", kwargs))
            return {"id": str(uuid4()), "lease_token": str(uuid4()), "kind": "answer_question", "attempts": 1, "max_attempts": 3, "payload": {}, "owner_id": None}

        def heartbeat(self, **kwargs):
            return True

        def fail(self, **kwargs):
            calls.append(("fail", kwargs))
            runner.STOP = True
            return True

    def failing(payload, publish_guard=None, last_try=True):
        raise runner.AnswerFailed("AI_RATE_LIMITED")

    monkeypatch.setattr(runner, "PostgresJobQueue", Queue)
    monkeypatch.setattr(runner, "settings", SimpleNamespace(persistence_backend="postgres", database_url="test"))
    monkeypatch.setattr(runner, "complete_answer_job", failing)
    monkeypatch.setattr(runner, "_clean_expired_guests", lambda: None)
    monkeypatch.setenv("SOURCELENS_WORKER_KINDS", "answer_question")
    monkeypatch.setattr(runner, "STOP", False)
    runner.run(poll_seconds=0.1)
    claim = calls[0][1]
    fail = next(kwargs for name, kwargs in calls if name == "fail")
    assert claim["kinds"] == ["answer_question"]
    assert fail["retry_at"] is None and fail["error_code"] == "AI_RATE_LIMITED"


# --- Answers go before readings; a lost answer job ends its card -----------------------------

class _QueueConnection:
    def __init__(self, expired=()):
        self.calls, self.expired = [], list(expired)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.calls.append((text, params))
        if text.startswith("UPDATE jobs SET status='failed',error_code='LEASE_EXPIRED'"):
            rows = self.expired
        elif text.startswith("UPDATE messages SET status='failed'"):
            rows = [{"current_answer_revision_id": uuid4()}]
        elif text.startswith("INSERT INTO answer_revisions"):
            rows = [{"id": uuid4()}]
        elif text.startswith("SELECT COALESCE(MAX(event_no)"):
            rows = [{"next": 1}]
        else:
            rows = []
        return SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: rows[0] if rows else None, rowcount=len(rows))


def test_claim_takes_answers_before_readings_and_can_be_limited_to_some_kinds(monkeypatch):
    from report_qa.infrastructure.postgres import job_queue

    connection = _QueueConnection()
    queue = job_queue.PostgresJobQueue("postgresql://unused")
    monkeypatch.setattr(queue, "_connect", lambda: connection)
    queue.claim(worker_id="w", kinds=["answer_question"])
    sql, params = next(call for call in connection.calls if call[0].startswith("WITH candidate"))
    assert "ORDER BY (kind = 'answer_question') DESC, created_at" in sql
    assert params[:2] == (["answer_question"], ["answer_question"])


def test_an_answer_job_whose_lease_ran_out_for_good_ends_its_card_as_failed(monkeypatch):
    from report_qa.infrastructure.postgres import job_queue

    message_id, chat_id = uuid4(), uuid4()
    connection = _QueueConnection(expired=[
        {"id": uuid4(), "kind": "answer_question", "chat_id": chat_id, "payload": {"assistant_message_id": str(message_id)}},
        {"id": uuid4(), "kind": "extract_document", "chat_id": chat_id, "payload": {"document_id": str(uuid4())}},
    ])
    queue = job_queue.PostgresJobQueue("postgresql://unused")
    monkeypatch.setattr(queue, "_connect", lambda: connection)
    queue.claim(worker_id="w")
    updates = [params for sql, params in connection.calls if sql.startswith("UPDATE messages SET status='failed'")]
    assert updates == [(job_queue.ANSWER_FAILED_TEXT, message_id, chat_id)]
    assert any(sql.startswith("INSERT INTO answer_revisions") for sql, _ in connection.calls)


# --- A reading with no live job shows as failed ---------------------------------------------

@pytest.mark.parametrize(("row", "expected"), [
    ({"extraction_status": "queued", "extraction_job_live": False}, ("failed", "EXTRACTION_STOPPED")),
    ({"extraction_status": "running", "extraction_job_live": False}, ("failed", "EXTRACTION_STOPPED")),
    ({"extraction_status": None, "version_status": "uploaded", "extraction_job_live": False}, ("failed", "EXTRACTION_STOPPED")),
    ({"extraction_status": "running", "extraction_job_live": True}, ("processing", None)),
    ({"extraction_status": "queued", "extraction_job_live": True}, ("queued", None)),
    ({"extraction_status": "completed", "extraction_job_live": False}, ("ready", None)),
    ({"extraction_status": "failed", "extraction_error": "MODEL_FAILED", "extraction_job_live": False}, ("failed", "MODEL_FAILED")),
    ({"extraction_status": "failed", "extraction_error": "MODEL_FAILED", "extraction_job_live": True}, ("queued", None)),
])
def test_reading_status_as_the_api_shows_it(row, expected):
    from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore

    assert PostgresRuntimeStore._extraction_state(row) == expected


def test_an_old_snapshot_cannot_fail_a_reading_that_was_queued_again(monkeypatch):
    from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore

    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    calls = []
    monkeypatch.setattr(store, "_execute", lambda sql, params=(): calls.append(" ".join(sql.split())) or [])
    store._sync_document(uuid4(), {"id": str(uuid4()), "extraction_status": "failed", "extraction_error": "X", "page_count": 2})
    failed = next(sql for sql in calls if sql.startswith("UPDATE extraction_runs SET status='failed'"))
    assert failed.endswith("AND status='running'")


def test_a_failed_document_offers_a_retry_when_the_queue_can_run_it(monkeypatch):
    from report_qa.api import main

    monkeypatch.setattr(main, "durable_job_queue", object())
    assert main.public_document({"id": "d", "extraction_status": "failed"})["can_retry"] is True
    assert main.public_document({"id": "d", "extraction_status": "ready"})["can_retry"] is False


def test_retrying_a_failed_reading_requeues_it_and_its_job_in_one_transaction(monkeypatch):
    from report_qa.api import main

    events = []

    class Store:
        connection = "conn"

        @contextmanager
        def transaction(self):
            events.append("begin")
            yield self
            events.append("commit")

        def requeue_failed_extraction(self, session_id, document_id):
            events.append("requeue")
            return "requeued"

    class Queue:
        def enqueue(self, **kwargs):
            events.append(("enqueue", kwargs["kind"], kwargs["connection"], kwargs["dedup_key"].startswith("extract:d:")))
            return {"id": "job-1"}

    document = {"id": "d", "extraction_status": "failed", "extraction_error": "EXTRACTION_STOPPED"}
    monkeypatch.setattr(main, "get_session", lambda *_: {"id": str(uuid4()), "documents": [document], "messages": []})
    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: Store())
    monkeypatch.setattr(main, "durable_job_queue", Queue())
    body = TestClient(main.app).post(f"/api/v1/sessions/{uuid4()}/documents/d/extraction").json()
    assert events == ["begin", "requeue", ("enqueue", "extract_document", "conn", True), "commit"]
    assert body["document"]["extraction_status"] == "queued" and body["job"]["id"] == "job-1"


def test_retrying_a_ready_reading_is_still_refused_with_the_queue(monkeypatch):
    from report_qa.api import main

    monkeypatch.setattr(main, "get_session", lambda *_: {"id": "s", "documents": [{"id": "d", "extraction_status": "ready"}], "messages": []})
    monkeypatch.setattr(main, "durable_job_queue", object())
    response = TestClient(main.app).post("/api/v1/sessions/s/documents/d/extraction")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "REEXTRACTION_NOT_SUPPORTED"


# --- A question is stored with its job, or not at all ---------------------------------------

class _TransactionStore:
    def __init__(self, events, fail_on=None):
        self.events, self.fail_on, self.connection = events, fail_on, "conn"

    @contextmanager
    def transaction(self):
        self.events.append("begin")
        try:
            yield self
        except Exception:
            self.events.append("rollback")
            raise
        self.events.append("commit")

    def sync_catalog(self, catalog, **kwargs):
        session = next(iter(catalog["sessions"].values()))
        self.events.append(("save", len(session["messages"])))
        if self.fail_on == "save":
            raise RuntimeError("save refused")

    def put_idempotency_response(self, owner, route, key, request_hash, response):
        self.events.append(("key", key, response["status"]))


def _async_ask(monkeypatch, fail_on=None):
    from report_qa.api import main

    events = []

    class Queue:
        def enqueue(self, **kwargs):
            events.append(("enqueue", kwargs["kind"], kwargs["connection"]))
            if fail_on == "enqueue":
                raise RuntimeError("queue refused")
            return {"id": "job-1"}

    session = {"id": str(uuid4()), "owner_id": main.LOCAL_OWNER_ID, "documents": [{"id": "d", "extraction_status": "ready"}], "messages": [], "request_keys": {}}
    monkeypatch.setattr(main, "get_session", lambda *_: session)
    monkeypatch.setattr(main, "durable_job_queue", Queue())
    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: _TransactionStore(events, fail_on))
    monkeypatch.setattr(main, "settings", SimpleNamespace(**{**{name: getattr(main.settings, name) for name in main.settings.__slots__}, "async_answer_jobs": True}))
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.post(f"/api/v1/sessions/{session['id']}/messages", json={"document_id": "d", "question": "Doanh thu?"}, headers={"Idempotency-Key": "k1"})
    return response, events, session


def test_a_queued_question_its_job_and_its_resend_key_commit_together(monkeypatch):
    response, events, session = _async_ask(monkeypatch)
    assert response.status_code == 202
    assert events == ["begin", ("save", 2), ("enqueue", "answer_question", "conn"), ("key", "k1", "queued"), "commit"]
    assert len(session["messages"]) == 2


@pytest.mark.parametrize("fail_on", ["save", "enqueue"])
def test_a_question_that_cannot_be_stored_leaves_no_job_and_no_message(monkeypatch, fail_on):
    response, events, session = _async_ask(monkeypatch, fail_on)
    assert response.status_code == 500
    assert events[-1] == "rollback"
    assert ("key", "k1", "queued") not in events
    assert session["messages"] == [] and "k1" not in session["request_keys"]


# --- Upload into a chosen project -----------------------------------------------------------

def test_upload_into_a_project_uses_its_newest_chat_or_starts_one(monkeypatch):
    from report_qa.api import main

    project_id = str(uuid4())
    chats = {"answer": {"id": "chat-1"}}
    targets = []

    class Store:
        def project_chat(self, project):
            return chats["answer"]

    monkeypatch.setattr(main, "postgres_runtime", True)
    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: Store())
    monkeypatch.setattr(main, "get_session", lambda session_id, owner: {"id": session_id, "documents": [], "messages": []})
    monkeypatch.setattr(main, "_upload_into", lambda session, *args: targets.append(session) or {"session_id": session["id"], "document": {}, "job": None, "persistence": {}})
    client = TestClient(main.app)
    files = {"file": ("bao-cao.pdf", b"%PDF-1.4", "application/pdf")}
    assert client.post(f"/api/v1/projects/{project_id}/documents", files=files).status_code == 200
    chats["answer"] = {}
    assert client.post(f"/api/v1/projects/{project_id}/documents", files=files).status_code == 200
    chats["answer"] = None
    missing = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert targets[0]["id"] == "chat-1"
    assert targets[1]["project_id"] == project_id and targets[1]["documents"] == []
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "PROJECT_NOT_FOUND"
