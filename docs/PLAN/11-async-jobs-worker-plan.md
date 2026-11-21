# Kế hoạch durable jobs, worker, queue và xử lý tải

> Trạng thái: Proposed - chờ duyệt.

## 1. Vấn đề cần giải quyết

Extraction và gọi AI là công việc dài, có thể timeout, retry hoặc bị process kill. Nếu chạy trực tiếp trong HTTP request hoặc `BackgroundTasks`:

- restart API làm mất việc;
- browser thấy request treo;
- không có retry/cancel/visibility tin cậy;
- nhiều request đồng thời làm nghẽn API;
- kết quả cũ có thể ghi đè dữ liệu đã sửa.

Đích là API ghi command bền và trả `202` nhanh; worker xử lý độc lập; UI theo dõi job.

## 2. Vì sao dùng PostgreSQL queue trước Redis

Repo đã chọn PostgreSQL là source of truth và schema có `jobs/job_events`. Với quy mô demo/gần production:

- transaction tạo resource + enqueue atomic;
- ít một hạ tầng cần vận hành;
- `FOR UPDATE SKIP LOCKED` đủ cho worker concurrency vừa phải;
- dễ kiểm thử recovery bằng DB thật.

Chỉ thêm Redis/broker khi metrics chứng minh queue latency/throughput/connection contention không đạt SLO, và phải có ADR. Redis không thay thế database record của job.

## 3. Job state machine

```text
queued -> running -> succeeded
              |----> failed
              |----> queued      (retry)
queued/running ----> cancelled
queued/running ----> superseded
running --lease expired--> queued hoặc failed khi quá max_attempts
```

State transition phải qua service/repository method có compare-and-set, không update tùy ý.

## 4. Data model

### `jobs`

```text
id uuid PK
owner_id uuid FK
job_type text
queue_name text
priority smallint
status text
payload jsonb                 -- chỉ IDs/config snapshot nhỏ, không binary PDF
dedup_key text NULL
idempotency_key text NULL
input_data_revision bigint
attempts int
max_attempts int
available_at timestamptz
lease_token uuid NULL
leased_by text NULL
lease_expires_at timestamptz NULL
heartbeat_at timestamptz NULL
progress_current int NULL
progress_total int NULL
progress_stage text NULL
result_ref jsonb NULL
error_code text NULL
error_detail_redacted text NULL
created_at, started_at, finished_at, updated_at
```

Index: `(queue_name, status, available_at, priority, created_at)` cho claim; partial index running leases; unique dedup theo policy.

### `job_events`

Append-only event timeline dùng cho product status/operations:

```text
id bigint PK
job_id uuid FK
event_type text
stage text NULL
message_code text NULL
metadata jsonb redacted
created_at
```

Đây không phải raw audit payload. API chỉ expose event an toàn, cần cho progress/error recovery.

## 5. Claim và lease algorithm

Trong transaction ngắn:

```sql
SELECT id
FROM jobs
WHERE queue_name = :queue
  AND status = 'queued'
  AND available_at <= now()
ORDER BY priority DESC, created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Sau đó update `running`, `lease_token`, `leased_by`, `lease_expires_at`, increment attempts và commit. Worker không giữ DB transaction trong lúc gọi OCR/AI.

Mọi heartbeat/progress/publish phải có điều kiện `id + lease_token + status=running`. Worker mất lease không được publish.

## 6. Revision fence

Mỗi job snapshot:

- `document_version_id`;
- evidence/numeric data revision cần dùng;
- chat/message ID;
- prompt/schema/model version;
- resource reservation ID nếu giới hạn concurrency/storage cần reserve.

Trước publish, worker kiểm tra lease, ownership và `input_data_revision`. Nếu input đã đổi, job thành `superseded`; không ghi đè answer/extraction mới.

## 7. Job types ban đầu

| Job type | Queue | Kết quả |
|---|---|---|
| `extract_document` | cpu/io | page text, tables, numbers, chart metadata, index |
| `answer_question` | ai | structured answer revision + citations |
| `recalculate_answer` | cpu | deterministic calculations từ selected values |
| `purge_document` | maintenance | object/metadata cleanup idempotent |

Không gộp mọi việc vào một handler `process_job`. Registry map job type tới typed payload validator và handler.

## 8. AI question flow

```text
POST question
  -> transaction:
       persist user_message
       persist assistant_message(status=queued)
       reserve resource capacity nếu policy yêu cầu
       enqueue answer_question(dedup/revision snapshot)
  -> 202 {message_id, job_id, status}

worker
  -> claim + heartbeat
  -> understand question -> retrieval -> deterministic calculation plan
  -> model generation -> structured schema validation -> citation validation
  -> transaction publish answer_revision + links + assistant status
  -> succeeded
