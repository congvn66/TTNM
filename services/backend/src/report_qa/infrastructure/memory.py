"""Deterministic repository adapter used until the DB adapter is scaffolded."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from report_qa.domain.errors import ConflictError
from report_qa.domain.models import (
    AnswerInput,
    AnswerRevision,
    AnswerScope,
    AccountToken,
    AuditEvent,
    Chat,
    ChatEvidence,
    ChatSource,
    Document,
    DocumentVersion,
    EvidenceRevision,
    ExtractedEvidence,
    ExtractionRun,
    AuthSession,
    Job,
    JobEvent,
    Message,
    MessagePin,
    Project,
    ProjectDocument,
    RequestKey,
    SourceRegion,
    User,
)


class UuidProvider:
    def new_id(self) -> UUID:
        return uuid4()


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(slots=True)
class DataState:
    users: dict[UUID, User] = field(default_factory=dict)
    projects: dict[UUID, Project] = field(default_factory=dict)
    documents: dict[UUID, Document] = field(default_factory=dict)
    project_documents: dict[tuple[UUID, UUID], ProjectDocument] = field(default_factory=dict)
    document_versions: dict[UUID, DocumentVersion] = field(default_factory=dict)
    extraction_runs: dict[UUID, ExtractionRun] = field(default_factory=dict)
    source_regions: dict[UUID, SourceRegion] = field(default_factory=dict)
    extracted_evidences: dict[UUID, ExtractedEvidence] = field(default_factory=dict)
    chats: dict[UUID, Chat] = field(default_factory=dict)
    chat_sources: dict[UUID, ChatSource] = field(default_factory=dict)
    chat_evidences: dict[UUID, ChatEvidence] = field(default_factory=dict)
    evidence_revisions: dict[UUID, EvidenceRevision] = field(default_factory=dict)
    messages: dict[UUID, Message] = field(default_factory=dict)
    answer_revisions: dict[UUID, AnswerRevision] = field(default_factory=dict)
    answer_inputs: list[AnswerInput] = field(default_factory=list)
    answer_scopes: list[AnswerScope] = field(default_factory=list)
    message_pins: dict[UUID, MessagePin] = field(default_factory=dict)
    auth_sessions: dict[UUID, AuthSession] = field(default_factory=dict)
    account_tokens: dict[UUID, AccountToken] = field(default_factory=dict)
    jobs: dict[UUID, Job] = field(default_factory=dict)
    job_events: dict[UUID, list[JobEvent]] = field(default_factory=dict)
    audit_events: dict[UUID, AuditEvent] = field(default_factory=dict)
    request_keys: dict[tuple[UUID, str, str], RequestKey] = field(default_factory=dict)


class InMemoryDataRepository:
    """Small repository with the same ownership/fence semantics as the DB port."""

    def __init__(self) -> None:
        self.ids = UuidProvider()
        self.clock = UtcClock()
        self.state = DataState()
        self._requests: dict[tuple[UUID, str, str], Any] = {}
        self._jobs_by_dedup: dict[str, UUID] = {}

    def get_request(self, owner_id: UUID, route: str, key: str, request_hash: str | None = None) -> Any | None:
        request = self.state.request_keys.get((owner_id, route, key))
        if request is None:
            return None
        if request_hash is not None and request.request_hash != request_hash:
            raise ConflictError("idempotency key was reused with a different request")
        return self._requests.get((owner_id, route, key))

    def put_request(self, owner_id: UUID, route: str, key: str, request_hash: str, response: Any) -> None:
        self._requests[(owner_id, route, key)] = response
        self.state.request_keys[(owner_id, route, key)] = RequestKey(
            owner_id=owner_id,
            route=route,
            key=key,
            request_hash=request_hash,
            response=response if isinstance(response, dict) else {"replayable": True},
        )

    def add_document(self, document: Document) -> Document:
        self.state.documents[document.id] = document
        return document

    def get_document(self, document_id: UUID) -> Document | None:
        return self.state.documents.get(document_id)

    def get_document_version(self, version_id: UUID) -> DocumentVersion | None:
        return self.state.document_versions.get(version_id)

    def next_document_version_no(self, document_id: UUID) -> int:
        return 1 + max(
            (item.version_no for item in self.state.document_versions.values() if item.document_id == document_id),
            default=0,
        )

    def save_document_version(self, version: DocumentVersion) -> None:
        self.state.document_versions[version.id] = version

    def get_extraction_run(self, run_id: UUID) -> ExtractionRun | None:
        return self.state.extraction_runs.get(run_id)

    def next_extraction_run_no(self, version_id: UUID) -> int:
        return 1 + max(
            (item.run_no for item in self.state.extraction_runs.values() if item.document_version_id == version_id),
            default=0,
        )

    def save_extraction_run(self, run: ExtractionRun) -> None:
        self.state.extraction_runs[run.id] = run

    def save_source_region(self, region: SourceRegion) -> None:
        self.state.source_regions[region.id] = region

    def save_extracted_evidence(self, evidence: ExtractedEvidence) -> None:
        self.state.extracted_evidences[evidence.id] = evidence

    def get_extracted_evidence(self, evidence_id: UUID) -> ExtractedEvidence | None:
        return self.state.extracted_evidences.get(evidence_id)

    def get_chat(self, chat_id: UUID) -> Chat | None:
        return self.state.chats.get(chat_id)

    def save_chat(self, chat: Chat) -> None:
        self.state.chats[chat.id] = chat

    def get_chat_source(self, source_id: UUID) -> ChatSource | None:
        return self.state.chat_sources.get(source_id)

    def active_chat_sources(self, chat_id: UUID) -> tuple[ChatSource, ...]:
        return tuple(item for item in self.state.chat_sources.values() if item.chat_id == chat_id and item.source_status == "active")

    def save_chat_source(self, source: ChatSource) -> None:
        self.state.chat_sources[source.id] = source

    def get_chat_evidence(self, chat_evidence_id: UUID) -> ChatEvidence | None:
        return self.state.chat_evidences.get(chat_evidence_id)

    def save_chat_evidence(self, evidence: ChatEvidence) -> None:
        self.state.chat_evidences[evidence.id] = evidence

    def save_evidence_revision(self, revision: EvidenceRevision) -> None:
        self.state.evidence_revisions[revision.id] = revision

    def get_evidence_revision(self, revision_id: UUID) -> EvidenceRevision | None:
        return self.state.evidence_revisions.get(revision_id)

    def add_job(self, job: Job) -> Job:
        existing = self.find_job_by_dedup(job.idempotency_key or "")
        if existing is not None:
            return existing
        self.state.jobs[job.id] = job
        if job.idempotency_key:
            self._jobs_by_dedup[job.idempotency_key] = job.id
        return job

    def find_job_by_dedup(self, dedup_key: str) -> Job | None:
        job_id = self._jobs_by_dedup.get(dedup_key)
        return self.state.jobs.get(job_id) if job_id else None

    def add_chat(self, chat: Chat) -> Chat:
        self.state.chats[chat.id] = chat
        return chat

    def save_message(self, message: Message) -> None:
        self.state.messages[message.id] = message

    def get_message(self, message_id: UUID) -> Message | None:
        return self.state.messages.get(message_id)

    def save_answer_revision(self, revision: AnswerRevision) -> None:
        self.state.answer_revisions[revision.id] = revision

    def add_answer_input(self, item: AnswerInput) -> None:
        self.state.answer_inputs.append(item)

    def add_answer_scope(self, item: AnswerScope) -> None:
        self.state.answer_scopes.append(item)

    def answer_inputs_for(self, answer_revision_id: UUID) -> tuple[AnswerInput, ...]:
        return tuple(item for item in self.state.answer_inputs if item.answer_revision_id == answer_revision_id)

    def answer_scopes_for(self, answer_revision_id: UUID) -> tuple[AnswerScope, ...]:
        return tuple(item for item in self.state.answer_scopes if item.answer_revision_id == answer_revision_id)

    def get_job(self, job_id: UUID) -> Job | None:
        return self.state.jobs.get(job_id)

    @contextmanager
    def transaction(self):
        """Provide rollback semantics for application tests.

        A SQL adapter will replace this with a real DB transaction. Keeping the
        same boundary here catches partial-write bugs in flow orchestration.
        """

        snapshot = deepcopy(self.state)
        requests = deepcopy(self._requests)
        jobs_by_dedup = deepcopy(self._jobs_by_dedup)
        try:
            yield self
        except Exception:
            self.state = snapshot
            self._requests = requests
            self._jobs_by_dedup = jobs_by_dedup
            raise

    def add_job_event(self, job_id: UUID, event_type: str, payload: dict[str, Any] | None = None) -> JobEvent:
        events = self.state.job_events.setdefault(job_id, [])
        event = JobEvent(
            id=self.ids.new_id(),
            job_id=job_id,
            event_no=len(events) + 1,
            event_type=event_type,
            payload=dict(payload or {}),
        )
        events.append(event)
        return event

    def messages_for_chat(self, chat_id: UUID) -> list[Message]:
        return sorted((m for m in self.state.messages.values() if m.chat_id == chat_id), key=lambda m: m.sequence_no)

    def revisions_for_evidence(self, chat_evidence_id: UUID) -> list[EvidenceRevision]:
        return sorted(
            (r for r in self.state.evidence_revisions.values() if r.chat_evidence_id == chat_evidence_id),
            key=lambda r: r.revision_no,
        )

    def answer_revision_count(self, message_id: UUID) -> int:
        return sum(1 for item in self.state.answer_revisions.values() if item.message_id == message_id)
