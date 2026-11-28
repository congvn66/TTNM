from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from report_qa.api import auth
from report_qa.application import guest_cleanup
from report_qa.application.guest_cleanup import LocalCopies, claim_expired_guests, purge_guest, remove_expired_guests


class FakeConnection:
    """Records SQL and transaction edges; ``answers`` is a list of (SQL fragment, rows) tried in order.

    Rows may be a list (returned every time), an iterator of lists (one per
    call) or an int (a rowcount). Unmatched statements return no rows.
    """

    def __init__(self, answers=(), *, autocommit=True, fail_on=None):
        self.log = []
        self.calls = []
        self.answers = list(answers)
        self.autocommit = autocommit
        self.fail_on = fail_on

    def execute(self, statement, values=()):
        sql = " ".join(statement.split())
        self.log.append(sql)
        self.calls.append((sql, values))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("database refused")
        for fragment, rows in self.answers:
            if fragment in sql:
                if hasattr(rows, "__next__"):
                    rows = next(rows, [])
                return Result(rows)
        return Result([])

    @contextmanager
    def transaction(self):
        self.log.append("BEGIN")
        try:
            yield self
        except BaseException:
            self.log.append("ROLLBACK")
            raise
        self.log.append("COMMIT")

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def statements(self):
        return [sql for sql in self.log if sql not in {"BEGIN", "COMMIT", "ROLLBACK"}]


class Result:
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else []
        self.rowcount = rows if isinstance(rows, int) else len(self.rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeStorage:
    def __init__(self, listed=()):
        self.deleted = []
        self.listed = list(listed)

    def delete_file(self, key):
        self.deleted.append(key)

    def list_keys(self, prefix):
        return [key for key in self.listed if key.startswith(prefix)]


def _request(headers=None, client=("203.0.113.7", 5000), cookies=None):
    raw = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw, "query_string": b"", "client": client})


@pytest.fixture
def postgres(monkeypatch):
    """auth on PostgreSQL with one fake connection; returns a holder whose .connection the test sets."""
    holder = type("Holder", (), {"connection": None, "kwargs": []})()
    monkeypatch.setattr(auth, "settings", replace(auth.settings, persistence_backend="postgres"))

    def connect(**kwargs):
        holder.kwargs.append(kwargs)
        return holder.connection
    monkeypatch.setattr(auth, "_connection", connect)
    monkeypatch.setattr(auth, "_user_from_request", lambda request: None)
    return holder


# Cleanup ---------------------------------------------------------------------------------------------

DOCUMENT = {"document_id": "d1", "version_id": "v1", "storage_key": "documents/d1.pdf"}


def _cleanup_connection(**extra):
    return FakeConnection([
        ("pg_try_advisory_lock", [{"locked": extra.get("locked", True)}]),
        ("UPDATE users SET deleted_at=now()", iter([[{"id": "g1"}]])),
        ("FROM users u WHERE u.is_guest AND u.deleted_at IS NOT NULL", [{"id": "g1"}]),
        ("SELECT d.id AS document_id", [DOCUMENT]),
        ("DELETE FROM folders f", iter([2, 1, 0])),
    ], fail_on=extra.get("fail_on"))


def test_claiming_closes_one_expired_guest_per_committed_transaction_and_rechecks_it():
    connection = FakeConnection([("UPDATE users SET deleted_at=now()", iter([[{"id": "g1"}], [{"id": "g2"}], []]))])
    assert claim_expired_guests(connection) == ["g1", "g2"]
    claim = next(sql for sql in connection.log if sql.startswith("UPDATE users"))
    assert "FOR UPDATE SKIP LOCKED" in claim
    # The outer WHERE checks the row again: a guest who signed up meanwhile is no longer a guest.
    assert claim.count("is_guest AND deleted_at IS NULL AND guest_expires_at < now()") == 2
    assert connection.log[:4] == ["BEGIN", claim, "UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", "COMMIT"]


