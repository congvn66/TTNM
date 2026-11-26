"""Owner-scoped job status API for the PostgreSQL queue."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request

from report_qa.config import settings
from report_qa.infrastructure.postgres.job_queue import JobQueueError, PostgresJobQueue
from .auth import owner_id_for_request
from .user_messages import user_error


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
RUNTIME_OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")


def queue() -> PostgresJobQueue:
    if settings.persistence_backend != "postgres":
        raise user_error(503, "DURABLE_QUEUE_DISABLED")
    try:
        return PostgresJobQueue(settings.database_url)
    except JobQueueError as error:
        raise user_error(503, "QUEUE_UNAVAILABLE") from error


@router.get("")
def list_jobs(request: Request, status: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=100)):
    return {"jobs": queue().list(owner_id=owner_id_for_request(request), status=status, limit=limit)}


@router.get("/{job_id}")
def get_job(job_id: UUID, request: Request):
    item = queue().get(owner_id=owner_id_for_request(request), job_id=job_id)
    if item is None:
        raise user_error(404, "JOB_NOT_FOUND")
    return {"job": item}


@router.get("/{job_id}/events")
def get_job_events(job_id: UUID, request: Request, limit: int = Query(default=100, ge=1, le=200)):
    return {"events": queue().events(owner_id=owner_id_for_request(request), job_id=job_id, limit=limit)}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: UUID, request: Request):
    if not queue().cancel(owner_id=owner_id_for_request(request), job_id=job_id):
        raise user_error(409, "JOB_NOT_CANCELLABLE")
    return {"job_id": str(job_id), "status": "cancelled"}


@router.post("/{job_id}/retry")
def retry_job(job_id: UUID, request: Request):
    item = queue().retry(owner_id=owner_id_for_request(request), job_id=job_id)
    if item is None:
        raise user_error(409, "JOB_NOT_RETRYABLE")
    return {"job": item}
