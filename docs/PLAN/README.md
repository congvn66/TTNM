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

Đã hoàn tất P0 cutover cho session/document/extraction/evidence/message metadata
qua `PostgresRuntimeStore`, migration `0001` + `0002` và smoke test trên Supabase.
Còn thiếu: object-storage adapter, durable worker lease/race thật, auth/ownership
và full JSON Schema validator cho production.

## 2. Tài liệu trong PLAN

| Tài liệu | Mục đích |
|---|---|
| [01-code-review.md](01-code-review.md) | Nhận xét code, điểm mạnh, lỗi/rủi ro theo P0/P1/P2 |
| [02-implementation-roadmap.md](02-implementation-roadmap.md) | Thứ tự triển khai từ skeleton đến vertical slice chạy với PostgreSQL |
| [03-data-and-migration-plan.md](03-data-and-migration-plan.md) | Kế hoạch đồng bộ domain model, DDL, repository, transaction và migration |
| [04-test-plan.md](04-test-plan.md) | Test matrix, race/failure cases và quality gates |
| [05-execution-backlog.md](05-execution-backlog.md) | Backlog task có ID, dependency, đầu ra và Definition of Done |
| [06-p0-data-foundation-execution-plan.md](06-p0-data-foundation-execution-plan.md) | Kế hoạch P0 chi tiết để chuyển luồng session/document sang PostgreSQL, object storage, durable jobs và revision graph |
| [07-production-saas-master-plan.md](07-production-saas-master-plan.md) | Master plan nâng cấp sản phẩm gần production; trạng thái Proposed, chờ duyệt |
| [08-frontend-architecture-plan.md](08-frontend-architecture-plan.md) | Frontend routes, feature/component boundaries, design system, theme và migration khỏi WorkspaceScreen monolith |
| [09-auth-settings-theme-plan.md](09-auth-settings-theme-plan.md) | Authentication, server session, ownership, settings và light/dark/system theme |
| [10-library-file-folder-plan.md](10-library-file-folder-plan.md) | Project/folder tree, document actions, immutable PDF versions, archive/restore/purge và object storage |
| [11-async-jobs-worker-plan.md](11-async-jobs-worker-plan.md) | Durable PostgreSQL queue, worker lease, retry, cancellation, AI/extraction jobs và xử lý tải |
| [12-backend-modularization-plan.md](12-backend-modularization-plan.md) | Tách FastAPI main monolith thành app factory, routers, use cases, ports, adapters và worker |
| [13-visual-assets-plan.md](13-visual-assets-plan.md) | Visual system, functional SVG icons, custom PNG/WebP illustrations và asset pipeline |
| [14-test-rollout-plan.md](14-test-rollout-plan.md) | Test matrix, migration gates, recovery/load drills và rollout theo vertical slice |
| [../production-saas-audit.md](../production-saas-audit.md) | Audit bàn giao UI/API, checklist flow và các gap cần đóng trước staging |
| [17-persistence-security-and-cleanup-plan.md](17-persistence-security-and-cleanup-plan.md) | P0 kiểm chứng Supabase/R2, hardening quyền truy cập, purge và cleanup runtime |

## 2.1 Proposal gần production đang chờ duyệt

Các tài liệu `07`-`14` là đề xuất mới, chưa phải xác nhận đã triển khai. Phạm vi đã loại bỏ payment, subscription, billing provider và paywall. Giới hạn upload/storage/job nếu có chỉ là policy bảo vệ vận hành.

Thứ tự duyệt khuyến nghị:

1. `07` để chốt scope và các quyết định kiến trúc.
2. `12`, `09`, `10`, `11` để chốt backend/data/worker contracts.
3. `08`, `13` để chốt product UX và art direction.
4. `14` để chốt quality gates và rollout.

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
