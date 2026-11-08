# P0 execution plan - nền dữ liệu có thể kiểm chứng

## 1. Kết luận và phạm vi

P0 tiếp theo không phải là tiếp tục làm đẹp UI hoặc nối thêm model AI. Điểm nghẽn hiện tại là luồng session/document đã chạy được nhưng dữ liệu chính vẫn nằm trong `runtime/sessions.json`, PDF nằm trên filesystem local và job chạy theo process. Vì vậy hệ thống chưa chứng minh được transaction, ownership, revision bất biến, khôi phục sau restart, lease/retry và truy vết qua nhiều process.

Mục tiêu P0 là tạo một **data foundation chạy thật trên PostgreSQL và object storage**, sau đó chuyển đúng một vertical slice từ upload đến hỏi đáp/citation sang nền này. Hoàn thành P0 khi có thể trả lời bằng dữ liệu và test:

1. File, phiên bản và hash nào đã được dùng?
2. Dữ liệu được lưu ở bảng/object key nào sau mỗi thao tác?
3. Dữ liệu có còn sau khi API và worker restart không?
4. Hai request trùng hoặc hai worker tranh cùng job có tạo bản ghi sai không?
5. Câu trả lời đã dùng revision căn cứ nào và chịu ảnh hưởng bởi scope nào?
6. Khi sửa căn cứ, lịch sử cũ còn nguyên và câu trả lời mới có được fence đúng revision không?

### 1.1 P0 bao gồm

- Chốt mapping 23 bảng giữa domain, PostgreSQL DDL và repository ports.
- Thêm PostgreSQL 16, Alembic và object storage tương thích S3 cho môi trường local.
- Tạo migration có thể upgrade/downgrade và chạy trên database có seed cũ.
- Tạo PostgreSQL repository, Unit of Work và durable job lease.
- Tạo object storage adapter với staged upload, hash và finalize an toàn.
- Chuyển vertical slice: upload PDF -> extraction -> chat source -> question -> answer revision -> citation -> evidence revision -> recalculate.
- Chuyển dữ liệu session/document hiện tại từ local runtime bằng script có `--dry-run`.
- Hiển thị trace ID, entity ID, revision ID và trạng thái persistence để kiểm tra trên UI/terminal.
- Có contract, integration, migration, restart và race tests.

### 1.2 Không thuộc P0

- Redis làm source of truth hoặc session store chính.
- Vector database, semantic search production-grade hoặc OCR hoàn chỉnh.
- Tối ưu prompt/model, streaming token và đánh giá chất lượng câu trả lời diện rộng.
- Multi-tenant organization, billing, chia sẻ project hoặc RBAC phức tạp.
- Kubernetes, autoscaling hoặc triển khai cloud production.
- Backfill bbox chính xác cho dữ liệu local cũ khi nguồn cũ không chứa bbox. Không được tự bịa bbox.

Redis chỉ được cân nhắc sau P0 cho cache, rate limit hoặc progress fan-out. Mất Redis không được làm mất PDF, chat, revision, job hay audit.

## 2. Quyết định kỹ thuật phải đóng băng trước adapter

| Chủ đề | Quyết định P0 | Lý do/giới hạn |
|---|---|---|
| Metadata, quan hệ, lịch sử | PostgreSQL 16 là source of truth | Cần FK, transaction, lock và audit đáng tin cậy |
| PDF và artifact lớn | MinIO local, API S3-compatible | DB chỉ giữ `storage_key`, hash, size và metadata |
| API/worker | Cùng package `report_qa`, hai entrypoint/process | Tránh nhân đôi domain và persistence logic |
| ORM/driver | SQLAlchemy 2.x + psycopg 3 | Typed mapping, transaction và PostgreSQL hiện đại |
| Migration | Alembic; migration đã phát hành không được sửa | Có lịch sử schema và rollback có kiểm soát |
| Decimal | PostgreSQL `NUMERIC`; API là chuỗi thập phân | Không đưa số chính xác qua JSON float |
| ID | UUID sinh ở application hoặc DB | Cho phép reserve ID trước khi upload object |
| Time | `timestamptz`, ghi UTC | So sánh lease và audit nhất quán |
| JSON | JSONB chỉ cho semantic/config/payload có schema version | Quan hệ và khóa không được giấu trong JSONB |
| Local JSON | Adapter dev/migration input, không phải runtime production | Không an toàn khi nhiều process |
| Auth P0 | Một local development principal được tạo rõ ràng | Repository vẫn lấy owner từ server context |

