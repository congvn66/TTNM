# Chạy SourceLens trên máy

Pull `main`, cài, điền `.env`, chạy 3 lệnh là dùng được app. Dữ liệu (tài khoản, báo cáo, câu hỏi, số đã sửa) nằm chung trên Supabase. File PDF nằm trên Cloudflare R2.

App gồm 3 phần chạy cùng lúc:

| Phần | Làm gì | Cổng |
|---|---|---|
| API | Nhận request từ web, đọc/ghi Supabase và R2 | 8000 |
| Worker | Đọc PDF vừa tải lên (bảng, số, biểu đồ), trả lời câu hỏi chạy nền | không có |
| Web | Giao diện | 4173 |

Thiếu worker thì báo cáo tải lên sẽ đứng ở "Đang đọc" mãi.

## 1. Cài một lần

Cần có: Python 3.12, Node 20 trở lên, Git. Báo cáo dạng scan (ảnh) cần thêm Tesseract có tiếng Việt.

Mac / Linux:

```bash
git clone https://github.com/congvn66/TTNM.git && cd TTNM
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,postgres,object-storage,pdf-extraction,docling-deplot]"
cd apps/web && npm install && cd ../..
brew install tesseract tesseract-lang   # chỉ cần nếu đọc báo cáo scan
```

Windows (PowerShell):

```powershell
git clone https://github.com/congvn66/TTNM.git; cd TTNM
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev,postgres,object-storage,pdf-extraction,docling-deplot]"
cd apps\web; npm install; cd ..\..
```

Windows đọc scan: cài Tesseract từ https://github.com/UB-Mannheim/tesseract/wiki và tick thêm "Vietnamese" lúc cài.

Lần đầu đọc PDF, Docling tự tải model (vài trăm MB). Lần đầu đọc biểu đồ, DePlot tải thêm khoảng 1 GB. Các lần sau không tải lại.

## 2. Điền `.env`

Tạo file `.env` ở thư mục gốc repo (cùng chỗ với `pyproject.toml`), dán mẫu dưới rồi điền 6 chỗ trống. File này đã nằm trong `.gitignore`, đừng commit và đừng gửi lên nhóm chat.

```dotenv
# AI
REPORT_QA_AI_MODE=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
REPORT_QA_ASSISTANT_MODE=tools
REPORT_QA_AI_TIMEOUT_SECONDS=60

# Đọc PDF
PDF_EXTRACTION_BACKEND=docling
CHART_READER_BACKEND=deplot
OMP_NUM_THREADS=4

# Supabase: chuỗi "Session pooler" (cổng 5432), bắt đầu bằng postgresql://
PERSISTENCE_BACKEND=postgres
DATABASE_URL=

# Cloudflare R2
STORAGE_BACKEND=r2
R2_ENDPOINT=
R2_BUCKET=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_REGION=auto

# Đăng nhập (tài khoản lưu trong Supabase)
AUTH_REQUIRED=true
```

- `GEMINI_API_KEY`: tự tạo ở https://aistudio.google.com/apikey.
- `DATABASE_URL` và 4 biến `R2_`: xin Quốc Anh.

Kiểm tra (chỉ in "set" hay "MISSING", không in giá trị):

```bash
.venv/bin/python scripts/check_env.py
```

Windows: `.venv\Scripts\python.exe scripts\check_env.py`

Kiểm tra kết nối Supabase và R2:

```bash
set -a; . ./.env; set +a
PYTHONPATH=services/backend/src .venv/bin/python scripts/check_postgres.py
PYTHONPATH=services/backend/src .venv/bin/python scripts/check_r2.py
```

Cả hai phải ra `"status": "ok"`.

## 3. Tạo bảng trong database

Chỉ cần khi database mới tinh hoặc khi có migration mới. Chạy lại nhiều lần cũng không sao.

```bash
scripts/migrate.sh            # Windows: .\scripts\migrate.ps1
```

## 4. Chạy app

Mở 3 cửa sổ terminal, mỗi cửa sổ một lệnh:

```bash
scripts/start_backend.sh      # Windows: .\scripts\start_backend.ps1
scripts/start_worker.sh       # Windows: .\scripts\start_worker.ps1
scripts/start_frontend.sh     # Windows: .\scripts\start_frontend.ps1
```

Mở http://127.0.0.1:4173, tạo tài khoản, bấm "Dùng thử báo cáo mẫu". Đúng thì sau khoảng 1 phút báo cáo chuyển sang "Sẵn sàng", có tóm tắt, hỏi được và sửa được số.

Cổng 8000 hoặc 4173 đã có app khác dùng (Mac / Linux):

```bash
API_PORT=8010 scripts/start_backend.sh
API_PORT=8010 WEB_PORT=4180 scripts/start_frontend.sh
```

Đổi cổng web thì thêm dòng `WEB_ORIGINS=http://127.0.0.1:4180` vào `.env` rồi chạy lại API, không thì trình duyệt chặn request.

## 5. Lỗi hay gặp

| Thấy gì | Vì sao | Sửa |
|---|---|---|
| Báo cáo đứng ở "Đang đọc" mãi | Worker chưa chạy | Chạy `start_worker` |
| `Missing .env` khi chạy script | Chưa tạo `.env` ở thư mục gốc | Làm bước 2 |
| Đăng nhập báo lỗi 503 `AUTH_REQUIRES_POSTGRES` | `PERSISTENCE_BACKEND` không phải `postgres` | Sửa `.env`, chạy lại API |
| `check_postgres.py` ra `unavailable` | Sai `DATABASE_URL`, hoặc mạng chặn cổng 5432 | Copy lại chuỗi Session pooler từ Supabase |
| Báo cáo scan ra chữ không dấu, tóm tắt lỗi | Tesseract thiếu tiếng Việt | Cài `tesseract-lang` (Mac) hoặc tick Vietnamese (Windows) |
| Web báo "Backend chưa sẵn sàng" | API chưa chạy, hoặc chạy ở cổng khác | Chạy `start_backend`, nhớ `API_PORT` nếu đã đổi |

## Chạy không cần cloud (offline)

Đổi trong `.env`: `PERSISTENCE_BACKEND=json`, `STORAGE_BACKEND=local`, `AUTH_REQUIRED=false`, xoá `DATABASE_URL` và các biến `R2_`. Dữ liệu nằm trong `runtime/` trên máy, không cần worker và không có đăng nhập. Web chạy bằng:

```bash
cd apps/web && VITE_AUTH_REQUIRED=false npm run dev
```

## Chạy test

```bash
PYTHONPATH=services/backend/src .venv/bin/python -m pytest -q services/backend/tests
cd apps/web && npx vitest run
```
