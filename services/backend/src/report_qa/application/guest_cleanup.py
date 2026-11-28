"""Remove guests whose time is up: their rows, then their files, then the guest itself.

Guests keep their reports for a few days (auth.GUEST_DAYS). Removal has two
steps, each committed on its own:

1. Claim. One transaction closes the guest (users.deleted_at) and revokes its
   sessions, but only while the row is still a guest and its time is up.
   From then on sign-up, sign-in and uploads refuse it, so nothing can
   move its reports to an account or add new ones.
2. Purge. One transaction writes the list of the guest's files (each PDF and
   every reading) on the user row and deletes every other row it owns,
   children first. Then the files are deleted from object storage and from
   this machine's disk, and last the user row. So no row ever points at a
   deleted file, and a failure after the rows are gone retries the files from
   the saved list. A purge that fails is counted on the user row and tried
   again on the next run, up to MAX_ATTEMPTS times.

Only one worker runs this at a time (a session advisory lock).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from report_qa.infrastructure.object_storage import validate_object_key

logger = logging.getLogger(__name__)
BATCH = 50
MAX_ATTEMPTS = 5
# pg_try_advisory_lock key: one cleaner at a time across workers.
CLEANUP_LOCK = 7_301_002

# Rows of the guest's chats, children before parents. Every statement takes the guest id.
_IN_CHATS = "chat_id IN (SELECT id FROM chats WHERE owner_id=%s)"
_IN_RUNS = """extraction_run_id IN (SELECT r.id FROM extraction_runs r JOIN document_versions v ON v.id=r.document_version_id
                                     JOIN documents d ON d.id=v.document_id WHERE d.owner_id=%s)"""
PURGE_STATEMENTS = (
    # Self and circular references first, so the deletes below meet no RESTRICT.
    f"UPDATE messages SET reply_to_message_id=NULL, current_answer_revision_id=NULL WHERE {_IN_CHATS}",
    f"UPDATE chat_evidences SET current_revision_id=NULL WHERE {_IN_CHATS}",
    f"DELETE FROM message_pins WHERE {_IN_CHATS}",
    f"DELETE FROM answer_inputs WHERE {_IN_CHATS}",
    f"DELETE FROM answer_scopes WHERE {_IN_CHATS}",
    f"DELETE FROM answer_revisions WHERE {_IN_CHATS}",
    f"DELETE FROM messages WHERE {_IN_CHATS}",
    f"DELETE FROM evidence_revisions WHERE {_IN_CHATS}",
    f"DELETE FROM chat_evidences WHERE {_IN_CHATS}",
    f"DELETE FROM chat_sources WHERE {_IN_CHATS}",
    f"DELETE FROM chat_documents WHERE {_IN_CHATS}",
    "DELETE FROM jobs WHERE owner_id=%s",
    "DELETE FROM request_keys WHERE owner_id=%s",
    "DELETE FROM chats WHERE owner_id=%s",
    f"DELETE FROM extracted_evidences WHERE {_IN_RUNS}",
    f"DELETE FROM source_regions WHERE {_IN_RUNS}",
    """DELETE FROM extraction_runs WHERE document_version_id IN (
           SELECT v.id FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.owner_id=%s)""",
    "DELETE FROM project_documents WHERE owner_id=%s",
    "DELETE FROM document_versions WHERE document_id IN (SELECT id FROM documents WHERE owner_id=%s)",
    "DELETE FROM documents WHERE owner_id=%s",
)
# Folders reference their parent (RESTRICT): delete leaves until none is left.
_DELETE_LEAF_FOLDERS = """DELETE FROM folders f WHERE f.owner_id=%s
                          AND NOT EXISTS (SELECT 1 FROM folders c WHERE c.parent_id=f.id)"""


@dataclass(frozen=True, slots=True)
class LocalCopies:
    """This machine's copies of a document: the PDF, the readings and the number logs."""

    uploads: Path
    extractions: Path
    number_state: Path

    def delete(self, document_id: str, version_id: str, storage_key: str) -> None:
        paths = [self.uploads / validate_object_key(storage_key), self.extractions / f"{version_id}.json",
                 *self.extractions.glob(f"{document_id}.*"), *self.number_state.glob(f"{document_id}.*")]
        for path in paths:
            path.unlink(missing_ok=True)


def guest_documents(connection: Any, guest_id: Any) -> list[dict[str, str]]:
    rows = connection.execute(
        """SELECT d.id AS document_id, dv.id AS version_id, dv.storage_key FROM document_versions dv
           JOIN documents d ON d.id = dv.document_id WHERE d.owner_id = %s""", (guest_id,)).fetchall()
    return [{key: str(value) for key, value in row.items()} for row in rows]