Nếu một quyết định thay đổi meaning dữ liệu, topology hoặc privacy, phải tạo ADR trước phần phụ thuộc. Không viết toàn bộ ORM khi mapping 23 bảng chưa được review.

## 3. Kết quả bàn giao và cấu trúc file đích

```text
infra/
  compose/dev.yml
  postgres/init/
  storage/README.md
services/backend/
  alembic.ini
  alembic/
    env.py
    versions/
      0001_identity_library_conversation_jobs.py
      0002_extraction_provenance.py
      0003_evidence_answer_revisions.py
  src/report_qa/
    config.py
    infrastructure/
      postgres/
        base.py
        models/
        repositories/
        unit_of_work.py
      object_storage/
        port.py
        filesystem.py
        s3.py
      jobs/postgres_queue.py
tests/
  integration/postgres/
  integration/object_storage/
  migration/
  race/
scripts/
  migrate_local_runtime_to_postgres.py
  inspect_trace.py
doc/
  adr/
  data-model.md
  processing-flows.md
  storage-and-data-runtime.md
```

Tên file có thể điều chỉnh nhỏ để khớp package, nhưng ownership không thay đổi: domain không import SQLAlchemy/S3, application chỉ dùng ports/UoW, adapter nằm trong infrastructure.

## 4. Thứ tự triển khai theo PR

Mỗi PR dưới đây phải nhỏ, chạy độc lập và có rollback. Không gộp PR 2-8 thành một thay đổi lớn.

### PR P0.1 - Chốt hợp đồng dữ liệu và mapping 23 bảng

**Mục tiêu:** loại bỏ drift giữa `domain/models.py`, `doc/data-model.md`, `doc/initial-schema.sql`, contracts và repository ports.

**Công việc:**

1. Lập mapping cho từng bảng: aggregate owner, PK/FK, unique key, mutable/append-only, state transition, repository method và flow sử dụng.
2. Chốt cardinality và cùng-owner FK cho mọi liên kết xuyên aggregate.
3. Chốt `chat.data_revision`, `current_revision_id`, `current_answer_revision_id` và fence khi publish.
4. Chốt source replacement: chỉ inactive source được thay; không ảnh hưởng source khác.
5. Chốt job lease: `lease_token`, expiry, heartbeat, attempt limit, reclaim và terminal states.
6. Chốt canonical validation path cho bốn JSON Schema trong `contracts/`.
7. Cập nhật `doc/data-model.md`, `doc/processing-flows.md` và ADR nếu meaning thay đổi.

**Mapping bắt buộc review:**

