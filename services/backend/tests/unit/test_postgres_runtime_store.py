from uuid import uuid4

from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore


def test_catalog_owner_match_accepts_json_string_and_uuid_forms():
    owner = uuid4()

    assert PostgresRuntimeStore._owner_matches(str(owner), owner)
    assert PostgresRuntimeStore._owner_matches(owner, str(owner))
    assert not PostgresRuntimeStore._owner_matches(str(uuid4()), owner)


class _Recorder:
    """Record SQL; answer the few reads the code under test needs."""

    def __init__(self, answers=()):
        self.calls, self.answers = [], list(answers)

    def __call__(self, sql, params=()):
        sql = " ".join(sql.split())
        self.calls.append((sql, params))
        return next((rows for start, rows in self.answers if sql.startswith(start)), [])

    def statements(self, start):
        return [(sql, params) for sql, params in self.calls if sql.startswith(start)]


def test_two_numbers_in_one_text_span_keep_their_own_region(monkeypatch):
    """The region names one evidence_key; a shared region mixed the two values up."""
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    execute = _Recorder()
    monkeypatch.setattr(store, "_execute", execute)
    evidences = [
        {"evidence_key": key, "source_region_key": "page-1-span-0", "source_type": "text", "page_number": 1, "bbox": [0, 0, 1, 1], "raw_text": value, "numeric_value": value, "data_status": "valid", "extraction_method": "text"}
        for key, value in (("q1", "100"), ("q2", "250"))
    ]
    store._complete_extraction(uuid4(), uuid4(), uuid4(), {"page_count": 1}, {"evidence_batch": {"evidences": evidences}})
    regions = execute.statements("INSERT INTO source_regions")
    assert [params[2] for _, params in regions] == ["q1", "q2"]
    assert len({params[0] for _, params in regions}) == 2
    assert [params[2] for _, params in execute.statements("INSERT INTO extracted_evidences")] == [params[0] for _, params in regions]


def test_saving_an_old_snapshot_cannot_rename_or_restore_a_chat_or_document(monkeypatch):
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    execute = _Recorder()
    monkeypatch.setattr(store, "_execute", execute)
    session = {"id": str(uuid4()), "project_id": str(uuid4()), "title": "old", "messages": [], "documents": [{"id": str(uuid4()), "file_name": "old.pdf", "extraction_status": "queued"}]}
    store._sync_session(session, extraction_loader=None)
    for table in ("chats", "documents", "document_versions"):
        update = execute.statements(f"INSERT INTO {table} ")[0][0].split("DO UPDATE SET")[1]
        assert not any(column in update for column in ("deleted_at", "title=", "file_name="))


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
        if sql.startswith(("SELECT 1", "SELECT COALESCE")):
            return [{"value": 1}]
        return []
    monkeypatch.setattr(store, "_execute", execute)
    store._sync_messages(uuid4(), [
        {"id": str(uuid4()), "role": "user", "body": "question"},
        {"id": str(uuid4()), "role": "assistant", "status": "failed", "mode": "answer_question_job", "answer_revisions": [{"id": str(revision_id)}]},
    ])
    writes = [params for sql, params in calls if sql.startswith("UPDATE messages SET content")]
    assert writes[0][1] == "failed"
    # answer_revisions rows are immutable: the failure is a new revision.
    assert not any(sql.lstrip().startswith("UPDATE answer_revisions") for sql, _ in calls)


def test_saving_a_failed_answer_again_does_not_add_another_revision(monkeypatch):
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    revision_id, failed_id = uuid4(), uuid4()
    execute = _Recorder([
        ("SELECT id,status", [{"id": uuid4(), "status": "failed", "current_answer_revision_id": failed_id}]),
        ("SELECT 1 FROM answer_revisions", [{"value": 1}]),
        ("SELECT answer_status", [{"answer_status": "processing_error"}]),
    ])
    monkeypatch.setattr(store, "_execute", execute)
    store._sync_messages(uuid4(), [
        {"id": str(uuid4()), "role": "user", "body": "question"},
        {"id": str(uuid4()), "role": "assistant", "status": "failed", "mode": "answer_question_job", "answer_revisions": [{"id": str(revision_id)}]},
    ])
    assert not execute.statements("INSERT INTO answer_revisions")
    assert execute.statements("UPDATE messages SET content")[0][1][3] == failed_id


