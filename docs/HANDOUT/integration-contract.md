# Hợp đồng tích hợp, persistence và trace

## 1. Sequence chuẩn duy nhất

| Bước | Component | Input | Output/trạng thái được lưu |
|---:|---|---|---|
| 1 | API | PDF + session | document/document_version `stored` |
| 2 | Base extractor | document version | evidence batch `base_document` |
| 3 | Publisher | validated batch | immutable extracted regions/evidences, extraction run `completed` |
| 4 | Question planner | question + chat context | question plan |
| 5a | Orchestrator | plan `needs_clarification` | assistant clarification; dừng |
| 5b | Resolver | plan `ready` + base evidence | resolved/missing fact set |
| 6 | Chart extractor, có điều kiện | chỉ unresolved chart fact | evidence batch `on_demand_chart` |
| 7 | Resolver | base + chart evidence revisions | final operand bindings |
| 8 | Calculator | plan + bound operands | calculation result |
| 9 | Answer composer | result + citations | structured answer, không tính lại |
| 10 | Publisher | tất cả snapshot | answer revision + inputs/scopes + trace |

## 2. Correlation IDs

Mọi stage phải mang:

- `trace_id`: một HTTP action;
- `session_id`, `document_version_id`;
- `question_plan_id` từ planner trở đi;
- `extraction_run_id` cho từng extraction batch;
- `evidence_revision_id` khi bind operand;
- `answer_revision_id` khi publish.

Không dùng text câu hỏi hoặc raw PDF làm correlation key.

## 3. Schema boundary

| Boundary | Schema |
|---|---|
| extractor → domain | `document-evidence-v2.schema.json` |
| planner → orchestrator | `question-plan-v2.schema.json` |
| calculator → answer composer | `calculation-result-v1.schema.json` |
| legacy/domain payload | các schema v1 còn lại trong `contracts/` |

Payload mẫu đầy đủ nằm trong `contracts/examples/`. Producer phải tạo payload tương đương và consumer phải contract-test bằng fixture này trước khi nối provider thật.

Schema đã phát hành là immutable về meaning. Thay đổi incompatible tạo file version mới. Consumer phải reject major version chưa hỗ trợ.

## 4. Trạng thái và error code ổn định

| Code | Nơi phát | Hành vi UI/pipeline |
|---|---|---|
| `QUESTION_NEEDS_CLARIFICATION` | planner | hiển thị câu hỏi + options; không chạy extraction/calculation |
| `QUESTION_UNSUPPORTED` | planner | giải thích phạm vi; dừng |
| `EVIDENCE_MISSING` | resolver | trả thiếu dữ liệu, liệt kê fact; không dùng 0 |
| `CHART_READ_AMBIGUOUS` | chart extractor | yêu cầu nguồn khác/xác nhận thủ công |
| `ZERO_DENOMINATOR` | calculator | không có numeric result |
| `UNIT_MISMATCH` | resolver/calculator | nêu hai unit; không tự convert |
| `STALE_INPUT_REVISION` | publisher | discard result, enqueue lại theo revision mới |
| `EVIDENCE_REVISION_CONFLICT` | evidence revision API | client đang sửa trên revision cũ; tải lại evidence/history rồi quyết định sửa lại |
| `VALUE_UNCHANGED` | evidence revision API | giá trị mới trùng revision hiện hành; không tạo history rỗng |
| `PROVIDER_TIMEOUT` | adapter | retry giới hạn; sau đó failed có thể retry |
| `SCHEMA_VALIDATION_FAILED` | boundary | không publish payload |

## 5. Transaction và persistence

- Base extraction chỉ publish sau khi toàn batch validate; `completed` là immutable.
- On-demand chart batch là extraction run riêng, liên kết `question_plan_id`; không sửa base run.
- Khi người dùng sửa evidence trong chat, tạo `evidence_revision` mới; extracted evidence gốc không đổi.
- Calculator nhận exact revision IDs. Answer publisher ghi `answer_inputs` trong cùng transaction với `answer_revision`.
- Worker publish chỉ khi `lease_token`, owner và `input_data_revision` còn hợp lệ.
- Redis chỉ phù hợp cache/notification/rate limit; không phải source of truth cho session, evidence, plan, calculation hay answer.
- PostgreSQL là source of truth đích; PDF/object binary ở object storage. Runtime JSON hiện tại chỉ là adapter local trong giai đoạn cutover.

### Week 1: contract đang chạy trong runtime local

Sau khi `completed`, mỗi numeric evidence có một revision `initialize` chứa
`numeric_value` gốc. API đọc evidence trả `original_numeric_value`,
`current_revision_id` và history append-only. API tạo revision yêu cầu
`numeric_value`, `reason`, `expected_revision_id`; revision `edit` luôn ghi
`old_numeric_value`, `numeric_value`, `previous_revision_id`, người thực hiện
và thời điểm. Nếu revision kỳ vọng không còn là current revision, server trả
`409 EVIDENCE_REVISION_CONFLICT` và không ghi gì.

Mỗi answer revision lưu `answer_inputs` gồm tối thiểu `evidence_key` và
`evidence_revision_id`. Khi một evidence đổi, answer đã snapshot revision cũ
được đánh dấu `needs_update`; không được ghi đè answer hoặc giả vờ rằng nó đã
tính lại. Recalculation tạo answer revision mới là bước tiếp theo của worker
PostgreSQL, chưa phải hành vi của runtime JSON local.

## 6. Trace tối thiểu

```text
QUESTION_RECEIVED
QUESTION_PLAN_CREATED | CLARIFICATION_REQUESTED
BASE_EVIDENCE_RESOLVED
CHART_READ_REQUESTED? -> CHART_EVIDENCE_PUBLISHED?
OPERANDS_BOUND
CALCULATION_SUCCEEDED | CALCULATION_REJECTED
ANSWER_COMPOSED
ANSWER_PERSISTED
```

Mỗi event log ID/count/status/timing, không log toàn văn PDF. `OPERANDS_BOUND` phải có mapping `fact_key -> evidence_revision_id`; `CALCULATION_*` ghi `formula_id`, status và reason code, không cần log prompt.

## 7. Contract tests ghép nhánh

### Happy path text/bảng

Planner tạo growth-rate plan → resolver bind hai evidence có bbox → chart adapter call count bằng 0 → calculator trả succeeded → answer có hai citation/input revisions.

### Happy path chart on-demand

Một fact thiếu ở base evidence → đúng một chart request cho đúng chart/fact → method label hiển thị “đọc từ nhãn” hoặc “ước lượng theo trục” → calculator chạy sau publish.

### Clarification

Planner trả `needs_clarification` → assert resolver/chart/calculator không được gọi → UI hiển thị options → câu trả lời của user tạo plan mới, không mutate plan cũ.

### Failure matrix

- required fact missing;
- baseline 0;
- VND và USD không có conversion;
- `%` vs percentage point;
- bbox invalid;
- chart payload chứa fact ngoài trigger;
- stale evidence revision khi calculator đang chạy;
- provider timeout/retry exhausted;
- duplicate request/idempotency.

## 8. Checklist handoff PR

- Link schema version và fixture mẫu.
- Liệt kê field producer đảm bảo và consumer sử dụng.
- Contract test chạy không cần provider/network.
- Recorded provider fixture đã loại dữ liệu nhạy cảm.
- Timeout/retry/maximum payload được cấu hình.
- Không có phép tính trong prompt hoặc answer composer.
- Trace chứng minh chart reader chỉ chạy khi cần.
