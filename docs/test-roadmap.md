# Lo trinh kiem thu va quality gates

## 0. Baseline co the chay ngay

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/run_flow_tests.py
```

Lenh sinh mock data, validate 23 bang/20 PDF/180 question/12 mutation va chay 13 reference/design tests. Day la executable specification offline; khi backend co implementation, them PostgreSQL/API/browser test chuyen cung requirement IDs, khong thay the bang test mock don thuan.

## 1. Chien luoc

Test theo rui ro, khong theo ti le hinh thap co dinh. Ba rui ro cao nhat la sai so nhung nghe hop ly, ro ri du lieu giua owner/chat, va race lam ket qua cu ghi de ket qua moi.

| Lop | Muc tieu | Co AI that? |
|---|---|---|
| Unit/property | decimal, unit, period, status, bbox, dependency matching | Khong |
| Schema/contract | Pydantic, JSON Schema, OpenAPI, provider output | Fake/recorded |
| DB integration | FK, transaction, optimistic lock, lease, idempotency | Khong |
| Component | extractor adapter, storage, PDF.js mapping | Co profile rieng |
| E2E | 5 user journeys, keyboard, failure recovery | Stub mac dinh |
| Benchmark | dev/final metrics va baseline | Co, pinned config |
| User study | RQ1-RQ3, task completion/usability | Prepared answers/pipeline frozen |

## 2. Nam kich ban vang

1. Tra gia tri bang va mo dung o/trang/bbox.
2. Cau ket hop van ban + chart, clarify absolute/percent, roi hoi noi tiep.
3. Sua 38 -> 58; ranking doi; history/input cu van dung; chat khac khong doi.
4. Hoi metric khong co: tra insufficient, khong nham 0.
5. Mat ket noi trong luc job dang chay, tai lai trang, tiep tuc theo doi va khong mat ket qua/tao trung answer.

## 3. Test bat buoc theo domain

### Calculator

- Decimal exact; rounding chi o presentation.
- Sum/difference/growth/percentage-point/ranking/ties.
- Denominator 0, missing operand, incompatible/convertible units.
- Compare before rounding; incomplete group khong ket luan winner.
- Property tests cho unit conversion va order independence khi operation cho phep.

### Time/semantic

- Known/partial/unspecified/not-applicable.
- Khong bien upload/publication date thanh data period.
- Question time requirement vs source period completeness.
- Explicit/context/user provenance.

### Evidence/provenance

- 0 khac missing; error co null effective value.
- Bbox boundary/rotation mapping; page 1-based.
- Verify/edit/restore tao revision, raw khong doi.
- Answer cu load dung evidence revision cu.

### Dependency/recalculation

- Direct input change.
- Scope member change/addition cho ranking.
- Context text edit lam invalid explanation/condition.
- Unrelated answer khong bi mark.
- Hai edit lien tiep: job revision cu `superseded`, khong publish.

### Security/privacy

- IDOR tren moi resource va signed URL.
- Session expiry/revoke/reset; token hash va single use.
- Upload fake MIME, oversized/page bomb, path/key injection.
- Log redaction cho token, password, PDF content va PII.
- Permanent purge khong xoa object con duoc history tham chieu.

## 4. Race va failure injection

- Hai tab edit cung `expected_revision_id`: mot success, mot 409.
- Worker crash sau claim/sau DB write truoc ack; lease reclaim khong tao answer trung.
- Retry cung idempotency key; khac body bi conflict.
- Storage timeout, extractor timeout, invalid AI JSON, rate limit, provider 5xx.
- DB transaction rollback giua revision/pointer/job.
- Disconnect/reconnect doc tiep job events khong bo hoac lap trang thai cuoi.

## 5. UI quality gate

- Keyboard: thu tu focus, dialog trap/return va viewer-to-evidence-to-answer tren luong chinh.
- Trang thai job/edit/recalculate hien ro, khong chi bang mau.
- Chart co bang du lieu de nguoi dung doi chieu gia tri.
- Chrome/Firefox smoke test truoc demo va user study.

## 6. Lo trinh

### Gate 0 - Test foundation

- Test runner, lint/type-check, PostgreSQL disposable, fake storage/provider.
- 3 PDF fixture nho va golden JSON.
- CI chay unit + contract + DB integration.

Exit: mot commit co the tai tao local/CI; seed deterministic.

### Gate 1 - Ingestion/evidence

- Upload validation, extraction state machine, source/bbox mapping, immutable run.
- Adapter contract test voi recorded outputs.

Exit: nap 3 fixture, mo dung source region; failure co retry/status ro.

### Gate 2 - Answer/calculation

- Question action, retrieval schema, calculator, answer/input/scope transaction.
- Oracle-evidence evaluation tren tap dev nho.

Exit: kich ban vang 1, 2, 4 qua; khong co free-form number duoc dung ma khong validate.

### Gate 3 - Edit/recalculate/concurrency

- Revision, dependency matcher, job fence, idempotency, history.

Exit: kich ban vang 3 + race suite qua 100 lan khong flaky.

### Gate 4 - UI/E2E

- PDF viewer, evidence panel, correction flow, focus/live status.

Exit: 5 kich ban vang qua voi stub deterministic; UI va keyboard checklist.

### Gate 5 - Benchmark freeze

- 120 dev questions dung de chot config/threshold.
- Dong bang code/config/prompts va 60 final questions.

Exit: mot run co manifest, checksum, cost/latency va error analysis tai tao duoc.

### Gate 6 - User study/demo release

- Security/privacy review, backup/restore smoke, consent/retention decision.
- Pilot truoc khi recruitment chinh.

Exit: khong con P0/P1; known limitations va rollback/runbook duoc viet.

## 7. CI matrix de xuat

- PR hien tai: Python compile + `scripts/run_flow_tests.py` + docs/link/schema static checks.
- PR sau scaffold: lint, type-check, unit, schema, DB integration va web component.
- Main/nightly: full E2E, race/failure, migration from previous snapshot.
- Manual/on demand: provider integration va dev benchmark.
- Release candidate: final benchmark dung mot lan theo protocol, security/UI checklist.

## 8. Bug severity

- P0: ro ri cross-owner, mat/ghi de history, publish ket qua stale, secret leak.
- P1: sai so/nguon/pham vi ma van `answered`, correction khong tinh lai dung, luong giao dien chinh bi ket.
- P2: failure message/latency/layout gay kho nhung co workaround.
- P3: polish/observability/documentation nho.

Khong release demo voi P0/P1 mo.

## 9. PostgreSQL schema test bat buoc

- Migration up tren DB rong va previous snapshot.
- Moi CHECK/FK/trigger co mot positive va mot negative test.
- Completed extraction/revision UPDATE/DELETE bi chan.
- Pointer sai parent bi chan tai deferred constraint check.
- Chat source incomplete/cross-owner bi chan.
- Concurrent sequence/revision allocation khong trung.
- Job dedup key va request key khong tao duplicate effect.
- Query plan cho chat history/dependency/job claim dung index mong doi.

## 10. Provider contract test

Moi adapter co fixture request/response versioned cho success, missing field, wrong type, timeout, rate limit, 5xx va malicious/free-form output. Validator phai reject output ngoai schema; provider integration that chi chay manual/nightly voi pinned model/config va budget.
