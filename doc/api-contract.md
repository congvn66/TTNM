# Hop dong API MVP

## Luồng API chính

Trong lúc chưa có auth/PostgreSQL runtime, FastAPI cung cấp một contract session/document duy nhất:

- `GET /health` — trả persistence/AI/database status.
- `POST /api/v1/sessions` — tạo phiên tài liệu.
- `POST /api/v1/sessions/{session_id}/documents` — upload và bắt đầu trích xuất PDF.
- `POST /api/v1/sessions/{session_id}/messages` — hỏi tài liệu theo flow planner → evidence → calculator → answer.
- `GET /api/v1/sessions/{session_id}/messages/{message_id}/trace` — audit flow đã lưu.

FastAPI sinh OpenAPI tại `/openapi.json` và Swagger UI tại `/docs`. Contract local này chưa phải auth-ready public API.

## 1. Quy uoc

- Base path: `/api/v1`; JSON UTF-8; timestamp RFC 3339 UTC.
- ID la UUID do server tao. Client khong gui `owner_id` cho resource so huu.
- So chinh xac (`NUMERIC`) la chuoi thap phan, vi du `"58"`, `"154.054054"`.
- Page bat dau tu 1. Bbox chuan hoa `[x0,y0,x1,y1]` voi goc tren-trai.
- Mutation co nguy co retry nhan `Idempotency-Key`; edit co `expected_revision_id`.
- List dung cursor; response co `items`, `next_cursor`.
- Job dai tra `202 Accepted` voi `job_id` va resource placeholder.

