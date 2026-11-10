"""Dataclass representation of the first data-flow slice.

These objects mirror the immutable/revision-oriented parts of the SQL design.
They are deliberately persistence-agnostic; repository adapters own mapping to
rows and JSONB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from .errors import InvariantError
from .types import (
    AnswerStatus,
    DataStatus,
    JobStatus,
    MessageRole,
    MessageStatus,
    RunStatus,
    ValueKind,
    validate_bbox,
    validate_decimal_text,
)


@dataclass(slots=True)
class User:
    id: UUID
    email: str
    normalized_email: str
    password_hash: str
    display_name: str
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.normalized_email or not self.password_hash or not self.display_name.strip():
            raise InvariantError("user identity fields cannot be blank")


@dataclass(slots=True)
class Project:
    id: UUID
    owner_id: UUID
    name: str
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvariantError("project name cannot be blank")


@dataclass(slots=True)
class Document:
    id: UUID
    owner_id: UUID
    title: str
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise InvariantError("document title cannot be blank")


@dataclass(slots=True, frozen=True)
class ProjectDocument:
    owner_id: UUID
    project_id: UUID
    document_id: UUID


@dataclass(slots=True)
class ChatSource:
    id: UUID
    chat_id: UUID
    document_version_id: UUID
    extraction_run_id: UUID
    source_status: str = "active"

    def __post_init__(self) -> None:
        if self.source_status not in {"active", "inactive"}:
            raise InvariantError("invalid chat source status")


@dataclass(slots=True, frozen=True)
class MessagePin:
    id: UUID
    owner_id: UUID
    chat_id: UUID
    message_id: UUID
    answer_revision_id: UUID | None = None


@dataclass(slots=True)
class AuthSession:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass(slots=True)
class AccountToken:
    id: UUID
    user_id: UUID
    token_hash: str
    purpose: str
    expires_at: datetime
    used_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class JobEvent:
    id: UUID
    job_id: UUID
    event_no: int
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AuditEvent:
    id: UUID
    actor_id: UUID | None
    action: str
    target_type: str
    target_id: UUID | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RequestKey:
    owner_id: UUID
    route: str
    key: str
    request_hash: str
    response_status: int | None = None
    response: Mapping[str, Any] | None = None


@dataclass(slots=True)
class DocumentVersion:
    id: UUID
    owner_id: UUID
    document_id: UUID
    version_no: int
    file_name: str
    storage_key: str
    file_hash: str
    byte_size: int
    content_type: str = "application/pdf"
    status: str = "uploaded"
    page_count: int | None = None

    def __post_init__(self) -> None:
        if self.version_no <= 0 or self.byte_size <= 0:
            raise InvariantError("version_no and byte_size must be positive")
        if not self.file_name.strip() or not self.storage_key.strip():
            raise InvariantError("file_name and storage_key cannot be blank")


@dataclass(slots=True)
class ExtractionRun:
    id: UUID
    owner_id: UUID
    document_version_id: UUID
    run_no: int
    status: RunStatus = RunStatus.QUEUED
    extractor_name: str = "pending"
    extractor_version: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    input_data_revision: int = 0


@dataclass(slots=True)
class SourceRegion:
    id: UUID
    extraction_run_id: UUID
    region_key: str
    page_number: int
    region_type: str
    bbox: tuple[float, float, float, float] | None = None
    extracted_text: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.page_number <= 0 or not self.region_key.strip():
            raise InvariantError("region_key and page_number are required")
        if self.region_type not in {"paragraph", "table", "table_cell", "chart", "chart_element", "image", "other"}:
            raise InvariantError("invalid source region type")
        self.bbox = validate_bbox(self.bbox)


@dataclass(slots=True)
class ExtractedEvidence:
    id: UUID
    extraction_run_id: UUID
    source_region_id: UUID
    value_kind: ValueKind
    data_status: DataStatus
    semantic: dict[str, Any]
    raw_value: str | None = None
    raw_text: str | None = None
    extraction_method: str = "none"
    confidence: float | None = None

    def __post_init__(self) -> None:
        self.raw_value = validate_decimal_text(self.raw_value)
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise InvariantError("confidence must be between 0 and 1")
        if self.extraction_method not in {"direct_label", "axis_estimation", "text", "table", "ocr", "none"}:
            raise InvariantError("invalid extraction method")
        if self.data_status is DataStatus.VALID:
            if self.value_kind is ValueKind.NUMBER and (self.raw_value is None or self.raw_text is not None):
                raise InvariantError("valid number evidence requires raw_value only")
            if self.value_kind is ValueKind.TEXT and (self.raw_text is None or self.raw_value is not None):
                raise InvariantError("valid text evidence requires raw_text only")
        elif self.raw_value is not None or self.raw_text is not None:
            raise InvariantError("missing/error evidence cannot contain a value")


@dataclass(slots=True)
class Chat:
    id: UUID
    owner_id: UUID
    data_revision: int = 0
    next_sequence_no: int = 1
    deleted: bool = False

    def __post_init__(self) -> None:
        if self.data_revision < 0 or self.next_sequence_no <= 0:
            raise InvariantError("chat revision/sequence counters are invalid")


@dataclass(slots=True)
class ChatEvidence:
    id: UUID
    chat_id: UUID
    chat_source_id: UUID
    extracted_evidence_id: UUID
    extraction_run_id: UUID
    current_revision_id: UUID | None = None


@dataclass(slots=True, frozen=True)
class EvidenceRevision:
    id: UUID
    chat_evidence_id: UUID
    chat_id: UUID
    revision_no: int
    action: str
    verification_status: str
    value_kind: ValueKind
    data_status: DataStatus
    semantic: Mapping[str, Any]
    raw_value: str | None = None
    raw_text: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_decimal_text(self.raw_value)
        if self.revision_no <= 0:
            raise InvariantError("revision_no must be positive")
        if self.action not in {"initialize", "verify", "edit", "mark_error", "restore"}:
            raise InvariantError("invalid evidence revision action")
        if self.action in {"edit", "mark_error", "restore"} and not (self.reason or "").strip():
            raise InvariantError("reason is required for evidence revision action")
        if self.data_status is DataStatus.VALID:
            if self.value_kind is ValueKind.NUMBER and (self.raw_value is None or self.raw_text is not None):
                raise InvariantError("valid number revision requires raw_value only")
            if self.value_kind is ValueKind.TEXT and (self.raw_text is None or self.raw_value is not None):
                raise InvariantError("valid text revision requires raw_text only")
        elif self.raw_value is not None or self.raw_text is not None:
            raise InvariantError("missing/error revision cannot contain a value")


@dataclass(slots=True)
class Message:
    id: UUID
    chat_id: UUID
    sequence_no: int
    role: MessageRole
    body: str
    status: MessageStatus
    reply_to_message_id: UUID | None = None
    current_answer_revision_id: UUID | None = None
    needs_update: bool = False


@dataclass(slots=True, frozen=True)
class AnswerRevision:
    id: UUID
    message_id: UUID
    chat_id: UUID
    revision_no: int
    status: AnswerStatus
    input_data_revision: int
    structured_result: Mapping[str, Any]
    rendered_text: str
    question_context: Mapping[str, Any] = field(default_factory=dict)
    operation: Mapping[str, Any] | None = None
    assessment: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AnswerInput:
    answer_revision_id: UUID
    chat_id: UUID
    evidence_revision_id: UUID
    role: str = "operand"
    param_key: str = "value"


@dataclass(slots=True, frozen=True)
class AnswerScope:
    answer_revision_id: UUID
    chat_id: UUID
    chat_source_id: UUID
    measure_key: str
    subject_keys: tuple[str, ...]
    period_keys: tuple[str, ...]
    region_ids: tuple[UUID, ...]
    filter: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.measure_key.strip():
            raise InvariantError("answer scope measure_key cannot be blank")


@dataclass(slots=True)
class Job:
    id: UUID
    owner_id: UUID
    job_type: str
    status: JobStatus
    input_data_revision: int
    payload: dict[str, Any] = field(default_factory=dict)
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    idempotency_key: str | None = None
    attempts: int = 0
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.job_type not in {"extract_document", "answer_question", "recalculate_answer", "purge_resource"}:
            raise InvariantError("invalid job type")
        if self.input_data_revision < 0:
            raise InvariantError("job input_data_revision cannot be negative")
        if self.attempts < 0 or self.max_attempts <= 0 or self.attempts > self.max_attempts:
            raise InvariantError("job attempts/max_attempts are invalid")
