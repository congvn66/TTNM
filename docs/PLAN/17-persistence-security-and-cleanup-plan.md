# P0 plan: persistence, security và cleanup runtime

Tài liệu này chuyển kết quả audit tại [`../persistence-security-audit.md`](../persistence-security-audit.md) thành backlog có thứ tự. Không đánh dấu Done chỉ vì code đã viết; mỗi task phải có bằng chứng test tương ứng.

## 0. Trạng thái thực thi

- **P0-01 Inventory/readiness: Đạt cho lần chạy hiện tại.** Health/readiness trả về PostgreSQL và R2 `ok`; secret không được in.
- **P0-02 Round-trip: Đạt phần upload–read–archive.** Fixture thật đã ghi DB/R2, đọc lại đúng hash, archive đặt `deleted_at`; fixture đã được dọn sạch ở DB/R2.
- **P0-03 Owner isolation/RLS: Đạt phần backend negative test, chưa đạt RLS.** User B không đọc/xoá được session của A (`404`), A vẫn đọc được session của mình (`200`); schema vẫn chưa có RLS/policy nên cần ADR và DB access hardening.
- **P0-04 Purge worker: Chưa đạt.** Chưa có `ObjectStorage.delete_file`, outbox hoặc retry purge.
- **P0-05 Auth hardening: Chưa đạt.** Runtime còn `AUTH_COOKIE_SECURE=false`; chưa có fail-fast production/rate-limit đầy đủ.
- **P0-06 Cleanup quarantine: Đạt một phần.** Đã xoá artefact pytest/cache/screenshot/log cũ; giữ `runtime/`, source và browser profile.

## 1. Mục tiêu

- Chứng minh dữ liệu metadata sống bền trong Supabase và artifact sống bền trong R2.
- Phân biệt rõ archive mềm, purge bất đồng bộ và cache cục bộ.
- Không để người dùng hoặc frontend truy cập trực tiếp credential nhạy cảm.
- Đóng owner isolation, cookie/secret production và purge retry.
- Dọn artefact tạm mà không xoá nhầm PDF người dùng.

## 2. Thứ tự thực hiện

```text
P0-01 inventory + health probe
  -> P0-02 round-trip Supabase/R2
  -> P0-03 owner isolation + DB role/RLS decision
  -> P0-04 delete contract + outbox + R2 delete
  -> P0-05 auth production hardening
  -> P0-06 cleanup quarantine
  -> P1 load/failure/retention drills
```

## 3. Backlog chi tiết

### P0-01 — Inventory và readiness evidence

**Đầu ra:** report không chứa secret, gồm env flags, `/health`, `/health/ready`, process, bucket/key policy và manifest `runtime/tmp`.

**Acceptance:**

- Mask mọi DSN/password/token.
- Có timestamp, git SHA, adapter (`postgres`/`r2`) và version migration.
- Health fail nếu DB/R2 không sẵn sàng khi persistence mode yêu cầu chúng.

### P0-02 — Persistent round-trip

**Đầu ra:** script test tạo dữ liệu test riêng, upload PDF marker, query DB, `HeadObject`, restart API, đọc lại, rồi archive.

**Acceptance:**

- Hash byte trước/sau restart giống nhau.
- Metadata và extraction run vẫn có sau restart.
- Test không sử dụng PDF người dùng và có cleanup marker.
- Archive chứng minh `deleted_at`; không tuyên bố purge nếu chưa có delete adapter.

### P0-03 — Owner isolation và Supabase access model

**Đầu ra:** ADR chọn một trong hai: (A) backend-only private DB role + network restriction; (B) RLS đầy đủ theo `owner_id`.

**Acceptance:**

- User A không đọc/sửa/xoá được project/document/chat/job của user B.
- Frontend bundle không chứa `DATABASE_URL`, R2 secret, OpenRouter key hoặc service role.
- Nếu chọn RLS: migration có `ENABLE ROW LEVEL SECURITY`, policy cho bảng user-facing và test negative.
- Nếu chưa bật RLS: DB role không có quyền public/anonymous và chỉ backend truy cập.

