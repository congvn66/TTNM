# Kien truc he thong

## 1. Nguyen tac

- Modular monolith cho MVP: mot API, mot worker, mot web app, mot PostgreSQL va object storage.
- AI la adapter co the thay; domain, validation va phep tinh khong phu thuoc provider.
- Database luu metadata, quan he va lich su; object storage luu PDF/anh crop/artifact lon.
- Moi ket qua bat dong bo co version fence de tranh cong bo ket qua cu.
- Provenance va kha nang kiem tra ket qua la yeu cau kien truc, khong phai lop trang tri UI.

## 2. Thanh phan logic

```text
Browser (React, PDF.js)
        |
        | HTTPS REST + SSE/polling
        v
API (FastAPI)
  - auth/ownership
  - projects/documents/chats
  - question orchestration
  - evidence edit/versioning
  - OpenAPI + validation
        |
        +---- PostgreSQL (23 bang, jobs/outbox-like events)
        +---- S3-compatible storage (PDF, page image, crop)
        |
        v
Worker
  - document adapter (Docling/OCR)
  - question parser/retriever adapter
  - chart/VLM adapter
  - deterministic validator/calculator
  - answer composer
```

## 3. Bien tin cay

| Bien | Du lieu khong duoc tin | Kiem soat |
|---|---|---|
| Browser -> API | ID, owner, decimal, bbox, revision | auth session, ownership query, Pydantic/JSON Schema, optimistic concurrency |
| API -> AI provider | output tu do, citation, con so | schema-constrained output, validator, timeout, retry gioi han, provenance check |
| Worker -> DB | job cu/bi trung | lease token, job status, input data revision, idempotency key |
| Extractor -> domain | table/chart shape, unit, period | normalize schema, status `missing/error`, khong tu suy dien |
| DB -> object storage | storage key | server-generated key, allowlist bucket/prefix, signed URL ngan han |

## 4. Module backend

- `identity`: users, auth sessions, account tokens.
- `library`: projects, documents, document versions, storage.
- `extraction`: runs, regions, immutable extracted evidence.
- `conversation`: chats, sources, messages, pins.
- `evidence`: chat evidence, revision, verify/edit/restore.
- `answering`: question context, retrieval, calculation, answer revision, dependencies/scopes.
- `jobs`: claim/lease/progress/retry/cancel/idempotency.
- `audit`: security-relevant events; khong thay the domain history.

Moi module co service layer va repository interface. Tranh cho endpoint goi truc tiep provider hoac viet SQL nghiep vu rai rac.

## 5. Lua chon trien khai MVP

- Web: React + TypeScript + Vite, TanStack Query, PDF.js; component noi bo truoc khi chon UI kit.
- API/worker: Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic.
- DB: PostgreSQL 16+ voi `pgcrypto`; JSONB chi cho semantic/filter/payload thay doi theo loai.
- Job: bang `jobs` + `FOR UPDATE SKIP LOCKED` va lease. Them Redis/broker chi khi do duoc bottleneck.
- Storage: MinIO local, S3-compatible production.
- Observability: structured logs, correlation/request/job ID, OpenTelemetry neu du thoi gian.

Chi tiet ly do va he qua o ADR-0001.

## 6. Deployment topology

### Local/CI

Docker Compose: `web`, `api`, `worker`, `postgres`, `minio`. Provider AI duoc fake trong test; integration that chay bang profile rieng.

### Demo

- TLS o reverse proxy.
- API va worker dung cung image nhung entrypoint khac.
- PostgreSQL managed hoac container co volume/backups.
- Object storage private; browser chi nhan signed URL ngan han neu can.
- Secret qua environment/secret store, khong commit `.env`.

## 7. Non-functional baseline

- Security: password hash Argon2id, session token chi luu hash, rate limit auth/upload, MIME + magic-byte + page/size limit.
- Privacy: khong log noi dung PDF day du; retention va xoa vinh vien la config can chot truoc user study.
- Reliability: idempotent mutations, retry chi cho loi tam thoi, dead-letter/status failed co retry thu cong.
- Performance target de do (khong phai cam ket): API dong bo p95 < 500 ms; job co progress event; answer latency va chi phi duoc benchmark truoc khi dat SLO.
- Usability: semantic HTML, keyboard cho luong chinh, focus restore va bang du lieu thay the de kiem tra bieu do.

## 8. Huong mo rong

- Tach extraction/answering thanh service chi khi can scale/deploy doc lap.
- Them broker/Redis khi PostgreSQL queue khong dat throughput/latency da do.
- Them vector index khi retrieval tren tai lieu ngan khong du; neu dung, vector chi la chi muc, DB van la source of truth.
- Them format/tai lieu moi qua adapter va citation mapping rieng.

## 9. Dependency rule giua module

```text
transport/API -> application services -> domain rules
                         |                    |
                         v                    v
                  repository ports      provider ports
                         |                    |
                         v                    v
                 PostgreSQL/storage    Doc/LLM/VLM adapters
```

- Domain khong import FastAPI, SQLAlchemy, provider SDK hay object storage SDK.
- Application service dieu phoi transaction va port; khong chua SQL rai rac.
- Adapter khong tu cap nhat current pointer hay publish answer.
- Web chi tin API contract, khong suy dien business state tu text answer.
- Shared contract duoc sinh/kiem tu OpenAPI/JSON Schema, khong copy type bang tay khong test.

## 10. Ownership cua module

| Module | So huu bang/state | Public service |
|---|---|---|
| identity | users, sessions, tokens | register/login/logout/reset/current user |
| library | projects, documents, versions | upload/version/list/archive |
| extraction | runs, regions, extracted evidence | schedule/complete/query provenance |
| conversation | chats, sources, messages, pins | create chat/message/source/history |
| evidence | chat evidence, evidence revisions | initialize/verify/edit/restore |
| answering | answer revisions/inputs/scopes | parse/select/calculate/publish/recalculate |
| jobs | jobs/events/request keys | enqueue/claim/heartbeat/finalize/replay |
| audit | audit events | append security/management event |

Module khac khong update bang ma no khong so huu; goi service hoac cung tham gia transaction qua application use case da dinh nghia.

## 11. Consistency model

- Trong mot PostgreSQL transaction: strong consistency cho revision/pointer/fence/job state.
- Giua DB va object storage: eventual voi staged upload va cleanup/reconciliation job.
- Giua API va worker: at-least-once delivery, exactly-once business effect bang dedup/fence/unique constraint.
- Giua backend va browser: eventual progress; client tai resource state sau reconnect, khong chi replay event text.
- Provider output: untrusted proposal; chi thanh domain data sau validate.

## 12. Configuration va environment

- Config typed, fail-fast khi thieu; tach dev/test/demo.
- Secret chi tu secret store/environment injected, khong co default that.
- Provider/model/prompt/schema/calculator version duoc ghi o run/answer metadata de tai tao.
- Feature flag chi dung cho rollout; khong duoc tao hai meaning data khac nhau ma khong version.

## 13. Kien truc test

- Pure domain/calculator: unit/property.
- Repository/transaction/trigger: PostgreSQL integration.
- Adapter: contract test voi recorded fixture/fake deterministic.
- Use case: reference flow va service integration.
- API: OpenAPI/error/idempotency/ownership contract.
- Browser: vertical E2E cho 5 golden journeys.

`scripts/reference_flow.py` la executable spec tam thoi; implementation production phai dat behavior, khong can copy cau truc code.