```

Frontend append user message và assistant placeholder ngay; cuộn cuối sau append. SSE/polling cập nhật placeholder đúng vị trí, không append answer cũ xuống cuối khi retry hoàn thành.

## 9. Extraction/upload flow

```text
complete upload
  -> verify object/checksum
  -> transaction mark version queued + enqueue extract_document
  -> 202

worker
  -> extract pages/text/tables/numbers
  -> persist staging/result revision
  -> publish only if version/revision fence valid
  -> document_version ready
```

Không trả `ready` khi mới upload xong. Library item hiển thị queued/processing/ready/failure thật.

## 10. Retry policy

| Lỗi | Hành vi |
|---|---|
| Network timeout/429/5xx provider | retry exponential backoff + jitter |
| Invalid model structure | tối đa một repair attempt rồi fail typed |
| Citation quote không có trong context | fail validation/controlled retry; không publish answer giả |
| Unsupported/corrupt PDF | terminal failure |
| Missing resource/owner mismatch | terminal failure + security metric |
| Lost lease/stale revision | không publish; requeue hoặc supersede |
| Quota exceeded | reject trước enqueue hoặc terminal policy error |

Không retry vô hạn. Failed job giữ error code an toàn và correlation ID; raw provider response chỉ ở log protected theo retention.

## 11. Cancellation và supersede

- Cancel queued: compare-and-set sang cancelled, release reservation.
- Cancel running: đánh dấu `cancel_requested_at`; handler kiểm tra ở checkpoint; external call có thể không hủy tức thời.
- New answer request có thể supersede job cũ cho cùng assistant message nếu policy cho phép.
- Replace PDF supersede extraction chưa publish của version không còn cần, nhưng không xóa lịch sử tùy tiện.

## 12. API và realtime

| Method | Endpoint | Mục đích |
|---|---|---|
| GET | `/api/v1/jobs/{job_id}` | status/progress/result summary |
| GET | `/api/v1/jobs?status=active` | job center của owner |
| POST | `/api/v1/jobs/{job_id}/cancel` | request cancel |
| POST | `/api/v1/jobs/{job_id}/retry` | tạo retry hợp lệ |
| GET | `/api/v1/jobs/events` | SSE owner-scoped |

SSE là enhancement; polling với ETag/backoff là fallback. UI không cần websocket hai chiều.

## 13. Load control

- Worker concurrency cấu hình riêng theo queue; AI và CPU không dùng chung semaphore.
- Per-owner active job limit ngăn một user chiếm queue.
- Provider concurrency/rate limiter ở adapter.
- Backpressure: API vẫn nhận command trong quota nhưng có thể báo estimated queue state; khi hard limit thì 429/503 rõ ràng.
- Priority chỉ có vài mức; không để client tự chọn priority cao.
- Payload lớn nằm object storage, không nằm `jobs.payload`.

## 14. Observability không lộ audit UI

Giữ ở backend:

- structured log: request/job/correlation IDs;
- queue depth/age, claim latency, job duration, retry/failure, lease loss;
- AI provider latency/status/token usage đã redact;
- admin runbook/query để support.

Bỏ khỏi product UI:

- raw request/response;
- internal module trace;
- prompt/context payload;
- audit drawer thử nghiệm.

Người dùng chỉ thấy status, progress stage, friendly error và correlation ID.

## 15. Task breakdown

1. JOB-001: finalize schema/index/state transitions.
2. JOB-002: repository claim/heartbeat/publish/cancel với PostgreSQL.
3. JOB-003: worker main loop, registry và graceful shutdown.
4. JOB-004: move extraction khỏi request/background task.
5. JOB-005: move AI answer sang persisted placeholder + job.
6. JOB-006: retry/backoff/reclaim/supersede/revision fence.
7. JOB-007: SSE + polling endpoints và frontend job center.
8. JOB-008: metrics, structured logs và runbook.
9. JOB-009: purge và scheduled maintenance handlers.

## 16. Test bắt buộc

- Hai worker claim đồng thời không xử lý cùng job.
- Worker crash; lease expire; job reclaim đúng attempts.
- Old lease token heartbeat/publish bị từ chối.
- Stale `input_data_revision` không publish.
- API transaction rollback không để resource có mà job thiếu hoặc ngược lại.
- Duplicate idempotency key không tạo hai AI answers/uploads.
- Cancel/retry/release quota đúng.
- Provider 429/backoff không tạo retry storm.
- SSE disconnect/reconnect và polling fallback giữ đúng order.
- Kill/restart API/worker giữa extraction/AI vẫn hoàn tất hoặc fail có thể recovery.

## 17. Definition of Done

- API trả nhanh với persisted job cho extraction và AI.
- Worker restart/crash không mất việc và không double-publish.
- UI luôn có placeholder/status theo đúng thứ tự hội thoại.
- Queue có metrics, retry policy, cancellation và runbook.
- Không dùng local in-process background task cho công việc cần độ bền.
