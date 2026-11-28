"""Small PostgreSQL worker for durable extraction jobs.

It intentionally shares the application extraction function with the API so
there is one domain implementation. The worker owns the lease and never
publishes a result after its lease has been lost.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from starlette.requests import Request
from starlette.responses import Response
import psycopg

from fastapi import HTTPException

from report_qa.api.main import SessionQuestionRequest, ask_session_document, complete_document_extraction, get_session, save_session
from report_qa.api.user_messages import MESSAGES
from report_qa.config import settings
from report_qa.infrastructure.postgres.job_queue import PostgresJobQueue
from report_qa.infrastructure.postgres.runtime_store import PostgresRuntimeStore


logger = logging.getLogger("report_qa.worker")
STOP = False
# Expired guests are removed this often, between jobs, by whichever worker gets the lock.
CLEANUP_EVERY_SECONDS = 3600


def _clean_expired_guests() -> None:
    from psycopg.rows import dict_row

    from report_qa.api.object_storage_runtime import object_storage
    from report_qa.api.session_storage import EXTRACTION_ROOT, UPLOAD_ROOT, number_state_root
    from report_qa.application.guest_cleanup import LocalCopies, remove_expired_guests
    try:
        local = LocalCopies(uploads=UPLOAD_ROOT, extractions=EXTRACTION_ROOT, number_state=number_state_root())
        with psycopg.connect(settings.database_url, row_factory=dict_row, autocommit=True) as connection:
            removed = remove_expired_guests(connection, object_storage, local)
        if removed:
            logger.info("removed %d expired guests", removed)
    except Exception:
        logger.exception("guest cleanup failed; trying again in an hour")


class StaleJobError(RuntimeError):
    """The answer was computed from an input snapshot that is no longer current."""


class AnswerFailed(RuntimeError):
    """The answer failed and its card already says so: the job ends without a retry.

    A silent retry kept the job queued while the card read "failed", and a
    rate-limited provider is not back a second later. The reader asks again.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RetryLater(RuntimeError):
    """The question came before its report was read: the job tries again in WAIT_FOR_READING_SECONDS, its card still waiting."""


WAIT_FOR_READING_SECONDS = 30


def _failure_code(exc: Exception) -> str:
    """The user-facing code of an answer failure: the API error's code, else ANSWER_FAILED."""
    detail = exc.detail if isinstance(exc, HTTPException) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if code in MESSAGES else "ANSWER_FAILED"


def _stop(*_args) -> None:
    global STOP
    STOP = True


