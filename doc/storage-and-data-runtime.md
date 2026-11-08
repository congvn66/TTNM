# Lưu trữ runtime và khoảng trống dữ liệu

## Kết luận ngắn

Runtime local hiện không dùng Redis hay PostgreSQL. Session đang được lưu ở
`runtime/sessions.json`, PDF ở `runtime/uploads/{document_id}.pdf`, và text trích
xuất ở `runtime/extracted/{document_id}.json`. Cách này phù hợp để demo một máy,
restart-safe ở mức file, nhưng không an toàn cho nhiều worker/process và chưa có
transaction domain đầy đủ.

Không dùng Redis làm source of truth cho session. Redis chỉ nên giữ cache, lock
ngắn hạn hoặc queue/progress tạm thời. PostgreSQL phải là source of truth cho
metadata, ownership, messages, evidence revisions, answer revisions, jobs và
audit; object storage giữ PDF/artifact lớn.

## Runtime hiện tại

| Dữ liệu | Nơi lưu hiện tại | Tính bền vững | Rủi ro |
|---|---|---|---|
| Session, documents, messages | `runtime/sessions.json` | restart-safe trên một process/máy | lost update khi nhiều process, không có query/index/transaction |
| PDF gốc | `runtime/uploads/*.pdf` | bền trên local disk | chưa có object-store versioning/retention |
| Text từng trang | `runtime/extracted/*.json` | bền trên local disk | chưa có extraction revision/query layout |
| Retrieval trace | nhúng trong assistant message + log | bền cho session local | chưa có bảng audit/retention/PII policy |
| AI response | structured answer trong message | bền local | chưa có answer revision/input snapshot domain cho chat demo |
| P0 plan/calculation | `question_plan`, `calculation_result`, `answer_inputs` trong assistant message | bền local | cần tách thành job/answer revision/input rows khi cutover PostgreSQL |
| Job extraction | FastAPI background task | chỉ sống trong process request | crash giữa job không có lease/retry/resume |
| Cache/session UI | browser localStorage | chỉ phía trình duyệt | không phải authentication/session server |

## Target production flow

```text
Browser
  -> API transaction PostgreSQL: session/chat/message/job/trace metadata
  -> object storage: immutable PDF, page image, crop, extraction artifact
  -> worker claims jobs with lease_token
  -> provider/calculator
  -> PostgreSQL answer_revision + inputs + scopes + audit
  -> browser polls/SSE progress, then reads final revision
```

### PostgreSQL là nguồn sự thật

- `sessions/chats/messages` giữ lịch sử và thứ tự message.
- `documents/document_versions` giữ version PDF bất biến và hash.
- `extraction_runs/source_regions/extracted_evidences` giữ output extractor đã
  hoàn tất; không update tại chỗ.
- `chat_evidences/evidence_revisions` giữ working copy theo từng chat.
- `answer_revisions/answer_inputs/answer_scopes` giữ kết quả, input snapshot và
  toàn bộ scope có thể ảnh hưởng.
- `jobs/job_events/request_keys/audit_events` giữ retry, idempotency và audit.

### Redis chỉ là thành phần phụ

Chỉ dùng Redis khi cần và không lưu dữ liệu duy nhất ở đó:

- cache session summary hoặc retrieval cache có TTL;
- distributed lock ngắn hạn cho cùng document/job;
- pub/sub progress nếu polling PostgreSQL không đủ;
- rate limit.

Nếu Redis mất, hệ thống phải đọc lại từ PostgreSQL/object storage và không mất
message, evidence revision hoặc answer revision.

## Trạng thái triển khai PostgreSQL

Đã thêm runtime local PostgreSQL 16 tại `infra/compose/dev.yml`, baseline schema
được mount từ `doc/initial-schema.sql`, typed settings và connectivity probe.
API vẫn đang dùng JSON adapter mặc định (`PERSISTENCE_BACKEND=json`); chưa được
phép chuyển cờ sang `postgres` trước khi repository/UoW, Alembic migration,
data import và integration/race tests hoàn tất. Điều này tránh tình trạng health
hiển thị PostgreSQL nhưng mutation vẫn ghi ngầm vào JSON.

## Các chức năng dữ liệu còn thiếu so với scope

| Chức năng | Trạng thái | Việc cần triển khai |
|---|---|---|
| Session/message local persistence | Có | thay JSON bằng repository PostgreSQL khi chuyển production |
| PDF immutable + hash | Có ở local | object storage key/version, checksum reconciliation |
| Extraction text + numeric bbox | Có cho PDF text/layout table đơn giản | OCR, bảng phức tạp, extraction revision và retryable worker |
| Retrieval + claim quote validation | Có | vector/hybrid index chỉ là index phụ, DB vẫn là truth |
| Client text highlight | Có | persisted server `source_regions.bbox` cho layout/OCR còn thiếu |
| Deterministic growth calculator | Có | mở rộng operation registry: sum, difference, pp, ranking, ties |
| Evidence correction | Có trong domain/reference flow | nối vào uploaded-document chat và PostgreSQL revision transaction |
| Answer revision/recalculation | Có trong domain fixture | nối worker thật, lease, stale fence, idempotency |
| Job durability | Thiếu | bảng jobs + `FOR UPDATE SKIP LOCKED`, heartbeat, retry, DLQ |
| Ownership/authentication | Thiếu ở local demo | user/session auth, composite owner FK, 404 hidden access |
| Idempotency cho upload/message | Thiếu ở local chat | `request_keys`, request hash, replay response |
| Retention/deletion | Thiếu | purge job, object cleanup, legal hold/audit policy |
| Observability | Một phần | structured audit table, metrics, provider latency/cost, redaction |
| Multi-process consistency | Thiếu | PostgreSQL transaction; không dùng JSON catalog production |

## Quy tắc chuyển từ local sang production

1. Giữ API contract và `document_id/message_id` ổn định.
2. Viết repository PostgreSQL phía sau cùng application ports; không đổi domain
   rule để phù hợp với database.
3. Migrate metadata trước, copy PDF/extraction artifact theo hash, rồi bật
   read-after-write verification.
4. Chạy dual-read chỉ trong migration window; không dual-write vô thời hạn.
5. Chỉ bật worker production sau khi test migration trên database rỗng và có
   fixture, cùng test crash/retry/stale lease.

## Kiểm thử persistence bắt buộc

- restart API sau upload/question: message và PDF vẫn đọc được;
- hai request đồng thời cùng `Idempotency-Key`: chỉ một business effect;
- hai editor dùng revision cũ: request sau nhận `409 revision_conflict`;
- worker crash trước publish: retry không tạo answer revision trùng;
- xóa document: metadata, object và extraction artifact được reconcile;
- mất Redis: request đọc được từ PostgreSQL, không mất state;
- hash PDF/extraction trước và sau migration không đổi.
