# Implementation status: plans 07–14

Ngày cập nhật: 2026-11-19

Tài liệu này phân biệt phần đã chạy được với phần mới chỉ là thiết kế. Không coi một folder hoặc endpoint placeholder là đã hoàn thành feature.

## Đã triển khai trong vertical slice này

| Plan | Trạng thái | Bằng chứng |
|---|---|---|
| 07 – SaaS master | Đang triển khai | Design system, PostgreSQL/R2 health, queue boundary, worker command và frontend status đã có. Auth/library đầy đủ chưa xong. |
| 08 – Frontend architecture | Đã làm phần nền | Shared API client, ErrorBoundary, theme provider/bootstrap, lazy-load PDF.js, proxy health, asset manifest. `WorkspaceScreen` vẫn cần tách tiếp theo feature. |
| 09 – Auth/settings/theme | P0 auth/session + login/register UI đã nối | Register/login/logout/me/reset dùng opaque HttpOnly cookie, session hash trong PostgreSQL, origin guard, owner resolver và `AuthGate` khi `VITE_AUTH_REQUIRED=true`. Email delivery và UI settings đầy đủ vẫn còn. |
| 10 – Library/folder/version | Chưa hoàn tất | Session/document flow cũ vẫn chạy; folder tree, immutable version API, archive/purge chưa được bật. |
| 11 – Durable jobs | P0 queue + worker đã nối cho extraction và answer | Queue có dedup event, claim lease/reclaim, heartbeat, cancel, retry và owner-scoped events. `ASYNC_ANSWER_JOBS=true` tạo assistant placeholder, enqueue `answer_question`, worker chạy grounded pipeline và publish đúng placeholder. SSE, quota/load limiter và revision fence đầy đủ vẫn còn. |
| 12 – Backend modularization | Đang chuyển tiếp | Job queue đã tách thành infrastructure/API module; `api/main.py` vẫn còn orchestration cũ và chưa đạt Definition of Done. |
| 13 – Visual assets | Đã làm nền | Brand mark SVG, empty-library SVG, manifest và token system. Các variant processing/error và screenshot review còn lại. |
| 14 – Test rollout | Gate cục bộ đạt | Backend `112 passed`; frontend `npm.cmd run build` pass; chưa có Vitest/Testing Library/Playwright và chưa chạy cloud E2E. |

## Cách chạy phần đã triển khai

Terminal 1 – API:

```powershell
cd C:\Users\Admin\Desktop\TTNM
.\scripts\start_backend.ps1 -Reload
```

Terminal 2 – worker khi dùng PostgreSQL:

```powershell
cd C:\Users\Admin\Desktop\TTNM
.\scripts\start_worker.ps1
```

Terminal 3 – frontend:

```powershell
cd C:\Users\Admin\Desktop\TTNM\apps\web
npm.cmd run dev
```

Worker chỉ chạy khi `.env` có `PERSISTENCE_BACKEND=postgres`, `DATABASE_URL` hợp lệ và migration đã tạo bảng `jobs`. JSON/local mode tiếp tục dùng compatibility background task để test offline.

## Quality gates đã chạy

```powershell
$env:PERSISTENCE_BACKEND='json'
$env:STORAGE_BACKEND='local'
..\.venv\Scripts\python.exe -m pytest -q
cd apps\web
npm.cmd run build
```

Kết quả gần nhất: `112 passed`; Vite production build pass, initial JS chunk khoảng 262 kB và PDF engine được tách thành chunk lazy khoảng 443 kB.

## Phần bắt buộc tiếp theo để gọi là hoàn tất 07–14

1. Tách `WorkspaceScreen` thành `pages/`, `features/`, `entities/` và bỏ hẳn trace/audit UI khỏi product bundle.
2. Migration `0005_processing_answer_status` và `AUTH_REQUIRED=true` đã bật trên demo; tiếp theo hoàn thiện UI settings/email delivery và chạy IDOR E2E trên hai user. Compatibility mode vẫn dùng owner mặc định khi cờ này false.
3. Thêm migration/repository/API cho project, folder, document version và upload intent/complete.
4. Bổ sung polling/SSE, active-job quota và revision fence cho đường `answer_question`; hiện đã có queue/placeholder/worker nhưng chưa có realtime stream và stale revision guard đầy đủ.
5. Thêm Vitest/Testing Library/Playwright, visual snapshots light/dark và axe scan.
6. Chạy PostgreSQL/R2 E2E bằng fixture không nhạy cảm sau khi chủ sở hữu xác nhận việc ghi dữ liệu cloud.

## Cập nhật sau quality gate 2026-11-19

