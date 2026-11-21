# Kế hoạch modular hóa backend FastAPI

> Trạng thái: Proposed - chờ duyệt.

## 1. Đánh giá hiện trạng

Backend không hoàn toàn là một file: đã có `api`, `application`, `domain`, `infrastructure`, `worker`. Tuy nhiên `api/main.py` vẫn đang làm quá nhiều việc:

- khởi tạo app và middleware;
- khai báo nhiều schema/route;
- điều phối upload, extraction, retrieval, AI và revision;
- truy cập local session storage;
- chứa nhánh provider/fallback;
- map error/response không tập trung.

Kiến trúc đúng cho scope này là **layered modular monolith**, không phải microservice. Layer kiểm soát hướng dependency; module kiểm soát lifecycle nghiệp vụ.

## 2. Dependency rule

```text
api -> application -> domain
                 \-> ports
infrastructure -> ports/domain
worker -> application/ports
```

- Domain không import FastAPI, SQLAlchemy, provider SDK hoặc file system.
- Application không import concrete Postgres/S3/AI adapter.
- API chỉ parse/auth/call use case/map response.
- Infrastructure implement ports.
- Worker gọi cùng application use case/handler, không duplicate business logic.

## 3. Tree đích

```text
services/backend/src/report_qa/
├── api/
│   ├── app.py
│   ├── dependencies.py
│   ├── errors.py
│   ├── middleware/
│   │   ├── correlation.py
│   │   ├── auth.py
│   │   └── request_limits.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── projects.py
│   │   ├── folders.py
│   │   ├── documents.py
│   │   ├── conversations.py
│   │   ├── jobs.py
│   │   └── settings.py
│   └── schemas/
├── application/
│   ├── auth/
│   ├── library/
│   ├── extraction/
│   ├── conversations/
│   ├── evidence/
│   ├── jobs/
│   └── settings/
├── domain/
│   ├── identity/
│   ├── library/
│   ├── document_data/
│   ├── conversation/
│   └── jobs/
├── ports/
│   ├── repositories.py
│   ├── object_storage.py
│   ├── ai_provider.py
│   ├── extraction.py
│   ├── clock.py
│   └── unit_of_work.py
├── infrastructure/
│   ├── postgres/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── uow.py
│   │   └── migrations/
│   ├── object_storage/
│   ├── providers/
│   └── telemetry/
├── worker/
│   ├── main.py
│   ├── registry.py
│   ├── lease.py
│   └── handlers/
└── config.py
```

Không tạo repository/service class cho mọi bảng nếu không có lifecycle riêng. Module được tách vì invariant và transaction boundary, không chỉ để tăng số file.

## 4. App factory

`api/app.py` mục tiêu dưới khoảng 150 dòng và chỉ làm:

1. load/validate settings;
2. create FastAPI;
3. add middleware/error handlers;
4. include routers;
5. register lifespan startup/shutdown;
6. health/readiness endpoints.

Không khai báo business route implementation, SQL, extraction hoặc provider call trong app factory.

## 5. Router contract

Router mỗi resource/use case:

```python
@router.post("/{document_id}/questions", status_code=202)
def ask_question(
    document_id: UUID,
    body: AskQuestionRequest,
    user: CurrentUser,
    handler: AskQuestionHandlerDep,
) -> AskQuestionAccepted:
    return handler.execute(...)
```

Router không tự mở nhiều repository hoặc commit. Application handler sở hữu transaction qua UoW.

## 6. Application handlers

Mỗi command/query có input/output typed và transaction boundary rõ:

- `CreateUploadIntent`
- `CompleteUpload`
- `CreateFolder`
- `MoveDocument`
- `ReplaceDocumentVersion`
- `AskQuestion`
- `ReviseEvidence`
- `GetJobStatus`
- `UpdatePreferences`

Không biến mọi helper thành class. Pure function cho normalization/calculation/validation; handler cho orchestration và I/O.

## 7. Repository và Unit of Work

