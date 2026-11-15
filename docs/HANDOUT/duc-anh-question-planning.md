# Handout cho Đức Anh — hiểu câu hỏi và tạo kế hoạch thực thi

## 1. Kết quả cần bàn giao

Đức Anh sở hữu Question Planner: biến câu hỏi tự nhiên thành yêu cầu dữ liệu và phép tính rõ ràng. Output duy nhất là [question-plan-v2.schema.json](../../contracts/question-plan-v2.schema.json).

Planner không đọc PDF sâu, không chọn con số cuối cùng và không tính toán. Nó mô tả:

- cần fact nào;
- measure, subject, kỳ, unit và dimensions của từng fact;
- phép tính nào và thứ tự operand;
- fact nào được phép rơi xuống nguồn chart;
- câu hỏi có đủ rõ để chạy hay cần hỏi lại.

## 2. Ba trạng thái output

- `ready`: tất cả ý nghĩa cần thiết đã rõ; pipeline được phép retrieve/extract/calculate.
- `needs_clarification`: có ít nhất hai cách hiểu hợp lý; trả đúng một câu hỏi lại và các lựa chọn.
- `unsupported`: yêu cầu ngoài phạm vi hoặc không thể biểu diễn bằng operation hỗ trợ.

Không được trả `ready` bằng cách âm thầm chọn một cách hiểu.
Khi chưa xác định được phép tính hoặc yêu cầu nằm ngoài phạm vi, `operation` được để `null`; chỉ trạng thái `ready` mới bắt buộc có operation hoàn chỉnh.

## 3. Fact specification

Mỗi `fact` phải có key ổn định và trả lời được câu: “cần số gì, cho đối tượng nào, ở kỳ nào, đơn vị nào?”.

Ví dụ câu hỏi “Doanh thu Q1/2026 tăng bao nhiêu phần trăm so với Q1/2025?” cần:

```json
{
  "facts": [
    {
      "fact_key": "current",
      "measure": "doanh_thu",
      "subject": null,
      "period": "Q1/2026",
      "unit": "VND_BILLION",
      "dimensions": {},
      "required": true,
      "allowed_sources": ["table", "text", "chart"]
    },
    {
      "fact_key": "baseline",
      "measure": "doanh_thu",
      "subject": null,
      "period": "Q1/2025",
      "unit": "VND_BILLION",
      "dimensions": {},
      "required": true,
      "allowed_sources": ["table", "text", "chart"]
    }
  ],
  "operation": {
    "type": "growth_rate",
    "formula_id": "growth_rate_v1",
    "operand_fact_keys": ["current", "baseline"],
    "result_unit": "PERCENT"
  }
}
```

Thứ tự operand là contract. `difference(a,b)` nghĩa là `a-b`; `growth_rate(current,baseline)` lấy baseline làm mẫu số.

## 4. Operation được phép

| Operation | Công thức do code thực hiện | Điều kiện |
|---|---|---|
| `lookup` | `x` | một fact |
| `sum` | `Σx` | unit tương thích |
| `difference` | `a-b` | unit tương thích |
| `absolute_change` | `current-baseline` | unit tương thích |
| `growth_rate` | `(current-baseline)/baseline*100` | baseline khác 0 |
| `percentage_point_change` | `current_percent-baseline_percent` | cả hai là percent |
| `compare` | so sánh các operand | cùng measure/unit sau conversion hợp lệ |
| `ranking` | sắp hạng giá trị | nhóm fact đầy đủ |

LLM không được sinh kết quả số. Prompt chỉ được sinh `formula_id` và operand keys. Calculator map `formula_id` tới hàm code đã test.

## 5. Nguồn và chính sách chart

Planner luôn phát:

```json
{
  "priority": ["table", "text", "chart"],
  "chart_policy": "only_if_required_fact_unresolved",
  "chart_fact_keys": ["current"]
}
```

`chart_fact_keys` chỉ chứa fact mà câu hỏi thực sự có thể cần lấy từ chart. Việc có chart trong PDF không phải lý do để đọc chart. Resolver phải thử evidence text/bảng trước; chart adapter chỉ chạy nếu fact bắt buộc vẫn unresolved.

## 6. Xử lý riêng các tình huống bắt buộc

### Thiếu dữ liệu

Planner vẫn có thể trả `ready` nếu câu hỏi rõ. Sau retrieval, resolver/calculator trả `missing_data`; answer nói rõ thiếu fact nào và kỳ nào. Không thay missing bằng 0.

### Chia cho 0

Planner trả `growth_rate` bình thường nếu ngữ nghĩa rõ. Calculator phát hiện baseline `0`, trả `zero_denominator`; không trả vô cực, 0% hoặc một câu suy đoán.

### Sai đơn vị

Planner ghi unit mong đợi. Resolver chỉ conversion qua registry được duyệt. Nếu unit không tương thích, calculator trả `unit_mismatch`; LLM không tự quy đổi.

