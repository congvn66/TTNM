# Kế hoạch triển khai sau code review

## 1. Mục đích

Thư mục này chuyển kết quả review code hiện tại thành kế hoạch triển khai có thứ tự, đầu ra và exit gate. Đây là kế hoạch thực thi gần; roadmap sản phẩm tổng thể vẫn nằm ở `../delivery-roadmap.md`.

Trạng thái baseline tại thời điểm review (lịch sử, không phải trạng thái runtime hiện tại):

- Backend ban đầu là Python dependency-free, dùng dataclass và in-memory repository.
- Có 23-table metadata inventory, 4 JSON contracts và PostgreSQL DDL review.
- Có 5 backend flow tests và 13 executable reference/design tests.
- Các mục trên là gap của thời điểm review; hiện đã có package manifest, HTTP runtime, PostgreSQL compose/config và Alembic baseline. PostgreSQL repository/object-storage cutover vẫn còn thiếu.

## 1.1 Tiến độ sau Wave 1

Đã triển khai một phần backlog immediate-next:

- `ARCH-101`: typed repository facade; application/worker không còn đọc `repo.state`.
- `ARCH-102`: Unit of Work wrapper cho upload, extraction, question, evidence revision và answer publish.
- `PLAN-002`: source switch có `replaced_chat_source_id`, không deactive source không liên quan.
- `PLAN-003`: job lease có expiry, attempts, heartbeat, reclaim và retry limit cơ bản.
- `TEST-106`: repository contract tests cho idempotency hash, dedup job và rollback.

Chưa hoàn tất: mapping 23 bảng sang ORM/DDL, PostgreSQL adapter, lease race thật trên DB, full JSON Schema validator và API runtime.

## 2. Tài liệu trong PLAN

| Tài liệu | Mục đích |
|---|---|
| [01-code-review.md](01-code-review.md) | Nhận xét code, điểm mạnh, lỗi/rủi ro theo P0/P1/P2 |
| [02-implementation-roadmap.md](02-implementation-roadmap.md) | Thứ tự triển khai từ skeleton đến vertical slice chạy với PostgreSQL |
| [03-data-and-migration-plan.md](03-data-and-migration-plan.md) | Kế hoạch đồng bộ domain model, DDL, repository, transaction và migration |
| [04-test-plan.md](04-test-plan.md) | Test matrix, race/failure cases và quality gates |
| [05-execution-backlog.md](05-execution-backlog.md) | Backlog task có ID, dependency, đầu ra và Definition of Done |
| [06-p0-data-foundation-execution-plan.md](06-p0-data-foundation-execution-plan.md) | Kế hoạch P0 chi tiết để chuyển luồng session/document sang PostgreSQL, object storage, durable jobs và revision graph |

## 3. Thứ tự đọc và thực hiện

1. Chốt các P0 trong code review.
2. Thực hiện `S0` và `S1` trong implementation roadmap.
3. Chỉ tạo PostgreSQL adapter sau khi port/UoW và model-to-DDL mapping đã ổn định.
4. Triển khai từng vertical slice cùng integration/contract test; không hoàn thành toàn bộ ORM trước rồi mới nối flow.
5. Chỉ bắt đầu provider thật sau khi fake adapter, schema validation và privacy decision đã có gate.

## 4. Critical path

```text
P0 decisions
  -> repository ports + unit of work
  -> model/DDL alignment
  -> migration 0001 + PostgreSQL tests
  -> upload/extraction vertical slice
  -> question/answer vertical slice
  -> evidence correction/recalculation
  -> API/web/E2E hardening
```

## 5. Quy tắc cập nhật plan

- Task chỉ chuyển `Done` khi exit gate và test tương ứng đã chạy.
- Thay đổi contract/schema cần cập nhật data plan, migration, fixture và test trong cùng change.
- Quyết định làm đổi meaning dữ liệu, privacy hoặc topology phải có ADR.
- Không dùng in-memory test pass để thay thế PostgreSQL integration/race test.
