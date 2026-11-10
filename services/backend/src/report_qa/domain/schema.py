"""Machine-readable inventory of the 23 data-design tables.

This is deliberately metadata, not an ORM model. It lets code/tests assert
ownership and append-only policy before a SQLAlchemy mapping is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    owner_module: str
    append_only: bool = False
    requires_owner_scope: bool = False


TABLES: tuple[TableSpec, ...] = (
    TableSpec("users", "identity", requires_owner_scope=False),
    TableSpec("auth_sessions", "identity", requires_owner_scope=True),
    TableSpec("account_tokens", "identity", requires_owner_scope=True),
    TableSpec("projects", "library", requires_owner_scope=True),
    TableSpec("documents", "library", requires_owner_scope=True),
    TableSpec("document_versions", "library", requires_owner_scope=True),
    TableSpec("project_documents", "library", requires_owner_scope=True),
    TableSpec("extraction_runs", "extraction", requires_owner_scope=True),
    TableSpec("source_regions", "extraction", append_only=True, requires_owner_scope=True),
    TableSpec("extracted_evidences", "extraction", append_only=True, requires_owner_scope=True),
    TableSpec("chats", "conversation", requires_owner_scope=True),
    TableSpec("chat_sources", "conversation", requires_owner_scope=True),
    TableSpec("messages", "conversation", requires_owner_scope=True),
    TableSpec("message_pins", "conversation", requires_owner_scope=True),
    TableSpec("chat_evidences", "evidence", requires_owner_scope=True),
    TableSpec("evidence_revisions", "evidence", append_only=True, requires_owner_scope=True),
    TableSpec("answer_revisions", "answering", append_only=True, requires_owner_scope=True),
    TableSpec("answer_inputs", "answering", append_only=True, requires_owner_scope=True),
    TableSpec("answer_scopes", "answering", append_only=True, requires_owner_scope=True),
    TableSpec("jobs", "jobs", requires_owner_scope=True),
    TableSpec("job_events", "jobs", append_only=True, requires_owner_scope=True),
    TableSpec("audit_events", "audit", append_only=True, requires_owner_scope=False),
    TableSpec("request_keys", "identity", requires_owner_scope=True),
)


def table_names() -> tuple[str, ...]:
    return tuple(item.name for item in TABLES)


def validate_table_inventory(expected_count: int = 23) -> None:
    names = table_names()
    if len(names) != expected_count or len(set(names)) != len(names):
        raise RuntimeError("data-design table inventory is incomplete or duplicated")

