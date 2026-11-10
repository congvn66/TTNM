# Yeu cau he thong va tieu chi chap nhan

## 1. Quy uoc

- `MUST`: bat buoc de MVP duoc chap nhan.
- `SHOULD`: uu tien cao, co the hoan khi co rui ro/ADR ro rang.
- `MAY`: mo rong.
- Moi yeu cau co ID on dinh. Code, migration, test va issue nen tham chieu ID nay.

## 2. Functional requirements

### 2.1 Identity va ownership

| ID | Muc | Yeu cau | Chap nhan |
|---|---|---|---|
| FR-ID-001 | MUST | Dang ky, dang nhap, dang xuat, reset password bang token mot lan | Token chi luu hash; expiry/revoke/single-use duoc test |
| FR-ID-002 | MUST | Moi resource nghiep vu thuoc dung mot user | Cross-owner ID tra 404, khong ro ri resource ton tai |
| FR-ID-003 | MUST | Tat ca query/mutation loc owner tai repository/DB chain | Test IDOR cho project/document/chat/message/evidence/job/storage URL |

### 2.2 Document library va ingestion

| ID | Muc | Yeu cau | Chap nhan |
|---|---|---|---|
| FR-DOC-001 | MUST | Tao project, document va upload document version PDF | Version number tang; bytes cu khong bi ghi de |
| FR-DOC-002 | MUST | Validate MIME, magic byte, size, page count va storage key | File sai bi 422 truoc extraction; key do server tao |
| FR-DOC-003 | MUST | Moi extraction attempt co run/version/config/status rieng | Run completed bat bien; retry tao run moi |
| FR-DOC-004 | MUST | Luu region theo page/bbox/type va evidence theo value/status/semantic | Bbox chuan hoa; 0 khac missing; region/evidence cung run |
| FR-DOC-005 | SHOULD | OCR trang scan qua adapter | Provider output phai qua schema/validator, khong ghi truc tiep |

### 2.3 Chat va question lifecycle

| ID | Muc | Yeu cau | Chap nhan |
|---|---|---|---|
| FR-CHAT-001 | MUST | Chat chot document version + completed extraction run | Khong activate run queued/running/failed |
| FR-CHAT-002 | MUST | Message co thu tu on dinh va reply relation cung chat | `sequence_no` unique; allocation duoi row lock |
| FR-CHAT-003 | MUST | Gui cau hoi idempotent | Cung key/hash tra cung response; cung key/khac hash -> 409 |
| FR-CHAT-004 | MUST | Cau hoi mo ho/thieu/mau thuan khong duoc doan | Tra `needs_clarification|insufficient_data|source_conflict` co reason code |
| FR-CHAT-005 | MUST | Hoi noi tiep dung structured context | Context ghi measure/subject/period/operation/scope, khong chi dua text history |

### 2.4 Evidence va answer

| ID | Muc | Yeu cau | Chap nhan |
|---|---|---|---|
| FR-EV-001 | MUST | Moi can cu trong chat co raw origin va current revision | Sua chat A khong doi raw origin/chat B |
| FR-EV-002 | MUST | Verify/edit/mark error/restore tao revision bat bien | Restore tao row moi, khong chuyen pointer ve row cu |
| FR-EV-003 | MUST | Edit/error/restore bat buoc reason | Blank reason -> validation error |
| FR-ANS-001 | MUST | Moi answer revision luu context, operation, result, assessment va data revision | Mo answer cu tai tao dung structured output |
| FR-ANS-002 | MUST | Luu exact evidence revisions da dung | Answer cu khong join current evidence |
| FR-ANS-003 | MUST | Luu scope toan bo nhom da xet | Evidence moi/thay doi trong ranking van tim duoc answer bi anh huong |
| FR-ANS-004 | MUST | Phep tinh bang code deterministic | Decimal exact; formula/version/rounding duoc luu |
| FR-ANS-005 | MUST | Moi claim co provenance den page/bbox/evidence neu co | Khong dung citation chi la text model tu tao |

