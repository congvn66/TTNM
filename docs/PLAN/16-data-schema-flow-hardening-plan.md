# Plan 16 — Củng cố data schema, data flow và tool compatibility

Trạng thái: **Đã triển khai P0.1–P0.5; P1 còn lại**  
Thiết kế nguồn: `docs/data-design-hardening.md`.

## 1. Nguyên tắc triển khai

- Sửa theo lát cắt dọc: contract → validator → persistence → flow → test → docs.
- Không đổi nghĩa schema đã phát hành nếu không tăng major version.
- Mỗi migration có upgrade, downgrade và test trên DB rỗng + DB có fixture.
- Không bật provider thật trong unit/contract test.
- Không đưa chart value vào calculator trước khi có revision ID bền vững.

## 2. Thứ tự thực hiện

### P0.1 — Đồng bộ evidence status

Phạm vi:

- Domain enum nhận `valid|missing|unreadable|ambiguous|error`.
- Migration thay CHECK của `extracted_evidences` và `evidence_revisions`.
- Producer mới phát `value_kind`; runtime giữ `value_kind=number` cho numeric evidence null và validator vẫn đọc artifact v2 cũ thiếu field này.
- Initial revision copy đúng status và semantic.

File dự kiến:

- `domain/types.py`, `domain/contracts.py`, `domain/models.py`;
- migration `0007_extraction_contract_hardening.py`;
- `revision_store.py`, `runtime_store.py`;
- unit + PostgreSQL integration tests.

Nghiệm thu:

- Bốn fixture `valid=0`, `missing`, `unreadable`, `ambiguous` persist được.
- Ba status không valid không có effective numeric value.
- Số 0 không bị coi là missing.

### P0.2 — Contract validation thống nhất

Phạm vi:

- JSON Schema và semantic validator kiểm tra cùng tập invariant.
- Vector chart output bổ sung trigger, period, locator và proof metadata.
- Warning chỉ tham chiếu evidence key tồn tại.
- Base extraction không publish chart on-demand.

Nghiệm thu:

- Payload pass semantic validator thì cũng pass JSON Schema.
- Negative test cho invalid bbox, status/value mismatch, chart ngoài trigger,
  axis tick đảo và table locator thiếu.

### P0.3 — Persist chart on-demand

Phạm vi:

- `extraction_runs` bổ sung contract/scope/trigger/tool metadata.
- Dùng đúng `document_version_id`.
- Chart batch tạo run, region, evidence, chat source và initial revision trong
  một transaction.
- Resolver chạy lần hai với revision UUID thật.
- Answer publisher ghi `answer_inputs` và `answer_scopes`.

Nghiệm thu:

- Query từ answer input truy ngược tới chart region, run, document version và
  PDF bbox.
- Persistence fail thì calculator không dùng chart value.
- Retry cùng plan/region không tạo duplicate completed run.

### P0.4 — Idempotency và stale publish

Phạm vi:

- Không cho upsert thay request hash.
- Worker publish kiểm lease, owner và input data revision trước khi commit; việc gộp queue state và answer commit trong một DB transaction vẫn là P1 hardening.
- Stale job chuyển `superseded`, không dùng `failed` chung chung; queue có event
  `superseded` và không retry lại snapshot cũ.

Nghiệm thu:

- Race tests: duplicate request, lost lease, evidence edit trong lúc answer chạy.

### P0.5 — Tool invocation envelope

Phạm vi:

- Thêm `contracts/tool-invocation-v1.schema.json` và example.
- Adapter helper tạo canonical payload hash và redacted metadata.
- Docling, DePlot và AI provider dùng cùng status/error taxonomy.
- Trace/API không trả secret hoặc raw provider response.

Nghiệm thu:

- Có thể thay fake tool bằng Docling/DePlot mà orchestrator không đổi payload
  nghiệp vụ.
- Failed/rejected invocation luôn có stable error code và `retryable`.

### P1.1 — Document profile

Phạm vi:

- Thêm `document-profile-v1`.
- Phân loại page native/scanned/mixed/blank; lưu rotation/dimension/hash.
- OCR chỉ chạy vùng/trang cần thiết.

Nghiệm thu:

- Fixture scan, mixed, rotated, blank và encrypted có trạng thái đúng.

### P1.2 — Evidence v3 và bảng phức tạp

Phạm vi:

- Phát hành `document-evidence-v3`, không mutate meaning của v2.
- Canonical semantic/unit; header path; merged span; continued table.
- Viết adapter v2 → v3 chỉ cho trường hợp chuyển đổi không mất thông tin.

Nghiệm thu:

- Merged header và bảng qua trang không mất locator.
- Conversion không chắc chắn trả warning/review, không tự điền.

## 3. Migration database

Migration P0 phải:

1. Drop đúng CHECK constraint cũ theo tên.
2. Add CHECK mới cho năm evidence status.
3. Add invariant value null/non-null tương ứng.
4. Add extraction contract/scope/trigger/tool metadata với default tương thích
   dữ liệu cũ.
5. Backfill run cũ là `base_document`, contract legacy version 1.
6. Tạo index cho `(document_version_id, scope, created_at desc)`.
7. Tạo dedup index chart theo document version + question plan khi completed.

Downgrade chỉ được chạy khi không có row `ambiguous|unreadable` hoặc chart run;
nếu có phải fail với thông báo rõ, không ép dữ liệu về `error` âm thầm.

## 4. Test matrix bắt buộc

| Lớp | Test |
|---|---|
| JSON Schema | example hợp lệ; unknown field; status/value mismatch; trigger thiếu |
| Domain | zero/missing/unreadable/ambiguous; bbox; unit; period |
| Adapter | native text; OCR; merged table; direct label; axis estimate; timeout |
| DB | migration up/down; immutable completed run; revision FK; chart provenance |
| Queue | retry, lost lease, max attempt, stale revision, cancel |
| API | idempotency reuse; extraction not ready; clarification; provider failure |
| E2E | upload → worker → ask → citation; edit → stale → recalc |

Test không được gọi mạng. Live adapter test là suite riêng, opt-in bằng biến môi
trường và không được dùng làm bằng chứng duy nhất cho correctness.

## 5. Rollout

1. Merge contract và validator dưới feature flag, đọc được payload cũ.
2. Apply migration và chạy DB smoke query.
3. Deploy worker mới trước API mới để worker hiểu field mới.
4. Bật persist chart on-demand cho internal/demo account.
5. Theo dõi schema rejection, ambiguous rate, retry rate và stale publish.
6. Mở rộng dần; rollback flag không rollback dữ liệu lịch sử.

## 6. Definition of Done

- Tất cả tiêu chí trong mục 12 của thiết kế nguồn pass.
- Migration được kiểm tra trên PostgreSQL thật, không chỉ mock.
- Không còn evidence revision ID giả trong answer input.
- Không có tool/provider-specific field rò vào domain ngoài adapter/envelope.
- `docs/data-model.md`, `processing-flows.md`, contract README và OpenAPI được
  cập nhật theo implementation thực tế.
- Có báo cáo test ghi đúng lệnh, số test pass/skip và lớp chưa chạy được.
