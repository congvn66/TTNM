# Ma tran truy vet yeu cau - thiet ke - test

## 1. Muc dich

Moi MUST requirement phai co noi thiet ke va cach kiem. Ma tran nay ngan docs noi mot dang, fixture/test noi mot dang.

## 2. Core traceability

| Requirement | Thiet ke chinh | Executable check hien tai | Test can them khi co backend |
|---|---|---|---|
| FR-ID-002/003 | data-model 15/20; security 1 | `test_cross_owner_access_is_hidden` + seed validator | API IDOR matrix, storage signed URL |
| FR-DOC-001/003 | data-model 13.2/13.3; flows 1 | seed/version/run validator | upload/storage/DB integration |
| FR-DOC-004 | data-model 13.3/14 | structural validator; missing-zero test | extractor contract + bbox viewer |
| FR-CHAT-001 | schema trigger; data-model 13.4 | structural validator | DB negative trigger test |
| FR-CHAT-002 | data-model 16.2 | seed sequence validator | concurrent message insert |
| FR-CHAT-003 | API 1/5 | `test_submit_question_is_idempotent` | API + DB request-key replay |
| FR-CHAT-004 | domain rules 3 | evaluation action validator | parser/action contract suite |
| FR-EV-001/002 | data-model 3/13.5 | edit/history/isolation/restore tests | immutable trigger tests |
| FR-EV-003 | domain rules 8; schema check | `test_edit_requires_reason` | API validation |
| FR-ANS-001/002 | data-model 4/13.6 | correction preserves old answer/input | DB reload/history API |
| FR-ANS-003 | data-model 17 | scope-without-direct-input test | canonical scope matcher cases |
| FR-ANS-004 | domain rules 5/6 | ranking and zero denominator tests | calculator property tests |
| FR-REC-001 | flows 3; API 5 | stale editor conflict test | two DB transaction race test |
| FR-REC-002/005 | data-model 16 | stale recalc job test | worker lease/fence integration |
| FR-REC-003/004 | data-model 17; domain rules 8 | edit 38->58, scope fallback | add-member/remove-member scope tests |
| FR-LIFE-001 | flows 5 | source switch history test | API + DB source transition |
| DI-001..010 | schema/data-model 15 | `validate_mock_data.py` | PostgreSQL migration negative suite |
| NFR-TEST-001 | mock-data spec | `scripts/run_flow_tests.py` | CI required check |

## 3. Coverage policy

- `Executable check hien tai` khong de trong cho MUST domain invariant neu co the test offline.
- Khi backend test thay the reference test, giu reference test hoac ghi ly do/ADR; khong xoa trace.
- Bug P0/P1 them requirement/invariant neu thieu va regression test ID.
- PR thay doi state/error/schema phai update it nhat ma tran va mock data/validator.

## 4. MUST inventory bo sung

Bang nay liet ke rieng cac ID ma bang core gop nhom, de checker va reviewer khong bo sot requirement.

| Requirement | Design/kiem chung |
|---|---|
| FR-ID-001 | `security-operations.md` muc 2; can auth/session integration suite |
| FR-ID-003 | `data-model.md` muc 20 + schema owner chain; current cross-owner test, can full repository matrix |
| FR-DOC-002 | `security-operations.md` muc 3 + API 7; can upload negative suite |
| FR-DOC-003 | `data-model.md` muc 13.3 + immutability trigger; current structural validator, can DB trigger test |
| FR-CHAT-005 | `domain-rules.md` muc 3/7 + question-context schema; can follow-up parser contract test |
| FR-EV-002 | `data-model.md` muc 13.5; restore/history tests hien co |
| FR-ANS-002 | `data-model.md` muc 13.6/18.2; correction test xac nhan old input |
| FR-ANS-005 | `api-contract.md` claim/source representation; can bbox/claim contract va viewer test |
| FR-REC-004 | `domain-rules.md` muc 8 + reference recalculation full scope |
| FR-REC-005 | `processing-flows.md` muc 8; stale recalc job test hien co |
| FR-REC-006 | `data-model.md` muc 4; correction/history + source-switch tests |
| FR-LIFE-002 | `data-model.md` muc 10 + security operations muc 7; can archive/soft-delete integration test |
| FR-LIFE-003 | `security-operations.md` muc 7; can purge/object reconciliation integration test |
| NFR-SEC-001 | `security-operations.md` muc 2/3; can auth/storage deployment tests |
| NFR-SEC-002 | `security-operations.md` muc 3/4; can log-redaction/upload/rate-limit suite |
| NFR-REL-001 | `architecture.md` muc 11 + flows muc 9; idempotency/stale tests, can lease crash test |
| NFR-REL-002 | `security-operations.md` muc 6; can backup/restore drill |
| NFR-OBS-001 | `security-operations.md` muc 4/5; can telemetry contract test |
| NFR-UX-001 | `product-scope.md` + test roadmap UI gate; can browser E2E |