def complete_answer_job(payload: dict[str, object], *, publish_guard=None, last_try: bool = True) -> None:
    """Run the existing grounded answer pipeline and replace its placeholder.

    The compatibility API still owns the orchestration code.  This adapter
    makes the queue boundary real without maintaining a second answer
    implementation; the generated temporary pair is collapsed into the
    persisted assistant placeholder before the worker acknowledges the job.
    """
    session_id = str(payload["session_id"])
    assistant_id = str(payload["assistant_message_id"])
    owner_id = str(payload.get("owner_id") or "")
    if not owner_id:
        raise RuntimeError("JOB_OWNER_MISSING")
    session = get_session(session_id, owner_id)
    placeholder = next((item for item in session.get("messages", []) if item.get("id") == assistant_id), None)
    if placeholder is None:
        # The question and its card are stored with the job in one transaction, so this is a job from before
        # that: there is no card to answer into, and an answer without its question would not be saved.
        logger.warning("answer job has no stored question; skipped session=%s message=%s", session_id, assistant_id)
        return
    if placeholder.get("status") == "completed":
        return
    request = Request({
        "type": "http", "method": "POST", "path": f"/api/v1/sessions/{session_id}/messages",
        "headers": [(b"x-worker-job", b"1"), (b"x-trace-id", str(payload.get("trace_id") or "").encode("ascii", "ignore"))],
        "query_string": b"", "server": ("worker", 0), "client": ("worker", 0), "scheme": "http",
    })
    request.state.internal_owner_id = owner_id
    request.state.worker_job = True
    response = Response()
    try:
        result = ask_session_document(session_id, SessionQuestionRequest(document_id=str(payload["document_id"]), question=str(payload["question"])), request, response)
    except Exception as exc:
        code = _failure_code(exc)
        if code == "EXTRACTION_NOT_READY" and not last_try:
            raise RetryLater(code) from exc
        text = MESSAGES[code]
        session = get_session(session_id, owner_id)
        placeholder = next((item for item in session.get("messages", []) if item.get("id") == assistant_id), None)
        if placeholder is None:
            raise
        placeholder.update({"status": "failed", "mode": "answer_question_job", "body": text, "structured_answer": {"presentation": "error_v1", "answer": text, "summary": "", "error_code": code, "sections": [], "formulas": [], "tables": [], "claims": [], "warnings": [], "cited_pages": []}})
        # Only this session: the worker's cache holds older copies of other sessions, and saving those
        # put back document and answer states that had moved on since.
        save_session(session, owner_id)
        logger.warning("answer failed code=%s session=%s message=%s", code, session_id, assistant_id, exc_info=exc)
        raise AnswerFailed(code) from exc

    if publish_guard is not None and not publish_guard():
        raise StaleJobError("STALE_OR_CANCELLED_JOB")
    session = get_session(session_id, owner_id)
    generated_user = result["user_message"]
    generated_assistant = result["assistant_message"]
    session["messages"] = [item for item in session.get("messages", []) if item.get("id") not in {generated_user["id"], generated_assistant["id"]}]
    placeholder = next((item for item in session["messages"] if item.get("id") == assistant_id), None)
    if placeholder is None:
        # A crash between placeholder persistence and worker execution should
        # never silently lose the answer. Keep the generated assistant with a
        # stable job result if the placeholder was removed by a user action.
        generated_assistant["id"] = assistant_id
        session["messages"].append(generated_assistant)
    else:
        placeholder.clear()
        placeholder.update(generated_assistant)
        placeholder["id"] = assistant_id
        placeholder["status"] = "completed"
        placeholder["trace"] = [*(placeholder.get("trace") or []), {"stage": "job_worker", "status": "completed"}]
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_session(session, owner_id)


# A reading is one long library call that cannot be stopped from inside, so a
# worker whose job is cancelled exits with this code and start_worker.sh starts
# it again: the cancelled job stops holding a worker within HEARTBEAT_SECONDS.
CANCELLED_EXIT_CODE = 75
HEARTBEAT_SECONDS = 10


