"""The queue, reading states and Library rows against a real, throwaway PostgreSQL.

Skipped unless SOURCELENS_TEST_DATABASE_URL names a database migrated to head
that may be written to (never a shared one). Every test makes its own owner.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

DATABASE_URL = os.getenv("SOURCELENS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="needs SOURCELENS_TEST_DATABASE_URL (a throwaway PostgreSQL)")


def _db():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def _q(sql, params=()):
    with _db() as connection:
        cursor = connection.execute(sql, params)
        return cursor.fetchall() if cursor.description else cursor.rowcount


def _store(owner):
    from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore

    return PostgresRuntimeStore(DATABASE_URL, owner)


def _owner(owner=None):
    """A user row with its own email; sync_catalog's ensure_owner would reuse one shared email."""
    owner = owner or uuid4()
    _store(owner).ensure_owner(owner)
    return owner


def _queue():
    from report_qa.infrastructure.postgres.job_queue import PostgresJobQueue

    return PostgresJobQueue(DATABASE_URL)


def _session(owner, *, status="queued", project_id=None, messages=()):
    now = datetime.now(timezone.utc).isoformat()
    document = {"id": str(uuid4()), "file_name": "bao-cao.pdf", "byte_size": 10, "sha256": "x", "storage_name": f"{uuid4()}.pdf",
                "created_at": now, "extraction_status": status, "page_count": 2, "extraction_error": None}
    return {"id": str(uuid4()), "owner_id": str(owner), "title": "Báo cáo của tôi", "project_id": project_id, "created_at": now,
            "updated_at": now, "documents": [document], "messages": list(messages)}


def _save(owner, session):
    _store(owner).sync_catalog({"sessions": {session["id"]: session}})
    return session


def _document(owner, session_id):
    return _store(owner).load_session(session_id)["documents"][0]


def _enqueue_reading(owner, session, **kwargs):
    document_id = session["documents"][0]["id"]
    return _queue().enqueue(owner_id=owner, chat_id=UUID(session["id"]), kind="extract_document", dedup_key=f"extract:{document_id}:{uuid4()}",
                            payload={"session_id": session["id"], "document_id": document_id}, **kwargs)


def test_a_queued_reading_with_no_live_job_shows_as_failed_and_can_be_queued_again():
    owner = _owner()
    session = _save(owner, _session(owner))
    assert (_document(owner, session["id"])["extraction_status"], _document(owner, session["id"])["extraction_error"]) == ("failed", "EXTRACTION_STOPPED")
    listed = _store(owner).load_catalog()["sessions"][session["id"]]["documents"][0]
    assert listed["extraction_status"] == "failed"

    store = _store(owner)
    with store.transaction():
        assert store.requeue_failed_extraction(session["id"], session["documents"][0]["id"]) == "requeued"
        _queue().enqueue(owner_id=owner, chat_id=UUID(session["id"]), kind="extract_document", dedup_key=f"retry:{uuid4()}",
                         payload={"session_id": session["id"], "document_id": session["documents"][0]["id"]}, connection=store.connection)
    assert _document(owner, session["id"])["extraction_status"] == "queued"
    # A second "Thử lại" while the first job is live queues nothing.
    store = _store(owner)
    with store.transaction():
        assert store.requeue_failed_extraction(session["id"], session["documents"][0]["id"]) == "busy"


def test_a_failed_run_queued_again_is_not_failed_by_an_old_snapshot():
    owner = _owner()
    session = _save(owner, _session(owner, status="processing"))
    job = _enqueue_reading(owner, session)
    session["documents"][0].update(extraction_status="failed", extraction_error="MODEL_FAILED")
    _save(owner, session)
    # The worker's failed attempt, with another try queued: still waiting, not failed.
    assert _document(owner, session["id"])["extraction_status"] == "queued"
    _q("UPDATE jobs SET status='failed',finished_at=now() WHERE id=%s", (job["id"],))
    assert (_document(owner, session["id"])["extraction_status"], _document(owner, session["id"])["extraction_error"]) == ("failed", "MODEL_FAILED")
    store = _store(owner)
    with store.transaction():
        assert store.requeue_failed_extraction(session["id"], session["documents"][0]["id"]) == "requeued"
        _enqueue_reading(owner, session, connection=store.connection)
    # The old snapshot still says "failed": saving it again leaves the queued reading alone.
    _save(owner, session)
    assert _document(owner, session["id"])["extraction_status"] == "queued"


