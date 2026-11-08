# Mock data va executable specification

## 1. Muc tieu

Repository chua co backend production, nen bo script nay dong vai tro reference implementation cho bat bien va luong du lieu. No phai chay offline, deterministic va nhanh trong CI.

Khong coi reference model la code production. Backend that co the dung framework/DB khac, nhung phai qua cung acceptance behavior.

## 2. Thanh phan

| File | Vai tro |
|---|---|
| `scripts/generate_mock_data.py` | Sinh seed 23 bang, 20 PDF, 180 cau, 12 mutation va checksum |
| `scripts/validate_mock_data.py` | Kiem FK logic, invariant, split leakage, PDF va checksum |
| `scripts/reference_flow.py` | In-memory model cho idempotency, correction, dependency, recalc va source switch |
| `tests/test_reference_flows.py` | 13 reference/design tests co the chay bang stdlib |
| `scripts/run_flow_tests.py` | Mot lenh generate -> validate -> unittest |

Lenh chuan:

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/run_flow_tests.py
```

Khong can network hay package ngoai Python standard library.

## 3. Mock data coverage

- 2 owner, 2 project, 3 document, 4 document version.
- Completed extraction runs va source/evidence cho number, text, zero, missing va private owner data.
- 3 chat: chat A co answer ranking, chat B dung cung PDF nhung revision rieng, chat Bob de test isolation.
- Du it nhat mot row cho ca 23 bang logic.
- 20 PDF hop le cho smoke upload/page count; noi dung ASCII de generator khong can font/package.
- 180 question: 120 dev/60 final, dung phan bo task va report-level split.
- 12 mutation: edit, zero, missing, verification/no-result-change.

## 4. Test luong hien co

| Test | Requirement chinh |
|---|---|
| structural validator | DI-001..010, NFR-TEST-001 |
| idempotent submit | FR-CHAT-003, DI-008 |
| cross-owner hidden | FR-ID-002/003 |
| edit 38 -> 58 | FR-EV-002, FR-REC-003/004, FR-ANS-002/003 |
| concurrent stale edit | FR-REC-001 |
| stale recalc job | FR-REC-005 |
| restore creates revision | FR-EV-002 |
| scope without direct input | FR-REC-003 |
| missing vs zero | FR-DOC-004, DI-004 |
| zero denominator | FR-ANS-004, DI-007 |
| reason required | FR-EV-003 |
| source switch history | FR-LIFE-001 |

## 5. Generator contract

- UUID dung UUIDv5 voi namespace/name on dinh.
- Timestamp co dinh de output khong drift.
- JSON sort key va UTF-8.
- Manifest SHA-256 bao ve artifact bi sua tay.
- Sua du lieu phai sua generator, chay lai va commit toan bo output thay doi.

## 6. Gioi han co chu dich

- PDF mock khong danh gia OCR/tieng Viet/font/layout accuracy.
- Reference model khong thay PostgreSQL trigger/transaction integration test.
- Khong goi LLM/VLM that; provider contract test dung recorded/fake output.
- 180 cau synthetic la khung evaluation, khong phai gold benchmark da human-review.

Khi scaffold backend, giu bo nay va them adapter/integration/E2E tests; khong xoa reference tests cho den khi traceability co test thay the.