def test_an_expired_guest_loses_its_rows_first_then_every_reading_and_local_copy_then_itself(tmp_path):
    storage = FakeStorage(listed=["extractions/d1.run-a.json", "extractions/d1.run-b.json", "extractions/d2.run-a.json"])
    deleted_local = []

    class Local:
        def delete(self, *args):
            deleted_local.append(args)
            connection.log.append("LOCAL DELETE")

    class Recording(FakeStorage):
        def delete_file(self, key):
            super().delete_file(key)
            connection.log.append("FILE DELETE")
    storage = Recording(listed=storage.listed)
    connection = _cleanup_connection()
    assert remove_expired_guests(connection, storage, Local()) == 1
    assert storage.deleted == ["documents/d1.pdf", "extractions/v1.json", "extractions/d1.run-a.json", "extractions/d1.run-b.json"]
    assert deleted_local == [("d1", "v1", "documents/d1.pdf")]
    log = connection.log
    flag = log.index("SET LOCAL app.guest_purge = 'on'")
    saved = next(i for i, sql in enumerate(log) if sql.startswith("UPDATE users SET guest_cleanup_files"))
    first_delete = next(i for i, sql in enumerate(log) if sql.startswith("DELETE"))
    commit = log.index("COMMIT", first_delete)
    assert log[flag - 1] == "BEGIN" and flag < saved < first_delete
    # Files go only after the rows are committed; the user row goes last.
    assert commit < log.index("FILE DELETE") and log[-2].startswith("DELETE FROM users")
    saved_files = next(values for sql, values in connection.calls if sql.startswith("UPDATE users SET guest_cleanup_files"))
    assert '"extractions/d1.run-b.json"' in saved_files[0]
    deletes = [sql for sql in log if sql.startswith("DELETE")]
    tables = [sql.split()[2] for sql in deletes]
    # Children before parents; folders leaf by leaf until none is left.
    assert tables.index("message_pins") < tables.index("messages") < tables.index("chats")
    assert tables.index("answer_inputs") < tables.index("evidence_revisions") < tables.index("chat_evidences") < tables.index("chat_sources")
    assert tables.index("jobs") < tables.index("chats") < tables.index("extraction_runs") < tables.index("document_versions") < tables.index("documents")
    assert tables.count("folders") == 3 and tables.index("project_documents") < tables.index("folders") < tables.index("projects")
    assert tables[-1] == "users" and "is_guest AND deleted_at IS NOT NULL" in deletes[-1]


def test_a_failed_file_delete_keeps_the_guest_and_its_file_list_for_the_next_run():
    class Broken(FakeStorage):
        def delete_file(self, key):
            raise RuntimeError("storage down")
    connection = _cleanup_connection()
    assert remove_expired_guests(connection, Broken()) == 0
    assert not any(sql.startswith("DELETE FROM users") for sql in connection.log)
    failure = [values for sql, values in connection.calls if "guest_cleanup_attempts=guest_cleanup_attempts+1" in sql]
    assert failure == [("g1",)]
    assert connection.log[-1].startswith("SELECT pg_advisory_unlock")


def test_a_retry_after_the_rows_are_gone_deletes_the_saved_files_and_the_guest():
    files = [{**DOCUMENT, "keys": ["documents/d1.pdf", "extractions/d1.run-a.json"]}]
    connection = FakeConnection([("SELECT guest_cleanup_files", [{"guest_cleanup_files": files}])])
    storage = FakeStorage()
    purge_guest(connection, storage, "g1")
    assert storage.deleted == ["documents/d1.pdf", "extractions/d1.run-a.json"]
    assert [sql.split()[2] for sql in connection.log if sql.startswith("DELETE")] == ["users"]
    assert "BEGIN" not in connection.log


