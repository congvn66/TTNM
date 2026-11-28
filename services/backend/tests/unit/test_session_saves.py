from contextlib import contextmanager
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile

from report_qa.api import main


@pytest.fixture
def saved(monkeypatch):
    values = []
    monkeypatch.setattr(main, "postgres_runtime", True)
    monkeypatch.setattr(main, "save_catalog", lambda value, owner=None: values.append((value, owner)))
    return values


def test_a_request_saves_its_own_session_not_the_copy_another_request_put_in_the_cache(saved, monkeypatch):
    sid = str(uuid4())
    mine = {"id": sid, "owner_id": "o", "documents": [{"id": "a"}]}
    newer = {"id": sid, "owner_id": "o", "documents": [{"id": "b"}]}
    monkeypatch.setitem(main.catalog["sessions"], sid, newer)
    main.save_session(mine)
    assert saved == [({"sessions": {sid: mine}}, "o")]


def test_parallel_uploads_each_store_their_document(saved, monkeypatch):
    sid = str(uuid4())
    copies = [{"id": sid, "owner_id": "o", "documents": []} for _ in range(8)]
    for number, copy in enumerate(copies):
        monkeypatch.setitem(main.catalog["sessions"], sid, copy)  # every get_session replaces the cache entry
        copy["documents"].append({"id": f"d{number}"})
    for copy in copies:
        main.save_session(copy)
    stored = {document["id"] for value, _ in saved for session in value["sessions"].values() for document in session["documents"]}
    assert stored == {f"d{number}" for number in range(8)}


def test_the_workers_scratch_copy_is_never_saved(saved):
    main.save_session(main.ScratchSession({"id": str(uuid4()), "owner_id": "o"}))
    assert saved == []


def test_a_refused_save_drops_only_its_own_cached_copy(monkeypatch):
    sid = str(uuid4())
    mine = {"id": sid, "owner_id": "o"}
    monkeypatch.setattr(main, "postgres_runtime", True)
    monkeypatch.setattr(main, "save_catalog", lambda *args: (_ for _ in ()).throw(RuntimeError("refused")))
    monkeypatch.setitem(main.catalog["sessions"], sid, mine)
    with pytest.raises(RuntimeError):
        main.save_session(mine)
    assert sid not in main.catalog["sessions"]


def test_an_upload_stores_its_document_row_and_job_in_one_transaction(monkeypatch):
    log = []

    class Store:
        connection = "the-open-connection"

        @contextmanager
        def transaction(self):
            log.append("BEGIN")
            yield self
            log.append("COMMIT")

        def sync_catalog(self, value, **kwargs):
            log.append(("sync", list(value["sessions"])))

    class Queue:
        def enqueue(self, **kwargs):
            log.append(("enqueue", kwargs["connection"], kwargs["dedup_key"]))
            return {"id": "job"}
    sid = str(uuid4())
    owner = str(uuid4())
    monkeypatch.setattr(main, "durable_job_queue", Queue())
    monkeypatch.setattr(main, "_runtime_for_owner", lambda owner: Store())
    job = main._store_upload({"id": sid, "owner_id": owner, "documents": []}, {"id": "d1"}, "t")
    assert job == {"id": "job"}
    assert log == ["BEGIN", ("sync", [sid]), ("enqueue", "the-open-connection", "extract:d1"), "COMMIT"]


def _pdf() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_an_upload_whose_row_cannot_be_stored_leaves_no_pdf(monkeypatch):
    deleted = []
    monkeypatch.setattr(main, "uses_remote_object_storage", lambda: True)
    monkeypatch.setattr(main, "persist_pdf_cache", lambda name, path: None)
    monkeypatch.setattr(main, "object_storage", type("Storage", (), {"delete_file": lambda self, key: deleted.append(key)})())
    session = {"id": str(uuid4()), "owner_id": "o", "documents": []}

    def refuse(record):
        raise RuntimeError("database refused")
    with pytest.raises(RuntimeError):
        main.persist_pdf(UploadFile(BytesIO(_pdf()), filename="r.pdf"), session, store=refuse)
    assert session["documents"] == []
    assert len(deleted) == 1 and deleted[0].startswith("documents/")
    assert not main.document_path(deleted[0]).exists()


def test_enqueue_joins_a_given_transaction_without_committing_it():
    from report_qa.infrastructure.postgres.job_queue import PostgresJobQueue

    class Connection:
        def __init__(self):
            self.sql = []

        def execute(self, statement, values=()):
            self.sql.append(statement.split()[0])
            row = {"id": uuid4(), "owner_id": None, "chat_id": None, "lease_token": None, "next": 1}
            return type("Result", (), {"fetchone": lambda self: row})()

        def __exit__(self, *args):
            raise AssertionError("a joined transaction must not be closed or committed")
    connection = Connection()
    PostgresJobQueue("postgresql://unused").enqueue(owner_id=uuid4(), kind="extract_document", dedup_key="k", payload={}, connection=connection)
    assert connection.sql == ["INSERT", "SELECT", "INSERT"]


def test_a_new_default_project_gets_the_current_default_name(monkeypatch):
    from report_qa.config import DEFAULT_PROJECT_NAMES
    from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore
    store = PostgresRuntimeStore("postgresql://unused", uuid4())
    calls = []

    def execute(statement, values=()):
        calls.append((" ".join(statement.split()), values))
        return [{"id": UUID(int=1)}] if statement.lstrip().startswith("INSERT INTO projects") else []
    monkeypatch.setattr(store, "_execute", execute)
    store._sync_session({"id": str(uuid4()), "documents": [], "messages": []}, extraction_loader=None)
    lookup = next(values for sql, values in calls if sql.startswith("SELECT id FROM projects"))
    assert lookup[1] == list(DEFAULT_PROJECT_NAMES)
    insert = next(values for sql, values in calls if sql.startswith("INSERT INTO projects"))
    assert insert[1] == DEFAULT_PROJECT_NAMES[0]
