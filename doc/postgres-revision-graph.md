# PostgreSQL revision graph - runtime contract

## Source of truth

PostgreSQL is the sole source of truth for mutable domain metadata in a
production run. PDF bytes and rendered page crops live in object storage; they
are addressed from `document_versions.storage_key` and are immutable. Redis is
optional cache/notification infrastructure only and must never be needed to
rebuild a chat, an evidence revision, or an answer.

The current local UI still defaults to `PERSISTENCE_BACKEND=json` for backward
compatible offline demo data. Set `PERSISTENCE_BACKEND=postgres` only after the
API endpoint cutover is enabled: it must never silently write a JSON catalog
when Postgres was requested. `PostgresRevisionStore` is the concrete graph
writer used by that cutover; it writes the reviewed 23-table schema and is
transactional.

## Write transaction

```text
upload
  -> documents + document_versions (immutable file/version)
  -> extraction_runs completed
  -> source_regions + extracted_evidences (immutable extraction)
  -> chat_sources (only completed run, same owner)
  -> chat_evidences + evidence_revisions(action=initialize)

question
  -> messages(user, assistant)
  -> answer_revisions (append only)
  -> answer_inputs (exact evidence_revision IDs used)
  -> answer_scopes (full affected scope)
```

An evidence edit appends a new `evidence_revisions` row; it never updates
`extracted_evidences`. A recalculation appends a new `answer_revisions` row.
The `current_*_revision_id` columns are pointers only, guarded by deferred FK
triggers so they cannot point outside their owning chat/message.

## Runtime APIs required for the cutover

The legacy session endpoints may keep their JSON response shape, but their
handlers must call these graph operations in one database transaction:

1. `create_chat(owner, title)` for a new session.
2. `create_document_version(...)`, then `persist_completed_extraction(...)`
   after the extractor has completed.
3. `attach_source(...)`, followed by `initialize_chat_evidence(...)` to create
   the chat-local working copy.
4. `append_answer_revision(..., evidence_revision_ids=...)` for every
   assistant result. The caller derives IDs from the initialization map using
   `answer_inputs.evidence_key`; the stored answer must not contain synthetic
   evidence IDs.

Use `request_keys` for upload/message idempotency. Use a worker job with an
unexpired lease token for long extraction/OCR work; do not publish an answer if
its `input_data_revision` is stale.

## Migration/runbook

```powershell
docker compose -f infra/compose/dev.yml up -d postgres
$env:PERSISTENCE_BACKEND = 'postgres'
$env:DATABASE_URL = 'postgresql+psycopg://sourcelens:sourcelens-dev-only@127.0.0.1:5432/sourcelens'
.venv\Scripts\alembic.exe -c services/backend/alembic.ini upgrade head
```

Before directing traffic to Postgres, run the empty-db migration test, import a
disposable JSON fixture by hash, then compare document version hashes, page
counts, message ordering, evidence counts and answer-input revision IDs. Do
not run dual writes indefinitely; use one short backfill window, verify, then
switch the API read/write repository together.

## Extraction capability matrix

| Input | Adapter | Output / failure |
|---|---|---|
| PDF text layer | pypdf layout visitor | text evidence and normalized bbox |
| Digitally generated simple table | pypdf fallback | per-cell evidence, basic row/column locator |
| Complex/merged table | optional pdfplumber adapter | per physical cell with multi-row header path; fallback stays explicit |
| Scanned page | optional PyMuPDF + Tesseract | OCR token bbox/confidence, or `OCR_*` warning; never empty silent success |
| Single-axis vector bar chart requested by a plan | pypdf vector reader | `direct_label` or `axis_estimation`, each with provenance |
| Stacked/dual-axis/ambiguous chart | vector reader | no valid numeric evidence; warning/status asks for a safer source |