def test_a_failed_row_delete_rolls_back_deletes_no_file_and_is_counted():
    connection = _cleanup_connection(fail_on="DELETE FROM documents")
    storage = FakeStorage()
    assert remove_expired_guests(connection, storage) == 0
    assert "ROLLBACK" in connection.log and storage.deleted == []
    assert any("guest_cleanup_attempts+1" in sql for sql in connection.log)


def test_guests_that_failed_too_often_or_have_a_running_job_are_skipped():
    connection = _cleanup_connection()
    remove_expired_guests(connection, FakeStorage())
    sql, values = next((sql, values) for sql, values in connection.calls if "FROM users u WHERE u.is_guest" in sql)
    assert "guest_cleanup_attempts < %s" in sql and values[0] == guest_cleanup.MAX_ATTEMPTS
    assert "j.status='running'" in sql


def test_only_the_worker_holding_the_lock_cleans():
    connection = _cleanup_connection(locked=False)
    assert remove_expired_guests(connection, FakeStorage()) == 0
    assert connection.statements() == [connection.statements()[0]] and "pg_try_advisory_lock" in connection.log[0]


def test_cleanup_refuses_a_connection_without_autocommit():
    with pytest.raises(ValueError):
        remove_expired_guests(FakeConnection(autocommit=False), FakeStorage())


def test_local_copies_of_a_document_are_deleted_and_others_kept(tmp_path):
    uploads, extractions, numbers = tmp_path / "uploads", tmp_path / "extracted", tmp_path / "number-state"
    for folder in (uploads / "documents", extractions, numbers):
        folder.mkdir(parents=True)
    mine = [uploads / "documents/d1.pdf", extractions / "v1.json", extractions / "d1.run-a.json", numbers / "d1.run-a.jsonl", numbers / "d1.json"]
    other = [uploads / "documents/d2.pdf", extractions / "d2.run-a.json", numbers / "d2.run-a.jsonl"]
    for path in mine + other:
        path.write_text("x")
    LocalCopies(uploads, extractions, numbers).delete("d1", "v1", "documents/d1.pdf")
    assert not any(path.exists() for path in mine)
    assert all(path.exists() for path in other)


def test_r2_lists_every_page_of_a_prefix():
    from report_qa.infrastructure.object_storage import CloudflareR2ObjectStorage

    class Paginator:
        def paginate(self, Bucket, Prefix):
            assert (Bucket, Prefix) == ("b", "extractions/d1.")
            return [{"Contents": [{"Key": "extractions/d1.a.json"}]}, {"Contents": [{"Key": "extractions/d1.b.json"}]}, {}]
    storage = object.__new__(CloudflareR2ObjectStorage)
    storage.bucket = "b"
    storage._client = type("Client", (), {"get_paginator": lambda self, name: Paginator()})()
    assert storage.list_keys("extractions/d1.") == ["extractions/d1.a.json", "extractions/d1.b.json"]


def test_the_worker_cleans_on_a_clock_even_when_jobs_keep_coming(monkeypatch):
    from types import SimpleNamespace

    from report_qa.worker import runner
    cleaned, claims = [], []

    class BusyQueue:
        def __init__(self, database_url):
            pass

        def claim(self, *, worker_id):
            claims.append(1)
            if len(claims) == 2:
                runner.STOP = True
            return {"id": "00000000-0000-0000-0000-000000000001", "lease_token": "00000000-0000-0000-0000-000000000002", "kind": "other", "payload": {}}

        def heartbeat(self, **kwargs):
            return True

        def fail(self, **kwargs):
            pass
    monkeypatch.setattr(runner, "PostgresJobQueue", BusyQueue)
    monkeypatch.setattr(runner, "settings", SimpleNamespace(persistence_backend="postgres", database_url="test"))
    monkeypatch.setattr(runner, "_clean_expired_guests", lambda: cleaned.append(1))
    monkeypatch.setattr(runner, "STOP", False)
    runner.run()
    assert cleaned == [1] and len(claims) == 2