| Nhóm | Bảng | Tính chất | Repository/flow chịu trách nhiệm |
|---|---|---|---|
| Identity | `users` | Mutable có soft delete | Principal lookup; owner root |
| Identity | `auth_sessions` | Mutable/revocable | Auth session lifecycle |
| Identity | `account_tokens` | One-time, append + consume | Token lifecycle |
| Library | `projects` | Mutable có soft delete | Project repository |
| Library | `documents` | Mutable metadata, soft delete | Document aggregate |
| Library | `document_versions` | Bất biến sau finalize | Upload/finalize |
| Library | `project_documents` | Membership | Project-document link |
| Extraction | `extraction_runs` | State machine; completed bất biến | Extraction worker |
| Extraction | `source_regions` | Bất biến sau run completed | Extraction publish |
| Extraction | `extracted_evidences` | Bất biến sau run completed | Extraction publish |
| Conversation | `chats` | Mutable metadata + `data_revision` | Chat aggregate |
| Conversation | `chat_sources` | Append/state active-inactive | Source attach/replace |
| Conversation | `messages` | Append; assistant có current pointer | Question/answer flow |
| Conversation | `message_pins` | Membership | Pin/unpin |
| Evidence | `chat_evidences` | Working link; current pointer | Evidence aggregate |
| Evidence | `evidence_revisions` | Append-only | Verify/edit/restore |
| Answer | `answer_revisions` | Append-only | Answer publish/recalculate |
| Answer | `answer_inputs` | Snapshot direct dependency | Answer publish |
| Answer | `answer_scopes` | Snapshot scope dependency | Answer publish |
| Operations | `jobs` | Mutable state + lease | Queue/worker |
| Operations | `job_events` | Append-only | Worker audit/progress |
| Operations | `audit_events` | Append-only | Security/business audit |
| Operations | `request_keys` | Immutable request hash + result ref | Idempotency |

**Exit gate:**

- Consistency checker nhận đủ 23 bảng, không thừa/thiếu.
- Mọi append-only entity có test cấm update semantic fields.
- Mọi owner path từ root đến child có ít nhất một negative ownership case.
- `PLAN-001`, `PLAN-002`, `PLAN-003`, `PLAN-005` chỉ chuyển Done bằng link tới test/doc.

### PR P0.2 - Runtime local tái lập được

**Mục tiêu:** một lệnh tạo PostgreSQL và MinIO; config fail-fast, không hard-code secret.

**Công việc:**

1. Thêm dependencies: SQLAlchemy, psycopg, Alembic, S3 client, JSON Schema validator và test tooling.
2. Thêm `infra/compose/dev.yml` với PostgreSQL 16 và MinIO; healthcheck, named volumes, fixed internal ports.
3. Cập nhật `.env.example`, không commit `.env` thật.
4. Tạo typed settings cho database, object storage, timeout, pool size và environment.
5. Redact password, token, presigned URL và provider key trong log.
6. Thêm `/health/live` và `/health/ready`; readiness kiểm tra DB/bucket, không gọi AI provider.

**Exit gate:** máy sạch dựng được services; thiếu biến bắt buộc fail ngay; redaction test pass; tắt DB/MinIO làm readiness fail nhưng liveness vẫn pass.

**Rollback:** giữ volume, dùng feature flag quay về local adapter trong giai đoạn chuyển tiếp.

### PR P0.3 - Migration 0001: identity/library/conversation/jobs

**Bảng:** `users`, `auth_sessions`, `account_tokens`, `projects`, `documents`, `document_versions`, `project_documents`, `chats`, `chat_sources`, `messages`, `message_pins`, `jobs`, `job_events`, `audit_events`, `request_keys`.

**Công việc:**

1. Metadata naming convention để downgrade constraint ổn định.
2. Chuyển DDL review thành SQLAlchemy models và migration explicit; không dùng `create_all` làm migration.
3. Index theo query thật: owner/list, active source, message order, queued job, lease expiry, idempotency.
4. Check constraint cho states, positive sequence/version/attempt và terminal timestamps.
5. Composite FK bảo vệ cùng owner/cùng chat nơi khả thi.
6. Seed local development user bằng script riêng, không nằm trong production migration.

**Exit gate:**

- Database rỗng: `upgrade head -> downgrade base -> upgrade head` pass.
- Database seed ở revision 0001 nâng/hạ đúng dữ liệu đã mô tả.
- Duplicate normalized email, document version, message sequence và request key bị từ chối.
- Cross-owner project-document/chat-source bị DB hoặc repository từ chối.

### PR P0.4 - Migration 0002: extraction và provenance

**Bảng:** `extraction_runs`, `source_regions`, `extracted_evidences`.

**Công việc:**

