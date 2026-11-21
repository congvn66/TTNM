# Multi-user runtime: session, token, cache và cấu hình

**Trạng thái:** handout triển khai v1  
**Phạm vi:** web app SourceLens chạy nhiều tài khoản, một PostgreSQL/Supabase và Cloudflare R2.  
**Nguyên tắc:** mọi dữ liệu nghiệp vụ phải có `owner_id`; browser không được truy cập trực tiếp database, R2 secret hoặc OpenRouter key.

## 1. Mô hình tenant và quyền sở hữu

Trong đồ án, một user là tenant tối thiểu. `users.id` là owner gốc của:

```text
users
 ├─ projects
 │   ├─ project_folders
 │   └─ project_documents
 ├─ chats (UI gọi là phiên làm việc)
 │   ├─ chat_documents
 │   ├─ messages
 │   └─ answer_revisions
 ├─ documents → document_versions → extraction_runs
 └─ auth_sessions / user_preferences
```

Mỗi query đọc, sửa, archive hoặc enqueue job phải có điều kiện owner. Không nhận `owner_id` từ JSON của browser; server lấy owner từ session cookie. Job phải lưu cả `owner_id` và `chat_id`, vì worker chạy ngoài request và không có browser context.

### Quy tắc kiểm soát truy cập

| Tình huống | Quy tắc | Kết quả mong đợi |
|---|---|---|
| User A đọc ID của User B | Query kèm `owner_id=A` | `404` thống nhất, không leak tồn tại |
| User A sửa/xóa tài liệu của B | Update/delete kèm owner predicate | `404` hoặc `403` theo API contract |
| Worker xử lý job | Lấy owner từ payload đã ký bởi server và kiểm tra FK | Không cho phép payload từ client tự đặt owner |
| Admin/support (nếu có sau này) | Vai trò riêng, audit bắt buộc | Không dùng bypass owner mặc định |

Trong milestone hiện tại, backend đã thực hiện owner-scoping. Supabase vẫn nên được giới hạn private bằng DB role chỉ dành cho backend; nếu mở client access trong tương lai thì phải thêm RLS theo `owner_id` và test policy độc lập.

## 2. Session cookie và token

### 2.1 Browser session hiện tại

API dùng một opaque random token trong cookie `sourcelens_session`; PostgreSQL chỉ lưu SHA-256 digest trong `auth_sessions`. Browser không nhận bearer token và frontend không lưu token vào `localStorage`.

Cookie production:

```text
HttpOnly=true
Secure=true                 # bắt buộc khi HTTPS
SameSite=Lax                # Strict nếu không cần cross-site flow
Path=/
Max-Age=AUTH_SESSION_DAYS*86400 (1–90 ngày)
```

Mỗi lần login phải revoke token cũ của browser đó rồi tạo token mới. Logout chỉ revoke digest hiện tại và xóa cookie. Đổi mật khẩu revoke mọi session khác; reset mật khẩu revoke toàn bộ session.

### 2.2 Device/session management

`auth_sessions` lưu `created_at`, `last_seen_at`, `expires_at`, `revoked_at`, `user_agent` và `ip_hash`. UI settings hiển thị danh sách thiết bị đã đăng nhập, cho phép revoke từng session hoặc revoke-others. Không hiển thị token thô.

Quy trình request:

```text
Browser cookie
  → API hash(token)
  → SELECT auth_sessions JOIN users
       WHERE token_hash=? AND revoked_at IS NULL AND expires_at>now()
  → owner_id từ row user
  → repository query owner-scoped
```

Nếu DB không sẵn sàng, trả `503 AUTH_DATABASE_UNAVAILABLE`; không âm thầm rơi về demo owner hay JSON local khi `PERSISTENCE_BACKEND=postgres`.

### 2.3 CSRF và đăng nhập

Các mutation browser phải kiểm tra Origin/CSRF. Rate-limit login theo IP đã hash và normalized email, ghi audit event cho login thất bại, khóa tạm thời sau nhiều lần sai. Password dùng Argon2id; scrypt chỉ là fallback cho môi trường thiếu dependency.

## 3. Cache: cái gì được cache và cái gì là nguồn thật

| Lớp | Nội dung | TTL/invalidaton | Có phải nguồn thật? |
|---|---|---|---|
| Browser/query cache | danh sách project/session, trạng thái job | 15–60s; invalidate sau mutation | Không |
| API process cache | config bất biến, capability health | 30–60s; không cache dữ liệu riêng user | Không |
| Local runtime cache | PDF/extraction tải từ R2 để xử lý | theo `storage_key + sha256`; xóa theo retention | Không |
| PostgreSQL/Supabase | user, metadata, revision graph, job state | transaction/append-only | **Có với metadata** |
| Cloudflare R2 | PDF gốc, extraction artifact | key bất biến; lifecycle/purge job | **Có với binary** |

