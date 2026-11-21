# Kế hoạch authentication, settings và theme

> Trạng thái: Proposed - chờ duyệt.

## 1. Phạm vi

- Email/password register, login, logout.
- Xác minh email (có thể tắt ở local dev), forgot/reset password.
- Opaque session cookie, xem và revoke sessions.
- Profile và preferences, gồm light/dark/system.
- Ownership boundary cho toàn bộ API.

Giai đoạn đầu không làm Google OAuth, organization, team invitation, SSO hoặc RBAC nhiều vai trò. Các phần này chỉ thêm sau khi personal workspace ổn định.

## 2. Quyết định bảo mật

- Mật khẩu hash bằng Argon2id; không tự viết crypto.
- Session token ngẫu nhiên đủ entropy; DB chỉ lưu hash token.
- Cookie: `HttpOnly`, `Secure` ở HTTPS, `SameSite=Lax`, path phù hợp.
- Rotate session sau login/password reset và các thay đổi nhạy cảm.
- CSRF token cho mutation cookie-auth; kiểm tra Origin/Referer bổ sung.
- Rate limit login/forgot/reset theo IP và account key.
- Response login không tiết lộ email có tồn tại hay không.
- Owner hiện tại lấy từ auth dependency; request body/query không được chọn owner.
- Password reset token dùng một lần, hash trong DB và có TTL ngắn.
- Không log password, session token, reset token hoặc cookie.

Supabase trong kiến trúc hiện tại chỉ là managed PostgreSQL. Không kết hợp Supabase Auth nửa vời với custom `auth_sessions`; nếu đổi nhà cung cấp auth phải có ADR và migration riêng.

## 3. Data model

### `users`

```text
id uuid PK
email citext UNIQUE NOT NULL
password_hash text NOT NULL
display_name text NOT NULL
email_verified_at timestamptz NULL
status text CHECK active|locked|deleted
created_at, updated_at timestamptz
```

### `auth_sessions`

```text
id uuid PK
user_id uuid FK
token_hash text UNIQUE
user_agent text NULL
ip_hash text NULL
created_at, last_seen_at, expires_at timestamptz
revoked_at timestamptz NULL
```

### `account_tokens`

```text
id uuid PK
user_id uuid FK
purpose text CHECK verify_email|reset_password
token_hash text UNIQUE
expires_at, consumed_at, created_at
```

### `user_preferences`

```text
user_id uuid PK/FK
theme text CHECK light|dark|system
locale text
default_answer_style text
created_at, updated_at
version bigint
```

Email nên dùng `citext` hoặc normalized lowercase có unique index. Delete account là workflow riêng, không phải `DELETE users` trực tiếp.

## 4. API contract

| Method | Endpoint | Kết quả |
|---|---|---|
| POST | `/api/v1/auth/register` | tạo account, session tùy policy |
| POST | `/api/v1/auth/login` | rotate/set cookie, trả user summary |
| POST | `/api/v1/auth/logout` | revoke session hiện tại, clear cookie |
| GET | `/api/v1/auth/me` | user + preferences |
| POST | `/api/v1/auth/forgot-password` | luôn trả accepted |
| POST | `/api/v1/auth/reset-password` | consume token, revoke sessions cũ |
| GET | `/api/v1/settings/profile` | profile |
| PATCH | `/api/v1/settings/profile` | đổi display name |
| GET/PATCH | `/api/v1/settings/preferences` | theme/locale/answer preference |
| GET | `/api/v1/settings/sessions` | danh sách session đã làm mờ thông tin |
| DELETE | `/api/v1/settings/sessions/{id}` | revoke session |

Mutation nhận `Idempotency-Key` khi hành vi có thể retry. Error dùng problem details thống nhất, không trả raw exception.

## 5. Frontend flow

### Bootstrap

1. Inline script đọc local theme bootstrap và đặt `data-theme` trước paint.
2. App gọi `/auth/me` một lần qua query layer.
3. 200: hydrate user/preferences; 401: route public hoặc login.
4. Không dùng localStorage để giả định đã đăng nhập.

### Login

- Disable submit trong request, nhưng giữ input và hiển thị lỗi inline.
- Success redirect về route hợp lệ trước login hoặc `/app`.
- Cookie do server set; frontend không đọc token.
- Login page không tải PDF engine.

### Settings

- Profile và preference dùng optimistic update có rollback.
- Security actions yêu cầu recent authentication nếu nhạy cảm.
- Theme preview áp dụng tức thời; lưu DB sau debounce/mutation rõ ràng.

## 6. Ownership enforcement

Mọi repository query phải nhận `owner_id` từ `CurrentUser`, ví dụ:

```text
get_document(document_id, owner_id)
move_document(document_id, owner_id, target_folder_id)
get_job(job_id, owner_id)
```

Không dùng pattern lấy theo ID rồi mới check ở Python nếu có thể filter ownership trực tiếp trong SQL. Foreign key/composite constraint bảo vệ chéo owner ở mức DB cho project/folder/document association.

## 7. Task breakdown

1. AUTH-001: migration users/sessions/tokens/preferences.
2. AUTH-002: password/session services và repository.
3. AUTH-003: auth middleware/dependency + CSRF.
4. AUTH-004: register/login/logout/me endpoints.
5. AUTH-005: forgot/reset + email adapter giả ở dev.
6. AUTH-006: settings/profile/preferences/sessions endpoints.
7. AUTH-007: frontend public routes và auth bootstrap.
8. AUTH-008: settings UI + theme bootstrap.
9. AUTH-009: ownership retrofit toàn bộ endpoint hiện tại.
10. AUTH-010: security integration/E2E tests.

## 8. Test bắt buộc

- Hash/verify password và migration hash parameters.
- Token raw không xuất hiện trong DB/log.
- Cookie flags đúng ở production config.
- Login rotate session; logout/revoke làm cookie cũ vô hiệu.
- Reset token hết hạn/dùng lại bị từ chối; reset revoke sessions cũ.
- CSRF và cross-origin mutation bị chặn.
- User A không đọc/sửa document, folder, chat, job của user B.
- Timing/error message không lộ account enumeration rõ ràng.
- Theme không flash sai màu; system change được phản ánh.
- Browser refresh giữ session và preference.

## 9. Definition of Done

- Không endpoint business nào còn nhận/trust `owner_id` từ client.
- Session tồn tại bền qua restart và revoke được.
- Không secret/token trong frontend state persistence.
- Auth/settings có loading, error, success và keyboard flow đầy đủ.
- Light/dark/system đồng nhất trên Login, Library, Workspace và Settings.
- Security test matrix pass trên PostgreSQL thật.
