# Kế hoạch test chi tiết

## 1. Mục tiêu

Test phải chứng minh cả kết quả và invariant lịch sử/concurrency. In-memory tests dùng cho logic nhanh; PostgreSQL tests là bắt buộc cho FK, trigger, lock, lease và rollback.

## 2. Test layers

| Layer | Phạm vi | Gate |
|---|---|---|
| Domain unit/property | decimal, unit, period, status, calculator, scope match | Nhanh, deterministic, không I/O |
| Application use case | ownership, orchestration, UoW rollback, idempotency | Fake ports; fault injection từng write |
| Repository integration | SQL mapping, FK/check/trigger/index/transaction | PostgreSQL 16+, không SQLite thay thế |
| Contract/adapter | JSON Schema, API envelope, provider/storage fake | Positive + negative fixtures, version compatibility |
| E2E | upload, ask, inspect, edit/recalc, history/source switch | Browser + API + worker + DB + fake provider |

## 3. P0 test cases tiếp theo

### Ownership/integrity

- Upload document không tồn tại hoặc khác owner trả not-found và không tạo row/job.
- Attach evidence với source không tồn tại, khác chat, khác run bị từ chối.
- Query IDs của owner khác không tiết lộ existence.
- Source switch A không deactivate source B.

### Transaction/fault injection

- Fail sau insert version, run, job, request key: upload rollback hoàn toàn.
- Fail sau message thứ nhất/thứ hai/job: sequence và message rollback.
- Fail sau revision/pointer/fence/job: evidence edit rollback hoàn toàn.
- Fail sau answer/input/scope/pointer/event: answer publish rollback hoàn toàn.

### Idempotency

- Cùng key + cùng request hash trả cùng status/body/IDs.
- Cùng key + payload khác trả stable conflict.
- Hai request đồng thời chỉ tạo một business effect.
- Key hết hạn được xử lý đúng policy.

### Job/race

- Hai worker claim cùng lúc: chỉ một lease thắng.
- Heartbeat sai token hoặc lease hết hạn bị từ chối.
- Worker cũ không publish sau reclaim.
- Fence thay đổi trong lúc xử lý: answer graph không được ghi.
- Retry đạt max attempts chuyển failed/dead state rõ.

## 4. Domain/calculator matrix

| Operation | Happy path | Edge/failure |
|---|---|---|
| lookup | number/text exact | missing, ambiguous, conflicting source |
| sum | nhiều operand cùng unit | missing operand, incompatible unit |
| difference | signed exact decimal | wrong period/subject |
| absolute change | current - previous | missing period |
| growth rate | denominator non-zero | zero denominator -> undefined |
| percentage point | percent values cùng basis | không nhầm với percent growth |
| compare | tie/greater/lower | mixed unit/status |
| ranking | stable tie policy | scope member edit/add/remove |

Property tests tối thiểu: decimal serialization không NaN/Infinity/exponent; sum order invariant; restore tạo revision mới; append-only objects không mutate.

## 5. Contract test matrix

- Mỗi JSON Schema có fixture tối thiểu, đầy đủ và negative per required field/enum/additional property.
- Decimal truyền qua API là string; response không xuất JSON float cho giá trị exact.
- Bbox đúng 4 số, normalized, đúng coordinate order.
- Period known/partial/unspecified/not-applicable và provenance rules.
- Provider output unknown region/duplicate key/invalid confidence bị chặn trước DB.
- OpenAPI error code và HTTP status ổn định.

## 6. PostgreSQL integration/race suite

- Deferred pointer FK trong cùng transaction.
- Append-only triggers sau completed/published.
- Composite FK bảo vệ same owner/chat/run.
- Unique allocation dưới lock cho version/revision/sequence/event.
- `FOR UPDATE SKIP LOCKED` claim order và expired lease reclaim.
- Partial indexes được query planner dùng cho hot paths.
- Migration upgrade/downgrade/seed upgrade.

## 7. E2E golden journeys

1. Upload PDF -> extraction complete -> provenance mở đúng page/bbox.
2. Hỏi lookup/calculation -> xem input/formula/result.
3. Thiếu/mơ hồ/conflict -> trạng thái có hành động, không đoán.
4. Edit evidence -> affected answer needs update -> recalc revision mới -> history cũ còn nguyên.
5. Switch document version -> question mới dùng source mới -> answer cũ vẫn mở source cũ.

## 8. CI gates đề xuất

### Mỗi change

- format/lint/type check;
- domain/application unit tests;
- schema/fixture/design consistency;
- PostgreSQL repository tests nếu chạm data/flow;
- contract tests nếu chạm API/schema.

### Main/release

- migration clean + seeded upgrade;
- full integration/race suite;
- 5 golden E2E;
- security/static dependency scan;
- backup/restore và failure recovery smoke;
- benchmark manifest reproducibility.

## 9. Coverage policy

## 10. Session/document HTTP smoke

Luồng có thể chạy ngay bằng `python scripts/run_api_tests.py`:

1. `POST /api/v1/sessions` tạo session server-owned.
2. `POST /api/v1/sessions/{id}/documents` kiểm tra upload, lưu binary và extraction.
3. `POST /api/v1/sessions/{id}/messages` kiểm tra retrieval guard, answer và citation.
4. `GET .../messages/{message_id}/trace` kiểm tra stage, context manifest và persistence.
5. OpenAPI contract phải không có endpoint fixture song song với luồng sản phẩm.

Các test này chứng minh local adapter; chúng không thay thế PostgreSQL integration/race suite.

Không dùng một tỷ lệ coverage duy nhất làm bằng chứng correctness. Bắt buộc branch coverage cho state/failure paths P0; mutation/reference tests bảo vệ invariant; code mới không được làm giảm coverage baseline sau khi baseline được đo ở S2.