1. Ràng buộc source region và evidence cùng extraction run.
2. Validate bbox ở application và DB: bốn số hữu hạn, normalized, đúng thứ tự.
3. Validate `value_kind`, `data_status`, `raw_value`, `raw_text` bằng check constraint.
4. `semantic.schema_version` bắt buộc; full semantic được validate trước insert.
5. Khi run `completed`, cấm sửa/xóa source/evidence.
6. Index page/region và extraction status; chưa tạo GIN index khi chưa có query evidence.

**Exit gate:** bbox sai, NaN/Infinity, period thiếu provenance và trạng thái/value không tương thích đều fail; publish lỗi giữa chừng không để partial rows; completed run bất biến; hai worker finalize chỉ một winner.

### PR P0.5 - Migration 0003: evidence/answer revision graph

**Bảng:** `chat_evidences`, `evidence_revisions`, `answer_revisions`, `answer_inputs`, `answer_scopes`.

**Công việc:**

1. Denormalize `chat_id` ở link/revision cần thiết để composite FK bảo vệ cùng chat.
2. Unique `(parent_id, revision_no)` và current pointer FK.
3. Revision là full snapshot, không lưu patch khó phục dựng.
4. Answer revision lưu structured answer, calculator status, provider metadata tối thiểu và `input_data_revision`.
5. Inputs snapshot đúng revision; scopes snapshot toàn bộ phạm vi đã xét.
6. Cấm current pointer trỏ revision của entity/chat khác.

**Exit gate:** verify/edit/restore tạo revision mới; bản cũ không đổi; số `0` không thành missing; decimal round-trip nguyên chuỗi; cross-chat reference fail; evidence edit tăng `chat.data_revision` đúng một lần.

### PR P0.6 - PostgreSQL repositories và Unit of Work

**Mục tiêu:** application flow không biết SQLAlchemy và cùng contract suite chạy trên memory/PostgreSQL.

**Công việc:**

1. Repository ports theo aggregate; không expose SQLAlchemy session hoặc `GenericRepository`.
2. Mọi read/write nhận server principal context; client payload không quyết định owner.
3. UoW quản lý một transaction cho một command.
4. Lock order chung: `chat -> chat_source/chat_evidence -> message -> answer_revision -> job`.
5. Idempotency lưu owner + operation + key + canonical request hash + result reference.
6. Cùng key/cùng hash trả kết quả cũ; cùng key/khác hash trả conflict ổn định.
7. Map DB errors sang domain error code tiếng Việt; không lộ SQL/constraint nội bộ.

**Contract suite tối thiểu:** owner isolation; rollback bằng fault injection; append-only; uniqueness; idempotency; current pointer cùng aggregate/chat; source replacement isolation; `data_revision` fence; pagination order ổn định.

**Exit gate:** memory và PostgreSQL cùng pass suite; integration tests không mock SQLAlchemy.

### PR P0.7 - Object storage và upload hai pha

**Mục tiêu:** không có DB row `ready` trỏ object thiếu và không có object rác không được thu gom.

**Luồng:**

1. Xác thực owner, content type, size <= 100 MB và idempotency key.
2. Transaction A reserve `document_version` với UUID, expected hash/size và staging key.
3. Stream file vào staging, vừa stream vừa tính SHA-256; không đọc toàn bộ vào RAM.
4. Kiểm tra actual size/hash/PDF signature.
5. Finalize object sang immutable key.
6. Transaction B cập nhật storage metadata và enqueue extraction job.
7. Lỗi giữa chừng tạo failure state rõ ràng; sweeper xóa staging quá hạn.
8. Retry cùng idempotency key không tạo version/object thứ hai.

Object key dựa trên owner/document/version UUID, không chứa filename chưa sanitize.

**Exit gate:** upload rỗng/non-PDF/PDF lỗi/>100 MB fail đúng mã; fault giữa từng bước không tạo ready row sai; hash mismatch fail; retry trả cùng version; file còn đúng hash sau restart; cross-owner download fail.