def test_chart_run_is_completed_only_after_its_values_are_inserted(monkeypatch):
    """Payload rows of a completed run are immutable, and points of one chart share a source region."""
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    version, run, chat = uuid4(), uuid4(), uuid4()
    calls = []

    def execute(sql, params=()):
        calls.append((" ".join(sql.split()), params))
        if "FOR UPDATE" in sql:
            return [{"id": version}]
        if "MAX(run_no)" in sql:
            return [{"value": 2}]
        if sql.startswith("SELECT id FROM chat_sources"):
            return [{"id": uuid4()}]
        return []

    class NoTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(store, "_execute", execute)
    monkeypatch.setattr(store, "transaction", NoTransaction)
    monkeypatch.setattr(store, "initialize_chat_evidence", lambda *args: {"a": uuid4()})
    evidences = [
        {"evidence_key": key, "source_region_key": "page-1-picture-0", "page_number": 1, "bbox": [0, 0, 1, 1], "raw_text": "1", "numeric_value": "1", "data_status": "valid", "extraction_method": "axis_estimation", "confidence": 0.8}
        for key in ("a", "b")
    ]
    store.persist_on_demand_chart(
        chat_id=chat, document_version_id=version, question_plan_id="q", chart_record={"chart_region_key": "page-1-picture-0"},
        evidence_batch={"schema_version": 2, "document_version_id": str(version), "extraction_run_id": str(run), "scope": "on_demand_chart", "trigger": {"question_plan_id": "q", "chart_region_keys": ["page-1-picture-0"]}, "evidences": evidences},
    )
    statements = [sql for sql, _ in calls]
    completed = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE extraction_runs SET status='completed'"))
    assert max(i for i, sql in enumerate(statements) if sql.startswith(("INSERT INTO source_regions", "INSERT INTO extracted_evidences"))) < completed
    assert [params[2] for sql, params in calls if sql.startswith("INSERT INTO source_regions")] == ["a", "b"]


def test_a_chart_point_already_in_the_chat_is_reused_not_stored_twice(monkeypatch):
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    version, kept = uuid4(), uuid4()

    class NoTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    execute = _Recorder([
        ("SELECT dv.id", [{"id": version}]),
        ("SELECT COALESCE(MAX(run_no)", [{"value": 3}]),
        ("SELECT sr.meta", [{"evidence_key": "a", "current_revision_id": kept}]),
        ("SELECT id FROM chat_sources", [{"id": uuid4()}]),
    ])
    monkeypatch.setattr(store, "_execute", execute)
    monkeypatch.setattr(store, "transaction", NoTransaction)
    fresh = uuid4()
    monkeypatch.setattr(store, "initialize_chat_evidence", lambda *args: {"b": fresh})
    evidences = [
        {"evidence_key": key, "source_region_key": "r", "page_number": 1, "bbox": [0, 0, 1, 1], "raw_text": "1", "numeric_value": "1", "data_status": "valid", "extraction_method": "axis_estimation", "confidence": 0.8}
        for key in ("a", "b")
    ]
    revisions = store.persist_on_demand_chart(
        chat_id=uuid4(), document_version_id=version, question_plan_id="q2",
        evidence_batch={"schema_version": 2, "document_version_id": str(version), "extraction_run_id": str(uuid4()), "scope": "on_demand_chart", "trigger": {"question_plan_id": "q2", "chart_region_keys": ["r"]}, "evidences": evidences},
    )
    assert [params[2] for _, params in execute.statements("INSERT INTO source_regions")] == ["b"]
    assert revisions == {"a": kept, "b": fresh}
