from uuid import uuid4

from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore


def test_catalog_owner_match_accepts_json_string_and_uuid_forms():
    owner = uuid4()

    assert PostgresRuntimeStore._owner_matches(str(owner), owner)
    assert PostgresRuntimeStore._owner_matches(owner, str(owner))
    assert not PostgresRuntimeStore._owner_matches(str(uuid4()), owner)


def test_source_region_identity_is_shared_by_multiple_evidence_rows():
    first = {"evidence_key": "number-1", "source_region_key": "page-1-span-0"}
    second = {"evidence_key": "text-1", "source_region_key": "page-1-span-0"}

    assert PostgresRuntimeStore._source_region_key(first) == PostgresRuntimeStore._source_region_key(second)
    assert PostgresRuntimeStore._source_region_key({"evidence_key": "fallback"}) == "fallback"


def test_stale_pending_snapshot_cannot_reset_completed_message(monkeypatch):
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    calls = []
    def execute(sql, params=()):
        calls.append((sql, params))
        return [{"id": params[0], "status": "completed", "current_answer_revision_id": uuid4()}]
    monkeypatch.setattr(store, "_execute", execute)
    store._sync_messages(uuid4(), [
        {"id": str(uuid4()), "role": "user", "body": "question"},
        {"id": str(uuid4()), "role": "assistant", "status": "processing", "mode": "answer_question_job"},
    ])
    assert not any(sql.startswith("UPDATE") for sql, _ in calls)


def test_failed_job_mode_is_persisted_as_failed_not_processing(monkeypatch):
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    calls = []
    revision_id = uuid4()
    def execute(sql, params=()):
        calls.append((sql, params))
        if sql.startswith("SELECT id,status"):
            return [{"id": params[0], "status": "processing", "current_answer_revision_id": revision_id}]
        if sql.startswith("SELECT 1"):
            return [{"value": 1}]
        return []
    monkeypatch.setattr(store, "_execute", execute)
    store._sync_messages(uuid4(), [
        {"id": str(uuid4()), "role": "user", "body": "question"},
        {"id": str(uuid4()), "role": "assistant", "status": "failed", "mode": "answer_question_job", "answer_revisions": [{"id": str(revision_id)}]},
    ])
    writes = [params for sql, params in calls if sql.startswith("UPDATE messages SET content")]
    assert writes[0][1] == "failed"