### PR P0.8 - Durable job queue, lease và worker recovery

**Claim:** chọn queued job hoặc lease hết hạn bằng `FOR UPDATE SKIP LOCKED`, tăng attempt, sinh token mới, dùng database time và append `job_event`.

**Heartbeat:** chỉ lease token hiện tại được gia hạn.

**Finalize:** `WHERE id=? AND lease_token=? AND status='running'`; đồng thời kiểm tra owner và `input_data_revision`. Token/fence sai không publish.

**Retry P0:** validation/business là terminal; timeout/network/provider 429/5xx retry hữu hạn với backoff+jitter; crash được reclaim; quá attempt thành failed; duplicate enqueue trả job hiện có.

**Exit gate:**

- 10 worker claim cùng job chỉ một winner.
- Lease cũ không heartbeat/finalize sau reclaim.
- Crash sau provider call trước publish không tạo duplicate revision.
- Evidence đổi khi job chạy thì answer stale không được set current.
- Restart API/worker có recovery deterministic.

### PR P0.9 - Chuyển vertical slice và trace quan sát được

1. Chuyển upload/session/chat/question/evidence edit/recalculate qua application services và PostgreSQL UoW.
2. Response trả `trace_id` và resource IDs, không trả storage secret.
3. Log structured: `HTTP_IN`, `COMMAND_ACCEPTED`, `DB_TX_COMMIT/ROLLBACK`, `OBJECT_STAGED/FINALIZED`, `JOB_ENQUEUED/CLAIMED`, `PROVIDER_CALL`, `ANSWER_PUBLISHED`, `HTTP_OUT`.
4. Không log full PDF text, prompt chứa dữ liệu người dùng, token hoặc raw provider response mặc định.
5. Giao diện chính thêm inspector chỉ đọc: entity timeline, current revision, input/scope, job events và backend persistence.
6. Citation click dùng `source_region_id`, page và normalized bbox từ API; frontend không tự suy bbox khi backend có region.

**Exit gate:** từ một thao tác UI lần được cùng `trace_id` qua HTTP -> DB -> job -> provider -> answer revision; inspector xác nhận dữ liệu còn sau restart.

### PR P0.10 - Import dữ liệu local và cutover

**Script:** `scripts/migrate_local_runtime_to_postgres.py` có `--dry-run`, `--owner-email`, `--source-dir`, `--report` và rerun idempotent.

| Nguồn local | Đích | Quy tắc |
|---|---|---|
| Session | `chats` | Gán development owner rõ ràng; giữ created time hợp lệ |
| PDF | documents/version + object | Recompute SHA-256/size; không tin metadata cũ |
| Extracted page text | extraction artifact/run | Ghi extractor legacy; không tự tạo metric evidence |
| User message | `messages` | Giữ thứ tự, normalize timestamp |
| Assistant structured response | `answer_revisions` nếu validate | Invalid payload report/quarantine, không ép insert |
| Citation page/quote | legacy source region nếu xác định được | `bbox=NULL` nếu không có tọa độ; không đoán |
| Trace local | migration report/audit | Không đưa secret/full prompt vào audit |

**Import gate:** dry-run báo count/invalid/missing/hash collision; rerun không nhân đôi; đối chiếu chat/message/document/hash; quarantine có reason code; một record lỗi không commit nửa session.

**Cutover:** đóng write local -> backup runtime/DB -> dry-run -> import -> reconciliation -> bật `PERSISTENCE_BACKEND=postgres` -> smoke/golden journeys -> giữ runtime local read-only một release. Không dual-write.

**Rollback:** chỉ quay feature flag về local nếu chưa có write mới trên PostgreSQL. Nếu đã có, dùng DB backup hoặc migration ngược có kiểm soát; không tự merge hai nguồn.

## 5. Transaction recipes bắt buộc

### 5.1 Submit question