### P0-04 — Delete contract và purge worker

**Đầu ra:** schema `deletion_requests`/outbox hoặc tương đương; `ObjectStorage.delete_file`; job idempotent, retry, audit.

**Acceptance:**

- DELETE chỉ tạo request/soft archive trong HTTP transaction.
- Worker xoá R2, local cache và cập nhật trạng thái.
- `404 Not Found` từ R2 được coi là idempotent success.
- DB lỗi/R2 lỗi không làm mất thông tin retry.
- UI chỉ hiện “đã xoá vĩnh viễn” sau `completed`.

### P0-05 — Auth production hardening

**Đầu ra:** fail-fast config, secure cookie, CSRF/rate-limit policy, secret rotation runbook.

**Acceptance:**

- Production thiếu secret mạnh hoặc `AUTH_COOKIE_SECURE=false` thì không start.
- Login thất bại có rate limit và audit event.
- Session revoke có test cross-user và concurrent revoke.
- Cookie có HttpOnly, Secure, SameSite phù hợp domain.

### P0-06 — Cleanup quarantine

**Đầu ra:** script/manifest cleanup chỉ nhắm `tmp/` và cache đã xác nhận; không xoá `runtime/uploads` mặc định.

**Acceptance:**

- Process được dừng hoặc lock được kiểm tra.
- Có dry-run và danh sách file trước khi xoá.
- Có policy retention cho log, extraction cache, PDF archive.
- Cleanup không chạm source/docs/.venv hoặc dữ liệu user nếu chưa có explicit approval.

## 4. Test matrix bắt buộc

| Nhóm | Ca kiểm thử | Kết quả cần thấy |
|---|---|---|
| Persistence | upload → restart → read | byte hash và metadata không đổi |
| Persistence | R2 timeout sau DB prepare | trạng thái retry, không báo thành công giả |
| Auth | user A truy cập ID của B | 404/403, không leak existence ngoài policy |
| Delete | archive hai lần | idempotent, một purge request |
| Delete | R2 404 | completed, audit rõ |
| Delete | worker crash giữa các bước | resume bằng lease/attempt |
| Security | production config dev secret | startup fail |
| Cleanup | dry-run tmp | chỉ liệt kê artefact được phép |

## 5. Không làm trong P0

- Không xoá hàng loạt `runtime/`.
- Không đổi toàn bộ key R2 cũ nếu chưa có migration.
- Không đưa Supabase credential vào frontend.
- Không coi local JSON hoặc `runtime/` là backup.
- Không bật hard-delete trực tiếp trong request.

## 6. Definition of Done

P0 chỉ hoàn thành khi có:

1. Migration/schema và code contract tương ứng.
2. Test integration với Supabase/R2 thật trong môi trường an toàn.
3. Report health + round-trip + negative access test.
4. Runbook rollback/retry/retention.
5. Cập nhật `docs/README.md`, data model, API contract và security operations.
 
## 7. Evidence cập nhật sau khi thực thi

- Migration Supabase đã ở head `0007_data_contract_hardening`.
- PostgreSQL/R2 readiness pass; OpenRouter live smoke pass với model `openai/gpt-6-luna`.
- Worker đã chạy process riêng ngoài API; `SOURCELENS_WORKER_ID` được ghi nhận trong `job_events`.
- Extraction job đã kiểm tra retry, lease expiry và explicit retry; answer job async đã publish thành công vào message/answer revision.
- Backend test: 134 passed, 2 skipped. Frontend test: 7 passed. Vite build pass.
- Không đánh dấu purge Done: archive hiện chỉ soft-delete vì chưa có delete adapter/outbox. Docling/DePlot đã live-pass; cần benchmark cold-start/CPU và giới hạn tài nguyên trước khi tải lớn.

Tài liệu multi-user/session/token/cache/config: [../multi-user-session-token-cache-config.md](../multi-user-session-token-cache-config.md).