def test_answers_are_claimed_before_older_readings_and_a_lane_takes_only_its_kinds():
    owner = _owner()
    session = _save(owner, _session(owner))
    # Other tests' live jobs would compete for the claim.
    _q("UPDATE jobs SET status='cancelled',finished_at=now(),lease_token=NULL,lease_expires_at=NULL WHERE status IN ('queued','running')")
    reading = _enqueue_reading(owner, session)
    answer = _queue().enqueue(owner_id=owner, chat_id=UUID(session["id"]), kind="answer_question", dedup_key=f"answer:{uuid4()}", payload={})
    reading_lane = _queue().claim(worker_id="readings", kinds=["extract_document"])
    first = _queue().claim(worker_id="w")
    assert reading_lane["id"] == reading["id"]
    assert first["id"] == answer["id"]


def test_an_answer_job_out_of_tries_ends_its_card_as_failed_and_the_card_stays_in_the_chat():
    owner = _owner()
    user_id, assistant_id = str(uuid4()), str(uuid4())
    session = _session(owner, status="ready", messages=[
        {"id": user_id, "role": "user", "body": "Doanh thu?", "document_id": None},
        {"id": assistant_id, "role": "assistant", "body": "Đang tạo câu trả lời…", "status": "processing", "mode": "answer_question_job"},
    ])
    session["messages"][0]["document_id"] = session["messages"][1]["document_id"] = session["documents"][0]["id"]
    _save(owner, session)
    job = _queue().enqueue(owner_id=owner, chat_id=UUID(session["id"]), kind="answer_question", dedup_key=f"answer:{assistant_id}",
                           payload={"assistant_message_id": assistant_id}, max_attempts=1)
    _q("""UPDATE jobs SET status='running',attempts=1,lease_token=gen_random_uuid(),lease_expires_at=now()-interval '1 minute'
           WHERE id=%s""", (job["id"],))
    _queue().claim(worker_id="w")
    assert _q("SELECT status,error_code FROM jobs WHERE id=%s", (job["id"],))[0] == {"status": "failed", "error_code": "LEASE_EXPIRED"}
    messages = _store(owner).load_session(session["id"])["messages"]
    assert [(item["role"], item["status"]) for item in messages] == [("user", "accepted"), ("assistant", "failed")]
    assert all(item["document_id"] == session["documents"][0]["id"] for item in messages)
    assert messages[1]["body"] == "Không thể tạo câu trả lời. Hãy thử lại."


def _library(monkeypatch, owner):
    from report_qa.api import library

    monkeypatch.setattr(library, "settings", SimpleNamespace(persistence_backend="postgres", database_url=DATABASE_URL))
    monkeypatch.setattr(library, "owner_id_for_request", lambda request: owner)
    return library


def test_moving_a_chat_moves_its_reports_out_of_the_old_project_and_the_old_project_can_be_deleted(monkeypatch):
    owner = _owner()
    library = _library(monkeypatch, owner)
    old = library.create_project(library.ProjectCreateRequest(name=f"Cũ {uuid4()}"), None)["project"]["id"]
    new = library.create_project(library.ProjectCreateRequest(name=f"Mới {uuid4()}"), None)["project"]["id"]
    session = _save(owner, _session(owner, status="ready", project_id=str(old)))
    document_id = session["documents"][0]["id"]
    _store(owner).rename_document(session["id"], document_id, "doi-ten.pdf")
    assert _q("SELECT display_name FROM project_documents WHERE document_id=%s", (document_id,)) == [{"display_name": "doi-ten.pdf"}]

    library.move_session_to_project(UUID(session["id"]), library.SessionProjectUpdateRequest(project_id=new), None)
    rows = _q("SELECT project_id,display_name FROM project_documents WHERE document_id=%s", (document_id,))
    assert rows == [{"project_id": new, "display_name": "doi-ten.pdf"}]
    assert library.archive_project(old, None)["status"] == "archived"


def test_a_project_whose_reports_are_deleted_can_be_deleted(monkeypatch):
    owner = _owner()
    library = _library(monkeypatch, owner)
    project = library.create_project(library.ProjectCreateRequest(name=f"Dự án {uuid4()}"), None)["project"]["id"]
    session = _save(owner, _session(owner, status="ready", project_id=str(project)))
    _store(owner).archive_document(session["id"], session["documents"][0]["id"])
    # The chat that held the report is left empty, and must not keep the project.
    assert library.archive_project(project, None)["status"] == "archived"
    assert _q("SELECT deleted_at IS NOT NULL AS gone FROM chats WHERE id=%s", (session["id"],)) == [{"gone": True}]