```text
BEGIN
  lock chat by (chat_id, owner_id)
  validate active source and ready extraction
  validate/reuse request_key
  allocate message.sequence_no
  insert user message(status=accepted)
  insert answer job(input_data_revision=chat.data_revision)
  save request result reference
COMMIT
```

Provider không được gọi trong transaction. API trả message/job ngay; UI hiển thị bubble và trạng thái đang xử lý.

### 5.2 Publish extraction

```text
BEGIN
  lock extraction_run
  verify lease token + ownership + running state
  validate all regions/evidences/contracts before first insert
  bulk insert source_regions and extracted_evidences
  mark run completed and document_version ready
  append job_event/audit_event
COMMIT
```

Không commit theo từng page. Artifact lớn có thể upload staging trước, chỉ expose sau commit.

### 5.3 Create evidence revision

```text
BEGIN
  lock chat then chat_evidence
  verify current revision and expected chat.data_revision
  insert full evidence_revision snapshot
  update current_revision_id
  increment chat.data_revision
  mark affected messages needs_update via answer_inputs/scopes
  enqueue deduplicated recalc jobs
  append audit_event
COMMIT
```

### 5.4 Publish answer

```text
BEGIN
  lock chat then assistant message
  verify job lease token
  verify job.input_data_revision == chat.data_revision
  verify input evidence revisions
  insert answer_revision, answer_inputs, answer_scopes
  set message.current_answer_revision_id
  mark message completed and job succeeded
  append job_event/audit_event
COMMIT
```

Fence sai thì không set current; job `superseded` hoặc được enqueue lại theo policy.

## 6. Test matrix và lệnh chuẩn

