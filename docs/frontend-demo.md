# SourceLens frontend and local document flow

## Architecture

The frontend is a React/Vite application. PDF.js renders the actual file bytes served by FastAPI; the old reconstructed reference canvas and buildless state machine have been removed.

```text
session sidebar -> selected document -> PDF.js reader
                                  \-> page-text retrieval chat -> page citation
```

## Session and document contract

The server owns the local owner identity; no `owner_id` is accepted from the browser.

| Operation | Endpoint | Persistence |
|---|---|---|
| List/create sessions | `GET/POST /api/v1/sessions` | `runtime/sessions.json` |
| Read session | `GET /api/v1/sessions/{session_id}` | metadata and chat history |
| Upload PDF | `POST /api/v1/sessions/{session_id}/documents` | original bytes in `runtime/uploads` |
| Read PDF | `GET /api/v1/sessions/{session_id}/documents/{document_id}/file` | inline immutable PDF response |
| Ask document | `POST /api/v1/sessions/{session_id}/messages` | messages and page citation in session catalog |
| Inspect answer flow | `GET /api/v1/sessions/{session_id}/messages/{message_id}/trace` | persisted retrieval/provider/persistence stages |

The reference smoke check is read-only and uses the PDF outside the repository:

```powershell
\.\.venv\Scripts\python.exe scripts/run_snapshot_reference_checks.py
```

It validates the supplied `Snapshot Q1-26 VI.pdf` page count and the retrieval
markers used by the Q1/2026 gaming question. Set `REPORT_QA_REFERENCE_PDF` to
override the local path.

PDF upload is streamed in 1 MiB chunks, hashed while writing and atomically published only after validation. The hard limit is 100 MiB. Temporary partial files are removed after failure.

## Reader behavior

PDF.js loads the selected document file endpoint. The reader supports previous/next page, zoom, fit-width, rotation, normal scrolling and pointer drag-to-pan. Clicking a citation changes the rendered page to its cited source page.

## Chat truth boundary

The current provider is `deterministic_text_retrieval`: pypdf extracts text per page, the query is matched by token overlap, and the assistant returns the most relevant page excerpt. It is useful for verifying upload -> extraction -> retrieval -> citation, but it is not an LLM and does not synthesize a reliable narrative answer.

Gemini 2.5 Flash can be enabled with `REPORT_QA_AI_MODE=gemini` and `GEMINI_API_KEY`; OpenRouter uses `REPORT_QA_AI_MODE=openrouter`, `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` (the current live test model is `openai/gpt-6-luna`). The provider receives only server-selected page context and must return the validated structured answer schema. The UI renders summary, sections, claims/evidence quotes, formulas, tables and warnings. Supported growth formulas are independently checked by the Decimal calculator; unsupported formulas are visibly marked unverified.

Arbitrary uploaded PDFs still return API citations with `bbox=null`; the UI now uses PDF.js text-layer coordinates to highlight matching claim text on the actual rendered page. This is a client-side text evidence overlay, not a persisted server bbox. Exact persisted regions still require a layout/OCR extractor.

## Local-only limitations

Metadata, original PDFs and extracted text are stored under ignored `runtime/` paths. This is restart-safe local persistence for the main session flow; it does not replace PostgreSQL, object storage, multi-user authorization or production job processing.
