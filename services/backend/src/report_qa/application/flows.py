"""Application data-flow skeleton.

Each flow expresses the transaction boundary and fence checks described in
``doc/processing-flows.md``. Persistence is intentionally delegated to the
repository port; this module contains no SQL or provider SDK calls.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping
from uuid import UUID

from report_qa.application.ports import DataRepository
from report_qa.domain.errors import ConflictError, InvariantError, NotFoundError
from report_qa.domain.contracts import validate_provider_payload, validate_semantic_payload
from report_qa.domain.models import (
    AnswerInput,
    AnswerRevision,
    AnswerScope,
    ChatEvidence,
    ChatSource,
    DocumentVersion,
    EvidenceRevision,
    ExtractedEvidence,
    ExtractionRun,
    Job,
    Message,
    SourceRegion,
)
from report_qa.domain.types import (
    AnswerStatus,
    DataStatus,
    EvidenceAction,
    JobStatus,
    MessageRole,
    MessageStatus,
    RunStatus,
    ValueKind,
    require_unique,
    validate_bbox,
    validate_decimal_text,
)


def _request_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class UploadStarted:
    document_version_id: UUID
    extraction_run_id: UUID
    job_id: UUID


@dataclass(frozen=True, slots=True)
class QuestionAccepted:
    user_message_id: UUID
    assistant_message_id: UUID
    job_id: UUID


@dataclass(frozen=True, slots=True)
class EvidenceChanged:
    revision_id: UUID
    affected_message_ids: tuple[UUID, ...]
    recalculate_job_ids: tuple[UUID, ...]


class UploadFlow:
    def __init__(self, repo: DataRepository) -> None:
        self.repo = repo

    def start(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        file_name: str,
        file_hash: str,
        byte_size: int,
        content_type: str = "application/pdf",
        idempotency_key: str,
    ) -> UploadStarted:
        request_hash = _request_hash(
            {
                "document_id": document_id,
                "file_name": file_name,
                "file_hash": file_hash,
                "byte_size": byte_size,
                "content_type": content_type,
            }
        )
        cached = self.repo.get_request(owner_id, "POST /document-versions", idempotency_key, request_hash)
        if cached is not None:
            return cached
        with self.repo.transaction():
            if content_type != "application/pdf" or not file_name.lower().endswith(".pdf"):
                raise InvariantError("only application/pdf uploads are accepted")
            if byte_size <= 0 or not file_hash.strip():
                raise InvariantError("file_hash and positive byte_size are required")
            document = self.repo.get_document(document_id)
            if document is None or document.owner_id != owner_id or document.deleted_at is not None:
                raise NotFoundError("document not found")

            version_id = self.repo.ids.new_id()
            run_id = self.repo.ids.new_id()
            job_id = self.repo.ids.new_id()
            storage_key = f"owners/{owner_id}/documents/{document_id}/versions/{version_id}.pdf"
            version = DocumentVersion(
                id=version_id,
                owner_id=owner_id,
                document_id=document_id,
                version_no=self.repo.next_document_version_no(document_id),
                file_name=file_name,
                storage_key=storage_key,
                file_hash=file_hash,
                byte_size=byte_size,
                content_type=content_type,
            )
            run = ExtractionRun(
                id=run_id,
                owner_id=owner_id,
                document_version_id=version_id,
                run_no=self.repo.next_extraction_run_no(version_id),
                extractor_name="pending",
            )
            job = Job(
                id=job_id,
                owner_id=owner_id,
                job_type="extract_document",
                status=JobStatus.QUEUED,
                input_data_revision=0,
                payload={"document_version_id": str(version_id), "extraction_run_id": str(run_id)},
                idempotency_key=f"extract:{version_id}",
            )
            self.repo.save_document_version(version)
            self.repo.save_extraction_run(run)
            self.repo.add_job(job)
            result = UploadStarted(version_id, run_id, job_id)
            self.repo.put_request(owner_id, "POST /document-versions", idempotency_key, request_hash, result)
            return result


class ExtractionFlow:
    def __init__(self, repo: DataRepository) -> None:
        self.repo = repo

    def complete(
        self,
        *,
        extraction_run_id: UUID,
        regions: Iterable[Mapping[str, Any]],
        evidences: Iterable[Mapping[str, Any]],
        extractor_name: str,
        extractor_version: str | None = None,
    ) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
        try:
            with self.repo.transaction():
                return self._complete(
                    extraction_run_id=extraction_run_id,
                    regions=regions,
                    evidences=evidences,
                    extractor_name=extractor_name,
                    extractor_version=extractor_version,
                )
        except Exception:
            failed_run = self.repo.get_extraction_run(extraction_run_id)
            if failed_run is not None and failed_run.status is not RunStatus.COMPLETED:
                failed_run.status = RunStatus.FAILED
                self.repo.save_extraction_run(failed_run)
            raise

    def _complete(
        self,
        *,
        extraction_run_id: UUID,
        regions: Iterable[Mapping[str, Any]],
        evidences: Iterable[Mapping[str, Any]],
        extractor_name: str,
        extractor_version: str | None = None,
    ) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
        run = self.repo.get_extraction_run(extraction_run_id)
        if run is None:
            raise NotFoundError("extraction run not found")
        if run.status is RunStatus.COMPLETED:
            raise ConflictError("completed extraction runs are immutable")
        run.status = RunStatus.RUNNING
        run.extractor_name = extractor_name
        run.extractor_version = extractor_version
        self.repo.save_extraction_run(run)

        region_items = [dict(item) for item in regions]
        evidence_items = [dict(item) for item in evidences]
        try:
            validate_provider_payload(
                {
                    "schema_version": 1,
                    "regions": [
                        {
                            "region_key": item["region_key"],
                            "page_number": item["page_number"],
                            "bbox": item.get("bbox"),
                            "region_type": item["region_type"],
                            "text": item.get("text"),
                            "meta": item.get("meta", {}),
                        }
                        for item in region_items
                    ],
                    "evidences": [
                        {
                            "evidence_key": item.get("evidence_key", f"evidence-{index}"),
                            "source_region_key": item["source_region_key"],
                            "value_kind": item["value_kind"],
                            "raw_value": item.get("raw_value"),
                            "raw_text": item.get("raw_text"),
                            "semantic": item["semantic"],
                            "data_status": item["data_status"],
                            "extraction_method": item.get("extraction_method", "none"),
                            "confidence": item.get("confidence"),
                        }
                        for index, item in enumerate(evidence_items, start=1)
                    ],
                    "warnings": [],
                }
            )
            region_ids_by_key: dict[str, UUID] = {}
            staged_regions: dict[UUID, SourceRegion] = {}
            staged_evidences: dict[UUID, ExtractedEvidence] = {}
            created_region_ids: list[UUID] = []
            created_evidence_ids: list[UUID] = []
            for item in region_items:
                key = str(item["region_key"])
                if key in region_ids_by_key:
                    raise InvariantError("region_key must be unique per extraction run")
                region_id = self.repo.ids.new_id()
                region = SourceRegion(
                    id=region_id,
                    extraction_run_id=extraction_run_id,
                    region_key=key,
                    page_number=int(item["page_number"]),
                    region_type=str(item["region_type"]),
                    bbox=validate_bbox(item.get("bbox")),
                    extracted_text=item.get("text"),
                    meta=dict(item.get("meta", {})),
                )
                staged_regions[region_id] = region
                region_ids_by_key[key] = region_id
                created_region_ids.append(region_id)

            for item in evidence_items:
                region_id = region_ids_by_key.get(str(item["source_region_key"]))
                if region_id is None:
                    raise InvariantError("evidence must reference a region in the same run")
                evidence_id = self.repo.ids.new_id()
                evidence = ExtractedEvidence(
                    id=evidence_id,
                    extraction_run_id=extraction_run_id,
                    source_region_id=region_id,
                    value_kind=ValueKind(str(item["value_kind"])),
                    data_status=DataStatus(str(item["data_status"])),
                    semantic=dict(item["semantic"]),
                    raw_value=item.get("raw_value"),
                    raw_text=item.get("raw_text"),
                    extraction_method=str(item.get("extraction_method", "none")),
                    confidence=item.get("confidence"),
                )
                staged_evidences[evidence_id] = evidence
                created_evidence_ids.append(evidence_id)
        except Exception:
            run.status = RunStatus.FAILED
            self.repo.save_extraction_run(run)
            raise

        for region in staged_regions.values():
            self.repo.save_source_region(region)
        for evidence in staged_evidences.values():
            self.repo.save_extracted_evidence(evidence)

        run.status = RunStatus.COMPLETED
        version = self.repo.get_document_version(run.document_version_id)
        if version is None:
            run.status = RunStatus.FAILED
            self.repo.save_extraction_run(run)
            raise NotFoundError("document version not found")
        version.status = "ready"
        version.page_count = max((staged_regions[item].page_number for item in created_region_ids), default=1)
        self.repo.save_document_version(version)
        self.repo.save_extraction_run(run)
        return tuple(created_region_ids), tuple(created_evidence_ids)

    def attach_evidence(
        self,
        *,
        owner_id: UUID,
        chat_id: UUID,
        chat_source_id: UUID,
        extracted_evidence_id: UUID,
    ) -> ChatEvidence:
        evidence = self.repo.get_extracted_evidence(extracted_evidence_id)
        chat = self.repo.get_chat(chat_id)
        source = self.repo.get_chat_source(chat_source_id)
        run = self.repo.get_extraction_run(evidence.extraction_run_id) if evidence else None
        if evidence is None or chat is None or source is None or run is None:
            raise NotFoundError("chat or extracted evidence not found")
        if chat.owner_id != owner_id or source.chat_id != chat_id or source.extraction_run_id != evidence.extraction_run_id:
            raise NotFoundError("chat source not found")
        if run.owner_id != owner_id:
            raise NotFoundError("extraction run not found")
        if run.status is not RunStatus.COMPLETED:
            raise InvariantError("only completed extraction runs can be attached")
        chat_evidence = ChatEvidence(
            id=self.repo.ids.new_id(),
            chat_id=chat_id,
            chat_source_id=chat_source_id,
            extracted_evidence_id=extracted_evidence_id,
            extraction_run_id=evidence.extraction_run_id,
        )
        self.repo.save_chat_evidence(chat_evidence)
        revision = EvidenceRevision(
            id=self.repo.ids.new_id(),
            chat_evidence_id=chat_evidence.id,
            chat_id=chat_id,
            revision_no=1,
            action="initialize",
            verification_status="unverified",
            value_kind=evidence.value_kind,
            data_status=evidence.data_status,
            semantic=evidence.semantic,
            raw_value=evidence.raw_value,
            raw_text=evidence.raw_text,
        )
        self.repo.save_evidence_revision(revision)
        chat_evidence.current_revision_id = revision.id
        self.repo.save_chat_evidence(chat_evidence)
        return chat_evidence

    def switch_source(
        self,
        *,
        owner_id: UUID,
        chat_id: UUID,
        document_version_id: UUID,
        extraction_run_id: UUID,
        replaced_chat_source_id: UUID | None = None,
    ) -> ChatSource:
        """Activate a completed run while preserving unrelated active sources."""

        chat = self.repo.get_chat(chat_id)
        version = self.repo.get_document_version(document_version_id)
        run = self.repo.get_extraction_run(extraction_run_id)
        if chat is None or chat.owner_id != owner_id or version is None or version.owner_id != owner_id:
            raise NotFoundError("chat or document version not found")
        if run is None or run.document_version_id != document_version_id or run.owner_id != owner_id:
            raise NotFoundError("extraction run not found")
        if run.status is not RunStatus.COMPLETED:
            raise InvariantError("only completed extraction runs can be selected")
        if replaced_chat_source_id is not None:
            replaced = self.repo.get_chat_source(replaced_chat_source_id)
            if replaced is None or replaced.chat_id != chat_id:
                raise NotFoundError("source to replace not found")
            replaced.source_status = "inactive"
            self.repo.save_chat_source(replaced)
        source = ChatSource(
            id=self.repo.ids.new_id(),
            chat_id=chat_id,
            document_version_id=document_version_id,
            extraction_run_id=extraction_run_id,
            source_status="active",
        )
        self.repo.save_chat_source(source)
        chat.data_revision += 1
        self.repo.save_chat(chat)
        return source


class QuestionFlow:
    def __init__(self, repo: DataRepository) -> None:
        self.repo = repo

    def submit(self, *, owner_id: UUID, chat_id: UUID, question: str, idempotency_key: str) -> QuestionAccepted:
        request_hash = _request_hash({"chat_id": chat_id, "question": question})
        cached = self.repo.get_request(owner_id, "POST /chats/{chat_id}/messages", idempotency_key, request_hash)
        if cached is not None:
            return cached
        chat = self.repo.get_chat(chat_id)
        if chat is None or chat.owner_id != owner_id or chat.deleted:
            raise NotFoundError("chat not found")
        if not question.strip():
            raise InvariantError("question cannot be blank")
        with self.repo.transaction():
            user_id = self.repo.ids.new_id()
            assistant_id = self.repo.ids.new_id()
            job_id = self.repo.ids.new_id()
            user_message = Message(user_id, chat_id, chat.next_sequence_no, MessageRole.USER, question, MessageStatus.ACCEPTED)
            chat.next_sequence_no += 1
            assistant = Message(
                assistant_id,
                chat_id,
                chat.next_sequence_no,
                MessageRole.ASSISTANT,
                "",
                MessageStatus.PROCESSING,
                reply_to_message_id=user_id,
            )
            chat.next_sequence_no += 1
            self.repo.save_message(user_message)
            self.repo.save_message(assistant)
            self.repo.save_chat(chat)
            job = Job(
                id=job_id,
                owner_id=owner_id,
                job_type="answer_question",
                status=JobStatus.QUEUED,
                input_data_revision=chat.data_revision,
                payload={"chat_id": str(chat_id), "message_id": str(assistant_id), "question": question},
                idempotency_key=f"answer:{chat_id}:{user_id}",
            )
            self.repo.add_job(job)
            result = QuestionAccepted(user_id, assistant_id, job_id)
            self.repo.put_request(owner_id, "POST /chats/{chat_id}/messages", idempotency_key, request_hash, result)
            return result


class EvidenceFlow:
    def __init__(self, repo: DataRepository) -> None:
        self.repo = repo

    def apply_revision(
        self,
        *,
        owner_id: UUID,
        chat_evidence_id: UUID,
        expected_revision_id: UUID,
        action: EvidenceAction,
        value_kind: ValueKind,
        data_status: DataStatus,
        semantic: Mapping[str, Any],
        raw_value: str | None = None,
        raw_text: str | None = None,
        reason: str | None = None,
    ) -> EvidenceChanged:
        with self.repo.transaction():
            return self._apply_revision(
                owner_id=owner_id,
                chat_evidence_id=chat_evidence_id,
                expected_revision_id=expected_revision_id,
                action=action,
                value_kind=value_kind,
                data_status=data_status,
                semantic=semantic,
                raw_value=raw_value,
                raw_text=raw_text,
                reason=reason,
            )

    def _apply_revision(
        self,
        *,
        owner_id: UUID,
        chat_evidence_id: UUID,
        expected_revision_id: UUID,
        action: EvidenceAction,
        value_kind: ValueKind,
        data_status: DataStatus,
        semantic: Mapping[str, Any],
        raw_value: str | None = None,
        raw_text: str | None = None,
        reason: str | None = None,
    ) -> EvidenceChanged:
        item = self.repo.get_chat_evidence(chat_evidence_id)
        chat = self.repo.get_chat(item.chat_id) if item else None
        if item is None or chat is None or chat.owner_id != owner_id:
            raise NotFoundError("chat evidence not found")
        if item.current_revision_id != expected_revision_id:
            raise ConflictError("current evidence revision differs from expected_revision_id")
        if action in {EvidenceAction.EDIT, EvidenceAction.MARK_ERROR, EvidenceAction.RESTORE} and not (reason or "").strip():
            raise InvariantError("reason is required for this evidence action")
        validate_decimal_text(raw_value)
        validate_semantic_payload(semantic)
        revision_no = len(self.repo.revisions_for_evidence(chat_evidence_id)) + 1
        revision = EvidenceRevision(
            id=self.repo.ids.new_id(),
            chat_evidence_id=chat_evidence_id,
            chat_id=chat.id,
            revision_no=revision_no,
            action=action.value,
            verification_status="verified" if action is EvidenceAction.VERIFY else "edited",
            value_kind=value_kind,
            data_status=data_status,
            semantic=dict(semantic),
            raw_value=raw_value,
            raw_text=raw_text,
            reason=reason,
        )
        self.repo.save_evidence_revision(revision)
        item.current_revision_id = revision.id
        chat.data_revision += 1
        self.repo.save_chat_evidence(item)
        self.repo.save_chat(chat)

        affected: list[UUID] = []
        jobs: list[UUID] = []
        for message in self.repo.messages_for_chat(chat.id):
            if message.role is not MessageRole.ASSISTANT or message.current_answer_revision_id is None:
                continue
            answer_id = message.current_answer_revision_id
            direct = any(
                link.answer_revision_id == answer_id and link.evidence_revision_id == expected_revision_id
                for link in self.repo.answer_inputs_for(answer_id)
            )
            scoped = any(
                scope.answer_revision_id == answer_id and scope.chat_source_id == item.chat_source_id
                for scope in self.repo.answer_scopes_for(answer_id)
            )
            if direct or scoped:
                message.needs_update = True
                self.repo.save_message(message)
                affected.append(message.id)
                dedup = f"recalculate:{message.id}:{chat.data_revision}"
                job = self.repo.find_job_by_dedup(dedup)
                if job is None:
                    job = Job(
                        id=self.repo.ids.new_id(),
                        owner_id=owner_id,
                        job_type="recalculate_answer",
                        status=JobStatus.QUEUED,
                        input_data_revision=chat.data_revision,
                        payload={"chat_id": str(chat.id), "message_id": str(message.id)},
                        idempotency_key=dedup,
                    )
                    self.repo.add_job(job)
                jobs.append(job.id)
        return EvidenceChanged(revision.id, tuple(affected), tuple(jobs))


class AnswerFlow:
    def __init__(self, repo: DataRepository) -> None:
        self.repo = repo

    def publish(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        status: AnswerStatus,
        structured_result: Mapping[str, Any],
        rendered_text: str,
        evidence_revision_ids: Iterable[UUID] = (),
        scopes: Iterable[Mapping[str, Any]] = (),
        question_context: Mapping[str, Any] | None = None,
        operation: Mapping[str, Any] | None = None,
        assessment: Mapping[str, Any] | None = None,
    ) -> AnswerRevision:
        with self.repo.transaction():
            return self._publish(
                job_id=job_id,
                lease_token=lease_token,
                status=status,
                structured_result=structured_result,
                rendered_text=rendered_text,
                evidence_revision_ids=evidence_revision_ids,
                scopes=scopes,
                question_context=question_context,
                operation=operation,
                assessment=assessment,
            )

    def _publish(
        self,
        *,
        job_id: UUID,
        lease_token: str,
        status: AnswerStatus,
        structured_result: Mapping[str, Any],
        rendered_text: str,
        evidence_revision_ids: Iterable[UUID] = (),
        scopes: Iterable[Mapping[str, Any]] = (),
        question_context: Mapping[str, Any] | None = None,
        operation: Mapping[str, Any] | None = None,
        assessment: Mapping[str, Any] | None = None,
    ) -> AnswerRevision:
        job = self.repo.get_job(job_id)
        if job is None or job.job_type not in {"answer_question", "recalculate_answer"}:
            raise NotFoundError("answer job not found")
        if job.status is not JobStatus.RUNNING or job.lease_token != lease_token or (job.lease_expires_at is not None and job.lease_expires_at <= self.repo.clock.now()):
            raise ConflictError("job lease is not valid")
        chat_id = UUID(job.payload["chat_id"])
        message_id = UUID(job.payload["message_id"])
        chat = self.repo.get_chat(chat_id)
        message = self.repo.get_message(message_id)
        if chat is None or message is None:
            raise NotFoundError("answer target not found")
        if message.chat_id != chat_id or message.role is not MessageRole.ASSISTANT:
            raise InvariantError("answer job must target an assistant message in the same chat")
        if chat.data_revision != job.input_data_revision:
            job.status = JobStatus.SUPERSEDED
            raise ConflictError("answer input_data_revision is stale")
        if not isinstance(rendered_text, str) or not rendered_text.strip():
            raise InvariantError("rendered_text cannot be blank")
        evidence_id_values = tuple(UUID(item) for item in require_unique((str(item) for item in evidence_revision_ids), "evidence_revision_ids"))
        scope_values = tuple(dict(scope) for scope in scopes)
        for evidence_revision_id in evidence_id_values:
            evidence_revision = self.repo.get_evidence_revision(evidence_revision_id)
            if evidence_revision is None or evidence_revision.chat_id != chat_id:
                raise InvariantError("answer input evidence must belong to the same chat")
        for scope in scope_values:
            scope_chat_source_id = UUID(str(scope["chat_source_id"]))
            source = self.repo.get_chat_source(scope_chat_source_id)
            if source is None or source.chat_id != chat_id:
                raise InvariantError("answer scope source must belong to the same chat")
        revision_no = self.repo.answer_revision_count(message_id) + 1
        revision = AnswerRevision(
            id=self.repo.ids.new_id(),
            message_id=message_id,
            chat_id=chat_id,
            revision_no=revision_no,
            status=status,
            input_data_revision=job.input_data_revision,
            structured_result=dict(structured_result),
            rendered_text=rendered_text,
            question_context=dict(question_context or {}),
            operation=dict(operation) if operation else None,
            assessment=dict(assessment or {}),
        )
        self.repo.save_answer_revision(revision)
        for evidence_revision_id in evidence_id_values:
            self.repo.add_answer_input(AnswerInput(revision.id, chat_id, evidence_revision_id))
        for scope in scope_values:
            scope_chat_source_id = UUID(str(scope["chat_source_id"]))
            self.repo.add_answer_scope(
                AnswerScope(
                answer_revision_id=revision.id,
                chat_id=chat_id,
                chat_source_id=scope_chat_source_id,
                measure_key=str(scope["measure_key"]),
                subject_keys=tuple(scope.get("subject_keys", ())),
                period_keys=tuple(scope.get("period_keys", ())),
                region_ids=tuple(UUID(str(item)) for item in scope.get("region_ids", ())),
                filter=dict(scope.get("filter", {})),
                )
            )
        message.current_answer_revision_id = revision.id
        message.status = MessageStatus.COMPLETED
        message.needs_update = False
        self.repo.save_message(message)
        job.status = JobStatus.SUCCEEDED
        job.lease_expires_at = None
        self.repo.add_job(job)
        self.repo.add_job_event(job_id, "succeeded")
        return revision