- Repository method owner-scoped mặc định.
- UoW mở transaction cho command, commit một lần, rollback tự động.
- Enqueue job cùng transaction với resource state.
- Query read-only có transaction/session ngắn.
- Không trả ORM model ra ngoài infrastructure; map sang domain/entity DTO.
- JSON local adapter chỉ được giữ tạm sau port để migration/characterization, sau đó xóa khỏi runtime composition.

## 8. Error model

Domain/application dùng typed errors:

```text
NotFound
Forbidden/OwnershipViolation
Conflict/RevisionConflict
ValidationFailure
ResourceLimitExceeded
ProviderUnavailable
JobNotRetryable
```

API map sang RFC 9457-style problem details:

```json
{
  "type": "https://errors.sourcelens.dev/revision-conflict",
  "title": "Dữ liệu đã thay đổi",
  "status": 409,
  "code": "revision_conflict",
  "correlation_id": "...",
  "details": {}
}
```

Không trả stack trace/provider raw error cho client.

## 9. Configuration

Một typed settings object, fail fast khi production thiếu biến bắt buộc:

- `APP_ENV`, `DATABASE_URL`, object storage config;
- auth cookie/session secrets;
- AI provider/model/timeouts;
- worker lease/concurrency/retry;
- upload/storage limits;
- CORS/allowed hosts/log level.

`VITE_*` chỉ dành dữ liệu public frontend. Backend secret không được copy sang frontend env.

## 10. Public API và audit cleanup

- Xóa route/UI công khai trả raw message trace, module event hoặc prompt context.
- Giữ correlation ID trên response và structured log nội bộ.
- Job API chỉ trả stage/status/error code an toàn.
- Nếu cần support tool sau này, tạo admin-only surface có auth/authorization và PII redaction; không dùng product route hiện tại.

## 11. Migration strategy không làm vỡ hệ thống

### Step 1 - Characterize

- Freeze OpenAPI snapshot và E2E happy path hiện tại.
- Thêm tests quanh upload, extraction, question, evidence revision.

### Step 2 - App factory/routers

- Move route theo nhóm mà không đổi handler behavior.
- `main.py` tạm re-export `app` để command cũ vẫn chạy.

### Step 3 - Use-case extraction

- Di chuyển orchestration khỏi router vào application handlers.
- Introduce dependency injection và typed errors.

### Step 4 - Infrastructure cutover

- Port local storage qua repository interface.
- Implement PostgreSQL/object storage adapter.
- Run repository contract tests cho cả adapter trong giai đoạn chuyển tiếp.

### Step 5 - Worker cutover

- Extraction/AI dùng durable jobs.
- Xóa in-process background task và local fake flow khỏi production composition.

### Step 6 - Cleanup

- Xóa compatibility code, dead endpoint, debug trace và schema trùng.
- Cập nhật architecture/data/API docs.

## 12. Task breakdown

1. BE-001: OpenAPI snapshot + characterization tests.
2. BE-002: app factory, middleware và error mapper.
3. BE-003: split routers/schemas/dependencies.
4. BE-004: auth/library/settings use-case handlers.
5. BE-005: conversations/evidence use-case handlers.
6. BE-006: repository/UoW ports và owner-scoped interface.
7. BE-007: PostgreSQL repositories + object storage adapter.
8. BE-008: jobs worker registry/handlers.
9. BE-009: remove JSON runtime, audit public endpoints và dead fallback.
10. BE-010: dependency rule/lint/import tests và docs.

## 13. Quality gates

- `api/app.py` chỉ composition; router không chứa SQL/provider/extraction.
- Không import infrastructure từ domain/application.
- Không endpoint nào trực tiếp dùng local JSON store.
- Migration và repository contract tests chạy trên PostgreSQL thật.
- OpenAPI breaking change được review, không xảy ra ngầm.
- API/worker có graceful shutdown và readiness khác liveness.
- Error/correlation/structured log thống nhất.
- Backend restart không làm mất session, upload, job, chat hoặc revision.

## 14. Definition of Done

- `main.py` monolith được thay bằng app factory + routers + handlers có boundary thật.
- PostgreSQL/object storage là runtime adapters mặc định.
- API và worker dùng cùng application/domain invariants.
- Audit/debug flow không còn trong public product contract.
- Tests chứng minh ownership, transaction, idempotency và recovery.