def stored_keys(storage: Any, document: dict[str, str]) -> list[str]:
    """Every object-storage key of one document: its PDF and each reading.

    A reading is uploaded as extractions/{document id}.{run id}.json (one per
    reading, re-reads included) and again under the version's name.
    """
    keys = [document["storage_key"], f"extractions/{document['version_id']}.json"]
    keys += storage.list_keys(f"extractions/{document['document_id']}.")
    return list(dict.fromkeys(keys))


def claim_expired_guests(connection: Any, limit: int = BATCH) -> list[Any]:
    """Close up to ``limit`` expired guests, each in its own committed transaction; returns their ids."""
    claimed = []
    for _ in range(limit):
        with connection.transaction():
            row = connection.execute(
                """UPDATE users SET deleted_at=now(), updated_at=now()
                   WHERE id = (SELECT id FROM users WHERE is_guest AND deleted_at IS NULL AND guest_expires_at < now()
                               ORDER BY guest_expires_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                     AND is_guest AND deleted_at IS NULL AND guest_expires_at < now()
                   RETURNING id""").fetchone()
            if row is None:
                break
            connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (row["id"],))
        claimed.append(row["id"])
    return claimed


def _delete_rows(connection: Any, storage: Any, guest_id: Any) -> list[dict[str, Any]]:
    """In one transaction: save the guest's file list on its user row, then delete every row it owns but that one."""
    with connection.transaction():
        # Revision and reading rows are immutable (triggers); migration 0013 lets them go while this is on.
        connection.execute("SET LOCAL app.guest_purge = 'on'")
        files = [{**document, "keys": stored_keys(storage, document)} for document in guest_documents(connection, guest_id)]
        connection.execute("UPDATE users SET guest_cleanup_files=%s::jsonb WHERE id=%s", (json.dumps(files), guest_id))
        for statement in PURGE_STATEMENTS:
            connection.execute(statement, (guest_id,))
        while connection.execute(_DELETE_LEAF_FOLDERS, (guest_id,)).rowcount:
            pass
        connection.execute("DELETE FROM projects WHERE owner_id=%s", (guest_id,))
        # Edits the guest made in chats it no longer owns (moved by an older sign-in) keep no author.
        connection.execute("UPDATE evidence_revisions SET created_by=NULL WHERE created_by=%s", (guest_id,))
    return files


def purge_guest(connection: Any, storage: Any, guest_id: Any, local: LocalCopies | None = None) -> None:
    """Delete a claimed guest's rows, then its files, then the guest. Raises when a step fails; the next run resumes."""
    row = connection.execute("SELECT guest_cleanup_files FROM users WHERE id=%s", (guest_id,)).fetchone()
    files = row["guest_cleanup_files"] if row else None
    if files is None:
        files = _delete_rows(connection, storage, guest_id)
    for document in files:
        for key in document["keys"]:
            storage.delete_file(key)
        if local is not None:
            local.delete(document["document_id"], document["version_id"], document["storage_key"])
    # Sessions, tokens and preferences go with the user (ON DELETE CASCADE).
    connection.execute("DELETE FROM users WHERE id=%s AND is_guest AND deleted_at IS NOT NULL", (guest_id,))


def _guests_to_purge(connection: Any) -> list[Any]:
    # A closed guest with a running job waits: the job could still upload a reading after its files are gone.
    rows = connection.execute(
        """SELECT id FROM users u WHERE u.is_guest AND u.deleted_at IS NOT NULL AND u.guest_cleanup_attempts < %s
             AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.owner_id=u.id AND j.status='running')
           ORDER BY u.deleted_at LIMIT %s""", (MAX_ATTEMPTS, BATCH)).fetchall()
    return [row["id"] for row in rows]


def remove_expired_guests(connection: Any, storage: Any, local: LocalCopies | None = None) -> int:
    """Claim expired guests and purge closed ones; returns how many were purged.

    ``connection`` must be in autocommit mode, so each guest's claim and purge
    commit on their own. Returns 0 at once when another worker is cleaning.
    """
    if not getattr(connection, "autocommit", True):
        raise ValueError("guest cleanup needs an autocommit connection")
    if not connection.execute("SELECT pg_try_advisory_lock(%s) AS locked", (CLEANUP_LOCK,)).fetchone()["locked"]:
        return 0
    try:
        claim_expired_guests(connection)
        removed = 0
        for guest_id in _guests_to_purge(connection):
            try:
                purge_guest(connection, storage, guest_id, local)
                removed += 1
            except Exception:
                logger.exception("GUEST_CLEANUP_FAILED guest=%s", guest_id)
                connection.execute(
                    "UPDATE users SET guest_cleanup_attempts=guest_cleanup_attempts+1, guest_cleanup_failed_at=now() WHERE id=%s",
                    (guest_id,))
        return removed
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s)", (CLEANUP_LOCK,))
