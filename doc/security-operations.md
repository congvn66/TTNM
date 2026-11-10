# Bao mat, van hanh va observability

## 1. Threat model toi thieu

| Rui ro | Vi du | Kiem soat |
|---|---|---|
| IDOR/cross-owner | Doan UUID chat/evidence/job | Owner-scoped query, FK/trigger, 404, test |
| Malicious PDF | file gia MIME, bomb, parser exploit | magic byte, size/page/time/memory limit, worker isolation, patch dependency |
| Secret/token leak | log cookie/provider key | token hash, log allowlist/redaction, secret store |
| Prompt/data exfiltration | PDF gui provider ngoai | policy/consent, minimum crop/context, provider config, audit |
| Stale/duplicate write | retry, worker cu | idempotency key, dedup key, lease, data revision fence |
| Stored content injection | file name/reason/model text | escape output, CSP, no raw HTML |
| Orphan object | DB rollback/storage success | staged upload, cleanup job, storage inventory reconciliation |

## 2. Auth/session

- Password Argon2id theo tham so hien hanh duoc review dinh ky.
- Session token ngau nhien entropy cao; cookie Secure/HttpOnly/SameSite.
- DB chi luu hash; revoke/expiry tren moi request nhay cam.
- Reset token mot lan, expiry ngan; reset thanh cong revoke session cu theo policy.
- Rate limit login/reset/upload/question theo user/IP voi response khong ro ri account.

## 3. Upload va parser isolation

- Validate extension khong du; kiem MIME + magic bytes + parser page count.
- Ten file chi de hien thi; storage key server-generated.
- Gioi han byte/page, decompression, wall time, memory va concurrent jobs.
- Parser/OCR trong worker quyen toi thieu, khong co credential DB admin.
- Artifact/crop private; signed URL ngan han.

## 4. Logging

Moi log structured co `timestamp`, `level`, `service`, `request_id`, `job_id`, `owner_hash` (neu can), `route/event`, `duration_ms`, `error_code`.

Cam log: password, raw token/cookie, provider secret, full PDF text, full prompt/response, signed URL day du. Error stack chi o server log; API dung error envelope.

## 5. Metrics va alert

- API: request count/error/p50/p95 theo route.
- Job: queued/running age, attempts, failure, lease reclaim, superseded.
- Extraction: pages, duration, region/evidence count, error types.
- Answer: action distribution, invalid provider output, latency/cost, input count.
- Correction: conflict rate, affected answer count, recalc success/latency.
- Storage/DB: object orphan, connection saturation, slow query, backup age.

Alert P0: cross-owner detection, backup/restore failure, secret leak. P1: queue age vuot threshold, provider failure spike, stale publish attempt bat thuong.

## 6. Backup va restore

- PostgreSQL PITR/backup theo moi truong; object versioning neu co.
- Backup ma hoa va access rieng.
- Restore drill dinh ky vao moi truong cach ly; verify row counts, FK, current pointers va object hash/sample open.
- RPO/RTO chua chot; phai do va ghi truoc demo co du lieu that.

## 7. Retention va purge

- Domain history giu den user delete/policy.
- Job events/request keys/token co TTL nhu `data-model.md`.
- Soft delete khong dong nghia da xoa du lieu.
- Purge co plan: cancel jobs -> lock/tombstone -> delete dependency -> delete object -> audit summary.
- Purge retry idempotent; object delete loi khong lam resource hien lai.

## 8. Incident/runbook toi thieu

1. Dung deploy/rotate key neu co kha nang leak.
2. Khoanh vung request/job/owner/resource IDs tu audit/log.
3. Tat provider/upload/worker path lien quan bang config neu can.
4. Bao toan log, khong copy du lieu nhay cam vao issue cong khai.
5. Recover/forward-fix; chay integrity validator va regression test.
6. Ghi timeline, impact, root cause va action item.