### Hai cách hiểu

Nếu câu hỏi “tăng bao nhiêu?” có thể là chênh lệch tuyệt đối hoặc phần trăm, trả:

```json
{
  "status": "needs_clarification",
  "clarification": {
    "reason_code": "AMBIGUOUS_OPERATION",
    "question_to_user": "Bạn muốn xem mức tăng tuyệt đối hay tỷ lệ tăng phần trăm?",
    "options": ["Mức tăng tuyệt đối", "Tỷ lệ tăng phần trăm"]
  }
}
```

Tương tự phải hỏi lại khi mơ hồ về measure, subject hoặc kỳ. Context hội thoại chỉ được dùng nếu referent gần nhất là duy nhất và còn hợp lệ với document version hiện tại.

## 7. Quy tắc không suy diễn

- Không suy năm báo cáo thành năm của mọi số.
- Không suy “quý này” nếu conversation context không có active period duy nhất.
- Không coi “tăng 5%” và “tăng 5 điểm phần trăm” là một.
- Không tự chọn consolidated/segment khi tài liệu có cả hai.
- Không tự điền unit từ một chart/bảng khác nếu không có liên kết vùng.

## 8. Acceptance tests tối thiểu

1. Lookup một số, có kỳ và subject.
2. Tổng nhiều fact cùng unit.
3. Hiệu với operand order chính xác.
4. Growth rate tạo hai fact current/baseline và đúng formula.
5. Phân biệt growth rate với percentage point change.
6. Mơ hồ operation, period, subject và measure đều trả clarification.
7. Missing context không bịa period.
8. Chart không cần thiết có `chart_fact_keys=[]`.
9. Câu hỏi cần chart chỉ đánh dấu đúng fact, không yêu cầu đọc mọi chart.
10. Output lạ field, thiếu fact hoặc formula không khớp operation phải fail schema.

## 9. Không thuộc trách nhiệm của Đức Anh

- Không OCR, parse bảng hoặc ước lượng trục chart.
- Không resolve evidence cụ thể.
- Không chạy phép tính.
- Không viết giá trị số vào answer.
- Không quyết định retry/provider timeout.

## 10. Trạng thái triển khai (branch `tien-fork`)

Planner nằm ở `services/backend/src/report_qa/application/question_planner.py`, được gọi trong `POST /api/v1/sessions/{session_id}/messages`.

- AI là planner mặc định khi có key. AI chỉ thấy catalog gồm measure, subject, kỳ, unit và tên cột, tên dòng. Mọi số trong đoạn chữ đều bị che, nên AI không thấy giá trị.
- Code dựng `question-plan-v2` từ output ngắn của AI và kiểm tra lại. Output sai format thì dùng planner regex cũ trong `p0_pipeline.py`. Trace ghi `planner`, `planner_fallback` và `rules_applied`.
- Luật hỏi lại chạy trên mọi plan, dù AI hay regex tạo ra: mức tăng tuyệt đối hay phần trăm, điểm phần trăm hay tương đối, nhiều loại lợi nhuận, quý không có năm, câu nối tiếp khi chưa có ngữ cảnh. Khi người dùng vừa chọn một lựa chọn, luật đó không hỏi lại lần nữa.
- `unsupported`, ví dụ dự báo hay xin ý kiến, dừng trước bước truy hồi, mode `question_unsupported`.

Cấu hình bằng biến môi trường, đặt trong `.env` (không commit):

| Biến | Ý nghĩa |
|---|---|
| `REPORT_QA_PLANNER_MODE` | `openrouter`, `sambanova`, `gemini` hoặc `rules`. Bỏ trống thì tự dùng provider đầu tiên có key. |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | Model mặc định `openai/gpt-6-luna` |
| `SAMBANOVA_API_KEY`, `SAMBANOVA_MODEL` | Model mặc định `Meta-Llama-3.3-70B-Instruct` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gọi qua endpoint tương thích OpenAI |
| `REPORT_QA_PLANNER_MODEL` | Ghi đè model riêng cho planner |

Test không cần mạng: `services/backend/tests/unit/test_question_planner.py` (10 acceptance test ở mục 8 cùng các ca dự phòng) và ba test API trong `tests/integration/test_session_api.py`. Integration test đặt `REPORT_QA_PLANNER_MODE=rules`.

Đánh giá trên 296 câu của bộ test phần hiểu câu hỏi (branch `ducanh`, thư mục `question-understanding`), chạy qua planner, resolver và calculator:

```bash
python scripts/eval_question_planner.py --qu-root ../question-understanding --model rules
```

Với một model trên OpenRouter, đặt `OPENROUTER_API_KEY` và giới hạn chi phí bằng `--budget`, ví dụ `--model meta-llama/llama-3.1-8b-instruct --budget 0.06 --record run.jsonl`. Dùng `--replay run.jsonl` để chạy lại mà không gọi model.
