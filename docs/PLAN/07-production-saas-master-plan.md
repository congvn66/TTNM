# Kế hoạch nâng cấp SourceLens thành SaaS gần production

> Trạng thái: **Proposed - chờ duyệt**  
> Phạm vi của tài liệu: thiết kế và chia việc; **chưa cho phép triển khai code**.  
> Baseline: branch `migration`, frontend React/Vite, backend FastAPI modular monolith, PostgreSQL là đích lưu trữ nhưng runtime còn phần local JSON.

## 1. Kết luận review hiện trạng

Nhận định "mọi thứ nằm trong `App.jsx`" chưa hoàn toàn chính xác:

- `apps/web/src/app/App.jsx` chỉ là lớp composition nhỏ.
- Điểm gộp thật sự là `features/workspace/WorkspaceScreen.jsx`: đang chứa page shell, tải dữ liệu, PDF reader, chat, evidence, audit drawer và nhiều trạng thái UI.
- Backend đã có khung `api/application/domain/infrastructure/worker`, nhưng `api/main.py` vẫn quá lớn: route, orchestration, local persistence, extraction và AI provider bị trộn.
- PostgreSQL schema đã được thiết kế một phần, nhưng runtime chưa dùng database làm source of truth cho toàn bộ luồng.
- Trace/audit thử nghiệm đang lộ ra UI người dùng. Đây là công cụ debug, không phải tính năng sản phẩm.

Vì vậy, mục tiêu không phải "chia nhiều component cho đẹp tree" mà là tách theo ownership, lifecycle dữ liệu và ranh giới giao dịch.

## 2. Mục tiêu sản phẩm

Sau chương trình này, SourceLens phải có:

1. Đăng ký, đăng nhập, đăng xuất, khôi phục mật khẩu và session an toàn.
2. Library quản lý project, folder, PDF và version; hỗ trợ tạo, đổi tên, di chuyển, archive, restore và xóa theo chính sách.
3. Workspace đọc PDF, hỏi AI, theo dõi job và mở citation; không hiển thị audit flow nội bộ.
4. Light/dark/system theme đồng nhất và lưu preference.
5. AI/extraction chạy qua durable job, worker và retry; HTTP request không giữ kết nối trong suốt thời gian model xử lý.
6. PostgreSQL là source of truth; binary PDF nằm ở object storage; API/worker không dùng JSON local làm runtime chính.
7. Frontend có loading, empty, error, retry, offline/reconnect và accessibility states đầy đủ.

## 3. Ngoài phạm vi của đợt này

- Không tách microservice.
- Không thêm Redis trước khi PostgreSQL queue có số đo chứng minh là nút thắt.
- Không xây hệ thống organization/RBAC nhiều tầng; phiên bản đầu chỉ có personal workspace và owner boundary.
- Không triển khai payment, subscription, billing provider hoặc paywall.
- Không sửa byte của PDF tại chỗ; "sửa PDF" luôn tạo `document_version` mới.
- Không big-bang rewrite toàn bộ JSX sang TypeScript trong một pull request.
- Không giữ audit/trace drawer trong product UI. Correlation ID và structured log vẫn được giữ cho vận hành.

## 4. Kiến trúc đích

```text
Browser
  -> React SPA
       -> FastAPI API process
            -> PostgreSQL: metadata, auth, jobs, settings
            -> S3-compatible storage: original PDF, derived artifacts
            -> AIProvider adapter -> model provider
       -> SSE/polling job status

Worker process (cùng codebase)
  -> claim PostgreSQL jobs bằng SKIP LOCKED + lease
  -> đọc object storage
  -> extraction / retrieval / AI / validation
  -> publish kết quả nếu lease và revision fence còn hợp lệ
```

Kiến trúc vẫn là **modular monolith**: một codebase, hai process deploy (`api`, `worker`). Đây là mức phức tạp phù hợp đồ án và demo gần production; vẫn đủ ranh giới để thay provider hoặc tách service sau này.

## 5. Các quyết định bắt buộc

| Chủ đề | Quyết định |
|---|---|
| Authentication | Opaque server session trong cookie `HttpOnly`, không JWT trong localStorage |
| Tenant ownership | `owner_id` lấy từ session phía server; không tin `owner_id` từ client |
| Runtime database | PostgreSQL là source of truth |
| File storage | Object storage; DB chỉ lưu metadata, checksum và object key |
| Queue | Bảng `jobs` trong PostgreSQL, claim bằng `FOR UPDATE SKIP LOCKED` và lease |
| PDF update | Immutable `document_version`; rename chỉ đổi display name |
| UI server state | TanStack Query; state cục bộ giữ trong component/feature |
| Theme | Design tokens + `data-theme`, hỗ trợ light/dark/system |
| Resource limits | Policy server-side cho upload, storage và active jobs; không gắn payment |
| Observability | Structured logs + metrics + correlation ID; không có audit debug UI công khai |
| Functional icons | SVG/icon component; PNG/WebP chỉ dùng cho illustration/decorative item art |

