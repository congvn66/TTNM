# Kế hoạch test, migration và rollout

> Trạng thái: Proposed - chờ duyệt. Mục tiêu là nâng cấp từng lát dọc mà hệ thống luôn chạy được.

## 1. Test pyramid theo rủi ro

| Lớp | Mục đích | Công cụ đề xuất |
|---|---|---|
| Domain/unit | invariant, calculation, normalization, state machine | pytest / Vitest |
| Contract | repository/provider/API schema cùng hành vi | pytest parametrized, OpenAPI snapshot |
| Integration | PostgreSQL, object storage, worker lease, transaction | pytest + Docker/Testcontainers/Compose |
| Component | UI state/keyboard/error | Testing Library + Vitest |
| E2E | user journey thật | Playwright |
| Visual | light/dark/responsive/PDF overlay | Playwright screenshot |
| Load/recovery | queue, provider concurrency, restart | k6/Locust + scripted process restart |

Unit test pass không thay thế PostgreSQL concurrency test.

## 2. Baseline trước refactor

Trước khi di chuyển code:

1. Snapshot OpenAPI và route inventory.
2. E2E smoke: upload PDF -> extraction ready -> hỏi -> citation jump.
3. Fixtures cho text, table, chart, OCR và malformed PDF.
4. Characterization tests cho evidence revision và numeric answer links.
5. Ghi baseline bundle size, first load, job latency và error rate.

Như vậy refactor router/component có thể chứng minh không làm đổi hành vi ngoài kế hoạch.

## 3. Ma trận acceptance theo feature

### Authentication/settings

- Register/login/logout/session refresh/revoke.
- Forgot/reset token expiry/reuse.
- CSRF, cookie flags, rate limit và account enumeration.
- Cross-owner IDOR cho mọi resource.
- Theme light/dark/system không flash và lưu đúng.

### Library/folder/version

- Folder create/rename/move/archive/restore; duplicate/cycle/conflict.
- Document upload/rename/move/bulk/archive/restore.
- Replace tạo version mới; old bytes/extraction/citation vẫn bất biến.
- Upload interrupted/retry/duplicate complete/checksum mismatch.
- Purge blocked khi đang tham chiếu và idempotent khi retry.

### Jobs/worker

- Concurrent claim không double-process.
- Lease expiry/reclaim/heartbeat/lost lease.
- Retry backoff/max attempts/cancel/supersede.
- Revision fence không publish stale result.
- API/worker restart giữa job không mất command.
- Queue overload/per-owner concurrency limit.

### Chat/PDF/evidence

- User message xuất hiện ngay và giữ đúng order.
- Queued/running/retry/fail/succeeded placeholder.
- Structured answer render heading/list/table/formula/citation.
- Citation jump đúng page/normalized bbox qua zoom/resize/fullscreen.
- Evidence quote validation; không publish claim sai context.
- User sửa số: giữ giá trị gốc, giá trị mới, history và answer links.

### UI quality

- ErrorBoundary từng panel và route.
- Loading/skeleton/empty/no-results/offline/reconnect.
- Keyboard/focus/dialog/menu/drag alternative.
- Light/dark visual snapshots ở desktop/tablet/mobile.
- UTF-8 tiếng Việt từ DB/API/HTML/PDF/chat.

## 4. Contract tests

### Repository contract

Chạy cùng suite cho adapter tạm và PostgreSQL trong thời gian migration:

- owner scoping;
- not-found/conflict semantics;
- idempotency;
- transaction rollback;
- optimistic concurrency;
- append-only revision/history;
- deterministic ordering/pagination.

Sau khi parity đạt và runtime PostgreSQL ổn định, xóa adapter JSON khỏi production composition; không giữ hai source of truth.

### Job handler contract

Mỗi handler có:

- typed payload validation;
- success result reference;
- retryable/terminal error mapping;
- idempotent replay;
- cancellation checkpoint;
- stale revision behavior.

### API contract

- OpenAPI snapshot review.
- Problem details/error code ổn định.
- JSON schema cho structured answer/job status.
- Backward compatibility trong một migration window; remove endpoint có note rõ.

## 5. Test data và fixtures

```text
tests/fixtures/
├── pdf/
│   ├── native-text.pdf
│   ├── scanned-vietnamese.pdf
│   ├── merged-table.pdf
│   ├── chart-labels.pdf
│   ├── chart-axis-estimate.pdf
│   ├── rotated-pages.pdf
│   └── corrupted.pdf
├── ai/
│   ├── structured-answer-valid.json
│   ├── citation-invalid.json
│   └── provider-errors.json
└── jobs/
    ├── stale-revision.json
    └── retry-sequence.json
```

