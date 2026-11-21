# Code review backend data flow

Ngày review: 2026-11-02.

## 1. Kết luận

Code hiện tại là executable skeleton tốt: flow chính đọc được, revision history và stale-result fence đã được biểu diễn, dữ liệu số không đi qua binary float, và test chạy offline nhanh. Tuy nhiên code chưa phải production foundation. Trước khi thêm FastAPI/SQLAlchemy cần sửa ranh giới persistence, transaction và ownership; nếu không adapter PostgreSQL sẽ bị ép mô phỏng cách truy cập dictionary hiện tại và tạo nợ kiến trúc ngay từ migration đầu.

Đánh giá tổng quát:

| Mặt | Nhận xét |
|---|---|
| Domain intent | Tốt; phản ánh append-only revision, missing khác zero, lease/fence |
| Layering | Có cấu trúc thư mục đúng, nhưng application vẫn phụ thuộc storage shape |
| Data integrity | DDL mạnh hơn implementation; một số FK/ownership chưa được flow kiểm tra |
| Transaction | Có adapter rollback thử nghiệm nhưng flow chưa sử dụng UoW |
| Contract | Có core validation, chưa tương đương đầy đủ JSON Schema |
| Test | Baseline hữu ích, coverage production flow/race còn mỏng |
| Production readiness | Chưa; phù hợp làm executable specification và nền refactor S0/S1 |

## 1.1 Cập nhật sau Wave 1

Các điểm sau đã được xử lý ở mức in-memory/application boundary:

- `CR-P0-01`: port đã typed và flow không còn đọc `repo.state`.
- `CR-P0-02`: UoW wrapper đã bao phủ các mutation flow chính; cần PostgreSQL rollback/race test.
- `CR-P0-03`: upload kiểm tra document owner; attach evidence kiểm tra owner/source/run.
- `CR-P0-04`: source switch chỉ thay source được chỉ định.
- `CR-P0-05`: request hash khác nhau trả conflict trong adapter.
- `CR-P0-06`: extraction validation failure rollback data và chuyển run sang `failed`.
- `CR-P0-07`: lease expiry/attempt/reclaim đã có ở worker skeleton; chưa có DB lock/reclaim race.

Vì vậy các mục P0 bên dưới vẫn được giữ như exit criteria production, nhưng phần còn lại đã chuyển từ “chưa có code” sang “cần adapter/integration proof”.

## 2. Điểm làm tốt

1. `domain/` không import FastAPI, SQLAlchemy hoặc provider SDK.
2. `EvidenceRevision` và `AnswerRevision` đi theo append-only; current pointer tách khỏi lịch sử.
3. `AnswerFlow.publish` kiểm tra lease và `input_data_revision`, đúng hướng chống stale worker publish.
4. Decimal dùng string + `Decimal`; `0`, `missing`, `NaN/Infinity` được phân biệt.
5. Provider payload, semantic payload và bbox có validation core trước khi thành domain data.
6. `schema.py` làm inventory đủ 23 bảng và ownership module, hữu ích để kiểm tra drift.
7. Fixture/reference tests đang bảo vệ các hành vi khó: cross-owner, stale edit, restore, dependency scope và zero denominator.

## 3. P0 - phải sửa trước PostgreSQL/API adapter

### CR-P0-01: Repository port làm lộ storage state

`DataRepository.state` có kiểu `Any`; application và worker đọc/ghi trực tiếp dictionary ở nhiều nơi. Vì vậy port chưa thực sự là abstraction, không thể map sạch sang transaction/row lock của PostgreSQL.

Hướng xử lý:

- Tách repository theo aggregate/use case: document, extraction, chat, evidence, answer, job, idempotency.
- Application chỉ gọi method có semantics (`lock_chat`, `append_revision`, `enqueue_job`), không đọc `repo.state`.
- Thêm `UnitOfWork` với `commit/rollback` và transaction context.

Exit gate: không còn `repo.state` trong `application/` và `worker/`; type checker xác nhận port cụ thể.

### CR-P0-02: Flow chưa chạy trong transaction boundary

`InMemoryDataRepository.transaction()` tồn tại nhưng upload, submit question, evidence edit và answer publish không dùng nó. Lỗi ở bước cuối có thể để lại version/message/revision/pointer dở dang.

Các transaction bắt buộc:

- upload: version + extraction run + job + request key;
- submit question: two messages + job + request key + sequence counter;
- evidence edit: revision + pointer + data revision + affected flags + recalc jobs;
- answer publish: answer revision + inputs + scopes + pointer + job final event.

Exit gate: fault-injection test tại từng write point chứng minh rollback không để orphan/partial state.

### CR-P0-03: Ownership và FK integrity chưa đầy đủ

- Upload nhận `document_id` tùy ý, chưa bắt buộc document tồn tại và thuộc owner.
- `attach_evidence` không nhận owner, không kiểm tra `chat_source_id` tồn tại/cùng chat/cùng extraction run.
- Unit test đang truyền `uuid4()` làm source không tồn tại và vẫn pass; đây là false confidence rõ ràng.
- Complete extraction chưa gắn chặt với job lease/owner đang xử lý.

