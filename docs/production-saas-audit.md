# Production SaaS audit — SourceLens

Ngày audit: 2026-11-21  
Phạm vi: workspace PDF, thư viện, hồ sơ/cài đặt, upload–xử lý nền–hỏi đáp, bằng chứng và các API mà frontend hiện gọi.

## 1. Kết luận điều hành

Luồng chính đã có đủ điểm nối cho một bản bàn giao demo production: tạo phiên, thêm PDF trong phiên, mở PDF, chờ tài liệu sẵn sàng, hỏi đáp, mở bằng chứng/trang trích dẫn, xem trace, sửa số liệu, đổi tên và archive. Các thao tác này đều có endpoint backend tương ứng và trạng thái thành công/lỗi trên UI.

Các thay đổi đã thực hiện trong đợt audit này:

1. Bỏ nút **Thêm tài liệu** trùng lặp trên header workspace. Điểm vào duy nhất nằm trong phiên đang chọn.
2. Neo menu hồ sơ/tài khoản ở mép phải header; menu gồm hồ sơ, tuỳ chọn giao diện, bảo mật, chỉnh sửa nhanh và đăng xuất.
3. Thay ngôn ngữ kỹ thuật **lập chỉ mục/extraction** bằng ngôn ngữ người dùng: **Đang chuẩn bị tài liệu**, **Đang đọc tài liệu**, **Sẵn sàng để hỏi**, **Không thể đọc — thử lại**. Chi tiết kỹ thuật chỉ còn trong Trung tâm tác vụ/trace dành cho vận hành.
4. Sửa polling upload: frontend tiếp tục hỏi trạng thái ở cả `queued` và `processing`; trước đây chỉ polling `queued`, vì vậy tài liệu có thể bị kẹt ở trạng thái đang xử lý và ô chat bị khoá mãi.
5. Chuẩn hoá tên tác vụ `extract_document`/`document_extraction` và trạng thái hiển thị trong Trung tâm tác vụ.
6. Đổi nhãn **Nguồn & số liệu** thành **Bằng chứng**, phù hợp với hành vi mở vùng số liệu và lịch sử chỉnh sửa.

## 2. Kiến trúc điều hướng và điểm vào

| Scene | Route | Điểm vào chính | Kết quả quan sát được |
|---|---|---|---|
| Workspace | `/app/workspace` | Logo, menu Workspace, mở tài liệu | Sidebar phiên + PDF reader + trợ lý tài liệu |
| Thư viện | `/app/library` | Menu Tài liệu | Project, folder, lọc và mở tài liệu về workspace |
| Hồ sơ | `/app/settings/profile` | Menu hồ sơ | Xem/sửa tên hiển thị |
| Tuỳ chọn | `/app/settings/preferences` | Menu hồ sơ | Theme và tuỳ chọn giao diện được lưu qua API |
| Bảo mật | `/app/settings/security` | Menu hồ sơ | Đổi mật khẩu, danh sách/revoke phiên đăng nhập |
| Auth | `/login`, `/register`, `/forgot-password`, `/reset-password` | Khi `VITE_AUTH_REQUIRED=true` | Đăng nhập/đăng ký/khôi phục tài khoản |

Header workspace chỉ giữ bốn nhóm: nhận diện và context ở trái; điều hướng scene; trạng thái hệ thống/tác vụ; tài khoản ở mép phải. Không đặt upload toàn cục vì upload phụ thuộc phiên.

## 3. Ma trận luồng chính và API