def test_the_worker_takes_the_owner_from_the_job_row(monkeypatch):
    from types import SimpleNamespace

    from report_qa.worker import runner
    seen = []

    class Queue:
        def __init__(self, database_url):
            pass

        def claim(self, *, worker_id):
            runner.STOP = True
            return {"id": "00000000-0000-0000-0000-000000000001", "lease_token": "00000000-0000-0000-0000-000000000002",
                    "kind": "extract_document", "owner_id": "account", "payload": {"session_id": "s", "document_id": "d", "owner_id": "guest"}}

        def heartbeat(self, **kwargs):
            return True

        def succeed(self, **kwargs):
            return True
    monkeypatch.setattr(runner, "PostgresJobQueue", Queue)
    monkeypatch.setattr(runner, "settings", SimpleNamespace(persistence_backend="postgres", database_url="test"))
    monkeypatch.setattr(runner, "_clean_expired_guests", lambda: None)
    monkeypatch.setattr(runner, "complete_document_extraction", lambda *args: seen.append(args[3]))
    monkeypatch.setattr(runner, "STOP", False)
    runner.run()
    assert seen == ["account"]


# Adopting a guest at sign-in ------------------------------------------------------------------------

def _adopt_connection(fail_on=None, guest=True):
    return FakeConnection([
        ("FROM users WHERE id=%s AND is_guest AND deleted_at IS NULL AND guest_expires_at > now() FOR UPDATE", [{"id": "guest"}] if guest else []),
        ("SELECT count(*) AS n FROM documents", [{"n": 2}]),
        ("SELECT id FROM projects WHERE owner_id=%s", iter([[{"id": "account-default"}], [{"id": "guest-default"}]])),
        ("FROM folders WHERE project_id = ANY", [
            {"id": "a1", "project_id": "account-default", "name": "Q1", "normalized_name": "q1"},
            {"id": "a2", "project_id": "account-default", "name": "Q1 (2)", "normalized_name": "q1 (2)"},
            {"id": "g1", "project_id": "guest-default", "name": "Q1", "normalized_name": "q1"},
        ]),
        ("FROM projects WHERE owner_id = ANY", [
            {"id": "p1", "owner_id": "account", "name": "Thuế"},
            {"id": "p2", "owner_id": "guest", "name": "Thuế"},
            {"id": "p3", "owner_id": "guest", "name": "Thuế (2)"},
        ]),
    ], fail_on=fail_on)


def test_signing_in_moves_every_owned_table_and_folds_the_default_project():
    connection = _adopt_connection()
    assert auth.adopt_guest(connection, "guest", "account") == 2
    statements = connection.statements()
    assert "FOR UPDATE" in statements[0] and statements[1] == "SET CONSTRAINTS ALL DEFERRED"
    # The deferred owner pairs are checked inside the transaction, not at a later commit.
    assert statements[-1] == "SET CONSTRAINTS ALL IMMEDIATE" and connection.log[-1] == "COMMIT"
    moved = {sql.split()[1] for sql in statements if "SET owner_id" in sql}
    assert moved == set(auth.OWNER_TABLES)
    folded = [values for sql, values in connection.calls if "SET project_id" in sql]
    assert folded and all(values == ("account-default", "guest-default") for values in folded)
    first_owner_move = next(i for i, sql in enumerate(statements) if "SET owner_id" in sql)
    archive_default = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE projects SET deleted_at"))
    rename = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE projects SET name"))
    assert archive_default < first_owner_move and rename < first_owner_move
    assert any(sql.startswith("UPDATE users SET deleted_at") for sql in statements)
    assert ("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", ("guest",)) in connection.calls