## 6. Thứ tự triển khai

### Phase 0 - Contract và decomposition

- Chốt API contract, data model và migration cho auth, folders và jobs.
- Tạo app factory/router boundaries ở backend.
- Tách frontend shell, route và shared API client mà chưa đổi hành vi.
- Bổ sung characterization tests cho luồng hiện có.

**Gate:** build/test hiện tại vẫn pass; không thay behavior ngoài ý muốn.

### Phase 1 - PostgreSQL và authentication

- Chuyển repository runtime từ JSON local sang PostgreSQL.
- Triển khai user/session/password reset.
- Bắt buộc owner check ở mọi read/write.
- Thêm profile/settings/preferences.

**Gate:** restart API không mất dữ liệu; test IDOR, session rotation, CSRF và logout pass.

### Phase 2 - Library, folders và document versions

- Folder tree theo project.
- Upload, rename display name, move, archive, restore, purge.
- Upload replacement tạo version mới và enqueue extraction.
- Bulk action, search, sort và job status trong library.

**Gate:** mọi thao tác file có transaction, concurrency guard và E2E test.

### Phase 3 - Durable jobs và worker

- Chuyển extraction và AI answer khỏi request/background task sang durable job.
- Lease, heartbeat, retry, cancel, supersede và stale-result guard.
- UI nhận trạng thái bằng SSE, fallback polling.

**Gate:** kill/restart worker không làm mất job hoặc publish kết quả cũ.

### Phase 4 - Frontend production UX

- Route: Login, Library, Workspace và Settings.
- Refactor `WorkspaceScreen` theo feature/component boundaries.
- Light/dark/system, responsive, keyboard/focus, skeleton/error/empty states.
- Gỡ audit drawer và nội dung thử nghiệm khỏi product UI.

**Gate:** component, integration, E2E và visual regression light/dark pass.

### Phase 5 - Visual assets và polish

- Bộ illustration riêng cho empty/upload/processing/error.
- Performance budget, lazy load, telemetry và accessibility audit.

**Gate:** asset manifest, dark-mode QA và Lighthouse/Playwright baseline đạt yêu cầu.

## 7. Critical path và dependency

```text
Contracts + migration
  -> PostgreSQL repositories
  -> authentication + ownership
  -> library/folder/version model
  -> durable jobs
  -> async AI workspace
  -> visual polish and rollout
```

Không làm file manager trước khi chốt semantics version/delete; không làm AI queue UI trước khi job state machine ổn định.

## 8. Backlog cấp chương trình

| ID | Hạng mục | Phụ thuộc | Tài liệu chi tiết |
|---|---|---|---|
| SAAS-001 | Backend modularization | - | `12-backend-modularization-plan.md` |
| SAAS-002 | Frontend architecture | SAAS-001 contract | `08-frontend-architecture-plan.md` |
| SAAS-003 | Auth/settings/theme | PostgreSQL repository | `09-auth-settings-theme-plan.md` |
| SAAS-004 | Library/file/folder/version | Auth/ownership | `10-library-file-folder-plan.md` |
| SAAS-005 | Durable AI/extraction jobs | PostgreSQL + object storage | `11-async-jobs-worker-plan.md` |
| SAAS-006 | Custom visual assets | Design tokens stable | `13-visual-assets-plan.md` |
| SAAS-007 | Test/rollout | tất cả phase | `14-test-rollout-plan.md` |

## 9. Definition of Done cấp sản phẩm

- Không còn runtime business data trong JSON local.
- API restart, worker restart và browser refresh không làm mất trạng thái hợp lệ.
- Mọi tài nguyên đều có ownership check server-side.
- Upload/replace/delete/AI answer đều idempotent hoặc có idempotency key.
- Kết quả worker cũ không ghi đè data revision mới.
- Người dùng thấy trạng thái xử lý rõ ràng; không thấy raw payload/audit nội bộ.
- Theme, keyboard, loading/error/retry hoạt động ở mọi route chính.
- Không có secret trong frontend bundle/log; không lưu card data.
- Migration, rollback strategy, fixtures và runbook được cập nhật cùng code.

## 10. Các điểm cần duyệt

1. Chấp thuận modular monolith + hai process API/worker.
2. Chấp thuận PostgreSQL queue trước Redis.
3. Chấp thuận project là workspace cấp cao, folder là cây bên trong project.
4. Chấp thuận PDF immutable theo version; không sửa file gốc tại chỗ.
5. Chấp thuận bỏ audit/debug flow khỏi product UI nhưng giữ internal telemetry.
6. Chấp thuận không triển khai payment/subscription trong phạm vi hiện tại.
7. Chấp thuận SVG cho functional icons, PNG/WebP cho illustration.
