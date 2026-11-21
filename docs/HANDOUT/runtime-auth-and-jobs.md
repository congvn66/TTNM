# Runtime handout: auth, AI và durable jobs

Tài liệu này mô tả những gì đang thực sự chạy trong branch `migration`, thay
vì coi schema thiết kế là feature đã hoàn tất.

## 1. Chọn mode trước khi chạy

```powershell
$env:PERSISTENCE_BACKEND = 'postgres'
$env:STORAGE_BACKEND = 'r2'       # hoặc local khi test offline
$env:AUTH_REQUIRED = 'true'
$env:ASYNC_ANSWER_JOBS = 'true'
$env:REPORT_QA_AI_MODE = 'openrouter' # hoặc gemini
```

`REPORT_QA_AI_MODE=deterministic` không gọi model. Đây là mặc định an toàn để
test không phát sinh chi phí. `OPENROUTER_MODEL` mặc định là
`openai/gpt-6-luna`; Gemini dùng `gemini-2.5-flash`.

## 2. Auth/session

1. `POST /api/v1/auth/register` tạo `users`, tạo `auth_sessions`, trả cookie
   `sourcelens_session` với `HttpOnly`, `SameSite=Lax`, `Secure` tùy config.
2. `POST /api/v1/auth/login` normalize email, verify hash, revoke cookie cũ và
   tạo session mới. Database chỉ lưu SHA-256 token hash.
3. `GET /api/v1/auth/me` đọc cookie và kiểm tra `revoked_at`/`expires_at`.
4. `POST /api/v1/auth/logout` revoke session và xóa cookie.
5. `POST /api/v1/auth/forgot-password` luôn trả `accepted`; token reset chỉ
   trả khi `AUTH_EXPOSE_RESET_TOKEN=true` ở local dev. `reset-password` consume
   token một lần và revoke các session cũ.

Khi `AUTH_REQUIRED=true`, owner được lấy từ session server. Client không gửi
`owner_id`; jobs, folders và session/document routes đều filter theo owner.

Migration cần chạy:

```powershell
alembic -c services/backend/alembic.ini upgrade head
```

`0004_auth_preferences` tạo `user_preferences` và metadata session còn thiếu;
`0005_processing_answer_status` cho phép lưu assistant placeholder ở trạng thái
`processing` trước khi worker publish answer revision mới.

## 3. AI và tool boundary

Luồng hỏi đồng bộ (compatibility) là:

```text
question -> question planner -> retrieval -> resolve_evidence
         -> calculator/chart tool nếu plan yêu cầu -> provider structured JSON
         -> citation/schema validator -> persist message/revision
```

- Calculator server là nguồn sự thật cho tổng, hiệu, tăng trưởng và điểm phần
  trăm; số model trả trong `formulas` chỉ là presentation.
- Chart reader chỉ chạy khi `chart_policy=only_if_required_fact_unresolved`.
  Mỗi evidence chart phải có `method_label`: `đọc từ nhãn` hoặc
  `ước lượng theo trục`.
- AI không được tự tạo citation: page phải thuộc context và quote phải xuất
  hiện liên tiếp sau normalization. Sai quote trả `AI_UNSUPPORTED_EVIDENCE`,
  tối đa một correction attempt rồi fail typed.
- `REPORT_QA_AI_RETRIES` mặc định là 1, timeout lấy từ
  `REPORT_QA_AI_TIMEOUT_SECONDS`; không retry vô hạn.

## 4. Answer job mode

Khi PostgreSQL + `ASYNC_ANSWER_JOBS=true`:

```text
POST /sessions/{id}/messages
  -> persist user + assistant(status=processing)
  -> enqueue jobs(kind=answer_question, dedup_key=answer:{assistant_id})
  -> 202 {job, assistant_message}

worker claim (SKIP LOCKED + lease)
  -> heartbeat mỗi 20 giây
  -> gọi cùng grounded pipeline với marker nội bộ
  -> collapse temporary pair vào assistant placeholder
  -> succeed(result) hoặc fail(error_code + bounded retry)
```

Theo dõi job:

```text
GET  /api/v1/jobs?status=queued
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/events
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
```

`events` không trả prompt, PDF hay raw provider response. Worker heartbeat và
lease token ngăn worker cũ publish sau khi lease bị mất; revision fence đầy đủ
cho mọi loại answer vẫn là việc tiếp theo.

## 5. Kiểm thử tối thiểu

```powershell
$env:PERSISTENCE_BACKEND='json'; $env:STORAGE_BACKEND='local'
.venv\Scripts\python.exe -m pytest -q
```

Test cloud chỉ chạy sau khi đã migrate database đích và có fixture PDF không
nhạy cảm. Không commit cookie, API key, reset token hoặc object-storage secret.