def _heartbeat_loop(queue: PostgresJobQueue, job_id: UUID, lease_token: UUID, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        if queue.heartbeat(job_id=job_id, lease_token=lease_token, lease_seconds=60, progress={"stage": "running"}):
            continue
        if queue.status(job_id) == "cancelled":
            logger.warning("job cancelled while running; restarting the worker job_id=%s", job_id)
            os._exit(CANCELLED_EXIT_CODE)
        logger.warning("job lease lost during heartbeat job_id=%s", job_id)
        return


def run(*, poll_seconds: float = 1.0, worker_id: str | None = None, once: bool = False) -> None:
    if settings.persistence_backend != "postgres":
        raise RuntimeError("worker requires PERSISTENCE_BACKEND=postgres")
    queue = PostgresJobQueue(settings.database_url)
    # Two workers that finish readings of one chat save it one after the other.
    PostgresRuntimeStore.save_statement_timeout = "10min"
    # The launcher passes a stable identity through the environment so that
    # ``job_events`` can distinguish a deployed worker from a one-off smoke
    # process.  Fall back to the PID for local/manual runs.
    worker_id = worker_id or os.getenv("SOURCELENS_WORKER_ID") or f"worker-{os.getpid()}"
    # SOURCELENS_WORKER_KINDS=answer_question makes a worker that only answers, so questions never wait
    # behind readings. Unset: every kind, answers first.
    kinds = [item.strip() for item in os.getenv("SOURCELENS_WORKER_KINDS", "").split(",") if item.strip()] or None
    reconnect_delay = max(1.0, poll_seconds)
    next_cleanup = 0.0
    while not STOP:
        # On a clock, not only when idle: a busy worker must still remove expired guests.
        if not once and time.monotonic() >= next_cleanup:
            next_cleanup = time.monotonic() + CLEANUP_EVERY_SECONDS
            _clean_expired_guests()
        try:
            job = queue.claim(worker_id=worker_id, **({"kinds": kinds} if kinds else {}))
            reconnect_delay = max(1.0, poll_seconds)
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            # A transient Supabase/pooler outage must not kill the worker and
            # leave every document permanently queued. Reconnect with bounded
            # exponential backoff; the next successful claim resumes safely.
            logger.error("queue unavailable; retrying in %.1fs error=%s", reconnect_delay, type(exc).__name__)
            if once:
                raise
            time.sleep(min(30.0, reconnect_delay))
            reconnect_delay = min(30.0, reconnect_delay * 2)
            continue
        if job is None:
            if once:
                return
            time.sleep(poll_seconds)
            continue
        job_id = UUID(job["id"])
        lease_token = UUID(job["lease_token"])
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(target=_heartbeat_loop, args=(queue, job_id, lease_token, heartbeat_stop), daemon=True)
        heartbeat.start()
        try:
            # jobs.owner_id is the owner; a sign-in moves it to the account while the job waits.
            payload = {**(job.get("payload") or {}), **({"owner_id": job["owner_id"]} if job.get("owner_id") else {})}
            if job["kind"] == "extract_document":
                complete_document_extraction(str(payload["session_id"]), str(payload["document_id"]), payload.get("trace_id"), payload.get("owner_id"))
                result = {"document_id": payload.get("document_id")}
            elif job["kind"] == "answer_question":
                complete_answer_job(
                    payload,
                    last_try=int(job.get("attempts") or 0) >= int(job.get("max_attempts") or 3),
                    publish_guard=lambda: queue.can_publish(
                        job_id=job_id,
                        lease_token=lease_token,
                        input_data_revision=job.get("input_data_revision"),
                    ),
                )
                result = {"assistant_message_id": payload.get("assistant_message_id")}
            else:
                queue.fail(job_id=job_id, lease_token=lease_token, error_code="UNSUPPORTED_JOB_KIND")
                continue
            if not queue.succeed(job_id=job_id, lease_token=lease_token, result=result):
                logger.warning("job lease lost before publish job_id=%s", job_id)
        except Exception as exc:
            attempts = int(job.get("attempts") or 0)
            stale = isinstance(exc, StaleJobError)
            final = stale or isinstance(exc, AnswerFailed)
            delay = WAIT_FOR_READING_SECONDS if isinstance(exc, RetryLater) else min(60, 2 ** max(0, attempts - 1))
            retry_at = None if final else datetime.now(timezone.utc) + timedelta(seconds=delay) if attempts < int(job.get("max_attempts") or 3) else None
            try:
                if stale:
                    queue.supersede(job_id=job_id, lease_token=lease_token, reason="STALE_INPUT_REVISION")
                else:
                    code = exc.code if isinstance(exc, AnswerFailed) else "ANSWER_FAILED" if job.get("kind") == "answer_question" else "EXTRACTION_FAILED"
                    queue.fail(job_id=job_id, lease_token=lease_token, error_code=code, retry_at=retry_at)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                # The lease may be recovered by another worker after a DB
                # outage. Never terminate the process while reporting failure.
                logger.error("could not persist job failure; lease recovery will retry job_id=%s", job_id)
            logger.exception("job failed job_id=%s kind=%s retry=%s", job_id, job.get("kind"), bool(retry_at))
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the durable PostgreSQL worker.")
    parser.add_argument("--once", action="store_true", help="Claim at most one job, useful for smoke tests.")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="Idle poll interval (default: 1s).")
    args = parser.parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    run(poll_seconds=max(0.1, args.poll_seconds), once=args.once)


if __name__ == "__main__":
    main()