- Backend offline gate: `112 passed` với runtime test tách biệt khỏi server đang chạy.
- Frontend gate: Vitest/Testing Library `3 passed`; `npm.cmd run build` pass.
- Plan 10 đã có migration `0003_library_folders` và API CRUD nền cho folder; UI tree, document version và purge vẫn chưa hoàn tất.
- Plan 11 đã có queue/worker cho `extract_document`; answer job và streaming/polling vẫn chưa hoàn tất.
- Các test cloud PostgreSQL/R2 chưa chạy để tránh ghi dữ liệu thật khi chưa có xác nhận riêng.
- Frontend shell đã bỏ trạng thái hạ tầng khỏi header; thay bằng context tài liệu, điều hướng workspace, profile workspace và theme control. `Chế độ demo` là nhãn trung thực vì auth/ownership thật chưa được bật.
- Backend P0 audit 2026-11-19: thêm auth/session routes, settings profile/preferences, owner-scoped library/jobs, job events/retry, worker heartbeat và answer job adapter. Offline regression: `116 passed` (112 legacy + 4 auth contract).
- Runtime demo sau restart: `/health` xác nhận `ai_mode=openrouter`, `ai_model=openai/gpt-6-luna`, PostgreSQL/R2 healthy; unauthenticated business route trả `401 AUTH_REQUIRED`.
- Supabase đã được migrate từ `0002_chat_documents` lên `0005_processing_answer_status (head)` trong lần audit này. Auth hash dùng Argon2id khi `argon2-cffi` có trong environment; local fallback là `scrypt$v1` để test không bị chặn bởi dependency optional. Production install phải dùng nhóm dependency `postgres` và không được coi fallback là cấu hình production cuối cùng.
- AI provider vẫn chỉ gọi model khi `REPORT_QA_AI_MODE=gemini|openrouter`; để `deterministic` là an toàn mặc định. Provider output luôn qua schema/citation validator; formula trong model chỉ là presentation, calculator server mới authoritative.

## P0 integration audit (2026-11-21)

Không đánh dấu adapter là “đã kết nối” chỉ vì có biến môi trường. Lệnh kiểm tra
chuẩn là:

```powershell
.\.venv\Scripts\python.exe scripts\check_integrations.py
.\.venv\Scripts\python.exe scripts\check_integrations.py --pdf services\backend\tests\fixtures\extraction\report.pdf
.\.venv\Scripts\python.exe scripts\check_integrations.py --live-ai
```

Kết quả trên môi trường hiện tại:

| Thành phần | Kết quả | Ý nghĩa |
|---|---|---|
| OpenRouter | `ok`; `--live-ai` trả structured response | Đã gọi thật model `openai/gpt-6-luna`, có citation page và schema hợp lệ |
| PDF extractor | `docling / ok` | Runtime chọn `PDF_EXTRACTION_BACKEND=docling`; fixture 3 trang trả 18 evidence, 0 warning |
| Docling | `installed / live-pass` | Docling 2.142.1 chạy trên Python 3.14; lần đầu tải model mất khoảng 7,8 phút trên CPU |
| DePlot | `installed / live-pass` | Transformers 5.20.2 + Torch 2.15.0; weights `google/deplot` đã tải và suy luận biểu đồ mẫu thành bảng |
| PostgreSQL/Supabase | `unavailable / OperationalError` | Không chứng minh được kết nối cổng 5432 từ môi trường chạy kiểm tra |
| Cloudflare R2 | `unavailable` | Không chứng minh được bucket qua mạng hiện tại |
| Worker | `requires_external_worker` | Phải chạy `scripts/start_worker.ps1` bằng terminal có kết nối DB |

API hiện có hai probe rõ ràng: `/health` là liveness và trả thêm
`capabilities/readiness`; `/health/ready` trả `503` cùng `blockers` nếu adapter
được chọn chưa sẵn sàng. Vì vậy tài liệu không còn hiển thị “đã lập chỉ mục” hay
“đã kết nối” khi worker/DB/R2 chưa được xác minh. Worker cũng reconnect với
exponential backoff thay vì thoát ngay khi pooler tạm thời mất kết nối.
## P0 audit follow-up (2026-11-20)

- Answer jobs now carry the authenticated `owner_id` in their payload; the worker rejects jobs without it.
- Worker answer execution runs against a deep-copied session snapshot. Temporary pipeline messages are therefore not persisted as a second user/assistant pair.
- PostgreSQL queue exposes `can_publish(job_id, lease_token, input_data_revision)`. The worker checks ownership, cancellation/lease replacement, and chat revision immediately before publishing.
- PostgreSQL catalog sync is owner-filtered; a process cache containing multiple users can no longer replay another owner's session through the current owner's store.
- Frontend active-job indicator now includes both `queued` and `running` jobs, and chat auto-scroll reacts to processing/status/body updates instead of only message-count changes. The mode badge reflects the latest assistant answer.

Validation in this environment: integration API `16 passed`; remaining backend compatibility tests `94 passed` (the two Docling tests require a writable temporary directory). Frontend test/build commands were blocked by Windows permissions on the repository `node_modules/.vite-temp`, not by an application assertion.