Cache key tối thiểu phải chứa `owner_id`, loại tài nguyên và revision/version. Không dùng một key toàn cục như `session:list` cho nhiều tài khoản. Khi rename/archive, invalidate query cache theo ID và collection owner; khi job đổi state, UI poll/stream phải cập nhật theo `job_id`.

Không cache password, session token, R2 credential, OpenRouter response thô hoặc PDF riêng tư vào `localStorage`. Service worker/CDN chỉ được cache asset public; API response riêng user phải có `Cache-Control: private, no-store` nếu chứa nội dung nhạy cảm.

## 4. Cấu hình và secret

Thứ tự ưu tiên:

```text
secret manager / process environment
  > .env trên server (không commit)
  > .env.example (placeholder, không secret)
  > default chỉ cho offline test
```

Các biến bắt buộc của runtime thật:

```text
PERSISTENCE_BACKEND=postgres
DATABASE_URL=postgresql+psycopg://...
STORAGE_BACKEND=r2
R2_ENDPOINT=...
R2_BUCKET=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
REPORT_QA_AI_MODE=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-6-luna
AUTH_REQUIRED=true
AUTH_COOKIE_SECURE=true       # HTTPS production
ASYNC_ANSWER_JOBS=true
```

Startup production phải fail-fast nếu thiếu DB/R2/AI secret, dùng dev fallback, hoặc `AUTH_COOKIE_SECURE=false`. `/health` chỉ trả trạng thái/capability đã mask; không trả DSN, bucket secret, token hay prompt đầy đủ.

Config được load một lần khi process start. Thay đổi model, bucket hoặc timeout phải restart API và worker cùng release; không để API và worker chạy hai bộ config khác nhau. Ghi `config_revision`/git SHA vào log startup để truy vết.

## 5. Job multi-user và worker riêng

API chỉ tạo job và placeholder message; worker riêng claim bằng lease:

```text
POST question
  → transaction: message accepted + assistant processing + jobs queued
  → worker claim (attempts++, lease_token, lease_expires_at)
  → heartbeat mỗi 20s
  → provider/tool call
  → can_publish kiểm tra lease + input_data_revision
  → transaction: answer_revision + inputs + message completed + job succeeded
```

Nếu process crash:

1. Lease hết hạn; worker khác reclaim nếu còn attempts.
2. Nếu lỗi tạm thời, `retry_scheduled` với backoff 1/2/4… giây.
3. Hết `max_attempts`, job `failed`, giữ `error_code` và event để UI cho phép retry thủ công.
4. Nếu evidence/data revision đã đổi, không publish kết quả cũ; job `superseded`.

`SOURCELENS_WORKER_ID` phải được dùng để định danh worker trong `job_events`; không dùng PID làm identity triển khai lâu dài. Mỗi worker phải chạy process/container riêng, không chạy background task trong uvicorn production.

## 6. Transaction publish và idempotency

Kết quả AI không được ghi từng phần vào nhiều transaction không có fence. Publish phải atomic ở mức database:

```text
verify lease + input revision
  → insert answer_revision (append-only)
  → insert answer_inputs / scopes / citations
  → update messages.current_answer_revision_id, status=completed
  → update jobs.status=succeeded, result
  → insert job_event(succeeded)
```

Retry cùng `dedup_key` không tạo thêm job. Retry sau crash trước commit sẽ chạy lại computation; retry sau commit phải thấy revision/message đã completed và không nhân đôi. Mọi external tool call nên có `tool_invocation_id`, request hash và timeout; response chỉ publish khi validate schema và citations.

## 7. Checklist kiểm thử multi-user

- [ ] A/B đăng ký; A không GET/PATCH/DELETE được ID của B.
- [ ] Logout làm cookie cũ không dùng được; revoke từng device làm session đó 401.
- [ ] Hai tab của cùng A rename/archived không làm mất dữ liệu của nhau; stale update nhận conflict rõ ràng.
- [ ] Hai user upload cùng tên vẫn có object key khác nhau và metadata đúng owner.
- [ ] Worker restart giữa extraction và publish: job reclaim/retry, không duplicate evidence/revision.
- [ ] OpenRouter timeout: job retryable, UI không hiện câu trả lời thành công giả.
- [ ] R2 `404` khi purge được coi là idempotent success; lỗi mạng giữ pending để retry.
- [ ] Cache của A không trả dữ liệu B sau logout/login đổi tài khoản.
- [ ] Đổi theme/profile/preferences ghi đúng `user_id`, reload vẫn giữ.
- [ ] Production config không in secret và fail-fast khi thiếu credential.

## 8. Trạng thái repo hiện tại

Đã có: opaque cookie + digest, owner-scoped repository, auth session revoke API, PostgreSQL job lease/retry, R2/AI readiness probe và async answer placeholder. Cần hoàn thiện trước khi gọi production thật: RLS hoặc private DB role được chốt bằng ADR, rate-limit login, purge outbox/delete worker, crash test tự động trong CI và bật `Secure` cookie trên HTTPS.

