# Data, repository và migration plan

## 1. Mục tiêu

Biến DDL review hiện tại thành persistence implementation có thể migrate, test race và truy vết; giữ PostgreSQL là source of truth cho metadata/history và object storage cho binary/artifact lớn.

## 2. Việc phải chốt trước ORM

### 2.1 Model-to-table mapping

Tạo bảng mapping cho cả 23 table với các cột:

- code field;
- DB column/type/nullability/default;
- API representation;
- persisted hay derived;
- immutable, pointer hay mutable state;
- owner lookup path;
- validation layer: JSON Schema/app/DB.

Các drift cần xử lý trước:

| Chủ đề | Hiện tại | Quyết định cần đạt |
|---|---|---|
| Version/run owner | Code có `owner_id`, DDL dùng join | Chọn derived owner qua repository query hoặc denormalize có FK bảo vệ |
| Job revision | Code bắt buộc int, DDL nullable | Null cho job không gắn chat; non-null cho answer/recalc |
| Job naming | `job_type` và `kind` | Một vocabulary duy nhất |
| Message update | Enum có `needs_update`, DDL dùng boolean | Giữ boolean; bỏ status không persist |
| Timestamps | Code thiếu nhiều field | DB/server clock là canonical; model snapshot rõ |
| Request response | Dataclass không serialize | Canonical JSON response envelope có schema/version |

## 3. Repository boundaries

Đề xuất ports tối thiểu:

- `DocumentRepository`: lock owner document, allocate version, store/finalize version.
- `ExtractionRepository`: create/lock run, batch insert validated regions/evidences, complete/fail.
- `ChatRepository`: lock chat, allocate sequence, manage active/replaced source.
- `EvidenceRepository`: lock evidence, append revision, move pointer, find affected answers.
- `AnswerRepository`: append revision graph, move message pointer, load snapshot scope.
- `JobRepository`: enqueue dedup, claim, heartbeat, reclaim, finalize, append event.
- `IdempotencyRepository`: reserve key with request hash, replay/finalize response.
- `AuditRepository`: append safe metadata only.

Application services dùng `UnitOfWork` tập hợp các port cần trong một transaction. Repository không commit riêng.

## 4. Critical transaction recipes

### T1 Upload

1. Reserve idempotency key và compare request hash.
2. Lock owner document.
3. Allocate `version_no` dưới lock/unique constraint.
4. Insert version, queued run/job.
5. Finalize replayable response và commit.

Không upload object chậm trong transaction. Dùng staged storage key + finalize/cleanup workflow.

### T2 Submit question

1. Reserve idempotency key.
2. Lock owner chat.
3. Allocate hai sequence number.
4. Insert user + assistant messages.
5. Insert answer job với snapshot `data_revision`.
6. Finalize response và commit.

### T3 Evidence revision

1. Lock owner chat và chat evidence theo lock order.
2. Compare current pointer với expected revision.
3. Append full snapshot revision, move pointer, increment fence.
4. Query direct/scope dependencies.
5. Mark current messages và enqueue dedup recalc jobs.
6. Commit trước model/provider work.

### T4 Answer publish

1. Lock chat, message và job.
2. Recheck owner, lease token + expiry và input data revision.
3. Insert answer revision, inputs và scopes.
4. Move pointer, clear `needs_update`, finalize job/event.
5. Commit atomically; stale result chuyển superseded không ghi answer graph.

## 5. Migration sequence

### Migration 0001 - identity/library/conversation/jobs foundation

Tạo extensions, users/sessions/tokens, projects/documents/versions, chats/sources/messages, jobs/events/request keys/audit. Thêm owner composite keys, hot indexes và job claim index.

### Migration 0002 - extraction/provenance

Tạo extraction runs, source regions, extracted evidences; thêm immutable-after-completed trigger và run/source integrity.

### Migration 0003 - revision/dependency graph

Tạo chat evidences/revisions, answer revisions/inputs/scopes, deferred current-pointer FKs và append-only triggers.

Nếu nhóm giữ một migration 0001 duy nhất cho MVP, vẫn phải tổ chức code revision thành ba section testable và có downgrade rõ. Không chỉnh migration đã phát hành; thay đổi tiếp theo tạo migration mới.

## 6. Migration tests

- Upgrade/downgrade DB rỗng.
- Upgrade seed snapshot của migration trước.
- Insert fixture hợp lệ cho đủ 23 bảng.
- Negative FK/check/trigger cases.
- Concurrent version/revision/sequence allocation.
- Job claim `SKIP LOCKED`, expired lease reclaim và stale finalize.
- Explain/index assertion cho hot queries.
- Schema drift check giữa migration head và ORM metadata.

## 7. Data lifecycle

- Object key do server sinh; PDF/crop không vào DB hoặc Git.
- Completed extraction, evidence revision, answer revision/input/scope và audit event là append-only.
- Soft-delete/archive không làm mất history reference.
- Purge theo dependency plan, object refcount/reconciliation và audit metadata an toàn.
- Backup/restore phải bao gồm DB + object manifest nhất quán; test restore trước demo/user study.

## 8. Exit gate data layer

- Adapter contract tests chạy giống nhau trên in-memory và PostgreSQL.
- Không có application code đọc ORM session/query trực tiếp ngoài repository adapter.
- Mọi mutation quan trọng có owner predicate, transaction và race test.
- Migration head dựng được DB từ zero và khớp 23-table inventory.

