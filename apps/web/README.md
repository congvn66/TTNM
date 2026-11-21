# SourceLens React workspace

SourceLens is the local document-QA test interface. It is implemented with React, Vite and PDF.js.

## Workspace structure

- Left: persisted analysis sessions and their PDF documents.
- Center: PDF.js renders the exact binary returned by the document file endpoint. Controls support page navigation, zoom, fit-width, rotation, scroll and drag-to-pan.
- Right: document chat and the **Dữ liệu** drawer. The drawer shows numeric evidence, its source location and append-only correction history. The current backend uses deterministic page-text retrieval and page citations by default; it does not claim to be an LLM.

## Upload and persistence

- Maximum PDF size: 100 MiB.
- Metadata: `runtime/sessions.json`.
- Original immutable PDF bytes: `runtime/uploads/{document_id}.pdf`.
- Extracted per-page text: `runtime/extracted/{document_id}.json`.
- Numeric evidence revisions: `evidence_state` under the document metadata. Extraction output remains immutable; each edit records old/new exact decimal values, reason and predecessor revision.
- Answer snapshots: `answer_revisions` under the assistant message. `answer_inputs` identifies the `evidence_key` and `evidence_revision_id` actually used.
- Runtime artifacts are ignored by Git.

## Run

```powershell
python -m uvicorn report_qa.api.main:app --app-dir services/backend/src --port 8000
cd apps/web
npm.cmd run dev
```

Open `http://127.0.0.1:4173`.

The backend root at `http://127.0.0.1:8000/` is a JSON landing response with links to the UI, Swagger and health endpoints; it is not the React page.

## Build and checks

```powershell
npm.cmd run build
python scripts/run_web_demo_tests.py
python scripts/run_api_tests.py
```

## Current limitations

- Uploaded PDFs receive text-level extraction and page citations. Claim clicks highlight matching PDF.js text-layer spans on the actual page; persisted server bbox extraction for arbitrary PDFs is not implemented yet.
- Chat is deterministic retrieval by default. Gemini 2.5 Flash and OpenRouter are opt-in structured answer providers; both are validated against the same schema, including claim-level evidence quotes.
- Persistence is local filesystem storage for the main session flow, not the planned PostgreSQL/object-storage deployment.
- Editing a number in **Dữ liệu** uses optimistic concurrency (`expected_revision_id`). A stale edit returns `409 EVIDENCE_REVISION_CONFLICT`; an answer using the old revision is marked `needs_update`. The local runtime preserves that old answer for audit and does not yet recalculate it automatically.
- Each assistant message has a `Data flow` action that reads its persisted trace from `GET /api/v1/sessions/{session_id}/messages/{message_id}/trace`.
- Entering a question immediately appends the user bubble and a typing indicator; the assistant placeholder is replaced after the API response or changed to an actionable error.
- A live provider is opt-in on the backend; with `REPORT_QA_AI_MODE=deterministic`, no external AI request is made. Set either Gemini variables or `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`.

To test the live path, start the backend in the same environment as the API process:

```powershell
$env:REPORT_QA_AI_MODE="gemini"
$env:GEMINI_API_KEY="..."
$env:GEMINI_MODEL="gemini-2.5-flash"
$env:PYTHONPATH="services/backend/src"
uvicorn report_qa.api.main:app --host 127.0.0.1 --port 8000
```

The response remains auditable: the assistant message stores `structured_answer`, citations and a trace with `retrieval`, `ai_provider`, `answer_generation` and `persistence` stages. The retrieval event includes selected pages, scores, character counts and text SHA-256 hashes in `context_manifest`; it intentionally omits raw PDF text and prompts. Without a provider key, keep deterministic mode for local tests.

OpenRouter can be tested with `REPORT_QA_AI_MODE=openrouter`, `OPENROUTER_API_KEY` and `OPENROUTER_MODEL=openai/gpt-6-luna`. The model name is passed through unchanged; an unavailable model is surfaced as `AI_MODEL_UNAVAILABLE`.

## Terminal data-flow audit

The backend emits grep-friendly `FLOW` records to the uvicorn terminal. They contain trace/session/document IDs, status, byte size, hash, page number, score and duration; they deliberately do not print PDF text, questions, prompts or tokens.

Start the API in a visible terminal:

```powershell
python -m uvicorn report_qa.api.main:app --app-dir services/backend/src --port 8000 --log-level info
```

Then upload and ask from the UI. The terminal should show, in order:

```text
FLOW HTTP_IN
FLOW UPLOAD_ACCEPTED
FLOW DOCUMENT_STORED
FLOW EXTRACTION_STARTED
FLOW EXTRACTION_FINISHED
FLOW HTTP_OUT
FLOW RETRIEVAL_SELECTED
FLOW ANSWER_PERSISTED
```

Use the same `trace_id` to correlate one button action across HTTP, extraction, question planning, evidence resolution, calculation and persistence. Click `Data flow` beside an assistant message to read the persisted trace in the UI, or call `GET /api/v1/sessions/{session_id}/messages/{message_id}/trace` for the complete JSON including `context_manifest`.

P0 deterministic answers render calculator output as verified, show the input table, and use each citation bbox to jump to the numeric evidence. Clarification responses are ordinary ordered assistant messages, so they appear immediately in the same conversation instead of opening a separate flow.