## 2. Error envelope

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "Can cu da co phien ban moi. Hay tai lai truoc khi sua.",
    "details": {"current_revision_id": "..."},
    "request_id": "..."
  }
}
```

Ma toi thieu: `validation_error`, `unauthenticated`, `forbidden`, `not_found`, `revision_conflict`, `idempotency_conflict`, `unsupported_pdf`, `job_failed`, `rate_limited`.

## 3. Endpoint map

### Identity

- `POST /auth/register`, `/auth/login`, `/auth/logout`
- `POST /auth/password/forgot`, `/auth/password/reset`
- `GET /me`, `PATCH /me`

### Projects/documents

- `GET|POST /projects`; `GET|PATCH|DELETE /projects/{id}`
- `GET|POST /documents`; `GET|PATCH|DELETE /documents/{id}`
- `POST /documents/{id}/versions` (multipart upload, idempotent)
- `GET /document-versions/{id}`; `GET /document-versions/{id}/extraction-runs`
- `GET /jobs/{id}`; `GET /jobs/{id}/events?after=` (SSE hoac polling fallback)

### Chats/messages

- `GET|POST /chats`; `GET|PATCH|DELETE /chats/{id}`
- `POST /chats/{id}/sources`; `PATCH /chats/{id}/sources/{source_id}`
- `GET /chats/{id}/messages?cursor=`
- `POST /chats/{id}/messages` de dat cau hoi
- `GET /messages/{id}/answer-revisions`; `GET /answer-revisions/{id}`
- `POST|DELETE /messages/{id}/pin`

### Evidence

- `GET /chats/{id}/evidences?source_id=&cursor=`
- `GET /chat-evidences/{id}`; `GET /chat-evidences/{id}/revisions`
- `POST /chat-evidences/{id}/revisions` voi action `verify|edit|mark_error|restore`
- `POST /messages/{id}/recalculate`

## 4. Payload mau

### Dat cau hoi

```json
{
  "content": "Trong quy 3, khu vuc nao tang nhieu nhat so voi quy 1?",
  "context": {
    "active_source_ids": ["uuid"],
    "focused_region_id": null
  }
}
```

Response `202`:

```json
{
  "user_message_id": "uuid",
  "assistant_message_id": "uuid",
  "job_id": "uuid",
  "input_data_revision": 7
}
```

### Sua can cu

```json
{
  "expected_revision_id": "uuid",
  "action": "edit",
  "reason": "Nhan tren bieu do ghi 58, khong phai 38",
  "data_status": "valid",
  "numeric_value": "58",
  "text_value": null,
  "semantic": {
    "measure": {"label": "Doanh thu thuan"},
    "subject": {"label": "Mien Bac"},
    "unit": {"code": "VND_MILLION", "label": "trieu dong", "multiplier": "1000000"},
    "period": {"status": "partial", "label": "Quy 1", "start": null, "end": null, "basis": "explicit"},
    "dimensions": {},
    "value_operator": "eq"
  }
}
```

Response gom revision moi, `chat_data_revision`, `affected_message_ids`, `job_ids`.

### Structured answer cua AI (local vertical slice)

Khi `REPORT_QA_AI_MODE=gemini` hoac `openrouter`, assistant message co them
`structured_answer`. Day la presentation contract, khong phai ket qua tinh toan
authoritative:

```json
{
  "answer": "Doanh thu mảng trò chơi trực tuyến tăng trong kỳ.",
  "summary": "Tóm tắt ngắn, chỉ dựa trên context máy chủ đã chọn.",
  "sections": [{"heading": "Tăng trưởng", "points": ["..."], "evidence_pages": [2]}],
  "formulas": [],
  "tables": [],
  "claims": [{
    "claim": "Tổng bookings tăng 48% so với cùng kỳ.",
    "evidence_pages": [3],
    "evidence_quotes": ["Tổng bookings tăng 48% YoY"]
  }],
  "warnings": [],
  "cited_pages": [2, 3]
}
```

Server chỉ nhận `evidence_pages` trong ba trang retrieval đã gửi cho provider.
Mỗi `evidence_quotes` phải xuất hiện trong text context sau chuẩn hóa Unicode và
khoảng trắng; nếu không, request bị từ chối với `AI_UNSUPPORTED_EVIDENCE`.
`trace` lưu `context_manifest` gồm trang, điểm retrieval, số ký tự và SHA-256
của text, không lưu toàn bộ prompt hoặc nội dung PDF vào log.

### Answer revision rut gon

```json
{
  "id": "uuid",
  "status": "answered",
  "answer_text": "...",
  "operation": {"name": "growth_rate_ranking", "rounding": {"display_decimals": 2}},
  "result": {"winner_subjects": ["Mien Nam"], "value": "80"},
  "assessment": {"complete": true, "reasons": []},
  "inputs": [
    {"param_key": "MN_Q1", "role": "comparison_group", "evidence_revision_id": "uuid"}
  ],
  "scopes": [
    {"chat_source_id": "uuid", "filter": {"measure": "Doanh thu", "periods": ["Q1", "Q3"], "all_subjects": true}}
  ],
  "claims": [
    {"text": "...", "evidence_revision_ids": ["uuid"], "source_regions": [{"page": 2, "bbox": [0.1, 0.2, 0.7, 0.8]}]}
  ]
}
```

`claims` co the duoc luu trong `result/assessment` o prototype, nhung neu can query doc lap thi tao ADR va table moi; khong them schema ngam.

## 5. Concurrency va idempotency

- Cung owner + route + key + request hash: tra response da luu.
- Cung key nhung khac hash: `409 idempotency_conflict`.
- Evidence edit dung optimistic concurrency qua `expected_revision_id`.
- Answer publish dung server-side `input_data_revision`; client khong the ep publish revision cu.

## 6. Quyen va loc du lieu

Moi query resource phai loc theo authenticated user o DB/repository. `404` duoc uu tien cho resource khong thuoc owner de tranh ro ri ton tai. Signed URL chi tao sau ownership check va het han ngan.

## 7. Header va HTTP semantics

| Header | Dung cho | Quy tac |
|---|---|---|
| `Idempotency-Key` | POST upload/message/retry/purge | Bat buoc voi mutation co the retry; 24-72h retention |
| `If-Match` hoac body `expected_revision_id` | evidence/source state change | Mismatch -> 409 `revision_conflict` |
| `X-Request-ID` | moi request | Server chap nhan hop le hoac sinh moi, tra lai |
| `Retry-After` | 429/503 | Seconds hoac HTTP date |
| `Last-Event-ID` | SSE reconnect | Resume job events; client van GET final resource |

HTTP: 200 read/update sync; 201 resource sync; 202 job async; 204 delete/unpin; 400 malformed; 401 no session; 404 hidden/not found; 409 state/idempotency conflict; 413 size; 415 media; 422 domain validation; 429 limit; 503 dependency unavailable.

## 8. Resource representation bat buoc

- Moi resource co `id`, relevant version/state, `created_at`; mutable resource co `updated_at`.
- Chat response co `data_revision` va active source summaries.
- Evidence response tach `origin`, `current_revision`, `history_summary`.
- Answer response tach `question_context`, `operation`, `result`, `assessment`, `inputs`, `scopes`, `claims`.
- Job response co `kind/status/attempts/progress/error_code/resource_ids`; khong tra stack/provider raw response.

## 9. Endpoint authorization matrix

| Resource | Read | Create/update | Ghi chu |
|---|---|---|---|
| project/document/version | owner | owner | document version bytes bat bien |
| extraction run/region | owner qua document | system worker; user schedule qua API | completed payload read-only |
| chat/source/message | owner | owner/system worker | source phai cung owner |
| evidence revision | owner | owner qua expected revision | raw origin khong sua |
| answer revision | owner | system worker only | user chi retry/recalc request |
| job/events | owner qua resource | system worker | client khong set lease/status |
| audit/request key | khong public hoac gioi han | system | khong expose secret/hash |

## 10. Pagination, sorting va expansion

- Cursor opaque encode sort key + ID; khong offset cho message/history lon.
- Message sort `sequence_no ASC`; revision `revision_no DESC`; chat list `updated_at DESC,id`.
- `limit` default 50, max 200.
- Expansion allowlist, vi du `include=current_answer,input_summary`; khong co arbitrary join.
- Bbox/source signed URL lay endpoint rieng de quyen va TTL ro.

## 11. Job event contract

SSE event:

```text
id: 4
event: progress
data: {"job_id":"...","status":"running","stage":"extract_tables","progress":0.6}
```

Progress la hint 0..1, co the null; `event_no` monotonic trong job. Event final gom resource IDs. SSE disconnect khong huy job.

## 12. Contract evolution

- API major trong path; additive field khong can major bump.
- Enum moi co the lam client strict vo, nen contract client phai co unknown-state fallback hoac bump phu hop.
- JSONB document co `schema_version`; migration/reader ho tro transition.
- OpenAPI snapshot duoc diff trong CI; breaking change can ADR/migration plan.

## 13. Session/document endpoints

These endpoints are a local vertical slice, not the final authenticated production surface:

| Method/path | Purpose |
|---|---|
| `GET /api/v1/sessions` | List server-owned local sessions and nested documents |
| `POST /api/v1/sessions` | Create a session; accepts title only, never client `owner_id` |
| `GET /api/v1/sessions/{session_id}` | Read session, documents and message history |
| `POST /api/v1/sessions/{session_id}/documents` | Stream, validate, hash and persist one PDF, maximum 100 MiB |
| `GET /api/v1/sessions/{session_id}/documents/{document_id}/file` | Return the immutable original PDF inline |
| `POST /api/v1/sessions/{session_id}/messages` | Retrieve up to three pages, reject low-overlap non-summary questions (score < 2), and persist question/answer/citation |
| `GET /api/v1/sessions/{session_id}/messages/{message_id}/trace` | Read the persisted stage trace for one assistant answer |
| `GET /api/v1/sessions/{session_id}/documents/{document_id}/evidences` | List numeric evidence with immutable original value, current value and current revision ID |
| `GET /api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions` | Read append-only revision history for a numeric evidence item |
| `POST /api/v1/sessions/{session_id}/documents/{document_id}/evidences/{evidence_key}/revisions` | Append an edit using `numeric_value`, `reason`, `expected_revision_id`; return affected answer message IDs |

Upload publication is atomic. A failed or oversized upload must remove its temporary file and must not add document metadata. By default chat responses declare `mode=deterministic_text_retrieval`; page citations have `bbox=null` until a layout extractor produces evidence coordinates.

### Week 1 local evidence-revision slice

On extraction completion, the local runtime creates an `initialize` revision for
every numeric evidence. The extraction artifact remains immutable. A correction
appends an `edit` revision containing `old_numeric_value`, `numeric_value`,
`previous_revision_id`, `reason` and timestamp. A stale
`expected_revision_id` returns `409 EVIDENCE_REVISION_CONFLICT`.

Every deterministic answer stores an `answer_revisions[0].answer_inputs`
snapshot. Each input includes the `evidence_key`, exact current
`evidence_revision_id`, decimal value and locator. When that revision is
superseded, the local runtime marks only answers that used that exact revision
as `needs_update=true`; it does not rewrite their historical snapshot.

`REPORT_QA_AI_MODE=deterministic` is the default. `REPORT_QA_AI_MODE=gemini` enables Gemini 2.5 Flash and `REPORT_QA_AI_MODE=openrouter` enables OpenRouter with `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`. Both adapters request structured JSON and persist `structured_answer` containing `answer`, `summary`, `sections`, `formulas`, `tables`, `claims`, `warnings` and `cited_pages`. Every evidence page must belong to the server-selected context and each claim quote must occur in that context. The model cannot write evidence, bbox or authoritative numeric results.

## 14. Cach doc Swagger va trace

Swagger duoc mo tai `/docs`; mo tag `sessions` de xem luong PDF -> question plan -> evidence -> calculator -> answer -> persistence. Mo `/openapi.json` de dung lam contract snapshot.

Endpoint quan trong nhat de audit la `POST /api/v1/sessions/{session_id}/messages`: response tra `trace_id` va `assistant_message.id`; dung hai gia tri nay de goi `GET /api/v1/sessions/{session_id}/messages/{message_id}/trace`. Chi trace co stage `persistence=committed` moi xac nhan assistant message da ghi vao `runtime/sessions.json`.

### P0 question/evidence/calculation payload

`assistant_message` có thể mang thêm:

- `question_plan`: payload `question-plan-v2`;
- `calculation_result`: payload `calculation-result-v1` khi operation cần tính;
- `answer_inputs`: exact `evidence_revision_id`, decimal value và unit đã bind;
- `citations[].bbox`: locator normalized của từng số;
- `citations[].method_label`: “đọc từ văn bản”, “đọc từ ô bảng”, sau này là “đọc từ nhãn” hoặc “ước lượng theo trục”.

Nếu planner trả `needs_clarification`, response vẫn là `200` và được lưu tuần tự trong chat, nhưng không có retrieval/calculation/citation. Nếu base evidence thiếu fact bắt buộc, chart port chỉ được gọi cho fact thiếu; adapter local hiện trả `CHART_READER_NOT_IMPLEMENTED` và calculator trả `missing_data`, không đoán số.

The stable presentation shape is:

```json
{
  "answer": "Một câu trả lời ngắn",
  "summary": "Tóm tắt kết luận",
  "sections": [{"heading": "Ý chính", "points": ["..."], "evidence_pages": [2]}],
  "formulas": [{"name": "Tăng trưởng", "expression": "(mới-cũ)/cũ", "substitution": "120/100", "result": "20", "unit": "%", "evidence_pages": [2], "calculation": {"status": "verified", "computed_result": "20", "unit": "%", "calculator": "decimal_growth_v1"}}],
  "tables": [{"title": "So sánh", "columns": ["Kỳ", "Giá trị"], "rows": [["Q1", "120"]], "evidence_pages": [2]}],
  "claims": [{"claim": "Bookings tăng 48% so với cùng kỳ.", "evidence_pages": [3], "evidence_quotes": ["Tổng bookings tăng 48% YoY"]}],
  "warnings": [],
  "cited_pages": [2]
}
```

`answer`/`summary` are display text; `expression`/`substitution`/`result` are presentation fields and must not replace the deterministic calculator. The UI renders each field separately and keeps page citations clickable.

For an OpenRouter test, set `REPORT_QA_AI_MODE=openrouter`, `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` (default `openai/gpt-6-luna`). The adapter uses `/api/v1/chat/completions` with `response_format.type=json_schema` and validates the same structured answer contract before persistence.