### 6.1 Baseline luôn phải pass

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/run_flow_tests.py
python scripts/run_backend_skeleton_tests.py
python scripts/run_web_demo_tests.py
```

### 6.2 Runtime/migration

```powershell
docker compose -f infra/compose/dev.yml up -d postgres minio
python -m alembic -c services/backend/alembic.ini upgrade head
python -m pytest tests/migration -q
python -m pytest tests/integration/postgres -q
python -m pytest tests/integration/object_storage -q
```

Migration test phải tạo database tạm; không downgrade database developer đang dùng.

### 6.3 Contract/race/restart

```powershell
python -m pytest services/backend/tests/contract -q
python -m pytest tests/race -q
python scripts/run_persistence_restart_test.py
python scripts/run_data_reconciliation.py
```

### 6.4 Ma trận tối thiểu

| Hành vi | Happy path | Failure/race bắt buộc | Bằng chứng |
|---|---|---|---|
| Upload | PDF <=100 MB | retry, hash mismatch, storage timeout | row/object/hash/restart |
| Extraction | publish full run | partial insert, stale lease, duplicate finalize | immutable run + event |
| Submit question | message/job tức thời | duplicate request, inactive source | stable result/error |
| Answer | structured revision + citations | stale revision, provider timeout | input/scope snapshots |
| Evidence edit | append revision + recalc | concurrent edit, cross-owner | old revision unchanged |
| Job | one claim/finalize | reclaim, old token, max attempts | event sequence |
| Import | rerun idempotent | corrupt PDF, invalid answer | reconciliation report |
| Restart | data survives | restart mid-job | deterministic recovery |

## 7. Definition of Done P0

- [ ] 23/23 bảng có mapping, migration và ownership path được review.
- [ ] PostgreSQL/object storage là backend mặc định; UI không ghi `sessions.json`.
- [ ] Redis không chứa dữ liệu không thể tái tạo.
- [ ] Upload retry-safe; object hash đúng và còn sau restart.
- [ ] Extraction completed và evidence/answer revisions bất biến.
- [ ] Edit/verify/restore tạo revision mới và tăng đúng `chat.data_revision`.
- [ ] Mỗi answer revision có `answer_inputs` và `answer_scopes` hợp lệ.
- [ ] Durable jobs pass claim/lease/reclaim/fence race tests.
- [ ] Ownership negative tests chạy ở repository và API boundary.
- [ ] Migration up/down/seed upgrade pass trên database tạm.
- [ ] Local import dry-run/rerun/reconciliation pass.
- [ ] Golden journey pass qua UI, API, worker, DB và object storage.
- [ ] Trace/inspector không lộ secret/full PDF text.
- [ ] Baseline tests cũ vẫn pass.
- [ ] Data model, processing flows, OpenAPI/contracts và runbook khớp hành vi thật.

Chưa hoàn thành nếu dữ liệu chỉ còn trong memory/JSON, background task cùng process thay worker lease, test mock DB, bbox do frontend đoán, hoặc answer không snapshot inputs/scopes.

## 8. Thứ tự làm ngay - 10 bước

1. Chạy baseline và lưu kết quả làm mốc.
2. Hoàn thành mapping 23/23, đặc biệt composite FK/current pointer.
3. Chốt job lease và source replacement bằng ADR/test cases.
4. Bổ sung dependencies/config, chưa đổi runtime mặc định.
5. Dựng PostgreSQL + MinIO local và health checks.
6. Viết migration 0001 cùng migration tests.
7. Viết migration 0002/0003 cùng invariant tests.
8. Cho memory/PostgreSQL chạy chung repository contract suite.
9. Chuyển upload + job trước, sau đó extraction và answer/revision.
10. Import local, chạy reconciliation/restart/race/golden journey rồi cutover.

Critical path: `P0.1 -> P0.2 -> P0.3/4/5 -> P0.6 -> P0.7/8 -> P0.9 -> P0.10`. Không bắt đầu bằng Redis, prompt engineering hoặc refactor UI vì chúng không giải quyết rủi ro mất/sai dữ liệu hiện tại.

## 9. Theo dõi tiến độ và bằng chứng

| Gate | Owner role | Status ban đầu | Bằng chứng cần gắn |
|---|---|---|---|
| P0.1 contracts/mapping | Data/backend | Ready | consistency + invariant tests |
| P0.2 runtime | Platform/backend | Ready | compose health + config tests |
| P0.3-5 migrations | Data/backend | Blocked bởi P0.1 | migration report |
| P0.6 repositories/UoW | Backend | Blocked bởi migrations | dual-adapter contract report |
| P0.7 storage/upload | Backend/platform | Blocked bởi P0.2/P0.6 | fault matrix + hash report |
| P0.8 jobs | Backend | Blocked bởi P0.3/P0.6 | race/restart report |
| P0.9 vertical slice | Full stack | Blocked bởi P0.7/P0.8 | trace + golden journey |
| P0.10 import/cutover | Data/backend | Blocked bởi P0.9 | dry-run + reconciliation |

Không dùng phần trăm cảm tính. Tiến độ tính bằng gate đã pass; PR merge nhưng test gate chưa pass vẫn là `In progress`.

## 10. Rủi ro và điều kiện dừng

| Rủi ro | Biện pháp | Điều kiện dừng/cần quyết định |
|---|---|---|
| DDL/domain lệch meaning | Mapping trước ORM | Field không xác định owner/mutability |
| Transaction ôm provider call | Outbox/job, recipe rõ | Flow cần giữ DB lock khi gọi AI |
| Dual-write phân kỳ | Cutover một chiều | Có write mới trên cả hai backend |
| Object/DB lệch | Staging/finalize/sweeper | Không reconciliation an toàn |
| Publish stale answer | data revision + lease fence | Answer không xác định input revision |
| Bịa provenance import | Quarantine/bbox null | Nguồn cũ thiếu page/quote/hash |
| Log lộ PDF/token | Structured events + redaction test | Test phát hiện secret/full payload |
| Downgrade phá dữ liệu | DB tạm + backup | Không thể khôi phục có kiểm soát |

Gặp điều kiện dừng thì không vá bằng JSON field hoặc bỏ constraint. Tạo ADR ngắn, cập nhật contract và test trước khi tiếp tục.