| Luồng | Frontend gọi | Trạng thái UI | Điều kiện nghiệm thu |
|---|---|---|---|
| Tải workspace | `GET /health`, `GET /api/v1/sessions`, `GET /api/v1/jobs` | loading, offline, dữ liệu, retry | Backend lỗi không làm trắng trang; nút thử lại hoạt động |
| Tạo phiên | `POST /api/v1/sessions` | nút disabled khi đang gửi, toast thành công/lỗi | Phiên xuất hiện ngay, được chọn làm active và giữ sau reload |
| Đổi tên/archive phiên | `PATCH/DELETE /api/v1/sessions/{id}` | menu portal + dialog xác nhận | Không bị menu cắt bởi sidebar; archive chuyển sang phiên kế tiếp |
| Thêm PDF | `POST /api/v1/sessions/{id}/documents` | toast + tài liệu mới + job | Tệp >100 MiB, sai PDF, mất mạng đều có lỗi rõ; không mất tệp đang có |
| Chuẩn bị PDF | `GET /api/v1/sessions` polling `queued/processing` | Đang chuẩn bị → Đang đọc → Sẵn sàng/Không thể đọc | Không còn kẹt ở processing; khi ready composer tự mở |
| Đổi tên/archive PDF | `PATCH/DELETE /api/v1/sessions/{sid}/documents/{did}` | menu document + dialog | PDF reader chuyển sang tài liệu hợp lệ sau xoá |
| Đọc PDF | `GET .../documents/{id}/file` | loading/error/reader | PDF thật được render; zoom, pan, trang và citation box hoạt động |
| Hỏi đáp | `POST /api/v1/sessions/{sid}/messages` | optimistic user + typing assistant; 202 thì polling | Enter gửi ngay, lịch sử theo thứ tự, retry giữ idempotency key |
| Bằng chứng | `GET .../evidences` | drawer, sửa số, conflict/error | Có giá trị gốc, giá trị hiện tại, revision; click focus PDF |
| Trace | `GET .../messages/{mid}/trace` | panel trace | Hiển thị retrieval, calculator/provider, persistence và trace id |
| Tác vụ | `GET /api/v1/jobs`, `POST .../cancel|retry` | pill + drawer | Có thể huỷ/retry job; lỗi worker không làm hỏng workspace |
| Thư viện | `/api/v1/projects*`, `/api/v1/folders*` | project/folder/document list | Tạo/đổi tên/archive project, tạo/đổi tên/xoá folder, gán folder |
| Auth/settings | `/api/v1/auth/*`, `/api/v1/settings/*` | auth gate, settings scenes | Không lộ dữ liệu giữa owner; logout/revoke có hiệu lực |

## 4. Luồng chuẩn để QA/khách hàng kiểm thử

### 4.1. Workspace và upload

1. Mở `/app/workspace`; chờ trạng thái hệ thống.
2. Bấm **Tạo mới**, nhập tên, xác nhận. Kiểm tra phiên xuất hiện trong sidebar.
3. Trong phiên, bấm **Thêm tài liệu** và chọn PDF thật.
4. Kiểm tra toast xác nhận upload. Quan sát nhãn lần lượt **Đang chuẩn bị tài liệu**, **Đang đọc tài liệu**, **Sẵn sàng để hỏi**.
5. Nếu job lỗi, mở **Tác vụ đang chạy** và bấm **Thử lại**. Nếu tệp không đọc được, thông báo phải nói rõ thử lại hoặc chọn tệp khác.

### 4.2. Hỏi đáp và citation

1. Khi nhãn là **Sẵn sàng để hỏi**, nhập câu hỏi và bấm Enter.
2. Tin nhắn người dùng phải xuất hiện ngay; bubble trợ lý hiển thị ba chấm trong lúc chờ.
3. Với backend async, response `202` tạo assistant placeholder; UI polling session/jobs cho đến khi placeholder thành câu trả lời hoặc lỗi.
4. Câu trả lời có cấu trúc (ý, bảng, công thức, cảnh báo). Bấm citation phải đổi trang và focus vùng bounding box.
5. Bấm **Xem luồng dữ liệu** để kiểm tra trace. Đây là công cụ kiểm tra nội bộ, không phải nội dung bắt buộc với khách hàng.

### 4.3. CRUD và dữ liệu bền vững

1. Đổi tên phiên, refresh trang: tên mới vẫn còn.
2. Đổi tên PDF, mở lại reader: binary không đổi, tên hiển thị đổi.
3. Archive PDF/phiên: mục biến mất khỏi danh sách hiện tại; không xoá ngầm lịch sử revision.
4. Sửa một số trong **Bằng chứng**: nhập giá trị mới + lý do. Kiểm tra giá trị gốc, giá trị hiện tại, revision count và câu trả lời bị đánh dấu cần cập nhật.
5. Mở lại bằng chứng sau refresh: revision cũ/mới vẫn còn. Gửi revision với `expected_revision_id` cũ phải nhận conflict `409`, không ghi đè.

