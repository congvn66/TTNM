# Kiểm tra tích hợp thật

`/health` chỉ trả lời một câu hỏi: tiến trình FastAPI còn nhận request hay
không. Nó không đồng nghĩa với việc PostgreSQL, R2, Docling, DePlot hay model
AI đã sẵn sàng. Vì vậy hệ thống có thêm `/health/ready` và một CLI tổng hợp.

## Kiểm tra không gọi AI

Từ thư mục gốc:

```powershell
.\.venv\Scripts\python.exe scripts\check_integrations.py
```

Kết quả là JSON không chứa secret. Các trường quan trọng:

| Trường | Ý nghĩa |
|---|---|
| `capabilities.ai` | Mode/model và việc đã có key hay chưa; chưa gửi request mạng |
| `capabilities.pdf_extraction` | Backend đang chọn (`legacy` hoặc `docling`) và module còn thiếu |
| `capabilities.chart_reader` | DePlot có đủ `transformers`, `torch`, Pillow và PyMuPDF hay chưa; không tải weights |
| `capabilities.database` | Kết nối PostgreSQL/Supabase thật |
| `capabilities.storage` | Bucket Cloudflare R2 thật |
| `capabilities.worker` | Chế độ queue; PostgreSQL + async cần chạy worker riêng |

`status=degraded` là kết quả trung thực, không phải lỗi của script. Ví dụ
PostgreSQL/R2 đang `unavailable` hoặc Docling/DePlot chưa được cài thì chưa thể
coi luồng production đã thông.

## Chạy một lần với PDF thật

Lệnh này chạy đúng backend được chọn trong `PDF_EXTRACTION_BACKEND` và không
gọi DePlot nếu câu hỏi không yêu cầu biểu đồ:

```powershell
.\.venv\Scripts\python.exe scripts\check_integrations.py --pdf .\path\to\report.pdf
```

Nếu đang chọn `PDF_EXTRACTION_BACKEND=legacy`, kết quả chứng minh chỉ legacy
đọc được PDF. Muốn kiểm tra Docling thật, cài extra trên Python tương thích rồi
đổi biến môi trường:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[docling-deplot,dev,postgres]"
$env:PDF_EXTRACTION_BACKEND = "docling"
$env:CHART_READER_BACKEND = "deplot"
.\.venv\Scripts\python.exe scripts\check_integrations.py --pdf .\path\to\report.pdf
```

Không coi test fixture/injected predictor là model DePlot thật: chúng chỉ kiểm
tra parser, provenance và schema. DePlot thật chỉ được xác nhận khi
`transformers`, `torch` tồn tại và một câu hỏi có trigger biểu đồ chạy thành
công.

## Gọi provider thật có chủ ý

Lệnh sau gửi đúng một request nhỏ tới provider đang chọn, có thể phát sinh chi
phí:

```powershell
.\.venv\Scripts\python.exe scripts\check_integrations.py --live-ai
```

`status=ok` ở `live_ai` chỉ chứng minh request, JSON schema và citation validator
đã đi qua. Nó không chứng minh retrieval của mọi tài liệu. Nếu gặp lỗi mạng
`WinError 10013`, proxy/firewall/sandbox đang chặn kết nối; không phải lỗi
schema của OpenRouter.

## Chạy smoke test phụ thuộc mạng

Test mặc định không gọi mạng ngoài. Khi đã export đúng `DATABASE_URL`,
`PERSISTENCE_BACKEND=postgres`, `STORAGE_BACKEND=r2`, các biến `R2_*` và
`REPORT_QA_AI_MODE`/API key thật, bật rõ cờ live:

```powershell
$env:SOURCELENS_LIVE_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest -q services/backend/tests/integration/test_live_adapters.py
```

Hai test này kiểm tra PostgreSQL `SELECT`/health, bucket R2 và một câu trả lời
structured từ provider thật. Nếu không bật cờ, test bị skip có chủ ý; không được
đọc kết quả skip là đã tích hợp thành công.

## Kiểm tra readiness từ trình duyệt/Swagger

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/health/ready
```

`/health/ready` trả `200` khi các adapter bắt buộc đã sẵn sàng, hoặc `503` kèm
`blockers` khi chưa. Endpoint không tải model DePlot và không gọi AI để tránh
request bất ngờ. Khi `ASYNC_ANSWER_JOBS=true`, worker phải chạy riêng:

```powershell
.\scripts\start_worker.ps1
```

Worker mới thêm job vào hàng đợi PostgreSQL; nếu worker không chạy, tài liệu có
thể giữ `queued` và chat trả placeholder `processing` một cách đúng trạng thái,
không giả vờ đã hoàn tất.
