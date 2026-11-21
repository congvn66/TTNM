"""Worker-side lease operations for the data-flow skeleton."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from report_qa.application.ports import DataRepository
from report_qa.domain.errors import ConflictError, NotFoundError
from report_qa.domain.types import JobStatus


class WorkerHandlers:
    def __init__(self, repo: DataRepository) -> None:
        self.repo = repo

    def claim(self, *, job_id: UUID, lease_token: str, lease_seconds: int = 60) -> None:
        job = self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError("job not found")
        now = self.repo.clock.now()
        reclaiming = job.status is JobStatus.RUNNING and job.lease_expires_at is not None and job.lease_expires_at <= now
        if job.status is not JobStatus.QUEUED and not reclaiming:
            raise ConflictError("only queued or expired-running jobs can be claimed")
        if not lease_token.strip():
            raise ConflictError("lease token is required")
        if lease_seconds <= 0:
            raise ConflictError("lease_seconds must be positive")
        if job.attempts >= job.max_attempts:
            raise ConflictError("job retry limit reached")
        job.status = JobStatus.RUNNING
        job.lease_token = lease_token
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempts += 1
        self.repo.add_job(job)
        self.repo.add_job_event(job_id, "reclaimed" if reclaiming else "started", {"input_data_revision": job.input_data_revision, "attempt": job.attempts})

    def heartbeat(self, *, job_id: UUID, lease_token: str, progress: int | None = None) -> None:
        job = self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError("job not found")
        if job.status is not JobStatus.RUNNING or job.lease_token != lease_token or (job.lease_expires_at is not None and job.lease_expires_at <= self.repo.clock.now()):
            raise ConflictError("job lease is not valid")
        job.lease_expires_at = self.repo.clock.now() + timedelta(seconds=60)
        self.repo.add_job(job)
        payload = {} if progress is None else {"progress": max(0, min(100, progress))}
        self.repo.add_job_event(job_id, "progress", payload)

    def fail(self, *, job_id: UUID, lease_token: str, error_code: str) -> None:
        job = self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError("job not found")
        if job.status is not JobStatus.RUNNING or job.lease_token != lease_token or (job.lease_expires_at is not None and job.lease_expires_at <= self.repo.clock.now()):
            raise ConflictError("job lease is not valid")
        job.status = JobStatus.FAILED
        job.lease_expires_at = None
        self.repo.add_job(job)
        self.repo.add_job_event(job_id, "failed", {"error_code": error_code})

    def succeed(self, *, job_id: UUID, lease_token: str) -> None:
        """Commit a non-answer worker job after its domain work completed."""
        job = self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError("job not found")
        if job.status is not JobStatus.RUNNING or job.lease_token != lease_token or (job.lease_expires_at is not None and job.lease_expires_at <= self.repo.clock.now()):
            raise ConflictError("job lease is not valid")
        job.status = JobStatus.SUCCEEDED
        job.lease_expires_at = None
        self.repo.add_job(job)
        self.repo.add_job_event(job_id, "succeeded")

    def succeed_event(self, *, job_id: UUID, lease_token: str) -> None:
        job = self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError("job not found")
        if job.status is not JobStatus.SUCCEEDED or job.lease_token != lease_token:
            raise ConflictError("job is not successfully completed under this lease")
        self.repo.add_job_event(job_id, "succeeded")

    def supersede(self, *, job_id: UUID, lease_token: str) -> None:
        job = self.repo.get_job(job_id)
        if job is None:
            raise NotFoundError("job not found")
        if job.status is not JobStatus.RUNNING or job.lease_token != lease_token or (job.lease_expires_at is not None and job.lease_expires_at <= self.repo.clock.now()):
            raise ConflictError("job lease is not valid")
        job.status = JobStatus.SUPERSEDED
        job.lease_expires_at = None
        self.repo.add_job(job)
        self.repo.add_job_event(job_id, "superseded")