## 5. Trạng thái bắt buộc trên UI

Mọi scene phải có nội dung và hành động rõ ràng cho: loading lần đầu, đang xử lý, có dữ liệu, trống, không có kết quả, lỗi có thể thử lại, thiếu quyền, mất kết nối và thay đổi chưa lưu. Không dùng màu đơn độc để biểu diễn trạng thái; luôn có nhãn hoặc biểu tượng.

Các từ dành cho khách hàng:

- `queued`: Đang chuẩn bị tài liệu
- `processing`: Đang đọc tài liệu
- `ready`: Sẵn sàng để hỏi
- `failed`: Không thể đọc — thử lại
- job `queued/running`: Đang chờ xử lý/Đang xử lý
- job `failed`: Cần thử lại

Các từ như `extraction`, `retrieval`, `worker`, `trace_id`, `revision` chỉ xuất hiện trong drawer vận hành hoặc docs kỹ thuật.

## 6. Các phần chưa nên coi là hoàn tất

1. **Worker production**: async answer/extraction chỉ hoàn tất khi tiến trình worker thật chạy cùng PostgreSQL queue. Nếu worker không chạy, UI chỉ có thể hiển thị job pending; cần alert vận hành.
2. **Migration Supabase**: phải chạy Alembic `0007_data_contract_hardening` trên database thật và kiểm tra constraint/index; test offline không chứng minh được network hoặc quyền DB.
3. **OpenRouter/Gemini/R2**: cần smoke test với credential thật ngoài sandbox; unit test hiện chỉ kiểm tra contract và fallback.
4. **Auth production**: build production mặc định bật auth; vẫn nên đặt tường minh `VITE_AUTH_REQUIRED=true`, bật cookie/session an toàn và kiểm thử register/login/logout/revoke trên staging. Dev local có thể để `false` có chủ đích.
5. **Library UX**: `LibraryScreenV2` đã nối project/folder CRUD, nhưng cần thêm dialog native thay cho `window.prompt/confirm` trước khi coi là production UX hoàn chỉnh.
6. **Tính nguyên tử queue–answer**: cần hoàn thiện transaction publish placeholder/result và kiểm tra worker crash/retry để tránh assistant pending vô hạn.

## 7. Lệnh kiểm thử đã chạy

Frontend build đã chạy thành công với output audit ngoài thư mục `dist`:

```powershell
cd apps/web
npx.cmd vite build --configLoader runner --outDir C:\Users\Admin\Desktop\pro\_ttnm_web_build --emptyOutDir false
```

Lần chạy `npm.cmd test -- --run` bị chặn bởi tiến trình Vite đang giữ file tạm `.vite-temp`; đây là vấn đề môi trường Windows, không phải lỗi compile. Chạy lại sau khi dừng tiến trình dev đang dùng `apps/web/node_modules/.vite-temp`, hoặc dùng một workspace build/test riêng.

Backend/unit/reference test trước audit: `115 passed` và `13 passed`; validator mock: `contracts=8`, `domain_rows=82`, `mutations=12`, `pdfs=20`, `questions=180`, `reports=20`.

## 8. Checklist bàn giao

- [ ] `VITE_AUTH_REQUIRED=true` ở staging/production.
- [ ] PostgreSQL migration đã apply và health/readiness báo ready.
- [ ] Worker chạy độc lập, có restart policy và log job.
- [ ] R2 credentials có quyền tối thiểu; không đưa secret vào frontend.
- [ ] Upload một PDF chữ, một PDF bảng, một PDF có biểu đồ và một PDF lỗi.
- [ ] Kiểm tra citation page/bbox ở zoom 75%, 100%, 200%.
- [ ] Kiểm tra reload trình duyệt sau mỗi CRUD và sau sửa revision.
- [ ] Kiểm tra lỗi 401/403/404/409/422/502/503 với thông báo người dùng dễ hiểu.
- [ ] Không còn nhãn kỹ thuật “lập chỉ mục” ở luồng khách hàng.
- [ ] Kiểm tra header: tài khoản nằm ở mép phải, không đè status/theme/menu.
