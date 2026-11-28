from contextlib import contextmanager

from report_qa.api import auth
from report_qa.application.guest_cleanup import remove_expired_guests


class FakeConnection:
    """Records SQL; answers SELECTs from a list of canned results, in order."""

    def __init__(self, answers=(), fail_on=None):
        self.sql = []
        self.answers = list(answers)
        self.fail_on = fail_on

    def execute(self, statement, values=()):
        self.sql.append((" ".join(statement.split()), values))
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("database refused")
        rows = self.answers.pop(0) if statement.lstrip().upper().startswith("SELECT") and self.answers else []
        return Result(rows)

    @contextmanager
    def transaction(self):
        yield self


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeStorage:
    def __init__(self):
        self.deleted = []

    def delete_file(self, key):
        self.deleted.append(key)


def test_an_expired_guest_loses_files_first_then_rows_and_cookie():
    connection = FakeConnection(answers=[[{"id": "g1"}], [{"version_id": "v1", "storage_key": "documents/d1.pdf"}]])
    storage = FakeStorage()
    assert remove_expired_guests(connection, storage) == 1
    assert storage.deleted == ["documents/d1.pdf", "extractions/v1.json"]
    updates = [sql for sql, _ in connection.sql if sql.startswith("UPDATE")]
    assert [sql.split()[1] for sql in updates] == ["chats", "documents", "projects", "auth_sessions", "users"]


def test_a_guest_whose_files_cannot_be_deleted_keeps_its_rows_for_the_next_run():
    class Broken(FakeStorage):
        def delete_file(self, key):
            raise RuntimeError("storage down")
    connection = FakeConnection(answers=[[{"id": "g1"}], [{"version_id": "v1", "storage_key": "documents/d1.pdf"}]])
    assert remove_expired_guests(connection, Broken()) == 0
    assert not any(sql.startswith("UPDATE") for sql, _ in connection.sql)


def test_signing_in_moves_every_owned_table_and_folds_the_default_project():
    connection = FakeConnection(answers=[[{"n": 2}], [{"id": "account-default"}], [{"id": "guest-default"}]])
    assert auth.adopt_guest(connection, "guest", "account") == 2
    statements = [sql for sql, _ in connection.sql]
    assert statements[0] == "SET CONSTRAINTS ALL DEFERRED"
    moved = {sql.split()[1] for sql in statements if "SET owner_id" in sql}
    assert moved == set(auth.OWNER_TABLES)
    folded = [values for sql, values in connection.sql if "SET project_id" in sql]
    assert folded and all(values == ("account-default", "guest-default") for values in folded)
    assert any(sql.startswith("UPDATE users SET deleted_at") for sql in statements)


def test_a_failed_move_still_lets_the_person_sign_in():
    connection = FakeConnection(answers=[[{"n": 1}], [], []], fail_on="UPDATE chats SET owner_id")
    assert auth.adopt_guest(connection, "guest", "account") == 0


def test_a_guest_has_a_flag_and_an_expiry_in_its_public_shape():
    from datetime import datetime, timezone
    expiry = datetime(2026, 12, 5, tzinfo=timezone.utc)
    user = auth._public_user({"id": "g", "email": "", "display_name": "Khách", "is_guest": True, "guest_expires_at": expiry})
    assert user["is_guest"] is True and user["guest_expires_at"] == expiry.isoformat()
    assert auth._public_user({"id": "u", "email": "a@b.vn", "display_name": "A"})["is_guest"] is False