Exit gate: mọi read/write use case query theo owner; cross-owner trả `not_found`; attach sai source/run bị từ chối ở unit và DB FK test.

### CR-P0-04: Source switch đang vô hiệu hóa toàn bộ source active

`switch_source` lặp qua mọi source active của chat và chuyển inactive. Với chat dùng nhiều document, đổi version của một document sẽ vô hiệu hóa các document không liên quan.

Hướng xử lý: API/use case phải nhận `replaced_chat_source_id` hoặc logical document identity, chỉ thay source mục tiêu; source khác giữ nguyên.

Exit gate: test chat có hai document, switch version A không thay trạng thái B; answer history vẫn trỏ source cũ.

### CR-P0-05: Idempotency chưa kiểm tra request hash

In-memory request key dùng `request_hash="in-memory"`; cùng key nhưng payload khác vẫn trả response cũ. Response dataclass cũng không được lưu vào `RequestKey.response`, nên behavior chưa mô phỏng bảng `request_keys`.

Exit gate: cùng key + cùng canonical request hash replay đúng; cùng key + hash khác trả conflict; test expiration/concurrent retry có trong integration suite.

### CR-P0-06: Extraction failure có state transition hở

Run được chuyển `running` trước `validate_provider_payload`, nhưng validation nằm ngoài `try`; payload lỗi có thể làm run mắc ở `running`. Flow cũng chưa finalize extraction job hoặc phát event atomically.

Exit gate: mọi validation/persistence failure dẫn đến policy rõ (`failed` hoặc retry), không có partial regions/evidences, job/run event nhất quán.

### CR-P0-07: Job lease chưa đủ semantics của DDL

Model/handler chưa có lease expiry, attempts, max attempts, available time, reclaim và final timestamps. Token đúng nhưng lease hết hạn vẫn có thể publish. Claim theo job ID cũng chưa mô phỏng `FOR UPDATE SKIP LOCKED`.

Exit gate: claim/heartbeat/reclaim/publish đều kiểm tra token + expiry; retry giới hạn; expired worker không finalize được; có PostgreSQL race tests.

### CR-P0-08: Domain model và DDL đang drift

Ví dụ: code thêm `owner_id` vào `DocumentVersion`/`ExtractionRun` dù DDL không có; code bắt `Job.input_data_revision` luôn là int trong khi DDL cho phép null; tên `job_type` khác `jobs.kind`; `MessageStatus.NEEDS_UPDATE` không nằm trong check constraint; nhiều timestamp/state fields chưa có trong code.

Exit gate: có mapping matrix cho đủ 23 bảng; mỗi field được đánh dấu persisted/derived/snapshot; ORM/migration/contract test cùng vocabulary.

## 4. P1 - hoàn thành trước vertical slice answer/correction

### CR-P1-01: Contract validator chưa tương đương schema phát hành

Core validator chưa enforce đầy đủ `additionalProperties=false`, entity shape, period/status/date, value operator, dimensions type, extraction method và question/answer-scope contracts. Không nên duy trì hai validator có semantics khác nhau.

Hướng xử lý: dùng JSON Schema files làm canonical boundary validator; core domain chỉ giữ invariant vượt ngoài schema.

### CR-P1-02: Calculator còn thiếu operation

Mới có sum và growth rate. Cần lookup, difference, absolute change, percentage-point difference, compare, ranking, unit compatibility và structured undefined/error result. Growth output hiện chưa có display rounding policy riêng.

### CR-P1-03: Frozen dataclass chưa tạo immutable snapshot sâu

`EvidenceRevision`, `AnswerRevision`, `AnswerScope` frozen nhưng chứa mutable dict/mapping. Caller còn có thể sửa nested data sau khi lưu. Cần deep-copy/freeze khi tạo và serialize canonical JSON khi persist.

### CR-P1-04: Test implementation còn ít và có lỗ assertion

Năm test hiện tại chủ yếu là happy-path tổng hợp. Cần test trực tiếp cho stale publish, concurrent edit, wrong owner, invalid source/run, idempotency payload mismatch, scope-only invalidation, transaction rollback từng bước, lease expiry và duplicate worker.

### CR-P1-05: Page count không nên suy ra từ extracted region

`page_count=max(region.page_number)` và mặc định 1 có thể sai khi trang không sinh region. Page count phải đến từ PDF envelope/parser metadata độc lập.

## 5. P2 - cleanup và maintainability

- Tách `flows.py` theo bounded module/use case để tránh file orchestration lớn.
- Chuẩn hóa error object có code + safe context, không chỉ exception message.
- Loại `hasattr(add_job_event)`; event port phải explicit.
- Tránh hai đường ghi success event (`AnswerFlow.publish` và `WorkerHandlers.succeed_event`).
- Thêm formatter, linter, type checker và coverage gate sau khi có `pyproject.toml`.
- Loại `__pycache__` khỏi workspace artifact; `.gitignore` đã bao phủ nhưng cần clean ở CI/package.

## 6. Quyết định review

Không nối trực tiếp FastAPI/SQLAlchemy vào flow hiện tại. Bước tiếp theo là `S0 Contract freeze` và `S1 Application boundary refactor` trong roadmap. Sau S1, in-memory adapter và PostgreSQL adapter phải chạy cùng một repository contract test suite.