Fixture nhỏ, có license/source và expected extraction snapshot. Không dùng tài liệu nhạy cảm thật trong CI.

## 6. Database migration gates

Mỗi schema change phải có:

- Alembic migration forward;
- rollback hoặc documented irreversible strategy;
- model/repository/schema docs cập nhật;
- backfill command idempotent nếu cần;
- test upgrade từ baseline data;
- verify constraint/index sau migration;
- plan cho zero/low downtime phù hợp scope.

Không cutover runtime bằng cách chỉ đổi `DATABASE_URL`; repository path và integration tests phải pass trước.

## 7. Frontend quality gates

- `npm run build` không warning nghiêm trọng hoặc bundle tăng ngoài budget.
- Lint/typecheck/unit/component pass.
- Playwright E2E Chrome; smoke thêm Firefox nếu PDF support cần.
- Initial login/library chunk không chứa PDF.js.
- Không có raw request/audit payload trong production bundle/UI.
- Axe/accessibility scan không có critical/serious issue ở route chính.
- Screenshot baselines ở 1440, 1024 và 390 px cho light/dark.

## 8. Backend quality gates

- Format/lint/typecheck/unit/integration pass.
- Dependency rule test chặn domain/application import infrastructure/api.
- PostgreSQL tests chạy transaction/race thật.
- Object storage fake contract và local S3-compatible integration pass.
- Worker graceful shutdown, reclaim và stale publish tests pass.
- Secret scan; no sensitive log fixtures.
- Liveness không phụ thuộc provider ngoài; readiness kiểm tra dependency thiết yếu có timeout.

## 9. Recovery và load scenarios

### Recovery drills

- Kill API sau commit trước response; retry client không duplicate.
- Kill worker sau external AI response trước publish; replay idempotent.
- PostgreSQL disconnect ngắn; worker backoff không busy-loop.
- Object storage timeout; version không bị đánh ready.
- Browser SSE disconnect; polling/reconnect khôi phục state.

### Load targets ban đầu

Targets cần benchmark rồi chốt, không hứa số giả. Baseline đề xuất cho demo:

- API metadata p95 < 300 ms trên local/staging không tính upload bytes.
- Enqueue command p95 < 500 ms.
- 20 upload/job commands đồng thời không làm API health timeout.
- Worker concurrency cấu hình được và không double-claim.
- Queue age/progress/failure quan sát được.

## 10. Rollout theo vertical slice

### R0 - Safety net

Characterization/OpenAPI/E2E baseline; chưa đổi runtime.

### R1 - Backend shell

App factory/routers/handlers mới sau cùng endpoint; compare response bằng tests.

### R2 - PostgreSQL/auth

Migrate schema và owner-scoped repositories. Dev/staging chạy PostgreSQL-only trước local default switch.

### R3 - Library/version

Feature flag UI mới; migrate/import local data nếu cần. Không xóa dữ liệu cũ cho tới verify count/checksum.

### R4 - Worker jobs

Chuyển extraction trước, AI sau. Theo dõi queue/retry/failure; có rollback composition nhưng không dual-write kéo dài.

### R5 - New UI/theme/assets

Enable route theo feature flag; visual/E2E pass; remove old audit UI.

### R6 - Cleanup

Xóa JSON runtime, compatibility endpoints, dead CSS/components và flags đã ổn định. Cập nhật README/runbook/architecture.

## 11. Release checklist

- Migration backup/restore đã thử.
- Config/secrets/allowed hosts/CORS/cookie HTTPS đúng.
- API và worker revision tương thích schema.
- Object storage bucket private và lifecycle policy đúng.
- Queue dashboards/alerts/runbook có sẵn.
- Test account và smoke PDF không chứa dữ liệu thật.
- Rollback trigger và owner quyết định rõ.
- README có lệnh dev/test/migrate/worker.

## 12. Definition of Done

- CI chạy unit, contract, integration, component và E2E phù hợp.
- Mọi feature mới có acceptance test theo failure/race/ownership, không chỉ happy path.
- PostgreSQL/object storage/worker recovery đã được drill.
- UI light/dark/responsive/accessibility/UTF-8 đã được kiểm tra.
- Dọn code cũ chỉ sau khi có bằng chứng parity và backup.

