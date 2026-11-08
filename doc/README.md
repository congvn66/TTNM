# Bo tai lieu thiet ke - Report QA co provenance va correction

## 1. Trang thai va muc dich

Bo tai lieu nay la source of truth cho MVP hoi dap tren PDF co can cu, phep tinh deterministic, correction theo chat va recalculation co version fence.

- Trạng thái tài liệu: `Final design v1` cho MVP local vertical slice; ADR kiến trúc đã Accepted, PostgreSQL là thiết kế đích và đang cutover từng bước, chưa bật runtime.
- Data design: baseline chi tiết + PostgreSQL DDL có constraint/trigger; JSON adapter local vẫn là runtime source of truth hiện tại.
- Week 1 local evidence-revision slice: UI/API lưu giá trị gốc, giá trị hiện hành, lịch sử append-only, optimistic concurrency và answer-input snapshot; automatic recalculation + PostgreSQL API cutover chưa bật.
- Executable specification: generator/validator, 26 backend skeleton tests, 13 reference/design tests và 10 API integration tests.
- Khong nam trong pham vi: multi-user collaboration, format ngoai PDF va chart ngoai tap MVP.

## 2. Ban do tai lieu

### San pham va yeu cau

| Tai lieu | Noi dung |
|---|---|
| [product-scope.md](product-scope.md) | Problem, actor, scope, success criteria va non-goals |
| [requirements.md](requirements.md) | FR/DI/NFR co ID va acceptance criteria |
| [domain-rules.md](domain-rules.md) | Tu vung, states, action decision, unit/time, formula va dependency rules |
| [traceability.md](traceability.md) | Mapping requirement -> design -> executable/backend test |

### Kien truc va hop dong

| Tai lieu | Noi dung |
|---|---|
| [workspace-structure.md](workspace-structure.md) | Cay monorepo, ownership, ranh gioi va thu tu scaffold |
| [data-flow-code-skeleton.md](data-flow-code-skeleton.md) | Khung code domain/application/adapter va cac data flow chinh |
| [frontend-demo.md](frontend-demo.md) | Demo web evidence-first, pham vi mock state va ke hoach noi API |
| [architecture.md](architecture.md) | Context, component, trust boundary, module dependency va deployment |
| [processing-flows.md](processing-flows.md) | Upload, question, publish, edit, recalc, version switch va failure compensation |
| [api-contract.md](api-contract.md) | REST conventions, endpoint, payload/error, idempotency/concurrency |
| [security-operations.md](security-operations.md) | Threat model, auth/upload, logging, metrics, backup, purge, incident |
| [data-flow-observability.md](data-flow-observability.md) | Cach audit request that, trace stage, persistence va failure semantics |
| [final-design.md](final-design.md) | Bản tổng hợp chuẩn: data flow, persistence, invariant và trạng thái triển khai |
| [HANDOUT/README.md](HANDOUT/README.md) | Luồng triển khai duy nhất, phân công Tiền/Đức Anh và contract tích hợp |

### Data

| Tai lieu | Noi dung |
|---|---|
| [data-model.md](data-model.md) | ERD, data dictionary 23 bang, JSONB contract, transaction, query, retention, migration |
| [storage-and-data-runtime.md](storage-and-data-runtime.md) | Luu runtime hien tai, quyet dinh PostgreSQL/Redis/object storage va khoang trong data |
| [postgres-revision-graph.md](postgres-revision-graph.md) | Transaction graph, cutover contract va capability matrix cho PostgreSQL/OCR/chart |
| [initial-schema.sql](initial-schema.sql) | PostgreSQL 16 baseline voi FK/check/index/trigger |
| [evaluation-dataset.md](evaluation-dataset.md) | Dataset nghien cuu 180 cau, split, annotation va metrics |
| [mock-data-and-executable-spec.md](mock-data-and-executable-spec.md) | Fixture deterministic va reference flow test |

### Delivery va decisions

| Tai lieu | Noi dung |
|---|---|
| [PLAN/README.md](PLAN/README.md) | Code review, implementation/data/test plan va execution backlog |
| [test-roadmap.md](test-roadmap.md) | Test layers, flow/race/security cases, gates va CI |
| [delivery-roadmap.md](delivery-roadmap.md) | Milestone va exit gate |
| [open-questions.md](open-questions.md) | P0/P1/P2 decisions can spike/chot |
| [adr/0001-mvp-architecture.md](adr/0001-mvp-architecture.md) | Modular monolith + PostgreSQL queue |
| [adr/0002-immutable-evidence-revisions.md](adr/0002-immutable-evidence-revisions.md) | Append-only evidence/answer revision |

## 3. Thu tu review

1. `product-scope.md` + `requirements.md`.
2. `domain-rules.md` + `traceability.md`.
3. `architecture.md` + ADR.
4. `data-model.md` + `initial-schema.sql`.
5. `HANDOUT/README.md` và ba handout giao việc.
6. `api-contract.md` + `processing-flows.md`.
7. `mock-data-and-executable-spec.md` + chay test.
8. `security-operations.md`, `test-roadmap.md`, `delivery-roadmap.md`.

## 4. Chay executable specification

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/run_flow_tests.py
```

Expected baseline:

- 23 domain tables, moi bang co fixture.
- 20 mock PDF.
- 180 evaluation questions (120 dev, 60 final).
- 12 mutation scenarios.
- 13 reference/design tests pass.

## 5. Source of truth va xung dot

Thu tu uu tien:

1. Requirement ID + ADR accepted.
2. Domain/data/API contract.
3. Executable tests/fixtures.
4. Roadmap va prose vi du.

Neu docs va test xung dot, khong sua test de "cho xanh" ma khong xac dinh y dinh. Cap nhat requirement/ADR/traceability, sau do sua docs + generator + test trong cung change.

## 6. Quy tac thay doi

- Schema: migration + data model + mock generator + validator + negative test.
- API/state/error: API contract + domain rules + requirement/traceability + contract test.
- Formula/scope: calculator/domain rule + fixture oracle + regression test.
- Provider: adapter contract + recorded fixture + privacy/cost/latency decision.
- Retention/security: security operations + data lifecycle + runbook/test.