def test_a_moved_name_takes_the_first_free_number():
    connection = _adopt_connection()
    auth.adopt_guest(connection, "guest", "account")
    folder = next(values for sql, values in connection.calls if sql.startswith("UPDATE folders SET name"))
    assert folder == ("Q1 (3)", "q1 (3)", "g1")  # "Q1 (2)" is taken in the account
    projects = [values for sql, values in connection.calls if sql.startswith("UPDATE projects SET name")]
    assert projects == [("Thuế (3)", "p2")]  # "Thuế (2)" is the guest's own other project


def test_queued_jobs_get_the_new_owner_in_their_payload_too():
    connection = _adopt_connection()
    auth.adopt_guest(connection, "guest", "account")
    sql, values = next((sql, values) for sql, values in connection.calls if sql.startswith("UPDATE jobs SET payload"))
    assert "jsonb_set(payload,'{owner_id}'" in sql and values == ("account", "guest")
    # Revisions are immutable; the author is moved only inside the purge flag, which is turned off again.
    author = connection.log.index("UPDATE evidence_revisions SET created_by=%s WHERE created_by=%s")
    assert connection.log[author - 1] == "SET LOCAL app.guest_purge = 'on'"
    assert connection.log[author + 1] == "SET LOCAL app.guest_purge = 'off'"


def test_a_guest_that_is_gone_moves_nothing():
    connection = _adopt_connection(guest=False)
    assert auth.adopt_guest(connection, "guest", "account") == 0
    assert not any("SET owner_id" in sql for sql in connection.log)


def test_a_failed_move_reports_failure():
    connection = _adopt_connection(fail_on="UPDATE chats SET owner_id")
    assert auth.adopt_guest(connection, "guest", "account") is None
    assert "ROLLBACK" in connection.log


def _account_row():
    return [{"id": "account", "email": "a@b.vn", "display_name": "A", "password_hash": auth._hash_password("password1"),
             "is_guest": False, "guest_expires_at": None}]


def test_login_commits_the_session_before_the_move_and_flags_a_failed_move(postgres, monkeypatch):
    postgres.connection = FakeConnection([("FROM users WHERE normalized_email=%s", _account_row())])
    monkeypatch.setattr(auth, "_user_from_request", lambda request: {"id": "guest", "is_guest": True})
    monkeypatch.setattr(auth, "adopt_guest", lambda connection, guest_id, user_id: None)
    result = auth.login(auth.LoginRequest(email="a@b.vn", password="password1"), _request(cookies={auth.SESSION_COOKIE: "guest-token"}), Response())
    assert postgres.kwargs == [{"autocommit": True}]
    assert result["adopt_failed"] is True and result["moved_reports"] == 0
    # The guest's session is not revoked: the reports stay reachable until the guest expires.
    assert not any("WHERE token_hash=%s" in sql for sql in postgres.connection.log)


def test_login_without_a_guest_revokes_the_old_cookie(postgres):
    postgres.connection = FakeConnection([("FROM users WHERE normalized_email=%s", _account_row())])
    result = auth.login(auth.LoginRequest(email="a@b.vn", password="password1"), _request(cookies={auth.SESSION_COOKIE: "old"}), Response())
    assert result["adopt_failed"] is False
    assert ("UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL", (auth._token_hash("old"),)) in postgres.connection.calls


# Sign-up from a guest -------------------------------------------------------------------------------

def _register(cookies=None):
    return auth.register(auth.RegisterRequest(email="new@b.vn", password="password1", display_name="N"), _request(cookies=cookies), Response())


def test_sign_up_upgrades_only_a_live_guest_and_revokes_all_its_sessions(postgres, monkeypatch):
    expiry = datetime.now(timezone.utc) + timedelta(days=3)
    monkeypatch.setattr(auth, "_user_from_request", lambda request: {"id": "guest", "is_guest": True, "guest_expires_at": expiry})
    postgres.connection = FakeConnection([("UPDATE users SET email=%s", [{"id": "guest", "email": "new@b.vn", "display_name": "N", "is_guest": False, "guest_expires_at": None}])])
    assert _register()["user"]["is_guest"] is False
    upgrade = next(sql for sql in postgres.connection.log if sql.startswith("UPDATE users SET email"))
    assert "is_guest AND deleted_at IS NULL AND guest_expires_at > now()" in upgrade
    assert ("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", ("guest",)) in postgres.connection.calls


