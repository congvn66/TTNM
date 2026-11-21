from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5


class DomainError(RuntimeError):
    pass


class NotFound(DomainError):
    pass


class RevisionConflict(DomainError):
    pass


class IdempotencyConflict(DomainError):
    pass


class InvalidState(DomainError):
    pass


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class ReferenceFlow:
    """In-memory executable specification, not production application code."""

    def __init__(self, seed: dict[str, Any]):
        self.data = copy.deepcopy(seed)
        self._counter = 0

    @classmethod
    def from_file(cls, path: Path) -> "ReferenceFlow":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def new_id(self, label: str) -> str:
        self._counter += 1
        return str(uuid5(NAMESPACE_URL, f"reference-flow:{label}:{self._counter}"))

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self.data[table]

    def by_id(self, table: str, row_id: str) -> dict[str, Any]:
        row = next((item for item in self.rows(table) if item.get("id") == row_id), None)
        if row is None:
            raise NotFound(f"{table}:{row_id}")
        return row

    def owned_chat(self, owner_id: str, chat_id: str) -> dict[str, Any]:
        chat = self.by_id("chats", chat_id)
        if chat["owner_id"] != owner_id:
            raise NotFound(f"chats:{chat_id}")
        return chat

    def submit_question(self, owner_id: str, chat_id: str, content: str, key: str) -> dict[str, Any]:
        chat = self.owned_chat(owner_id, chat_id)
        route = "POST /api/v1/chats/{id}/messages"
        request_hash = canonical_hash({"chat_id": chat_id, "content": content})
        existing = next((row for row in self.rows("request_keys") if row["owner_id"] == owner_id and row["route"] == route and row["key"] == key), None)
        if existing:
            if existing["request_hash"] != request_hash:
                raise IdempotencyConflict(key)
            return copy.deepcopy(existing["response"])

        sequence = chat["next_sequence_no"]
        user_message_id = self.new_id("user-message")
        assistant_message_id = self.new_id("assistant-message")
        job_id = self.new_id("answer-job")
        common = {"chat_id": chat_id, "needs_update": False, "created_at": "runtime"}
        self.rows("messages").extend(
            [
                {"id": user_message_id, "role": "user", "content": content, "reply_to_message_id": None, "sequence_no": sequence, "status": "accepted", "current_answer_revision_id": None, **common},
                {"id": assistant_message_id, "role": "assistant", "content": "", "reply_to_message_id": user_message_id, "sequence_no": sequence + 1, "status": "processing", "current_answer_revision_id": None, **common},
            ]
        )
        chat["next_sequence_no"] += 2
        response = {"user_message_id": user_message_id, "assistant_message_id": assistant_message_id, "job_id": job_id, "input_data_revision": chat["data_revision"]}
        self.rows("jobs").append(
            {"id": job_id, "owner_id": owner_id, "chat_id": chat_id, "kind": "answer_question", "dedup_key": f"answer:{assistant_message_id}:{chat['data_revision']}", "status": "queued", "input_data_revision": chat["data_revision"], "payload": {"schema_version": 1, "message_id": assistant_message_id}, "result": None, "attempts": 0, "max_attempts": 3, "created_at": "runtime"}
        )
        self.rows("request_keys").append(
            {"owner_id": owner_id, "route": route, "key": key, "request_hash": request_hash, "response_status": 202, "response": copy.deepcopy(response), "created_at": "runtime", "expires_at": "runtime+72h"}
        )
        return response

    def current_revision(self, chat_evidence_id: str) -> dict[str, Any]:
        evidence = self.by_id("chat_evidences", chat_evidence_id)
        return self.by_id("evidence_revisions", evidence["current_revision_id"])

    def edit_evidence(
        self,
        owner_id: str,
        chat_evidence_id: str,
        expected_revision_id: str,
        new_value: str | None,
        reason: str,
        *,
        action: str = "edit",
    ) -> dict[str, Any]:
        if action in {"edit", "mark_error", "restore"} and not reason.strip():
            raise InvalidState("reason_required")
        chat_evidence = self.by_id("chat_evidences", chat_evidence_id)
        chat = self.owned_chat(owner_id, chat_evidence["chat_id"])
        if chat_evidence["current_revision_id"] != expected_revision_id:
            raise RevisionConflict(chat_evidence["current_revision_id"])
        previous = self.by_id("evidence_revisions", expected_revision_id)
        siblings = [row for row in self.rows("evidence_revisions") if row["chat_evidence_id"] == chat_evidence_id]
        revision_id = self.new_id("evidence-revision")
        missing = new_value is None
        revision = {
            **copy.deepcopy(previous),
            "id": revision_id,
            "revision_no": max(row["revision_no"] for row in siblings) + 1,
            "numeric_value": None if missing else str(new_value),
            "text_value": None,
            "data_status": "missing" if missing else "valid",
            "verification_status": "edited" if action != "verify" else "verified",
            "action": action,
            "reason": reason,
            "created_by": owner_id,
            "created_at": "runtime",
        }
        self.rows("evidence_revisions").append(revision)
        chat_evidence["current_revision_id"] = revision_id
        chat["data_revision"] += 1

        affected_messages: list[str] = []
        jobs: list[str] = []
        semantic = revision["semantic"]
        measure_key = semantic["measure"]["code"]
        for message in self.rows("messages"):
            answer_id = message.get("current_answer_revision_id")
            if message["chat_id"] != chat["id"] or not answer_id:
                continue
            direct = any(row["answer_revision_id"] == answer_id and row["evidence_revision_id"] == expected_revision_id for row in self.rows("answer_inputs"))
            scoped = any(
                row["answer_revision_id"] == answer_id
                and row["chat_source_id"] == chat_evidence["chat_source_id"]
                and row["filter"].get("measure_key") == measure_key
                for row in self.rows("answer_scopes")
            )
            if not (direct or scoped):
                continue
            message["needs_update"] = True
            affected_messages.append(message["id"])
            job_id = self.new_id("recalculate-job")
            dedup_key = f"recalculate:{message['id']}:{chat['data_revision']}"
            if not any(row["dedup_key"] == dedup_key for row in self.rows("jobs")):
                self.rows("jobs").append(
                    {"id": job_id, "owner_id": owner_id, "chat_id": chat["id"], "kind": "recalculate_answer", "dedup_key": dedup_key, "status": "queued", "input_data_revision": chat["data_revision"], "payload": {"schema_version": 1, "message_id": message["id"]}, "result": None, "attempts": 0, "max_attempts": 3, "created_at": "runtime"}
                )
                jobs.append(job_id)
        return {"revision_id": revision_id, "chat_data_revision": chat["data_revision"], "affected_message_ids": affected_messages, "job_ids": jobs}

    def restore_evidence(self, owner_id: str, chat_evidence_id: str, expected_revision_id: str, restore_revision_id: str, reason: str) -> dict[str, Any]:
        target = self.by_id("evidence_revisions", restore_revision_id)
        if target["chat_evidence_id"] != chat_evidence_id:
            raise InvalidState("restore_revision_wrong_parent")
        return self.edit_evidence(owner_id, chat_evidence_id, expected_revision_id, target["numeric_value"], reason, action="restore")

    def run_recalculation(self, job_id: str) -> dict[str, Any] | None:
        job = self.by_id("jobs", job_id)
        if job["kind"] != "recalculate_answer" or job["status"] not in {"queued", "running"}:
            raise InvalidState("job_not_recalculable")
        chat = self.by_id("chats", job["chat_id"])
        if chat["data_revision"] != job["input_data_revision"]:
            job["status"] = "superseded"
            return None
        message = self.by_id("messages", job["payload"]["message_id"])
        current_answer = self.by_id("answer_revisions", message["current_answer_revision_id"])
        scopes = [row for row in self.rows("answer_scopes") if row["answer_revision_id"] == current_answer["id"]]
        if not scopes:
            raise InvalidState("answer_scope_missing")
        scope = scopes[0]
        values: dict[tuple[str, str], tuple[Decimal, str]] = {}
        candidate_subjects: set[str] = set()
        for ce in self.rows("chat_evidences"):
            if ce["chat_id"] != chat["id"] or ce["chat_source_id"] != scope["chat_source_id"]:
                continue
            revision = self.current_revision(ce["id"])
            sem = revision["semantic"]
            if sem["measure"]["code"] != scope["filter"]["measure_key"]:
                continue
            subject = sem.get("subject")
            period = sem.get("period", {}).get("label")
            if subject and period in scope["filter"]["period_keys"]:
                candidate_subjects.add(subject["label"])
            if revision["data_status"] != "valid" or revision["value_kind"] != "number":
                continue
            if subject and period in scope["filter"]["period_keys"]:
                values[(subject["label"], period)] = (Decimal(revision["numeric_value"]), revision["id"])

        rates: dict[str, Decimal] = {}
        input_rows: list[tuple[str, str]] = []
        incomplete_subjects: list[str] = []
        for subject in sorted(candidate_subjects):
            q1 = values.get((subject, "Quý 1"))
            q3 = values.get((subject, "Quý 3"))
            if not q1 or not q3 or q1[0] == 0:
                incomplete_subjects.append(subject)
                continue
            rates[subject] = (q3[0] - q1[0]) / q1[0] * Decimal("100")
            key = subject.upper().replace(" ", "_")
            input_rows.extend(((q1[1], f"{key}_Q1"), (q3[1], f"{key}_Q3")))
        if not rates or incomplete_subjects:
            result = {"schema_version": 1, "defined": False, "reason": "incomplete_comparison_group", "incomplete_subjects": incomplete_subjects, "partial_rates": {subject: decimal_text(rate) for subject, rate in sorted(rates.items())}, "winner_subjects": []}
            answer_status = "insufficient_data"
        else:
            best = max(rates.values())
            winners = sorted(subject for subject, rate in rates.items() if rate == best)
            result = {"schema_version": 1, "defined": True, "winner_subjects": winners, "value": decimal_text(best), "rates": {subject: decimal_text(rate) for subject, rate in sorted(rates.items())}}
            answer_status = "answered"

        revisions = [row for row in self.rows("answer_revisions") if row["message_id"] == message["id"]]
        answer_id = self.new_id("answer-revision")
        answer = {
            **copy.deepcopy(current_answer),
            "id": answer_id,
            "revision_no": max(row["revision_no"] for row in revisions) + 1,
            "answer_status": answer_status,
            "result": result,
            "answer_text": "Kết quả đã được tính lại.",
            "input_data_revision": chat["data_revision"],
            "created_at": "runtime",
        }
        self.rows("answer_revisions").append(answer)
        for revision_id, param_key in input_rows:
            self.rows("answer_inputs").append({"answer_revision_id": answer_id, "evidence_revision_id": revision_id, "chat_id": chat["id"], "role": "comparison_group", "param_key": param_key, "created_at": "runtime"})
        self.rows("answer_scopes").append({**copy.deepcopy(scope), "id": self.new_id("answer-scope"), "answer_revision_id": answer_id, "created_at": "runtime"})
        message["current_answer_revision_id"] = answer_id
        message["needs_update"] = False
        message["status"] = "completed"
        job["status"] = "succeeded"
        job["result"] = {"answer_revision_id": answer_id}
        return answer

    def switch_source(self, owner_id: str, chat_id: str, document_version_id: str, extraction_run_id: str) -> str:
        chat = self.owned_chat(owner_id, chat_id)
        run = self.by_id("extraction_runs", extraction_run_id)
        if run["document_version_id"] != document_version_id or run["status"] != "completed":
            raise InvalidState("source_not_ready")
        for source in self.rows("chat_sources"):
            if source["chat_id"] == chat_id and source["source_status"] == "active":
                source["source_status"] = "inactive"
                source["deactivated_at"] = "runtime"
        source_id = self.new_id("chat-source")
        self.rows("chat_sources").append({"id": source_id, "chat_id": chat_id, "document_version_id": document_version_id, "extraction_run_id": extraction_run_id, "source_status": "active", "added_at": "runtime", "deactivated_at": None})
        chat["data_revision"] += 1
        return source_id