def test_a_project_with_a_live_report_cannot_be_deleted(monkeypatch):
    owner = _owner()
    library = _library(monkeypatch, owner)
    project = library.create_project(library.ProjectCreateRequest(name=f"Dự án {uuid4()}"), None)["project"]["id"]
    _save(owner, _session(owner, status="ready", project_id=str(project)))
    with pytest.raises(HTTPException) as refused:
        library.archive_project(project, None)
    assert refused.value.status_code == 409


def test_the_library_shows_a_reading_with_no_live_job_as_failed(monkeypatch):
    owner = _owner()
    library = _library(monkeypatch, owner)
    project = library.create_project(library.ProjectCreateRequest(name=f"Dự án {uuid4()}"), None)["project"]["id"]
    stuck = _save(owner, _session(owner, status="processing", project_id=str(project)))
    waiting = _save(owner, _session(owner, project_id=str(project)))
    _enqueue_reading(owner, waiting)
    statuses = {row["document_id"]: row["extraction_status"] for row in library.project_library(project, None)["documents"]}
    assert statuses == {UUID(stuck["documents"][0]["id"]): "failed", UUID(waiting["documents"][0]["id"]): "queued"}


def test_signing_in_leaves_no_empty_guest_chat_in_the_account():
    from report_qa.api import auth

    account, guest = _owner(), uuid4()
    _q("""INSERT INTO users (id,email,normalized_email,password_hash,display_name,is_guest,guest_expires_at)
          VALUES (%s,'',%s,'!','Khách',true,now()+interval '1 day')""", (guest, f"guest:{guest}"))
    empty = _session(guest)
    empty["documents"] = []
    _save(guest, empty)
    kept = _save(guest, _session(guest, status="ready"))
    with _db() as connection:
        assert auth.adopt_guest(connection, guest, account) == 1
    chats = {str(row["id"]): row for row in _q("SELECT id,owner_id,deleted_at FROM chats WHERE id = ANY(%s)", ([UUID(empty["id"]), UUID(kept["id"])],))}
    assert chats[empty["id"]]["deleted_at"] is not None
    assert chats[kept["id"]]["deleted_at"] is None and chats[kept["id"]]["owner_id"] == account


def test_a_question_and_its_answer_job_are_stored_together(monkeypatch):
    from fastapi.testclient import TestClient

    from report_qa.api import main
    from report_qa.infrastructure.postgres.job_queue import PostgresJobQueue
    from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore

    owner = _owner(UUID(main.LOCAL_OWNER_ID))
    session = _save(owner, _session(owner, status="ready"))
    monkeypatch.setattr(main, "postgres_runtime", True)
    monkeypatch.setattr(main, "_runtime_for_owner", lambda value: PostgresRuntimeStore(DATABASE_URL, value))
    monkeypatch.setattr(main, "durable_job_queue", PostgresJobQueue(DATABASE_URL))
    monkeypatch.setattr(main, "settings", SimpleNamespace(**{**{name: getattr(main.settings, name) for name in main.settings.__slots__}, "async_answer_jobs": True}))
    client = TestClient(main.app, raise_server_exceptions=False)
    url = f"/api/v1/sessions/{session['id']}/messages"
    body = {"document_id": session["documents"][0]["id"], "question": "Doanh thu quý 3?"}
    key = str(uuid4())  # resend keys belong to the owner, and this owner is shared by every run
    accepted = client.post(url, json=body, headers={"Idempotency-Key": key})
    again = client.post(url, json=body, headers={"Idempotency-Key": key})
    assert accepted.status_code == 202 and again.json()["job"]["id"] == accepted.json()["job"]["id"]
    assert _q("SELECT count(*) AS n FROM jobs WHERE chat_id=%s AND kind='answer_question'", (UUID(session["id"]),))[0]["n"] == 1

    def refuse(**kwargs):
        raise RuntimeError("queue refused")

    monkeypatch.setattr(main.durable_job_queue, "enqueue", refuse)
    refused = client.post(url, json={**body, "question": "Lợi nhuận?"}, headers={"Idempotency-Key": str(uuid4())})
    assert refused.status_code == 500
    messages = _store(owner).load_session(session["id"])["messages"]
    assert [item["body"] for item in messages if item["role"] == "user"] == ["Doanh thu quý 3?"]