def test_sign_up_from_a_guest_cleanup_just_took_is_a_conflict(postgres, monkeypatch):
    monkeypatch.setattr(auth, "_user_from_request", lambda request: {"id": "guest", "is_guest": True})
    postgres.connection = FakeConnection()
    with pytest.raises(HTTPException) as refused:
        _register()
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "GUEST_EXPIRED"
    assert "ROLLBACK" in postgres.connection.log


def test_two_sign_ups_with_one_email_give_409_not_503(postgres):
    class UniqueViolation(Exception):
        sqlstate = "23505"

    class Racing(FakeConnection):
        def execute(self, statement, values=()):
            if statement.startswith("INSERT INTO users"):
                raise UniqueViolation()
            return super().execute(statement, values)
    postgres.connection = Racing()
    with pytest.raises(HTTPException) as refused:
        _register()
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "EMAIL_ALREADY_REGISTERED"


# Starting a guest -----------------------------------------------------------------------------------

def _guest_connection(everyone=0, recent=0):
    expiry = datetime.now(timezone.utc) + timedelta(days=auth.GUEST_DAYS)
    return FakeConnection([
        ("FROM users WHERE is_guest AND created_at", [{"n": everyone}]),
        ("FROM auth_sessions s JOIN users u", [{"n": recent}]),
        ("INSERT INTO users", [{"id": "g", "email": "", "display_name": auth.GUEST_NAME, "is_guest": True, "guest_expires_at": expiry}]),
    ])


def test_guests_are_made_one_at_a_time_and_their_session_ends_with_them(postgres):
    postgres.connection = _guest_connection()
    response = Response()
    auth.start_guest(_request(), response)
    log = postgres.connection.log
    assert log[0] == "BEGIN" and log[1].startswith("SELECT pg_advisory_xact_lock")
    session = next(values for sql, values in postgres.connection.calls if sql.startswith("INSERT INTO auth_sessions"))
    guest_expiry = postgres.connection.answers[2][1][0]["guest_expires_at"]
    assert session[2] <= guest_expiry
    max_age = int(response.headers["set-cookie"].split("Max-Age=")[1].split(";")[0])
    assert max_age <= auth.GUEST_DAYS * 86400


@pytest.mark.parametrize("everyone,recent", [(200, 0), (0, auth.GUESTS_PER_ADDRESS_PER_HOUR)])
def test_too_many_guests_overall_or_from_one_address_are_refused(postgres, everyone, recent):
    postgres.connection = _guest_connection(everyone=everyone, recent=recent)
    with pytest.raises(HTTPException) as refused:
        auth.start_guest(_request(), Response())
    assert refused.value.status_code == 429
    assert not any(sql.startswith("INSERT") for sql in postgres.connection.log)


def test_the_overall_guest_cap_is_a_setting(postgres, monkeypatch):
    monkeypatch.setenv("AUTH_GUESTS_PER_HOUR", "5")
    postgres.connection = _guest_connection(everyone=5)
    with pytest.raises(HTTPException):
        auth.start_guest(_request(), Response())


def test_a_forwarded_header_is_not_an_address_unless_the_deployment_names_one(monkeypatch):
    monkeypatch.delenv("AUTH_CLIENT_IP_HEADER", raising=False)
    assert auth.client_address(_request()) == "203.0.113.7"
    # uvicorn may have copied X-Forwarded-For into the peer: it is the visitor's own text.
    assert auth.client_address(_request({"X-Forwarded-For": "198.51.100.1"}, client=("198.51.100.1", 1))) is None
    spoofed = {auth._request_ip_hash(_request({"X-Forwarded-For": f"198.51.100.{n}"}, client=(f"198.51.100.{n}", 1))) for n in range(5)}
    assert len(spoofed) == 1  # changing the header does not make a new limit bucket
    monkeypatch.setenv("AUTH_CLIENT_IP_HEADER", "CF-Connecting-IP")
    assert auth.client_address(_request({"CF-Connecting-IP": "192.0.2.9", "X-Forwarded-For": "1.1.1.1"})) == "192.0.2.9"
    assert auth.client_address(_request()) is None


