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

from report_qa.api.main import SessionQuestionRequest, ask_session_document, catalog, complete_document_extraction, get_session, save_catalog
from report_qa.config import settings
from report_qa.infrastructure.postgres.job_queue import PostgresJobQueue


logger = logging.getLogger("report_qa.worker")
STOP = False


class StaleJobError(RuntimeError):
    """The answer was computed from an input snapshot that is no longer current."""


def _stop(*_args) -> None:
    global STOP
    STOP = True


def complete_answer_job(payload: dict[str, object], *, publish_guard=None) -> None:
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
    if placeholder and placeholder.get("status") == "completed":
        return
    request = Request({
        "type": "http", "method": "POST", "path": f"/api/v1/sessions/{session_id}/messages",
        "headers": [(b"x-worker-job", b"1"), (b"x-trace-id", str(payload.get("trace_id") or "").encode("ascii", "ignore"))],
        "query_string": b"", "server": ("worker", 0), "client": ("worker", 0), "scheme": "http",
    })
    request.state.internal_owner_id = owner_id
    response = Response()
    try:
        result = ask_session_document(session_id, SessionQuestionRequest(document_id=str(payload["document_id"]), question=str(payload["question"])), request, response)
    except Exception:
        session = get_session(session_id, owner_id)
        placeholder = next((item for item in session.get("messages", []) if item.get("id") == assistant_id), None)
        if placeholder is not None:
            placeholder.update({"status": "failed", "mode": "answer_question_job", "body": "Không thể tạo câu trả lời. Hãy thử lại.", "structured_answer": {"presentation": "error_v1", "answer": "Không thể tạo câu trả lời. Hãy thử lại.", "summary": "Worker gặp lỗi khi gọi pipeline.", "sections": [], "formulas": [], "tables": [], "claims": [], "warnings": ["JOB_FAILED"], "cited_pages": []}})
            save_catalog(catalog, owner_id)
        raise

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
    save_catalog(catalog, owner_id)


def _heartbeat_loop(queue: PostgresJobQueue, job_id: UUID, lease_token: UUID, stop: threading.Event) -> None:
    while not stop.wait(20):
        if not queue.heartbeat(job_id=job_id, lease_token=lease_token, lease_seconds=60, progress={"stage": "running"}):
            logger.warning("job lease lost during heartbeat job_id=%s", job_id)
            return


def run(*, poll_seconds: float = 1.0, worker_id: str | None = None, once: bool = False) -> None:
    if settings.persistence_backend != "postgres":
        raise RuntimeError("worker requires PERSISTENCE_BACKEND=postgres")
    queue = PostgresJobQueue(settings.database_url)
    # The launcher passes a stable identity through the environment so that
    # ``job_events`` can distinguish a deployed worker from a one-off smoke
    # process.  Fall back to the PID for local/manual runs.
    worker_id = worker_id or os.getenv("SOURCELENS_WORKER_ID") or f"worker-{os.getpid()}"
    reconnect_delay = max(1.0, poll_seconds)
    while not STOP:
        try:
            job = queue.claim(worker_id=worker_id)
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
            payload = job.get("payload") or {}
            if job["kind"] == "extract_document":
                complete_document_extraction(str(payload["session_id"]), str(payload["document_id"]), payload.get("trace_id"), payload.get("owner_id"))
                result = {"document_id": payload.get("document_id")}
            elif job["kind"] == "answer_question":
                complete_answer_job(
                    payload,
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
            retry_at = None if stale else datetime.now(timezone.utc) + timedelta(seconds=min(60, 2 ** max(0, attempts - 1))) if attempts < int(job.get("max_attempts") or 3) else None
            try:
                if stale:
                    queue.supersede(job_id=job_id, lease_token=lease_token, reason="STALE_INPUT_REVISION")
                else:
                    queue.fail(job_id=job_id, lease_token=lease_token, error_code="ANSWER_FAILED" if job.get("kind") == "answer_question" else "EXTRACTION_FAILED", retry_at=retry_at)
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
