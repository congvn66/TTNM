"""Remove guests whose time is up: their files go from storage, their rows are archived.

Guests keep their reports for a few days (auth.GUEST_DAYS). After that the PDFs
and readings are deleted from object storage first (the database does not
delete files), then the guest's chats and documents are archived like a
deleted report, and the guest account is closed so its cookie stops working.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
BATCH = 50


def expired_guest_files(connection: Any, guest_id: Any) -> list[str]:
    """The storage keys of a guest's PDFs and readings."""
    rows = connection.execute(
        """SELECT dv.id AS version_id, dv.storage_key FROM document_versions dv
           JOIN documents d ON d.id = dv.document_id WHERE d.owner_id = %s""", (guest_id,)).fetchall()
    keys: list[str] = []
    for row in rows:
        keys.append(row["storage_key"])
        keys.append(f"extractions/{row['version_id']}.json")
    return keys


def remove_expired_guests(connection: Any, storage: Any) -> int:
    """Close every expired guest (up to BATCH per call); returns how many were removed."""
    guests = connection.execute(
        """SELECT id FROM users WHERE is_guest AND deleted_at IS NULL AND guest_expires_at < now()
           ORDER BY guest_expires_at LIMIT %s""", (BATCH,)).fetchall()
    removed = 0
    for guest in guests:
        guest_id = guest["id"]
        try:
            for key in expired_guest_files(connection, guest_id):
                storage.delete_file(key)
            with connection.transaction():
                connection.execute("UPDATE chats SET deleted_at=now(),updated_at=now() WHERE owner_id=%s AND deleted_at IS NULL", (guest_id,))
                connection.execute("UPDATE documents SET deleted_at=now(),updated_at=now() WHERE owner_id=%s AND deleted_at IS NULL", (guest_id,))
                connection.execute("UPDATE projects SET deleted_at=now(),updated_at=now() WHERE owner_id=%s AND deleted_at IS NULL", (guest_id,))
                connection.execute("UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (guest_id,))
                connection.execute("UPDATE users SET deleted_at=now(),updated_at=now() WHERE id=%s", (guest_id,))
            removed += 1
        except Exception:
            # One guest's failure must not stop the others; it is tried again next time.
            logger.exception("GUEST_CLEANUP_FAILED guest=%s", guest_id)
    return removed
