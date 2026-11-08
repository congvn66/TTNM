"""PostgreSQL persistence boundary for immutable revision-graph writes.

This adapter intentionally exposes graph operations rather than a JSON blob:
the caller records an extraction once, attaches it to a chat, then appends
evidence/answer revisions.  Every method requires the owner UUID so ownership
is checked by the database query itself.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Iterator, Sequence
from uuid import UUID, uuid4


class PostgresRevisionStore:
    def __init__(self, database_url: str) -> None:
        import psycopg
        from psycopg.rows import dict_row
        self._psycopg = psycopg
        self._dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._row_factory = dict_row
        self._connection: Any | None = None

    @contextmanager
    def transaction(self) -> Iterator["PostgresRevisionStore"]:
        if self._connection is not None:
            yield self
            return
        with self._psycopg.connect(self._dsn, row_factory=self._row_factory) as connection:
            self._connection = connection
            try:
                yield self
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                self._connection = None

    def _execute(self, statement: str, values: Sequence[Any] = ()) -> Any:
        if self._connection is None:
            with self.transaction():
                return self._execute(statement, values)
        with self._connection.cursor() as cursor:
            cursor.execute(statement, values)
            return cursor.fetchall() if cursor.description else []

    def ensure_owner(self, owner_id: UUID, *, email: str | None = None, display_name: str = "Local user") -> None:
        value = email or f"local-{owner_id}@invalid"
        self._execute(
            """INSERT INTO users (id,email,normalized_email,password_hash,display_name)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (owner_id, value, value.casefold(), "local-runtime-not-a-password", display_name),
        )

    def create_chat(self, owner_id: UUID, title: str, *, chat_id: UUID | None = None) -> UUID:
        self.ensure_owner(owner_id)
        identifier = chat_id or uuid4()
        self._execute("INSERT INTO chats (id,owner_id,title) VALUES (%s,%s,%s)", (identifier, owner_id, title))
        return identifier

    def create_document_version(self, owner_id: UUID, title: str, file_name: str, storage_key: str, file_hash: str, byte_size: int, *, document_id: UUID | None = None, version_id: UUID | None = None) -> tuple[UUID, UUID]:
        self.ensure_owner(owner_id)
        document = document_id or uuid4()
        version = version_id or uuid4()
        self._execute("INSERT INTO documents (id,owner_id,title) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING", (document, owner_id, title))
        rows = self._execute("SELECT COALESCE(MAX(version_no),0)+1 AS value FROM document_versions WHERE document_id=%s", (document,))
        version_no = int(rows[0]["value"])
        self._execute(
            """INSERT INTO document_versions (id,document_id,version_no,file_name,storage_key,file_hash,byte_size)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (version, document, version_no, file_name, storage_key, file_hash, byte_size),
        )
        return document, version

    def persist_completed_extraction(self, owner_id: UUID, document_version_id: UUID, *, extractor_name: str, extractor_version: str | None, page_count: int, evidence_batch: dict[str, Any]) -> UUID:
        """Append an immutable extraction run, regions and numeric evidence."""
        self.ensure_owner(owner_id)
        rows = self._execute("""SELECT dv.id FROM document_versions dv JOIN documents d ON d.id=dv.document_id
                              WHERE dv.id=%s AND d.owner_id=%s AND d.deleted_at IS NULL""", (document_version_id, owner_id))
        if not rows:
            raise PermissionError("DOCUMENT_NOT_FOUND")
        run_id = uuid4()
        run_no = int(self._execute("SELECT COALESCE(MAX(run_no),0)+1 AS value FROM extraction_runs WHERE document_version_id=%s", (document_version_id,))[0]["value"])
        self._execute("""INSERT INTO extraction_runs (id,document_version_id,run_no,status,extractor_name,extractor_version,started_at,completed_at)
                       VALUES (%s,%s,%s,'completed',%s,%s,now(),now())""", (run_id, document_version_id, run_no, extractor_name, extractor_version))
        self._execute("UPDATE document_versions SET status='ready', page_count=%s WHERE id=%s", (page_count, document_version_id))
        for item in evidence_batch.get("evidences", []):
            region_id, evidence_id = uuid4(), uuid4()
            self._execute("""INSERT INTO source_regions (id,extraction_run_id,region_key,page_number,bbox,region_type,extracted_text,meta)
                           VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)""", (region_id, run_id, item["source_region_key"], item["page_number"], self._json(item["bbox"]), "table_cell" if item["source_type"] == "table" else "chart_element" if item["source_type"] == "chart" else "paragraph", item.get("raw_text"), self._json({"evidence_key": item["evidence_key"], "method_label": item["method_label"], "table_locator": item.get("table_locator"), "chart_read": item.get("chart_read")})))
            self._execute("""INSERT INTO extracted_evidences (id,extraction_run_id,source_region_id,value_kind,raw_value,semantic,data_status,extraction_method,confidence)
                           VALUES (%s,%s,%s,'number',%s::numeric,%s::jsonb,'valid',%s,%s)""", (evidence_id, run_id, region_id, item["numeric_value"], self._json(item["semantic"]), self._db_method(item["extraction_method"]), item.get("confidence")))
        return run_id

    def attach_source(self, owner_id: UUID, chat_id: UUID, document_version_id: UUID, extraction_run_id: UUID) -> UUID:
        row = self._execute("SELECT id FROM chats WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (chat_id, owner_id))
        if not row:
            raise PermissionError("CHAT_NOT_FOUND")
        source_id = uuid4()
        self._execute("INSERT INTO chat_sources (id,chat_id,document_version_id,extraction_run_id) VALUES (%s,%s,%s,%s)", (source_id, chat_id, document_version_id, extraction_run_id))
        return source_id

    def initialize_chat_evidence(self, owner_id: UUID, chat_id: UUID, chat_source_id: UUID) -> dict[str, UUID]:
        """Create immutable initial working copies, once per chat/source fact."""
        rows = self._execute(
            """SELECT ee.id AS extracted_id, ee.extraction_run_id, ee.value_kind, ee.raw_value::text AS raw_value,
                      ee.raw_text, ee.semantic, ee.data_status, sr.meta->>'evidence_key' AS evidence_key
                 FROM chat_sources cs JOIN chats c ON c.id=cs.chat_id
                 JOIN extracted_evidences ee ON ee.extraction_run_id=cs.extraction_run_id
                 JOIN source_regions sr ON sr.id=ee.source_region_id
                WHERE cs.id=%s AND cs.chat_id=%s AND c.owner_id=%s""",
            (chat_source_id, chat_id, owner_id),
        )
        result: dict[str, UUID] = {}
        for row in rows:
            existing = self._execute("SELECT ce.current_revision_id FROM chat_evidences ce WHERE ce.chat_id=%s AND ce.extracted_evidence_id=%s", (chat_id, row["extracted_id"]))
            if existing:
                result[str(row["evidence_key"])] = existing[0]["current_revision_id"]
                continue
            chat_evidence_id, revision_id = uuid4(), uuid4()
            self._execute("""INSERT INTO chat_evidences (id,chat_id,chat_source_id,extracted_evidence_id,extraction_run_id)
                           VALUES (%s,%s,%s,%s,%s)""", (chat_evidence_id, chat_id, chat_source_id, row["extracted_id"], row["extraction_run_id"]))
            self._execute("""INSERT INTO evidence_revisions (id,chat_id,chat_evidence_id,revision_no,value_kind,numeric_value,text_value,semantic,data_status,verification_status,action)
                           VALUES (%s,%s,%s,1,%s,%s::numeric,%s,%s::jsonb,%s,'unverified','initialize')""", (revision_id, chat_id, chat_evidence_id, row["value_kind"], row["raw_value"], row["raw_text"], self._json(row["semantic"]), row["data_status"]))
            self._execute("UPDATE chat_evidences SET current_revision_id=%s WHERE id=%s", (revision_id, chat_evidence_id))
            result[str(row["evidence_key"])] = revision_id
        return result

    def append_answer_revision(self, owner_id: UUID, chat_id: UUID, question: str, answer: dict[str, Any], *, answer_text: str, evidence_revision_ids: Sequence[UUID] = (), status: str = "answered") -> tuple[UUID, UUID]:
        """Write ordered user/assistant messages and an append-only answer revision."""
        chat = self._execute("SELECT id,data_revision,next_sequence_no FROM chats WHERE id=%s AND owner_id=%s AND deleted_at IS NULL FOR UPDATE", (chat_id, owner_id))
        if not chat:
            raise PermissionError("CHAT_NOT_FOUND")
        sequence = int(chat[0]["next_sequence_no"])
        user_id, assistant_id, revision_id = uuid4(), uuid4(), uuid4()
        self._execute("INSERT INTO messages (id,chat_id,role,content,sequence_no,status) VALUES (%s,%s,'user',%s,%s,'accepted')", (user_id, chat_id, question, sequence))
        self._execute("INSERT INTO messages (id,chat_id,role,content,reply_to_message_id,sequence_no,status) VALUES (%s,%s,'assistant',%s,%s,%s,'completed')", (assistant_id, chat_id, answer_text, user_id, sequence + 1))
        self._execute("""INSERT INTO answer_revisions (id,chat_id,message_id,revision_no,answer_status,question_context,operation,result,answer_text,assessment,input_data_revision)
                       VALUES (%s,%s,%s,1,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s)""", (revision_id, chat_id, assistant_id, status, self._json(answer.get("question_plan", {})), self._json((answer.get("question_plan") or {}).get("operation")), self._json(answer.get("calculation_result") or answer.get("structured_answer", {})), answer_text, self._json({"trace_id": answer.get("trace_id"), "citations": answer.get("citations", [])}), chat[0]["data_revision"]))
        self._execute("UPDATE messages SET current_answer_revision_id=%s WHERE id=%s", (revision_id, assistant_id))
        for index, evidence_revision_id in enumerate(evidence_revision_ids):
            self._execute("INSERT INTO answer_inputs (answer_revision_id,evidence_revision_id,chat_id,role,param_key) VALUES (%s,%s,%s,'operand',%s)", (revision_id, evidence_revision_id, chat_id, f"operand_{index + 1}"))
        self._execute("UPDATE chats SET next_sequence_no=%s, updated_at=now() WHERE id=%s", (sequence + 2, chat_id))
        return assistant_id, revision_id

    def put_idempotency_response(self, owner_id: UUID, route: str, key: str, request_hash: str, response: dict[str, Any]) -> None:
        self._execute("""INSERT INTO request_keys (owner_id,route,key,request_hash,response,expires_at)
                       VALUES (%s,%s,%s,%s,%s::jsonb,now() + interval '24 hours')
                       ON CONFLICT (owner_id,route,key) DO UPDATE SET request_hash=EXCLUDED.request_hash,response=EXCLUDED.response""", (owner_id, route, key, request_hash, self._json(response)))

    def get_idempotency_response(self, owner_id: UUID, route: str, key: str, request_hash: str) -> dict[str, Any] | None:
        rows = self._execute("SELECT request_hash,response FROM request_keys WHERE owner_id=%s AND route=%s AND key=%s AND expires_at > now()", (owner_id, route, key))
        if not rows: return None
        if rows[0]["request_hash"] != request_hash: raise ValueError("IDEMPOTENCY_KEY_REUSED")
        return rows[0]["response"]

    @staticmethod
    def _db_method(method: str) -> str:
        return {"table_cell": "table", "direct_label": "direct_label", "axis_estimation": "axis_estimation", "ocr": "ocr"}.get(method, "text")

    @staticmethod
    def _json(value: Any) -> str:
        import json
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


__all__ = ["PostgresRevisionStore"]
