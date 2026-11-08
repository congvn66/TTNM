# Khung code data flow và data design

## 1. Phạm vi đã triển khai

Khung domain/application là một lát cắt chạy được, chưa phải production persistence implementation. Invariant được biểu diễn bằng Python thuần; HTTP runtime, AI adapter, JSON persistence và PostgreSQL/Alembic foundation đã được thêm ở lớp ngoài:

```text
services/backend/
|-- src/report_qa/
|   |-- domain/
|   |   |-- models.py       # entity/revision/job dataclass
|   |   |-- types.py        # enum, decimal, bbox invariant
|   |   |-- contracts.py    # provider/semantic boundary validation
|   |   |-- schema.py       # inventory + ownership cua 23 bang
|   |   |-- service.py      # phép tính exact decimal
|   |   `-- errors.py       # error code ổn định
|   |-- application/
|   |   |-- ports.py        # typed repository/clock/id boundary
|   |   `-- flows.py        # upload, extract, question, evidence, answer
|   |-- infrastructure/
|   |   `-- memory.py       # adapter deterministic + Unit of Work cho test
|   `-- worker/
|       `-- handlers.py     # claim/supersede lease skeleton
`-- tests/unit/test_data_flow.py
```

## 2. Data flow hiện có

### Upload và extraction

`UploadFlow.start` kiểm tra PDF envelope, tạo `document_version`, `extraction_run` và job `extract_document` trong cùng application boundary. Idempotency key trả lại cùng kết quả; storage key do server sinh.

`ExtractionFlow.complete` nhận output đã được adapter chuẩn hóa, kiểm tra region/evidence cùng run, bbox, decimal, value kind và data status. Khi hoàn tất, run chuyển `completed` và version chuyển `ready`; lần complete sau bị từ chối để giữ immutable extraction.

### Evidence trong chat

`ExtractionFlow.attach_evidence` tạo liên kết chat và revision `initialize`. `EvidenceFlow.apply_revision` yêu cầu `expected_revision_id`, bắt buộc reason cho edit/mark-error/restore, tạo revision mới, di chuyển current pointer và tăng `chat.data_revision`.

Flow tìm answer bị ảnh hưởng qua direct input hoặc scope cùng `chat_source_id`, đánh dấu `needs_update` và enqueue job recalculate theo dedup key chứa message + data revision.

### Question và answer

`QuestionFlow.submit` tạo cặp user/assistant message với sequence tăng tuần tự và snapshot `chat.data_revision` vào job.

`WorkerHandlers.claim` đặt lease. `AnswerFlow.publish` chỉ publish khi job đang `running`, lease đúng và `chat.data_revision` vẫn khớp `input_data_revision`. Nó tạo `answer_revision`, snapshot `answer_inputs`/`answer_scopes`, di chuyển current pointer và complete job. Output cũ không bị ghi đè.

`WorkerHandlers.heartbeat/fail/supersede` tạo event stream theo job. `InMemoryDataRepository.transaction()` mô phỏng rollback để phát hiện flow ghi dở dang; adapter SQL sau này phải giữ cùng boundary.

## 3. Mapping sang data model

| Code object | Bảng đích dự kiến | Tính chất |
|---|---|---|
| `DocumentVersion` | `document_versions` | metadata version; status mutable theo flow |
| `ExtractionRun` | `extraction_runs` | completed không sửa |
| `SourceRegion` | `source_regions` | immutable sau completed |
| `ExtractedEvidence` | `extracted_evidences` | immutable sau completed |
| `ChatEvidence` | `chat_evidences` | current pointer mutable |
| `EvidenceRevision` | `evidence_revisions` | append-only snapshot |
| `Message` | `messages` | sequence/pointer mutable |
| `AnswerRevision` | `answer_revisions` | append-only snapshot |
| `AnswerInput` | `answer_inputs` | append-only dependency |
| `AnswerScope` | `answer_scopes` | append-only dependency scope |
| `Job` | `jobs` | lease/status mutable theo state machine |

Các entity account/project/source đầy đủ vẫn do schema SQL và migration adapter sở hữu; in-memory slice chỉ chứa phần cần để kiểm chứng flow chính.

`domain/schema.py` đã lập inventory metadata cho đủ 23 bảng, nhưng chưa phải ORM mapping. Mỗi table có owner module và cờ append-only/owner-scope để làm guardrail khi viết adapter.

## 4. Boundary và nguyên tắc mở rộng

- Domain không import FastAPI, SQLAlchemy, provider SDK hay object-storage SDK.
- Application flow không chứa SQL; chỉ điều phối transaction boundary, ownership/fence và revision.
- `InMemoryDataRepository` là test adapter, không được dùng làm persistence production.
- Khi thêm PostgreSQL adapter, giữ nguyên behavior contract và chuyển các thao tác state thành transaction/row lock/FK.
- Khi thêm provider adapter, map output vào `ExtractionFlow.complete` sau khi validate JSON Schema provider.
- Khi thêm API, map stable domain errors (`revision_conflict`, `not_found`, `invariant_violation`) sang error envelope trong `doc/api-contract.md`.

## 5. Cách chạy

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/run_backend_skeleton_tests.py
python scripts/run_flow_tests.py
```

Hiện có 18 backend skeleton tests, 13 executable reference tests và API integration tests. PostgreSQL migration baseline đã có nhưng chưa chạy được nếu Docker daemon chưa khởi động; repository/UoW production và object-storage cutover vẫn còn thiếu.

## 6. Bước triển khai kế tiếp

1. Tạo PostgreSQL repository/UoW theo port, giữ nguyên flow contract.
2. Chạy migration upgrade/downgrade trên DB disposable và test row-lock/lease.
3. Chuyển upload/session/message từ JSON catalog sang repository PostgreSQL.
4. Chuyển PDF/extraction artifact sang object storage adapter.
5. Thêm migration import, restart/race tests và chỉ sau đó bật feature flag postgres.
