"""Runtime catalog adapter for the PostgreSQL persistence cutover.

The HTTP API still exposes the small dictionary-shaped MVP contract.  This
adapter keeps that contract at the edge while making PostgreSQL the source of
truth for sessions/chats, document metadata, extraction/evidence revisions,
messages, answer snapshots and idempotency responses.

PDF bytes and extraction JSON remain on the configured local filesystem until
the object-storage milestone is enabled.  Their immutable storage keys are
recorded in PostgreSQL so a later storage adapter can migrate them safely.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4, uuid5

from .revision_store import PostgresRevisionStore


RUNTIME_NAMESPACE = UUID("00000000-0000-0000-0000-000000000001")


class PostgresRuntimeStore(PostgresRevisionStore):
    """Bridge the legacy dictionary API to the normalized revision graph."""

    def __init__(self, database_url: str, owner_id: str | UUID, *, extraction_root: Path | None = None) -> None:
        super().__init__(database_url)
        self.owner_id = UUID(str(owner_id))
        self.extraction_root = extraction_root

    @staticmethod
    def _uuid(value: str | UUID) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))

    @staticmethod
    def _owner_matches(session_owner: str | UUID | None, owner_id: str | UUID) -> bool:
        """Compare catalog values safely across JSON-string and UUID forms."""
        return str(session_owner) == str(owner_id)

    @staticmethod
    def _iso(value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return str(value) if value is not None else datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json_obj(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _number(value: Any) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def _document_version_id(document_id: UUID, record: dict[str, Any]) -> UUID:
        value = record.get("version_id")
        return UUID(str(value)) if value else uuid5(document_id, "version-1")

    @staticmethod
    def _run_id(version_id: UUID) -> UUID:
        return uuid5(version_id, "extraction-run-1")

    def load_catalog(self) -> dict[str, Any]:
        rows = self._execute(
            """SELECT id,project_id,title,created_at,updated_at,data_revision
                 FROM chats
                WHERE owner_id=%s AND deleted_at IS NULL
                ORDER BY updated_at DESC""",
            (self.owner_id,),
        )
        sessions: dict[str, Any] = {}
        for row in rows:
            sessions[str(row["id"])] = {
                "id": str(row["id"]),
                "project_id": str(row["project_id"]) if row.get("project_id") else None,
                "owner_id": str(self.owner_id),
                "title": row["title"],
                "created_at": self._iso(row["created_at"]),
                "updated_at": self._iso(row["updated_at"]),
                "data_revision": int(row["data_revision"] or 0),
                "documents": [],
                "messages": [],
                "request_keys": {},
            }
        if not sessions:
            return {"sessions": sessions}
        session_ids = [UUID(identifier) for identifier in sessions]
        document_rows = self._execute(
            """SELECT cd.chat_id, d.id AS document_id, d.created_at AS document_created_at,
                      dv.id AS version_id,
                      dv.file_name, dv.storage_key, dv.file_hash, dv.byte_size,
                      dv.page_count, dv.status AS version_status,
                      er.status AS extraction_status, er.error_code AS extraction_error,
                      (SELECT count(*) FROM extracted_evidences ee
                        WHERE ee.extraction_run_id=er.id) AS evidence_count
                 FROM chat_documents cd
                 JOIN document_versions dv ON dv.id=cd.document_version_id
                 JOIN documents d ON d.id=dv.document_id
                 LEFT JOIN LATERAL (
                     SELECT status,error_code,id FROM extraction_runs
                      WHERE document_version_id=dv.id AND scope='base_document'
                      ORDER BY run_no DESC LIMIT 1
                 ) er ON TRUE
                WHERE cd.chat_id = ANY(%s) AND d.deleted_at IS NULL
                ORDER BY cd.updated_at DESC""",
            (session_ids,),
        )
        for item in document_rows:
            session = sessions.get(str(item["chat_id"]))
            if session is None:
                continue
            session["documents"].append(
                {
                    "id": str(item["document_id"]),
                    "version_id": str(item["version_id"]),
                    "file_name": item["file_name"],
                    "byte_size": int(item["byte_size"]),
                    "sha256": item["file_hash"],
                    "status": "stored",
                    "created_at": self._iso(item["document_created_at"]),
                    "storage_name": item["storage_key"],
                    "extraction_name": f"{item['version_id']}.json",
                    "extraction_status": "ready" if item["extraction_status"] == "completed" else "processing" if item["extraction_status"] == "running" else item["extraction_status"] or ("ready" if item["version_status"] == "ready" else "queued"),
                    "page_count": item["page_count"],
                    "numeric_evidence_count": int(item["evidence_count"] or 0),
                    "extraction_error": item["extraction_error"],
                }
            )
        return {"sessions": sessions}

    def load_session(self, chat_id: UUID | str, *, row: dict[str, Any] | None = None) -> dict[str, Any] | None:
        # One connection for all of its queries: a new one per query costs ~0.4 s each to Supabase.
        with self.transaction():
            return self._load_session(chat_id, row=row)

    def _load_session(self, chat_id: UUID | str, *, row: dict[str, Any] | None = None) -> dict[str, Any] | None:
        chat_uuid = self._uuid(chat_id)
        if row is None:
            rows = self._execute(
                """SELECT id,project_id,title,created_at,updated_at,data_revision
                     FROM chats WHERE id=%s AND owner_id=%s AND deleted_at IS NULL""",
                (chat_uuid, self.owner_id),
            )
            if not rows:
                return None
            row = rows[0]
        session: dict[str, Any] = {
            "id": str(row["id"]),
            "project_id": str(row["project_id"]) if row.get("project_id") else None,
            "owner_id": str(self.owner_id),
            "title": row["title"],
            "created_at": self._iso(row["created_at"]),
            "updated_at": self._iso(row["updated_at"]),
            "data_revision": int(row["data_revision"] or 0),
            "documents": [],
            "messages": [],
            "request_keys": {},
        }
        document_rows = self._execute(
            """SELECT DISTINCT ON (d.id)
                        d.id AS document_id, d.title, d.created_at,
                        dv.id AS version_id, dv.file_name, dv.storage_key,
                        dv.file_hash, dv.byte_size, dv.status AS version_status,
                        dv.page_count, er.id AS extraction_run_id,
                        er.status AS extraction_status, er.error_code AS extraction_error,
                        (SELECT count(*) FROM extracted_evidences ee WHERE ee.extraction_run_id=er.id) AS evidence_count
                   FROM chat_documents cd
                   JOIN document_versions dv ON dv.id=cd.document_version_id
                   JOIN documents d ON d.id=dv.document_id
                   LEFT JOIN LATERAL (
                       SELECT id,status,error_code FROM extraction_runs
                        WHERE document_version_id=dv.id AND scope='base_document'
                        ORDER BY run_no DESC LIMIT 1
                   ) er ON TRUE
                  WHERE cd.chat_id=%s AND d.deleted_at IS NULL
                  ORDER BY d.id, dv.version_no DESC""",
            (chat_uuid,),
        )
        for item in document_rows:
            version_id = item["version_id"]
            document_id = item["document_id"]
            extraction_status = "ready" if item["extraction_status"] == "completed" else "processing" if item["extraction_status"] == "running" else item["extraction_status"] or ("ready" if item["version_status"] == "ready" else "queued")
            extraction_name = f"{version_id}.json"
            if self.extraction_root:
                target_path = self.extraction_root / extraction_name
                legacy_path = self.extraction_root / f"{document_id}.json"
                if not target_path.exists() and legacy_path.exists():
                    legacy_path.replace(target_path)
            document = {
                "id": str(document_id),
                "version_id": str(version_id),
                "file_name": item["file_name"],
                "byte_size": int(item["byte_size"]),
                "sha256": item["file_hash"],
                "status": "stored",
                "created_at": self._iso(item.get("created_at")),
                "storage_name": item["storage_key"],
                "extraction_name": extraction_name,
                "extraction_status": extraction_status,
                "page_count": item["page_count"],
                "numeric_evidence_count": int(item["evidence_count"] or 0),
                "extraction_error": item["extraction_error"],
            }
            document["evidence_state"] = self._load_evidence_state(chat_uuid, document_id)
            document["chart_extractions"] = self._load_chart_extractions(chat_uuid, version_id)
            session["documents"].append(document)

        message_rows = self._execute(
            """SELECT id,role,content,reply_to_message_id,sequence_no,status,
                        needs_update,created_at,updated_at,current_answer_revision_id
                   FROM messages WHERE chat_id=%s ORDER BY sequence_no""",
            (chat_uuid,),
        )
        messages_by_id: dict[str, dict[str, Any]] = {}
        for item in message_rows:
            message = {
                "id": str(item["id"]),
                "role": item["role"],
                "body": item["content"],
                "reply_to_message_id": str(item["reply_to_message_id"]) if item["reply_to_message_id"] else None,
                "created_at": self._iso(item["created_at"]),
                "status": item["status"],
                "needs_update": bool(item["needs_update"]),
            }
            revision_id = item["current_answer_revision_id"]
            if item["role"] == "assistant" and revision_id:
                revision_rows = self._execute(
                    """SELECT id,revision_no,answer_status,question_context,operation,
                                result,answer_text,assessment,input_data_revision,created_at
                           FROM answer_revisions
                          WHERE id=%s AND chat_id=%s""",
                    (revision_id, chat_uuid),
                )
                if revision_rows:
                    revision = revision_rows[0]
                    question_context = self._json_obj(revision["question_context"])
                    result = self._json_obj(revision["result"])
                    assessment = self._json_obj(revision["assessment"])
                    answer_inputs = list(result.get("answer_inputs") or [])
                    message.update(
                        {
                            "document_id": question_context.get("document_id"),
                            "mode": assessment.get("mode"),
                            "citations": assessment.get("citations", []),
                            "trace_id": assessment.get("trace_id"),
                            "trace": assessment.get("trace", []),
                            "question_plan": question_context.get("question_plan"),
                            "calculation_result": result.get("calculation_result"),
                            "structured_answer": result.get("structured_answer"),
                            "answer_inputs": answer_inputs,
                            "current_answer_revision_id": str(revision["id"]),
                            "answer_revisions": [
                                {
                                    "id": str(revision["id"]),
                                    "revision_no": int(revision["revision_no"]),
                                    "created_at": self._iso(revision["created_at"]),
                                    "answer_text": revision["answer_text"],
                                    "status": revision["answer_status"],
                                    "question_plan": question_context.get("question_plan"),
                                    "calculation_result": result.get("calculation_result"),
                                    "answer_inputs": answer_inputs,
                                }
                            ],
                        }
                    )
            messages_by_id[message["id"]] = message
            session["messages"].append(message)
        for item in message_rows:
            if item["role"] != "user":
                continue
            message = messages_by_id.get(str(item["id"]))
            if message and message["role"] == "user":
                # The document ID is stored in the paired assistant revision.
                paired = next((m for m in session["messages"] if m.get("role") == "assistant" and m.get("reply_to_message_id") == message["id"]), None)
                if paired:
                    message["document_id"] = paired.get("document_id")
        request_rows = self._execute(
            """SELECT route,key,request_hash,response FROM request_keys
                WHERE owner_id=%s AND expires_at > now()""",
            (self.owner_id,),
        )
        for item in request_rows:
            session["request_keys"][item["key"]] = {
                "request_hash": item["request_hash"],
                "response": item["response"],
                "created_at": self._iso(item.get("created_at")),
                "route": item["route"],
            }
        return session

    def _load_chart_extractions(self, chat_id: UUID, version_id: UUID) -> list[dict[str, Any]]:
        """Chart reads made by the tools assistant, oldest first."""
        rows = self._execute(
            """SELECT er.config->'chart_record' AS chart_record
                 FROM extraction_runs er
                 JOIN chat_sources cs ON cs.extraction_run_id=er.id
                WHERE cs.chat_id=%s AND er.document_version_id=%s
                  AND er.scope='on_demand_chart' AND er.status='completed'
                  AND er.config ? 'chart_record'
                ORDER BY er.run_no""",
            (chat_id, version_id),
        )
        return [dict(row["chart_record"]) for row in rows]

    def load_evidence_state(self, chat_id: UUID | str, document_id: UUID | str) -> dict[str, Any]:
        return self._load_evidence_state(self._uuid(chat_id), self._uuid(document_id))

    def _load_evidence_state(self, chat_id: UUID, document_id: UUID) -> dict[str, Any]:
        rows = self._execute(
            """SELECT ce.id AS chat_evidence_id,
                        sr.meta->>'evidence_key' AS evidence_key,
                        ce.current_revision_id,
                        ee.raw_value::text AS original_value,
                        rev.id AS revision_id, rev.revision_no, rev.action,
                        rev.numeric_value::text AS numeric_value, rev.text_value,
                        rev.reason, rev.created_at
                   FROM chat_evidences ce
                   JOIN chat_sources cs ON cs.id=ce.chat_source_id
                   JOIN extracted_evidences ee ON ee.id=ce.extracted_evidence_id
                   JOIN source_regions sr ON sr.id=ee.source_region_id
                   JOIN evidence_revisions rev ON rev.chat_evidence_id=ce.id
                  WHERE ce.chat_id=%s AND cs.document_version_id IN
                        (SELECT id FROM document_versions WHERE document_id=%s)
                  ORDER BY sr.meta->>'evidence_key', rev.revision_no""",
            (chat_id, document_id),
        )
        state = {"data_revision": 0, "items": {}, "event_count": 0}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        metadata: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row["evidence_key"])
            grouped[key].append(row)
            metadata[key] = row
        for key, history_rows in grouped.items():
            revisions: list[dict[str, Any]] = []
            previous: str | None = None
            for revision in history_rows:
                value = revision["numeric_value"] if revision["numeric_value"] is not None else revision["text_value"]
                revisions.append(
                    {
                        "id": str(revision["revision_id"]),
                        "revision_no": int(revision["revision_no"]),
                        "action": revision["action"],
                        "created_at": self._iso(revision["created_at"]),
                        "numeric_value": value,
                        "old_numeric_value": None,
                        "previous_revision_id": previous,
                        "reason": revision["reason"],
                    }
                )
                previous = str(revision["revision_id"])
            for index in range(1, len(revisions)):
                revisions[index]["old_numeric_value"] = revisions[index - 1]["numeric_value"]
            row = metadata[key]
            state["items"][key] = {
                "evidence_key": key,
                "original_numeric_value": self._number(row["original_value"]),
                "current_revision_id": str(row["current_revision_id"]),
                "revisions": revisions,
            }
            state["data_revision"] = max(state["data_revision"], len(revisions) - 1)
        return state

    def sync_catalog(
        self,
        catalog: dict[str, Any],
        *,
        extraction_loader: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> None:
        """Persist the current API projection in one DB transaction."""
        with self.transaction():
            self.ensure_owner(self.owner_id, email="local-runtime@sourcelens.invalid", display_name="Local runtime")
            # The API process cache can contain sessions for more than one
            # authenticated owner.  Never replay another owner's snapshot
            # through this owner-scoped store during a save.
            for session in (catalog.get("sessions") or {}).values():
                # Runtime snapshots store owner_id as a string while the
                # store is initialized with a UUID.  Comparing the two
                # directly made every session get skipped during catalog
                # synchronization, so freshly-created sessions appeared in
                # the response and disappeared on the next refresh.
                if not self._owner_matches(session.get("owner_id"), self.owner_id):
                    continue
                self._sync_session(session, extraction_loader=extraction_loader)

    def rename_chat(self, chat_id: UUID | str, title: str) -> bool:
        """Rename an owner-scoped chat without replaying the API cache."""
        with self.transaction():
            self._execute(
                """UPDATE chats SET title=%s,updated_at=now()
                   WHERE id=%s AND owner_id=%s AND deleted_at IS NULL""",
                (title, self._uuid(chat_id), self.owner_id),
            )
            rows = self._execute(
                "SELECT 1 FROM chats WHERE id=%s AND owner_id=%s AND deleted_at IS NULL",
                (self._uuid(chat_id), self.owner_id),
            )
        return bool(rows)

    def archive_chat(self, chat_id: UUID | str) -> bool:
        """Soft-delete a chat. Documents and answer history remain recoverable."""
        with self.transaction():
            self._execute(
                """UPDATE chats SET deleted_at=now(),updated_at=now()
                   WHERE id=%s AND owner_id=%s AND deleted_at IS NULL""",
                (self._uuid(chat_id), self.owner_id),
            )
            rows = self._execute(
                "SELECT 1 FROM chats WHERE id=%s AND owner_id=%s AND deleted_at IS NOT NULL",
                (self._uuid(chat_id), self.owner_id),
            )
        return bool(rows)

    def rename_document(self, chat_id: UUID | str, document_id: UUID | str, file_name: str) -> bool:
        """Rename only a document that belongs to this chat and owner."""
        chat_uuid, document_uuid = self._uuid(chat_id), self._uuid(document_id)
        with self.transaction():
            self._execute(
                """UPDATE documents d SET title=%s,updated_at=now()
                     WHERE d.id=%s AND d.owner_id=%s AND d.deleted_at IS NULL
                       AND EXISTS (
                         SELECT 1 FROM chat_documents cd
                         JOIN document_versions dv ON dv.id=cd.document_version_id
                         WHERE cd.chat_id=%s AND dv.document_id=d.id
                       )""",
                (file_name, document_uuid, self.owner_id, chat_uuid),
            )
            self._execute(
                """UPDATE document_versions SET file_name=%s
                     WHERE document_id=%s AND EXISTS (
                       SELECT 1 FROM chat_documents cd
                       JOIN document_versions linked ON linked.id=cd.document_version_id
                       WHERE cd.chat_id=%s AND linked.document_id=%s
                     )""",
                (file_name, document_uuid, chat_uuid, document_uuid),
            )
            rows = self._execute(
                """SELECT 1 FROM documents d WHERE d.id=%s AND d.owner_id=%s
                   AND d.deleted_at IS NULL""",
                (document_uuid, self.owner_id),
            )
        return bool(rows)

    def archive_document(self, chat_id: UUID | str, document_id: UUID | str) -> bool:
        """Soft-delete a document after proving its chat ownership relation."""
        chat_uuid, document_uuid = self._uuid(chat_id), self._uuid(document_id)
        with self.transaction():
            self._execute(
                """UPDATE documents d SET deleted_at=now(),updated_at=now()
                     WHERE d.id=%s AND d.owner_id=%s AND d.deleted_at IS NULL
                       AND EXISTS (
                         SELECT 1 FROM chat_documents cd
                         JOIN document_versions dv ON dv.id=cd.document_version_id
                         WHERE cd.chat_id=%s AND dv.document_id=d.id
                       )""",
                (document_uuid, self.owner_id, chat_uuid),
            )
            rows = self._execute(
                """SELECT 1 FROM documents d WHERE d.id=%s AND d.owner_id=%s
                   AND d.deleted_at IS NOT NULL""",
                (document_uuid, self.owner_id),
            )
        return bool(rows)

    # A save can replay a snapshot loaded minutes ago (a slow answer job), so it
    # must not write what has its own endpoint: title, project and deletion of a
    # chat, name and deletion of a document.
    def _sync_session(self, session: dict[str, Any], *, extraction_loader: Callable[[dict[str, Any]], dict[str, Any] | None] | None) -> None:
        chat_id = self._uuid(session["id"])
        project_id = self._uuid(session["project_id"]) if session.get("project_id") else None
        if project_id is None:
            canonical_name = "Workspace " + chr(0x00E1) + " nh" + chr(0x00E2) + "n"
            canonical = self._execute(
                "SELECT id FROM projects WHERE owner_id=%s AND name=%s AND deleted_at IS NULL ORDER BY created_at LIMIT 1",
                (self.owner_id, canonical_name),
            )
            project_id = canonical[0]["id"] if canonical else self._execute(
                """INSERT INTO projects (owner_id,name) VALUES (%s,%s)
                   ON CONFLICT (owner_id,name) WHERE deleted_at IS NULL
                   DO UPDATE SET updated_at=projects.updated_at
                   RETURNING id""",
                (self.owner_id, canonical_name),
            )[0]["id"]
            session["project_id"] = str(project_id)
        if project_id is None:
            default = self._execute("SELECT id FROM projects WHERE owner_id=%s AND name='Workspace cá nhân' AND deleted_at IS NULL ORDER BY created_at LIMIT 1", (self.owner_id,))
            project_id = default[0]["id"] if default else self._execute("INSERT INTO projects (owner_id,name) VALUES (%s,%s) RETURNING id", (self.owner_id, "Workspace cá nhân"))[0]["id"]
            session["project_id"] = str(project_id)
        self._execute(
            """INSERT INTO chats (id,owner_id,project_id,title,data_revision,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 project_id=COALESCE(chats.project_id, EXCLUDED.project_id),
                 data_revision=GREATEST(chats.data_revision, EXCLUDED.data_revision),
                 updated_at=EXCLUDED.updated_at""",
            (chat_id, self.owner_id, project_id, str(session.get("title") or "Phiên phân tích mới"), int(session.get("data_revision") or 0), session.get("created_at") or datetime.now(timezone.utc), session.get("updated_at") or datetime.now(timezone.utc)),
        )
        for document in session.get("documents", []):
            version_id, run_id = self._sync_document(chat_id, document)
            artifact = extraction_loader(document) if extraction_loader and document.get("extraction_status") == "ready" else None
            if artifact is not None:
                run_rows = self._execute("SELECT status FROM extraction_runs WHERE id=%s", (run_id,))
                if not run_rows or run_rows[0]["status"] != "completed":
                    self._complete_extraction(chat_id, version_id, run_id, document, artifact)
            self._sync_evidence_state(chat_id, document)
            display_name = str(document.get("file_name") or document.get("title") or "Tài liệu chưa đặt tên")
            self._execute("""INSERT INTO project_documents (owner_id,project_id,document_id,display_name)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (project_id,document_id) DO UPDATE
                    SET display_name=COALESCE(project_documents.display_name, EXCLUDED.display_name)""",
                (self.owner_id, project_id, UUID(str(document["id"])), display_name))
        self._sync_messages(chat_id, session.get("messages", []))
        for key, item in (session.get("request_keys") or {}).items():
            route = str(item.get("route") or "POST /api/v1/sessions/messages")
            self._execute(
                """INSERT INTO request_keys (owner_id,route,key,request_hash,response,expires_at)
                   VALUES (%s,%s,%s,%s,%s::jsonb,now()+interval '24 hours')
                   ON CONFLICT (owner_id,route,key) DO UPDATE SET request_hash=EXCLUDED.request_hash,response=EXCLUDED.response,expires_at=EXCLUDED.expires_at""",
                (self.owner_id, route, key, item.get("request_hash", ""), self._json(item.get("response", {}))),
            )

    def _sync_document(self, chat_id: UUID, document: dict[str, Any]) -> tuple[UUID, UUID]:
        document_id = self._uuid(document["id"])
        version_id = self._document_version_id(document_id, document)
        run_id = self._run_id(version_id)
        document["version_id"] = str(version_id)
        extraction_name = f"{version_id}.json"
        legacy_extraction_name = document.get("extraction_name")
        if self.extraction_root and legacy_extraction_name and legacy_extraction_name != extraction_name:
            legacy_path = self.extraction_root / str(legacy_extraction_name)
            target_path = self.extraction_root / extraction_name
            if legacy_path.exists() and not target_path.exists():
                legacy_path.replace(target_path)
        document["extraction_name"] = extraction_name
        version_status = {
            "queued": "uploaded",
            "processing": "processing",
            "ready": "ready",
            "failed": "failed",
        }.get(str(document.get("extraction_status") or "queued"), "uploaded")
        persisted_page_count = document.get("page_count")
        if version_status == "failed" and not persisted_page_count:
            # Baseline schema requires a diagnostic page_count for failed
            # versions too; one is a conservative sentinel, not a claim that
            # extraction succeeded.
            persisted_page_count = 1
        self._execute(
            """INSERT INTO documents (id,owner_id,title,created_at,updated_at,deleted_at)
               VALUES (%s,%s,%s,%s,%s,NULL)
               ON CONFLICT (id) DO UPDATE SET updated_at=EXCLUDED.updated_at""",
            (document_id, self.owner_id, str(document.get("file_name") or "document.pdf"), document.get("created_at") or datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )
        self._execute(
            """INSERT INTO document_versions (id,document_id,version_no,file_name,storage_key,file_hash,byte_size,content_type,page_count,status)
               VALUES (%s,%s,1,%s,%s,%s,%s,'application/pdf',%s,%s)
               ON CONFLICT (id) DO UPDATE SET storage_key=EXCLUDED.storage_key,
                 file_hash=EXCLUDED.file_hash,byte_size=EXCLUDED.byte_size,page_count=EXCLUDED.page_count,status=EXCLUDED.status""",
            (version_id, document_id, str(document.get("file_name") or "document.pdf"), str(document.get("storage_name") or f"{document_id}.pdf"), str(document.get("sha256") or "unknown"), int(document.get("byte_size") or 1), persisted_page_count, version_status),
        )
        self._execute(
            """INSERT INTO extraction_runs
                      (id,document_version_id,run_no,status,extractor_name,contract_name,contract_version,scope,started_at)
               VALUES (%s,%s,1,%s,'legacy_pdf_artifact','document-evidence',1,'base_document',now())
               ON CONFLICT (id) DO NOTHING""",
            (run_id, version_id, "queued"),
        )
        if version_status == "failed":
            self._execute("UPDATE extraction_runs SET status='failed',completed_at=now(),error_code=%s WHERE id=%s", (document.get("extraction_error") or "EXTRACTION_FAILED", run_id))
        elif version_status == "processing":
            self._execute("UPDATE extraction_runs SET status='running',started_at=now(),completed_at=NULL,error_code=NULL WHERE id=%s AND status <> 'completed'", (run_id,))
        chat_status = "queued" if version_status == "uploaded" else version_status
        self._execute(
            """INSERT INTO chat_documents (chat_id,document_version_id,status,error_code)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (chat_id,document_version_id) DO UPDATE SET status=EXCLUDED.status,error_code=EXCLUDED.error_code,updated_at=now()""",
            (chat_id, version_id, chat_status, document.get("extraction_error")),
        )
        # The schema trigger intentionally allows chat_sources only after an
        # extraction run is completed.  A freshly uploaded document is visible
        # immediately; `_complete_extraction` attaches the source only after
        # it has marked the run completed.  Doing it here would violate the
        # trigger because the run is still queued during this sync pass.
        return version_id, run_id

    def _ensure_chat_source(self, chat_id: UUID, version_id: UUID, run_id: UUID) -> None:
        self._execute(
            """INSERT INTO chat_sources (id,chat_id,document_version_id,extraction_run_id,source_status)
               VALUES (%s,%s,%s,%s,'active')
               ON CONFLICT (chat_id,extraction_run_id) DO UPDATE SET source_status='active',deactivated_at=NULL""",
            (uuid5(chat_id, f"source:{run_id}"), chat_id, version_id, run_id),
        )

    def _complete_extraction(self, chat_id: UUID, version_id: UUID, run_id: UUID, document: dict[str, Any], artifact: dict[str, Any]) -> None:
        existing = self._execute("SELECT 1 FROM extracted_evidences WHERE extraction_run_id=%s LIMIT 1", (run_id,))
        if not existing:
            # The text of each paragraph, so a number read from it can be shown and checked in its sentence.
            for paragraph in artifact.get("paragraphs") or []:
                self._execute(
                    """INSERT INTO source_regions (id,extraction_run_id,region_key,page_number,bbox,region_type,extracted_text,meta)
                       VALUES (%s,%s,%s,%s,%s::jsonb,'paragraph',%s,%s::jsonb)
                       ON CONFLICT (extraction_run_id,region_key) DO NOTHING""",
                    (uuid5(run_id, f"region:{paragraph['paragraph_key']}"), run_id, paragraph["paragraph_key"], int(paragraph["page_number"]),
                     self._json(paragraph["bbox"]), paragraph["text"], self._json({"label": paragraph.get("label")})),
                )
            for item in (artifact.get("evidence_batch") or {}).get("evidences", []):
                # One region per value. Two numbers in one text span used to
                # share a region, which names a single evidence_key: the second
                # number was loaded under the first one's key.
                region_key = item["evidence_key"]
                region_id, evidence_id = uuid5(run_id, f"region:{region_key}"), uuid5(run_id, f"evidence:{item['evidence_key']}")
                region_type = "table_cell" if item.get("source_type") == "table" else "chart_element" if item.get("source_type") == "chart" else "paragraph"
                self._execute(
                    """INSERT INTO source_regions (id,extraction_run_id,region_key,page_number,bbox,region_type,extracted_text,meta)
                       VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)
                       ON CONFLICT (extraction_run_id,region_key) DO NOTHING""",
                    (region_id, run_id, region_key, int(item["page_number"]), self._json(item.get("bbox")), region_type, item.get("raw_text"), self._json({"evidence_key": item["evidence_key"], "source_region_key": item.get("source_region_key"), "method_label": item.get("method_label"), "table_locator": item.get("table_locator"), "paragraph_locator": item.get("paragraph_locator"), "chart_read": item.get("chart_read")})),
                )
                numeric = item.get("numeric_value")
                method = str(item.get("extraction_method") or "text")
                source_type = str(item.get("source_type") or "text")
                # ``numeric_value=null`` does not mean that an evidence item is
                # textual: an unreadable/ambiguous table or chart number is
                # still a numeric operand candidate, just not a usable one.
                value_kind = str(item.get("value_kind") or (
                    "number" if numeric is not None or source_type in {"table", "chart"} else "text"
                ))
                if value_kind not in {"number", "text"}:
                    raise ValueError("INVALID_EVIDENCE_VALUE_KIND")
                data_status = str(item.get("data_status") or "valid")
                self._execute(
                    """INSERT INTO extracted_evidences (id,extraction_run_id,source_region_id,value_kind,raw_value,raw_text,semantic,data_status,extraction_method,confidence)
                       VALUES (%s,%s,%s,%s,%s::numeric,%s,%s::jsonb,%s,%s,%s)
                       ON CONFLICT (id) DO NOTHING""",
                    (evidence_id, run_id, region_id, value_kind, numeric if value_kind == "number" else None, item.get("raw_text") if value_kind == "text" else None, self._json(item.get("semantic") or {}), data_status, self._db_method(item.get("extraction_method", "text")), item.get("confidence")),
                )
        # Extraction payload rows are immutable after completion, so mark the
        # run completed only after all regions/evidences have been inserted.
        self._execute(
            """UPDATE extraction_runs SET status='completed',completed_at=COALESCE(completed_at,now()),error_code=NULL
               WHERE id=%s""",
            (run_id,),
        )
        self._execute("UPDATE document_versions SET status='ready',page_count=%s WHERE id=%s", (int(document.get("page_count") or len(artifact.get("pages", [])) or 1), version_id))
        self._ensure_chat_source(chat_id, version_id, run_id)
        source_rows = self._execute(
            "SELECT id FROM chat_sources WHERE chat_id=%s AND extraction_run_id=%s",
            (chat_id, run_id),
        )
        if source_rows:
            self.initialize_chat_evidence(self.owner_id, chat_id, source_rows[0]["id"])

    def persist_on_demand_chart(
        self,
        *,
        chat_id: UUID,
        document_version_id: UUID,
        evidence_batch: dict[str, Any],
        question_plan_id: str,
        chart_record: dict[str, Any] | None = None,
    ) -> dict[str, UUID]:
        """Persist chart evidence as an immutable, chat-visible extraction run.

        Chart reading is deliberately lazy, but its result is not ephemeral: the
        answer and its citations must reference real ``evidence_revisions``.  A
        retry with the same extraction-run id is idempotent and returns the
        existing revision ids.
        """
        if not evidence_batch or evidence_batch.get("schema_version") != 2:
            raise ValueError("INVALID_CHART_EVIDENCE_BATCH")
        if str(evidence_batch.get("document_version_id")) != str(document_version_id):
            raise ValueError("CHART_DOCUMENT_VERSION_MISMATCH")
        evidences = evidence_batch.get("evidences") or []
        if not evidences:
            return {}
        try:
            run_id = UUID(str(evidence_batch["extraction_run_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("INVALID_CHART_EXTRACTION_RUN_ID") from exc
        scope = str(evidence_batch.get("scope") or "on_demand_chart")
        trigger = dict(evidence_batch.get("trigger") or {})
        trigger.setdefault("question_plan_id", question_plan_id)
        trigger.setdefault("chart_region_keys", [])
        if scope != "on_demand_chart" or not isinstance(trigger.get("chart_region_keys"), list):
            raise ValueError("INVALID_CHART_TRIGGER")
        dedup_payload = {
            "document_version_id": str(document_version_id),
            "question_plan_id": str(trigger.get("question_plan_id")),
            "fact_keys": sorted(str(item) for item in trigger.get("fact_keys", [])),
            "chart_region_keys": sorted(str(item) for item in trigger.get("chart_region_keys", [])),
        }
        input_sha256 = __import__("hashlib").sha256(self._json(dedup_payload).encode("utf-8")).hexdigest()

        with self.transaction():
            owner_rows = self._execute(
                """SELECT dv.id
                     FROM document_versions dv
                     JOIN documents d ON d.id=dv.document_id
                     JOIN chat_documents cd ON cd.document_version_id=dv.id
                    WHERE dv.id=%s AND cd.chat_id=%s AND d.owner_id=%s AND d.deleted_at IS NULL
                    FOR UPDATE""",
                (document_version_id, chat_id, self.owner_id),
            )
            if not owner_rows:
                raise PermissionError("DOCUMENT_NOT_FOUND")
            existing_dedup = self._execute(
                """SELECT id FROM extraction_runs
                    WHERE document_version_id=%s AND scope='on_demand_chart'
                      AND input_sha256=%s AND status='completed'
                    ORDER BY created_at DESC LIMIT 1""",
                (document_version_id, input_sha256),
            )
            if existing_dedup:
                dedup_run_id = existing_dedup[0]["id"]
                self._ensure_chat_source(chat_id, document_version_id, dedup_run_id)
                source_rows = self._execute(
                    "SELECT id FROM chat_sources WHERE chat_id=%s AND extraction_run_id=%s",
                    (chat_id, dedup_run_id),
                )
                if not source_rows:
                    raise RuntimeError("CHART_SOURCE_NOT_ATTACHED")
                return self.initialize_chat_evidence(self.owner_id, chat_id, source_rows[0]["id"])
            # A point read by an earlier question already has a working copy in
            # this chat, perhaps corrected. Reuse it: a second copy under the
            # same key would mix two histories.
            known_revisions = {
                str(row["evidence_key"]): row["current_revision_id"]
                for row in self._execute(
                    """SELECT sr.meta->>'evidence_key' AS evidence_key, ce.current_revision_id
                         FROM chat_evidences ce
                         JOIN chat_sources cs ON cs.id=ce.chat_source_id
                         JOIN extracted_evidences ee ON ee.id=ce.extracted_evidence_id
                         JOIN source_regions sr ON sr.id=ee.source_region_id
                        WHERE ce.chat_id=%s AND cs.document_version_id=%s AND sr.meta->>'evidence_key' = ANY(%s)""",
                    (chat_id, document_version_id, [str(item.get("evidence_key")) for item in evidences]),
                )
            }
            existing = self._execute(
                "SELECT id FROM extraction_runs WHERE id=%s AND document_version_id=%s",
                (run_id, document_version_id),
            )
            if not existing:
                run_no = int(
                    self._execute(
                        "SELECT COALESCE(MAX(run_no),0)+1 AS value FROM extraction_runs WHERE document_version_id=%s",
                        (document_version_id,),
                    )[0]["value"]
                )
                self._execute(
                    """INSERT INTO extraction_runs
                           (id,document_version_id,run_no,status,extractor_name,extractor_version,
                            contract_name,contract_version,scope,trigger,input_sha256,tool_meta,
                            config,started_at,completed_at)
                       VALUES (%s,%s,%s,'running','chart_reader','v1',
                               'document-evidence','2',%s,%s::jsonb,%s,%s::jsonb,
                               %s::jsonb,now(),NULL)""",
                    (
                        run_id,
                        document_version_id,
                        run_no,
                        scope,
                        self._json(trigger),
                        input_sha256,
                        self._json({"reader": "vector_or_deplot", "question_plan_id": question_plan_id}),
                        self._json({"scope": scope, "question_plan_id": question_plan_id, **({"chart_record": chart_record} if chart_record else {})}),
                    ),
                )
                for item in evidences:
                    if str(item.get("evidence_key")) in known_revisions:
                        continue
                    evidence_key = str(item.get("evidence_key") or "")
                    if not evidence_key:
                        raise ValueError("CHART_EVIDENCE_KEY_REQUIRED")
                    region_id = uuid5(run_id, f"region:{evidence_key}")
                    evidence_id = uuid5(run_id, f"evidence:{evidence_key}")
                    self._execute(
                        """INSERT INTO source_regions
                               (id,extraction_run_id,region_key,page_number,bbox,region_type,extracted_text,meta)
                           VALUES (%s,%s,%s,%s,%s::jsonb,'chart_element',%s,%s::jsonb)
                           ON CONFLICT (id) DO NOTHING""",
                        (
                            region_id,
                            run_id,
                            # One chart yields several points that share a
                            # source_region_key; (run, region_key) is unique.
                            evidence_key,
                            int(item["page_number"]),
                            self._json(item.get("bbox")),
                            item.get("raw_text"),
                            self._json(
                                {
                                    "evidence_key": evidence_key,
                                    "source_region_key": item.get("source_region_key"),
                                    "method_label": item.get("method_label"),
                                    "chart_read": item.get("chart_read"),
                                    "question_plan_id": question_plan_id,
                                }
                            ),
                        ),
                    )
                    numeric = item.get("numeric_value")
                    value_kind = str(item.get("value_kind") or "number")
                    if value_kind != "number":
                        raise ValueError("CHART_EVIDENCE_MUST_BE_NUMERIC")
                    data_status = str(item.get("data_status") or "valid")
                    if data_status not in {"valid", "missing", "unreadable", "ambiguous", "error"}:
                        raise ValueError("INVALID_CHART_DATA_STATUS")
                    self._execute(
                        """INSERT INTO extracted_evidences
                               (id,extraction_run_id,source_region_id,value_kind,raw_value,raw_text,
                                semantic,data_status,extraction_method,confidence)
                           VALUES (%s,%s,%s,'number',%s::numeric,NULL,%s::jsonb,%s,%s,%s)
                           ON CONFLICT (id) DO NOTHING""",
                        (
                            evidence_id,
                            run_id,
                            region_id,
                            numeric if data_status == "valid" else None,
                            self._json(item.get("semantic") or {}),
                            data_status,
                            self._db_method(str(item.get("extraction_method") or "axis_estimation")),
                            item.get("confidence"),
                        ),
                    )
                # Payload rows are immutable once the run is completed, so
                # complete it only after every region and value is inserted.
                self._execute(
                    "UPDATE extraction_runs SET status='completed',completed_at=now() WHERE id=%s",
                    (run_id,),
                )
                self._ensure_chat_source(chat_id, document_version_id, run_id)
            else:
                # A retry may arrive after a client timeout.  It must not create
                # a second run or a second working copy in the chat.
                self._ensure_chat_source(chat_id, document_version_id, run_id)
            source_rows = self._execute(
                "SELECT id FROM chat_sources WHERE chat_id=%s AND extraction_run_id=%s",
                (chat_id, run_id),
            )
            if not source_rows:
                raise RuntimeError("CHART_SOURCE_NOT_ATTACHED")
            return {**known_revisions, **self.initialize_chat_evidence(self.owner_id, chat_id, source_rows[0]["id"])}

    def _sync_evidence_state(self, chat_id: UUID, document: dict[str, Any]) -> None:
        state = document.get("evidence_state") or {}
        for evidence_key, item in (state.get("items") or {}).items():
            # Initial working copies are created by `_complete_extraction`.
            # There is nothing to sync until this item carries an edit or a
            # later revision, which avoids one round-trip per untouched value
            # on every message/save request.
            revisions = item.get("revisions") or []
            if not any(revision.get("action") != "initialize" for revision in revisions):
                continue
            rows = self._execute(
                """SELECT ce.id,ce.current_revision_id
                     FROM chat_evidences ce JOIN chat_sources cs ON cs.id=ce.chat_source_id
                     JOIN source_regions sr ON sr.id=(SELECT source_region_id FROM extracted_evidences WHERE id=ce.extracted_evidence_id)
                    WHERE ce.chat_id=%s AND sr.meta->>'evidence_key'=%s""",
                (chat_id, evidence_key),
            )
            if not rows:
                continue
            current_id = str(rows[0]["current_revision_id"])
            for revision in revisions:
                if str(revision.get("id")) == current_id or revision.get("action") == "initialize":
                    continue
                try:
                    revision_id = self._uuid(revision["id"])
                except (ValueError, TypeError):
                    continue
                exists = self._execute("SELECT 1 FROM evidence_revisions WHERE id=%s", (revision_id,))
                if exists:
                    current_id = str(revision_id)
                    continue
                revision_no = int(revision.get("revision_no") or 1)
                numeric = revision.get("numeric_value")
                self._execute(
                    """INSERT INTO evidence_revisions (id,chat_id,chat_evidence_id,revision_no,value_kind,numeric_value,semantic,data_status,verification_status,action,reason,created_by)
                       VALUES (%s,%s,%s,%s,'number',%s::numeric,'{}'::jsonb,'valid','edited','edit',%s,%s)""",
                    (revision_id, chat_id, rows[0]["id"], revision_no, numeric, revision.get("reason") or "Edited in API", self.owner_id),
                )
                self._execute("UPDATE chat_evidences SET current_revision_id=%s WHERE id=%s", (revision_id, rows[0]["id"]))
                current_id = str(revision_id)

    def _sync_messages(self, chat_id: UUID, messages: list[dict[str, Any]]) -> None:
        for index, assistant in enumerate(messages):
            if assistant.get("role") != "assistant":
                continue
            try:
                assistant_id = self._uuid(assistant["id"])
            except (ValueError, TypeError):
                continue
            user = messages[index - 1] if index and messages[index - 1].get("role") == "user" else None
            if not user:
                continue
            try:
                user_id = self._uuid(user["id"])
            except (ValueError, TypeError):
                continue
            exists = self._execute("SELECT id,status,current_answer_revision_id FROM messages WHERE id=%s AND chat_id=%s", (assistant_id, chat_id))
            is_processing = assistant.get("status") == "processing" or (not assistant.get("status") and assistant.get("mode") == "answer_question_job")
            revision = (assistant.get("answer_revisions") or [{}])[0]
            try:
                revision_id = self._uuid(revision.get("id"))
            except (ValueError, TypeError):
                revision_id = uuid5(assistant_id, "answer-revision-1")
            question_plan = assistant.get("question_plan") or {}
            status = "processing" if is_processing else "needs_clarification" if assistant.get("mode") == "question_clarification" else "insufficient_data" if assistant.get("mode") == "question_unsupported" else "processing_error" if assistant.get("status") == "failed" else "answered"
            metadata = {
                "mode": assistant.get("mode"),
                "trace_id": assistant.get("trace_id"),
                "trace": assistant.get("trace", []),
                "citations": assistant.get("citations", []),
            }
            result = {
                "structured_answer": assistant.get("structured_answer"),
                "calculation_result": assistant.get("calculation_result"),
                "answer_inputs": assistant.get("answer_inputs", []),
            }
            if exists:
                if is_processing:
                    if exists[0].get("status") in {"completed", "failed"}:
                        continue
                    self._execute("UPDATE messages SET content=%s,status='processing',needs_update=%s,updated_at=now() WHERE id=%s AND status='processing'", (assistant.get("body", ""), bool(assistant.get("needs_update")), assistant_id))
                    continue
                current_revision = exists[0].get("current_answer_revision_id")
                incoming_id = revision_id
                incoming_exists = self._execute("SELECT 1 FROM answer_revisions WHERE id=%s", (incoming_id,))
                if not incoming_exists:
                    max_revision = self._execute("SELECT COALESCE(MAX(revision_no),0) AS value FROM answer_revisions WHERE message_id=%s", (assistant_id,))[0]["value"]
                    self._execute(
                        """INSERT INTO answer_revisions (id,chat_id,message_id,revision_no,answer_status,question_context,operation,result,answer_text,assessment,input_data_revision)
                           VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)""",
                        (incoming_id, chat_id, assistant_id, int(max_revision) + 1, status, self._json({"document_id": assistant.get("document_id"), "question_plan": question_plan}), self._json(question_plan.get("operation") or {}), self._json(result), assistant.get("body", ""), self._json(metadata), 0),
                    )
                    for operand_index, operand in enumerate(assistant.get("answer_inputs") or []):
                        try:
                            evidence_revision_id = self._uuid(operand.get("evidence_revision_id"))
                        except (ValueError, TypeError):
                            continue
                        self._execute("INSERT INTO answer_inputs (answer_revision_id,evidence_revision_id,chat_id,role,param_key) VALUES (%s,%s,%s,'operand',%s) ON CONFLICT DO NOTHING", (incoming_id, evidence_revision_id, chat_id, f"operand_{operand_index + 1}"))
                elif status == "processing_error":
                    # Revisions are immutable: record the failure as a new one,
                    # once, and keep it when this snapshot is saved again.
                    current = self._execute("SELECT answer_status FROM answer_revisions WHERE id=%s", (current_revision,)) if current_revision else []
                    if current and current[0]["answer_status"] == "processing_error":
                        incoming_id = current_revision
                    else:
                        incoming_id = uuid4()
                        max_revision = self._execute("SELECT COALESCE(MAX(revision_no),0) AS value FROM answer_revisions WHERE message_id=%s", (assistant_id,))[0]["value"]
                        self._execute(
                            """INSERT INTO answer_revisions (id,chat_id,message_id,revision_no,answer_status,question_context,operation,result,answer_text,assessment,input_data_revision)
                               VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)""",
                            (incoming_id, chat_id, assistant_id, int(max_revision) + 1, status, self._json({"document_id": assistant.get("document_id"), "question_plan": question_plan}), self._json(question_plan.get("operation") or {}), self._json(result), assistant.get("body", ""), self._json(metadata), 0),
                        )
                self._execute("UPDATE messages SET content=%s,status=%s,needs_update=%s,current_answer_revision_id=%s,updated_at=now() WHERE id=%s", (assistant.get("body", ""), "failed" if status == "processing_error" else "completed", bool(assistant.get("needs_update")), incoming_id, assistant_id))
                continue
            max_sequence_rows = self._execute("SELECT COALESCE(MAX(sequence_no),0) AS value FROM messages WHERE chat_id=%s", (chat_id,))
            sequence = int(max_sequence_rows[0]["value"]) + 1
            self._execute("INSERT INTO messages (id,chat_id,role,content,sequence_no,status) VALUES (%s,%s,'user',%s,%s,'accepted')", (user_id, chat_id, user.get("body", ""), sequence))
            self._execute("INSERT INTO messages (id,chat_id,role,content,reply_to_message_id,sequence_no,status,needs_update,current_answer_revision_id) VALUES (%s,%s,'assistant',%s,%s,%s,%s,%s,%s)", (assistant_id, chat_id, assistant.get("body", ""), user_id, sequence + 1, "processing" if is_processing else "failed" if status == "processing_error" else "completed", bool(assistant.get("needs_update")), revision_id))
            self._execute(
                """INSERT INTO answer_revisions (id,chat_id,message_id,revision_no,answer_status,question_context,operation,result,answer_text,assessment,input_data_revision)
                   VALUES (%s,%s,%s,1,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)""",
                (revision_id, chat_id, assistant_id, status, self._json({"document_id": assistant.get("document_id"), "question_plan": question_plan}), self._json(question_plan.get("operation") or {}), self._json(result), assistant.get("body", ""), self._json(metadata), 0),
            )
            for operand_index, operand in enumerate(assistant.get("answer_inputs") or []):
                try:
                    evidence_revision_id = self._uuid(operand.get("evidence_revision_id"))
                except (ValueError, TypeError):
                    continue
                self._execute("INSERT INTO answer_inputs (answer_revision_id,evidence_revision_id,chat_id,role,param_key) VALUES (%s,%s,%s,'operand',%s) ON CONFLICT DO NOTHING", (revision_id, evidence_revision_id, chat_id, f"operand_{operand_index + 1}"))
            self._execute("UPDATE chats SET next_sequence_no=GREATEST(next_sequence_no,%s),updated_at=now() WHERE id=%s", (sequence + 2, chat_id))

    def put_idempotency_response(self, owner_id: UUID, route: str, key: str, request_hash: str, response: dict[str, Any]) -> None:
        self._execute(
            """INSERT INTO request_keys (owner_id,route,key,request_hash,response,expires_at)
               VALUES (%s,%s,%s,%s,%s::jsonb,now()+interval '24 hours')
               ON CONFLICT (owner_id,route,key) DO UPDATE SET request_hash=EXCLUDED.request_hash,response=EXCLUDED.response,expires_at=EXCLUDED.expires_at""",
            (owner_id, route, key, request_hash, self._json(response)),
        )

    def append_evidence_revision(
        self,
        *,
        chat_id: UUID,
        document_id: UUID,
        evidence_key: str,
        revision: dict[str, Any],
        expected_revision_id: UUID,
    ) -> None:
        """Append one correction without re-syncing the whole session graph."""
        with self.transaction():
            rows = self._execute(
                """SELECT ce.id, ce.current_revision_id
                     FROM chat_evidences ce
                     JOIN chat_sources cs ON cs.id=ce.chat_source_id
                     JOIN extracted_evidences ee ON ee.id=ce.extracted_evidence_id
                     JOIN source_regions sr ON sr.id=ee.source_region_id
                    WHERE ce.chat_id=%s
                      AND cs.document_version_id IN (SELECT id FROM document_versions WHERE document_id=%s)
                      AND sr.meta->>'evidence_key'=%s
                    FOR UPDATE OF ce""",
                (chat_id, document_id, evidence_key),
            )
            if not rows:
                raise ValueError("EVIDENCE_NOT_FOUND")
            current = rows[0]["current_revision_id"]
            if current != expected_revision_id:
                raise ValueError("EVIDENCE_REVISION_CONFLICT")
            self._execute(
                """INSERT INTO evidence_revisions
                    (id,chat_id,chat_evidence_id,revision_no,value_kind,numeric_value,
                     semantic,data_status,verification_status,action,reason,created_by)
                   VALUES (%s,%s,%s,
                           (SELECT COALESCE(MAX(revision_no),0)+1 FROM evidence_revisions WHERE chat_evidence_id=%s),
                           'number',%s::numeric,'{}'::jsonb,'valid','edited','edit',%s,%s)""",
                (revision["id"], chat_id, rows[0]["id"], rows[0]["id"], revision["numeric_value"], revision["reason"], self.owner_id),
            )
            self._execute("UPDATE chat_evidences SET current_revision_id=%s WHERE id=%s", (revision["id"], rows[0]["id"]))
            self._execute(
                """UPDATE messages SET needs_update=TRUE, updated_at=now()
                    WHERE chat_id=%s AND id IN (
                        SELECT ar.message_id FROM answer_revisions ar
                        JOIN answer_inputs ai ON ai.answer_revision_id=ar.id
                       WHERE ai.evidence_revision_id=%s
                    )""",
                (chat_id, expected_revision_id),
            )
            self._execute("UPDATE chats SET data_revision=data_revision+1,updated_at=now() WHERE id=%s AND owner_id=%s", (chat_id, self.owner_id))


__all__ = ["PostgresRuntimeStore"]
