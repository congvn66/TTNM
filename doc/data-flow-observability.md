# Data-flow observability va cach audit local

Tai lieu nay la huong dan doc luong du lieu dang chay, khong chi doc danh sach endpoint trong Swagger.

## 1. Kiem tra server va adapter

```powershell
$base = "http://127.0.0.1:8001"
Invoke-RestMethod "$base/" | ConvertTo-Json -Depth 6
Invoke-RestMethod "$base/health" | ConvertTo-Json -Depth 6
```

`/health` nam ngoai `/api/v1` co chu y de health probe khong phu thuoc version API. Ket qua can ghi nhan:

- `adapter`: persistence adapter hien tai;
- `durability`: local disk hay process memory;
- `ai_mode` va `ai_model`: request co goi AI that hay deterministic.

## 2. Luong PDF -> chat

| Buoc | Endpoint/diem xu ly | Du lieu vao | Du lieu duoc luu | Cach xac minh |
|---|---|---|---|---|
| 1 | `POST /api/v1/sessions` | `title` | session metadata trong `runtime/sessions.json` | GET sessions/session |
| 2 | `POST /api/v1/sessions/{id}/documents` | multipart PDF | binary tam -> atomic `runtime/uploads/{document_id}.pdf`, sha256 + metadata | `file_url`, `byte_size`, `sha256` |
| 3 | background extraction | PDF binary | `runtime/extractions/{document_id}.json`, page text | `extraction_status=ready`, `page_count` |
| 4 | `POST /api/v1/sessions/{id}/messages` | `document_id`, `question` | user + assistant message, citations, structured answer, trace | response `trace_id` + GET trace |
| 5 | `GET .../messages/{message_id}/trace` | session/message id | khong tao du lieu moi | stage trace theo thu tu |

## 3. Trace thanh cong can thay

Voi `REPORT_QA_AI_MODE=deterministic`, trace toi thieu la:

```text
question_received(ok)
retrieval(ok|weak_match)
answer_generation(ok)
persistence(committed)
```

Voi `gemini` hoac `openrouter`, trace thanh cong la:

```text
question_received(ok)
retrieval(ok|weak_match)
ai_provider(running, response_format=structured_json)
ai_provider(validated, response_sha256, cited_pages)
answer_generation(ok, format=structured_answer_v1)
persistence(committed)
```

`context_manifest` trong retrieval chi luu page, score, so ky tu va SHA-256 cua text; khong ghi prompt/raw PDF vao log.

## 4. Trace loi va ket luan dung

- `retrieval` score thap voi cau hoi khong phai summary: HTTP `422 NO_TEXT_EVIDENCE`; khong co assistant message moi.
- AI timeout/network/invalid structured output: HTTP `502` voi ma loi on dinh; trace co `ai_provider(failed)`; khong ghi assistant answer vao session.
- AI thanh cong nhung quote khong nam trong context: `AI_UNSUPPORTED_EVIDENCE`; day la loi grounding, khong phai loi UI.
- Chi khi co `persistence(committed)` moi ket luan message da duoc luu. `HTTP 200` mot minh khong thay the cho stage nay.

## 5. Lenh audit mot request

```powershell
$base = "http://127.0.0.1:8001"
$sessions = Invoke-RestMethod "$base/api/v1/sessions"
$session = $sessions.sessions | Where-Object { $_.documents.Count -gt 0 -and $_.documents[0].extraction_status -eq "ready" } | Select-Object -First 1
$doc = $session.documents[0]

$body = @{ document_id = $doc.id; question = "Tóm tắt nội dung chính của tài liệu" } | ConvertTo-Json
$answer = Invoke-RestMethod "$base/api/v1/sessions/$($session.id)/messages" -Method Post -ContentType "application/json; charset=utf-8" -Body $body
$answer | ConvertTo-Json -Depth 20

$trace = Invoke-RestMethod "$base/api/v1/sessions/$($session.id)/messages/$($answer.assistant_message.id)/trace"
$trace.trace | Select-Object stage,status,code,provider,model,cited_pages | Format-Table -AutoSize
```

Neu cau hoi AI that mat 20-35 giay, xem `ai_provider` truoc khi ket luan UI bi treo. Neu co `validated` nhung khong co `persistence`, day la bug transaction can sua; neu co `failed`, day la provider/config/network.

## 6. Audit luồng chính không phụ thuộc provider

Contract tests gọi trực tiếp session/document/message endpoints với adapter deterministic. Trace phải chứng minh question plan, evidence revisions, operand bindings, calculation status và answer revision theo đúng thứ tự. Fixture provider chỉ thay adapter AI; không tạo endpoint hay flow sản phẩm thứ hai.
