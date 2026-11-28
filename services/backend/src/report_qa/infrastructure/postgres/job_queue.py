"""PostgreSQL-backed durable queue primitives.

The queue stores only identifiers and small configuration snapshots. Large
PDFs and extraction artifacts remain in object storage. Every mutation uses a
compare-and-set predicate so an expired or replaced lease cannot publish a
stale result.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class JobQueueError(RuntimeError):
    pass


# The worker's text for an answer that failed with no more specific reason (user_messages.MESSAGES["ANSWER_FAILED"]).
ANSWER_FAILED_TEXT = "Không thể tạo câu trả lời. Hãy thử lại."


def fail_answer_message(connection: Any, job: dict[str, Any], text: str) -> None:
    """End the "processing" answer card of an answer job that will not run again, keeping it in the chat.

    Revisions are immutable, so the failed answer is a new revision. A card
    that is already finished is left as it is.
    """
    message_id = (job.get("payload") or {}).get("assistant_message_id")
    if job.get("kind") != "answer_question" or not message_id:
        return
    message = connection.execute(
        "UPDATE messages SET status='failed',content=%s,updated_at=now() WHERE id=%s AND chat_id=%s AND status='processing' RETURNING current_answer_revision_id",
        (text, UUID(str(message_id)), job["chat_id"]),
    ).fetchone()
    if message and message["current_answer_revision_id"]:
        failed = connection.execute(
            """INSERT INTO answer_revisions (chat_id,message_id,revision_no,answer_status,question_context,operation,result,answer_text,assessment,input_data_revision)
               SELECT chat_id,message_id,(SELECT MAX(revision_no)+1 FROM answer_revisions WHERE message_id=source.message_id),'processing_error',question_context,operation,
                      jsonb_set(COALESCE(result,'{}'::jsonb),'{structured_answer}','null'::jsonb,true),%s,assessment,input_data_revision
                 FROM answer_revisions AS source WHERE id=%s RETURNING id""",
            (text, message["current_answer_revision_id"]),
        ).fetchone()
        connection.execute("UPDATE messages SET current_answer_revision_id=%s WHERE id=%s", (failed["id"], UUID(str(message_id))))


class PostgresJobQueue:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise JobQueueError("DATABASE_URL is required for the durable queue")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _public(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("id", "owner_id", "chat_id", "lease_token"):
            if result.get(key) is not None:
                result[key] = str(result[key])
        for key in ("created_at", "started_at", "finished_at", "available_at", "lease_expires_at"):
            if isinstance(result.get(key), datetime):
                result[key] = result[key].astimezone(timezone.utc).isoformat()
        return result

    def enqueue(
        self,
        *,
        owner_id: UUID,
        kind: str,
        dedup_key: str,
        payload: dict[str, Any],
        chat_id: UUID | None = None,
        input_data_revision: int | None = None,
        max_attempts: int = 3,
        connection: Any = None,
    ) -> dict[str, Any]:
        """Queue a job. With ``connection`` it joins the caller's open transaction, which commits it."""
        if max_attempts <= 0:
            raise JobQueueError("max_attempts must be positive")
        with nullcontext(connection) if connection is not None else self._connect() as connection:
            row = connection.execute(
                """INSERT INTO jobs (owner_id,chat_id,kind,dedup_key,status,input_data_revision,payload,max_attempts)
                   VALUES (%s,%s,%s,%s,'queued',%s,%s::jsonb,%s)
                   ON CONFLICT (dedup_key) DO NOTHING
                   RETURNING *""",
                (owner_id, chat_id, kind, dedup_key, input_data_revision, Jsonb(payload), max_attempts),
            ).fetchone()
            inserted = row is not None
            if row is None:
                row = connection.execute("SELECT * FROM jobs WHERE dedup_key=%s", (dedup_key,)).fetchone()
            if row is None:
                raise JobQueueError("job enqueue returned no row")
            if not inserted:
                # A deduplicated command is a read of the existing job; do
                # not emit a second `queued` event or make the timeline lie.
                return self._public(row) or {}
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (row["id"],)).fetchone()["next"]
            connection.execute(
                "INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'queued',%s::jsonb)",
                (row["id"], event_no, Jsonb({"kind": kind})),
            )
            return self._public(row) or {}

    def get(self, *, owner_id: UUID, job_id: UUID) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=%s AND owner_id=%s", (job_id, owner_id)).fetchone()
            return self._public(row)

    def list(self, *, owner_id: UUID, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as connection:
            if status:
                rows = connection.execute("SELECT * FROM jobs WHERE owner_id=%s AND status=%s ORDER BY created_at DESC LIMIT %s", (owner_id, status, limit)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM jobs WHERE owner_id=%s ORDER BY created_at DESC LIMIT %s", (owner_id, limit)).fetchall()
            return [self._public(row) or {} for row in rows]

    def events(self, *, owner_id: UUID, job_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        """Return the redacted append-only timeline for one owned job."""
        limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT e.id,e.event_no,e.event_type,e.payload,e.created_at
                     FROM job_events e JOIN jobs j ON j.id=e.job_id
                    WHERE e.job_id=%s AND j.owner_id=%s
                    ORDER BY e.event_no LIMIT %s""",
                (job_id, owner_id, limit),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["id"] = str(item["id"])
                if isinstance(item.get("created_at"), datetime):
                    item["created_at"] = item["created_at"].astimezone(timezone.utc).isoformat()
                result.append(item)
            return result

    def claim(self, *, worker_id: str, lease_seconds: int = 60, kinds: list[str] | None = None) -> dict[str, Any] | None:
        """Lease the next job: answers before readings, then oldest first. ``kinds`` limits it to those kinds (a worker lane).

        A reader waits for an answer; a reading takes minutes. Oldest-first put
        every question behind every queued reading.
        """
        lease_token = uuid4()
        with self._connect() as connection:
            # A crashed worker must not leave a terminal-attempt job in
            # ``running`` forever. Keep this recovery in the same transaction
            # as claim so another worker cannot claim it concurrently.
            expired = connection.execute(
                """UPDATE jobs SET status='failed',error_code='LEASE_EXPIRED',finished_at=now(),lease_token=NULL,lease_expires_at=NULL
                   WHERE status='running' AND lease_expires_at < now() AND attempts >= max_attempts
                   RETURNING id,kind,chat_id,payload"""
            ).fetchall()
            for item in expired:
                event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (item["id"],)).fetchone()["next"]
                connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'failed',%s::jsonb)", (item["id"], event_no, Jsonb({"error_code": "LEASE_EXPIRED"})))
                # Its answer card would say "Đang trả lời…" forever. (A reading shows as failed by itself: see
                # PostgresRuntimeStore._extraction_state.)
                fail_answer_message(connection, item, ANSWER_FAILED_TEXT)
            row = connection.execute(
                """WITH candidate AS (
                       SELECT id FROM jobs
                        WHERE ((status='queued' AND available_at <= now())
                           OR (status='running' AND lease_expires_at < now()))
                          AND (%s::text[] IS NULL OR kind = ANY(%s::text[]))
                        ORDER BY (kind = 'answer_question') DESC, created_at
                        FOR UPDATE SKIP LOCKED LIMIT 1
                   )
                   UPDATE jobs j SET status='running', lease_token=%s, lease_expires_at=now() + (%s || ' seconds')::interval,
                       started_at=COALESCE(started_at,now()), attempts=attempts+1
                    FROM candidate WHERE j.id=candidate.id AND j.attempts < j.max_attempts
                    RETURNING j.*""",
                (kinds, kinds, lease_token, lease_seconds),
            ).fetchone()
            if row is None:
                return None
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (row["id"],)).fetchone()["next"]
            connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'claimed',%s::jsonb)", (row["id"], event_no, Jsonb({"worker_id": worker_id, "attempt": row["attempts"]})))
            return self._public(row)

    def heartbeat(self, *, job_id: UUID, lease_token: UUID, lease_seconds: int = 60, progress: dict[str, Any] | None = None) -> bool:
        with self._connect() as connection:
            result = connection.execute("UPDATE jobs SET lease_expires_at=now() + (%s || ' seconds')::interval WHERE id=%s AND status='running' AND lease_token=%s", (lease_seconds, job_id, lease_token))
            if result.rowcount != 1:
                return False
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (job_id,)).fetchone()["next"]
            connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'progress',%s::jsonb)", (job_id, event_no, Jsonb(progress or {})))
            return True

    def status(self, job_id: UUID) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM jobs WHERE id=%s", (job_id,)).fetchone()
            return row["status"] if row else None

    def can_publish(self, *, job_id: UUID, lease_token: UUID, input_data_revision: int | None = None) -> bool:
        """Return whether this worker still owns a live, non-stale lease.

        The worker calls this immediately before committing a computed answer.
        A cancellation, lease replacement, or evidence revision therefore
        cannot silently publish an answer against an obsolete input snapshot.
        """
        with self._connect() as connection:
            row = connection.execute(
                """SELECT j.status,j.lease_token,j.input_data_revision,c.data_revision
                     FROM jobs j LEFT JOIN chats c ON c.id=j.chat_id
                    WHERE j.id=%s""",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] != "running" or row["lease_token"] != lease_token:
                return False
            if input_data_revision is not None and row["input_data_revision"] is not None:
                if int(row["input_data_revision"]) != int(row["data_revision"] or 0):
                    return False
            return True

    def succeed(self, *, job_id: UUID, lease_token: UUID, result: dict[str, Any] | None = None) -> bool:
        return self._finish(job_id=job_id, lease_token=lease_token, status="succeeded", result=result or {}, error_code=None)

    def fail(self, *, job_id: UUID, lease_token: UUID, error_code: str, retry_at: datetime | None = None) -> bool:
        status = "queued" if retry_at else "failed"
        with self._connect() as connection:
            result = connection.execute("UPDATE jobs SET status=%s,error_code=%s,available_at=COALESCE(%s,available_at),lease_token=NULL,lease_expires_at=NULL,finished_at=%s WHERE id=%s AND status='running' AND lease_token=%s", (status, error_code[:120], retry_at, None if retry_at else datetime.now(timezone.utc), job_id, lease_token))
            if result.rowcount != 1:
                return False
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (job_id,)).fetchone()["next"]
            connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,%s,%s::jsonb)", (job_id, event_no, "retry_scheduled" if retry_at else "failed", Jsonb({"error_code": error_code})))
            return True

    def supersede(self, *, job_id: UUID, lease_token: UUID, reason: str = "STALE_INPUT_REVISION") -> bool:
        """Close a leased job whose input snapshot is no longer current.

        ``failed`` means the work itself failed and may be retried.  A stale
        answer must not be retried against the same snapshot, so it gets the
        terminal ``superseded`` state and an explicit timeline event.
        """
        with self._connect() as connection:
            result = connection.execute(
                """UPDATE jobs
                      SET status='superseded',error_code=%s,finished_at=now(),
                          lease_token=NULL,lease_expires_at=NULL
                    WHERE id=%s AND status='running' AND lease_token=%s""",
                (reason[:120], job_id, lease_token),
            )
            if result.rowcount != 1:
                return False
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (job_id,)).fetchone()["next"]
            connection.execute(
                "INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'superseded',%s::jsonb)",
                (job_id, event_no, Jsonb({"reason": reason})),
            )
            return True

    def cancel(self, *, owner_id: UUID, job_id: UUID) -> bool:
        with self._connect() as connection:
            row = connection.execute("UPDATE jobs SET status='cancelled',finished_at=now(),lease_token=NULL,lease_expires_at=NULL WHERE id=%s AND owner_id=%s AND status IN ('queued','running') RETURNING kind,chat_id,payload", (job_id, owner_id)).fetchone()
            if row:
                fail_answer_message(connection, row, "Đã dừng tạo câu trả lời.")
                event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (job_id,)).fetchone()["next"]
                connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'cancelled','{}'::jsonb)", (job_id, event_no))
            return bool(row)

    def retry(self, *, owner_id: UUID, job_id: UUID) -> dict[str, Any] | None:
        """Explicitly requeue a terminal failed job without changing its id."""
        with self._connect() as connection:
            row = connection.execute(
                """UPDATE jobs SET status='queued',attempts=0,error_code=NULL,finished_at=NULL,
                              available_at=now(),lease_token=NULL,lease_expires_at=NULL
                     WHERE id=%s AND owner_id=%s AND status='failed' RETURNING *""",
                (job_id, owner_id),
            ).fetchone()
            if row is None:
                return None
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (job_id,)).fetchone()["next"]
            connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,'retry_requested','{}'::jsonb)", (job_id, event_no))
            return self._public(row)

    def _finish(self, *, job_id: UUID, lease_token: UUID, status: str, result: dict[str, Any], error_code: str | None) -> bool:
        with self._connect() as connection:
            updated = connection.execute("UPDATE jobs SET status=%s,result=%s::jsonb,error_code=%s,finished_at=now(),lease_token=NULL,lease_expires_at=NULL WHERE id=%s AND status='running' AND lease_token=%s", (status, Jsonb(result), error_code, job_id, lease_token))
            if updated.rowcount != 1:
                return False
            event_no = connection.execute("SELECT COALESCE(MAX(event_no),0)+1 AS next FROM job_events WHERE job_id=%s", (job_id,)).fetchone()["next"]
            connection.execute("INSERT INTO job_events (job_id,event_no,event_type,payload) VALUES (%s,%s,%s,%s::jsonb)", (job_id, event_no, status, Jsonb({})))
            return True