def test_an_expired_guest_cookie_no_longer_signs_in(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(auth, "settings", replace(auth.settings, persistence_backend="postgres"))
    monkeypatch.setattr(auth, "_connection", lambda **kwargs: connection)
    assert auth._user_from_request(_request(cookies={auth.SESSION_COOKIE: "t"})) is None
    assert "AND (NOT u.is_guest OR u.guest_expires_at > now())" in connection.log[0]


# Upload limit ---------------------------------------------------------------------------------------

def _slot_connection(is_guest=True, gone=False, used=0, everyone=0):
    return FakeConnection([
        ("FOR NO KEY UPDATE", [{"is_guest": is_guest, "gone": gone}]),
        ("SELECT is_guest FROM users", [{"is_guest": is_guest}]),
        ("FROM documents WHERE owner_id", [{"n": used}]),
        ("FROM documents d JOIN users u", [{"n": everyone}]),
    ])


def test_a_guest_upload_holds_the_guest_row_until_it_is_stored(postgres):
    postgres.connection = _slot_connection(used=2)
    with auth.guest_upload_slot("g"):
        assert postgres.connection.log[-1] != "COMMIT"
        assert any("FOR NO KEY UPDATE" in sql for sql in postgres.connection.log)
    assert postgres.connection.log[-1] == "COMMIT"


@pytest.mark.parametrize("kwargs", [{"used": auth.GUEST_UPLOADS_PER_DAY}, {"everyone": 500}, {"gone": True}])
def test_a_guest_without_a_slot_is_refused_before_the_upload_runs(postgres, kwargs):
    postgres.connection = _slot_connection(**kwargs)
    ran = []
    with pytest.raises(HTTPException) as refused:
        with auth.guest_upload_slot("g"):
            ran.append(1)
    assert refused.value.status_code == 429 and not ran


def test_an_account_upload_takes_no_lock(postgres):
    postgres.connection = _slot_connection(is_guest=False)
    with auth.guest_upload_slot("u"):
        pass
    assert not any("FOR NO KEY UPDATE" in sql for sql in postgres.connection.log)


def test_both_upload_routes_hold_the_guest_slot():
    import inspect

    from report_qa.api import main
    for endpoint in (main.upload_session_document, main.upload_document):
        assert "with guest_upload_slot(owner_id):" in inspect.getsource(endpoint)


def test_migration_0013_lets_only_the_purge_flag_through_the_immutability_triggers():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "migrations/versions/0013_guest_purge_flag.py").read_text()
    upgrade = text.split("def downgrade")[0]
    assert upgrade.count("current_setting('app.guest_purge', true) = 'on'") == 2
    assert "app_deny_revision_mutation" in upgrade and "app_guard_extraction_payload" in upgrade
    assert "guest_cleanup_files jsonb" in upgrade and 'down_revision = "0012_guest_limits_cleanup"' in text


def test_a_guest_has_a_flag_and_an_expiry_in_its_public_shape():
    expiry = datetime(2026, 12, 5, tzinfo=timezone.utc)
    user = auth._public_user({"id": "g", "email": "", "display_name": "Khách", "is_guest": True, "guest_expires_at": expiry})
    assert user["is_guest"] is True and user["guest_expires_at"] == expiry.isoformat()
    assert auth._public_user({"id": "u", "email": "a@b.vn", "display_name": "A"})["is_guest"] is False
