# Handout triển khai một luồng Document QA

## 1. Mục tiêu chung

Repository chỉ còn **một luồng sản phẩm**. Không có fixture API hay luồng kiểm thử song song:

```text
Upload PDF
  -> trích xuất nền (văn bản + bảng)
  -> lập chỉ mục
  -> hiểu câu hỏi và tạo QuestionPlan
  -> tìm evidence trong text/bảng
  -> nếu fact bắt buộc chưa đủ và plan yêu cầu chart: đọc đúng chart cần thiết
  -> resolve evidence revisions
  -> tính bằng code
  -> soạn câu trả lời + citation
  -> lưu message, answer revision, input snapshot và trace
```

### Week 1 — sửa số và truy xuất lịch sử (đã chạy local)

Sau khi extraction hoàn tất, runtime local tạo revision `initialize` cho từng
numeric evidence. Trên UI, mở **Dữ liệu** → chọn số → nhập giá trị mới và lý do
→ lưu revision. API chỉ append, không ghi đè:

```text
extracted evidence (bất biến, 100)
  -> initialize revision (100, r1)
  -> edit revision (old=100, new=110, reason, previous=r1, r2)
  -> answer_inputs snapshot dùng r1
  -> answer dùng r1 được đánh dấu needs_update
```

`expected_revision_id` là optimistic-concurrency fence: hai thao tác sửa cùng
lúc không thể cùng tạo revision kế tiếp. Request mang revision cũ nhận
`409 EVIDENCE_REVISION_CONFLICT`. Runtime JSON local **chưa tự động tính lại**;
nó giữ nguyên answer snapshot cũ để audit và đánh dấu câu trả lời cần tính lại.
Worker PostgreSQL sẽ tạo `answer_revision` mới ở bước cutover sau.

Nguyên tắc chốt:

- Text và bảng được đọc khi ingest tài liệu; biểu đồ chỉ được đọc theo nhu cầu của một câu hỏi cụ thể.
- Mỗi con số dùng để trả lời hoặc tính toán phải có `document_version_id`, trang bắt đầu từ 1 và `bbox` chuẩn hóa `[x0,y0,x1,y1]`.
- Giá trị số đi qua boundary bằng chuỗi thập phân; `0` là dữ liệu hợp lệ, không phải missing.
- LLM có thể hiểu câu hỏi và soạn câu; LLM không thực hiện phép tính và không tự điền dữ liệu thiếu.
- Một câu hỏi mơ hồ phải dừng ở `needs_clarification`. Không chạy chart reader, calculator hay answer composer trước khi người dùng chọn cách hiểu.
- Answer phải snapshot đúng `evidence_key` + `evidence_revision_id` đã dùng. Sửa evidence tạo revision mới, không sửa answer cũ; answer dùng revision cũ phải được đánh dấu `needs_update`.

## 2. Phân công và ranh giới

| Chủ trì | Phần sở hữu | Input chính | Output bắt buộc |
|---|---|---|---|
| Tiền | Đọc văn bản, bảng; đọc biểu đồ theo yêu cầu | PDF, `document_version_id`; với chart có thêm `QuestionPlan` | `document-evidence-v2` |
| Đức Anh | Hiểu câu hỏi và lập kế hoạch | câu hỏi, ngữ cảnh hội thoại, catalog measure/unit/period | `question-plan-v2` |
| Integration/backend | resolve evidence, calculator, persistence, API, trace | hai contract trên | `calculation-result-v1`, answer revision |
| Frontend | trạng thái tiến trình, clarification, citation/PDF highlight | API chính | UI theo một session/document flow |

Không được truyền object Python nội bộ, prompt text hoặc JSON tự do qua ranh giới nhóm. Payload phải validate bằng schema trong `contracts/`.

## 3. Tài liệu giao việc

- [tien-extraction.md](tien-extraction.md): đặc tả đọc text/bảng/chart và acceptance tests.
- [duc-anh-question-planning.md](duc-anh-question-planning.md): đặc tả hiểu câu hỏi, ambiguity và operation plan.
- [integration-contract.md](integration-contract.md): thứ tự gọi, trạng thái, error code, persistence và test tích hợp.

## 4. Definition of Done chung

Một thay đổi chỉ được coi là hoàn thành khi:

1. Output validate được bằng schema tương ứng.
2. Có fixture deterministic cho happy path và ít nhất một failure path.
3. Không có số nào thiếu trang/bbox/phương pháp đọc.
4. Chart reader không chạy nếu text/bảng đã đáp ứng đủ fact hoặc plan không yêu cầu chart.
5. Calculator có test cho missing, mẫu số 0, sai đơn vị và phân biệt `% thay đổi` với `điểm phần trăm`.
6. Trace cho phép nối `question_plan_id -> evidence_key + evidence_revision_id -> calculation result -> answer_revision_id`.
7. Khi sửa một số, API lưu đủ `old_numeric_value`, `numeric_value`, `reason`, `previous_revision_id`; history đọc lại được và request revision cũ trả `409`.
8. Không log toàn văn PDF, prompt chứa dữ liệu tài liệu, API key hoặc PII.

## 5. Thứ tự ghép nhánh

1. Chốt schema và fixtures.
2. Ghép Question Planner; chưa gọi extractor/chart/calculator.
3. Ghép base extraction text/bảng.
4. Ghép evidence resolver và nhánh `missing`.
5. Ghép chart on-demand với mock adapter trước, provider thật sau.
6. Ghép calculator deterministic.
7. Ghép answer composer, persistence, trace và UI clarification/citation.

Không ghép provider AI thật trước contract test: nếu làm vậy sẽ khó phân biệt lỗi prompt, lỗi schema và lỗi nghiệp vụ.