### 2.5 Correction va recalculation

| ID | Muc | Yeu cau | Chap nhan |
|---|---|---|---|
| FR-REC-001 | MUST | Edit dung optimistic concurrency | Stale `expected_revision_id` -> 409 |
| FR-REC-002 | MUST | Tang `chat.data_revision` khi source/evidence thay doi | Metadata UI nhu title khong tang fence |
| FR-REC-003 | MUST | Tim dependency bang direct input union scope match | Co test khi direct input bi bo nhung scope van bat duoc |
| FR-REC-004 | MUST | Recalculate toan scope tai snapshot moi | Khong patch mot operand vao result cu |
| FR-REC-005 | MUST | Job cu khong duoc publish | Lease + data revision mismatch -> superseded |
| FR-REC-006 | MUST | History va pin van mo duoc sau recalc | Current pointer doi; old revision/inputs khong doi |

### 2.6 Version switching, history va lifecycle

| ID | Muc | Yeu cau | Chap nhan |
|---|---|---|---|
| FR-LIFE-001 | MUST | Chuyen document version tao chat source moi, source cu inactive | Answer/scope cu van tro source cu |
| FR-LIFE-002 | MUST | Archive/soft delete tach khoi permanent purge | UI an resource; history/object chua xoa ngay |
| FR-LIFE-003 | MUST | Purge theo dependency va retention | Object chi xoa khi khong con reference; job purge idempotent |
| FR-LIFE-004 | SHOULD | Pin message hoac exact answer revision | Pin answer cu bao co revision moi |

## 3. Data integrity requirements

| ID | Bat bien |
|---|---|
| DI-001 | Project/document/chat/source/evidence/answer link khong duoc cross-owner/cross-chat/cross-run |
| DI-002 | Completed extraction payload, evidence revision va answer revision graph la append-only |
| DI-003 | Current pointer phai thuoc dung parent entity, khong chi cung chat |
| DI-004 | `valid number` co numeric value va text null; `valid text` nguoc lai; missing/error co effective value null |
| DI-005 | Decimal khong di qua API bang binary float; khong NaN/Infinity |
| DI-006 | Period khong duoc suy dien tu upload/publication date neu khong co provenance |
| DI-007 | Ranking/group conclusion chi hop le khi toan bo required group co input/tinh duoc |
| DI-008 | `request_keys` va `jobs.dedup_key` ngan duplicate effect |
| DI-009 | Message sequence, revision number va event number unique trong parent |
| DI-010 | Bbox co bon so ordered trong 0..1, page 1-based |

## 4. Non-functional requirements

| ID | Muc | Yeu cau/chi so |
|---|---|---|
| NFR-SEC-001 | MUST | Argon2id, token hash, TLS, private object, signed URL ngan han |
| NFR-SEC-002 | MUST | Khong log secret/full PDF/full prompt; upload hardening va rate limit |
| NFR-REL-001 | MUST | Retry co gioi han, lease reclaim, idempotent publish/purge |
| NFR-REL-002 | MUST | Backup/restore test; khong mat revision history |
| NFR-OBS-001 | MUST | request/job/chat correlation ID; metric latency/cost/failure/superseded |
| NFR-PERF-001 | SHOULD | API sync p95 muc tieu <500 ms, khong bao gom job AI; benchmark truoc SLO chinh thuc |
| NFR-UX-001 | MUST | Trang thai processing/missing/conflict/update ro; luong chinh dung duoc bang keyboard |
| NFR-TEST-001 | MUST | PR chay generator + validator + reference flow tests khong can network/provider |

## 5. Quy tac thay doi yeu cau

- Doi meaning/priority/acceptance cua requirement phai cap nhat `traceability.md`.
- Them state/operation/error code phai cap nhat domain rules, API contract, mock generator va test.
- Requirement lien quan privacy/retention/provider can ADR hoac quyet dinh duoc ghi ro.

