# SourceLens MVP — thiết kế chuẩn v1 và trạng thái triển khai

> Đây là tài liệu tổng hợp chuẩn để review hệ thống hiện tại. Nó phân biệt rõ
> **đã chạy**, **đã thiết kế nhưng chưa bật**, và **ngoài phạm vi MVP**.

## 1. Trạng thái chuẩn

| Hạng mục | Trạng thái hiện tại | Kết luận |
|---|---|---|
| React PDF reader + chat | Đã chạy | Có thể upload, đọc PDF, hỏi đáp và nhảy citation theo trang |
| Retrieval text | Đã chạy | Token-overlap local, chọn tối đa 3 trang |
| AI structured output | Đã chạy theo adapter | Gemini/OpenRouter có schema và grounding validation |
| Trace request | Đã chạy | `question_received -> retrieval -> AI -> answer_generation -> persistence` |
| Session/document/message persistence | Đã chạy local | JSON + local filesystem, không phải production DB |
| PostgreSQL schema | Đã thiết kế + baseline migration | Chưa phải runtime source of truth |
| PostgreSQL repository/UoW | Chưa hoàn tất | Không được bật `PERSISTENCE_BACKEND=postgres` |
| Redis | Chưa dùng | Chỉ cân nhắc cache/lock/progress sau PostgreSQL |
| Evidence bbox cho PDF upload mới | Đã chạy cho số trong PDF text/layout table | Bbox normalized; scan/OCR và bảng phức tạp vẫn cần provider |
| Question Planner P0 | Đã chạy deterministic | Growth/lookup và clarification; coverage ngôn ngữ/nghiệp vụ còn hẹp |
| Calculator P0 | Đã chạy trong `/messages` | Decimal, missing, zero denominator, unit mismatch; AI không tính |
| Chart on-demand | Có port và demand gate | Adapter thật chưa triển khai; thiếu fact trả trạng thái rõ |

## 2. Data flow đang chạy

```text
Upload PDF
  -> validate extension/header/100 MiB
  -> temporary file
  -> SHA-256
  -> atomic rename: runtime/uploads/{document_id}.pdf
  -> runtime/sessions.json (metadata)
  -> background extraction
  -> runtime/extracted/{document_id}.json

Ask question
  -> question_received
  -> ownership/document check
  -> token-overlap retrieval (max 3 pages)
  -> reject weak evidence (422) hoặc gọi AI adapter
  -> validate structured answer, cited pages và quote grounding
  -> answer_generation
  -> persist user + assistant message + trace
  -> persistence.committed
```

Chỉ `persistence.committed` xác nhận câu trả lời đã được lưu. AI timeout,
network error hoặc output sai schema trả `502` và không ghi assistant answer.

## 3. Data flow đích với PostgreSQL

```text
React
  -> FastAPI
  -> application flow + UnitOfWork
  -> PostgreSQL transaction
       sessions/chats/messages
       documents/document_versions
       extraction_runs/source_regions/extracted_evidences
       evidence_revisions/answer_revisions
       jobs/job_events/audit_events/request_keys
  -> object storage (PDF, page image, extraction artifact)
  -> worker lease + provider/calculator
  -> answer revision publish với input_data_revision fence
```

PostgreSQL là source of truth cho metadata, lịch sử, revision, job và audit.
Object storage giữ artifact lớn. Redis, nếu bổ sung, không được giữ dữ liệu duy
nhất.

## 4. Persistence hiện tại

| Dữ liệu | Runtime hiện tại | Đích PostgreSQL |
|---|---|---|
| Session/chat/message | `runtime/sessions.json` | `chats`, `messages` |
| PDF | `runtime/uploads/*.pdf` | `document_versions.storage_key` + object storage |
| Text extraction | `runtime/extracted/*.json` | `extraction_runs`, `source_regions` |
| Trace | assistant message + log | `audit_events`, `job_events`, answer metadata |
| Question plan/calculation | Chưa persist đầy đủ ở runtime local | `jobs`, plan payload, revisions, answer graph |

## 5. Invariants bắt buộc

- Không tin `owner_id` từ client.
- PDF/version/extraction completed bất biến.
- Evidence correction tạo revision mới, không update lịch sử.
- Answer/recalculation tạo answer revision mới và snapshot input revisions.
- `bbox=[x0,y0,x1,y1]`, normalized 0..1, page bắt đầu từ 1.
- Số chính xác qua API là decimal string; số 0 khác missing.
- Công thức chạy bằng code deterministic, không giao phép tính authoritative cho LLM.
- Citation/quote phải thuộc context server đã chọn.
- Không publish job nếu lease hoặc input revision đã stale.

## 6. Cách kiểm tra một request

1. `POST /api/v1/sessions`
2. `POST /api/v1/sessions/{id}/documents`
3. Chờ `extraction_status=ready` bằng `GET /api/v1/sessions/{id}`
4. `POST /api/v1/sessions/{id}/messages`
5. Dùng `assistant_message.id` gọi `GET .../messages/{message_id}/trace`
6. Kiểm tra stage cuối là `persistence=committed`

Chi tiết lệnh terminal nằm trong [data-flow-observability.md](data-flow-observability.md).

## 7. Tiêu chí chuyển production

Chưa được đánh dấu production-ready cho tới khi PostgreSQL repository/UoW,
Alembic upgrade/downgrade, migration dữ liệu local, durable job lease,
ownership/race tests và object-storage verification đều pass.

## 8. Luồng nghiệp vụ duy nhất để triển khai tiếp

Luồng đích được chốt là `base text/table extraction -> question plan -> evidence resolution -> chart on-demand nếu còn thiếu fact -> deterministic calculator -> answer + citations -> persistence`. Không tạo một API/ứng dụng kiểm thử riêng; fixture deterministic chạy qua cùng application ports và contract như production.

- Tiền bàn giao payload `document-evidence-v2`: mọi số có trang, bbox và phương pháp đọc; chart chỉ dùng “đọc từ nhãn” hoặc “ước lượng theo trục”.
- Đức Anh bàn giao payload `question-plan-v2`: fact, kỳ, unit, operand order, formula ID hoặc clarification.
- Calculator bàn giao `calculation-result-v1`; missing, mẫu số 0, unit mismatch và ambiguity không có numeric result.
- Hợp đồng và acceptance criteria chi tiết nằm tại [HANDOUT/README.md](HANDOUT/README.md).

Runtime P0 hiện lưu `question_plan`, `calculation_result`, `answer_inputs`, citation bbox và trace ngay trong assistant message của `runtime/sessions.json`. Đây là adapter local phục vụ kiểm chứng luồng; PostgreSQL revision graph vẫn là bước cutover tiếp theo.
