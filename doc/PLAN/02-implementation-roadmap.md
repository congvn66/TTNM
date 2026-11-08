# Roadmap triển khai kỹ thuật

Roadmap này ưu tiên giảm rủi ro dữ liệu và concurrency trước khi mở rộng bề mặt API/UI. Không gắn ngày cố định; mỗi stage kết thúc bằng exit gate đo được.

## S0 - Contract và decision freeze

Đầu ra:

- Chốt các P0 liên quan semantic/question/provider schema, privacy, file limit và provider spike trong `../open-questions.md`.
- ADR bổ sung cho repository/UoW boundary, source replacement semantics và job lease policy nếu làm đổi thiết kế hiện tại.
- Canonical vocabulary giữa API, code và DDL: `kind`, status, revision, timestamp, nullable fields.
- Model-to-table mapping matrix cho 23 bảng.

Exit gate:

- Không còn field/state có meaning mâu thuẫn giữa code, JSON schema và DDL.
- 4 JSON Schema validate toàn bộ fixture dương/âm.
- Open questions P0 ảnh hưởng scaffold có owner và quyết định hoặc spike task rõ.

## S1 - Application boundary refactor

Đầu ra:

- Repository ports theo module, không lộ dictionary/state.
- `UnitOfWork` và transaction boundary cho bốn critical mutations.
- Clock/ID/event/idempotency ports explicit.
- Domain snapshot deep-copy/freeze.
- In-memory adapter tuân port mới.

Exit gate:

- `rg "repo\.state" services/backend/src/report_qa/application services/backend/src/report_qa/worker` không có kết quả.
- Fault injection chứng minh rollback cho upload/question/edit/publish.
- Cùng một contract test suite chạy trên in-memory adapter.

## S2 - Runtime foundation

Đầu ra:

- `pyproject.toml` với Python version, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL driver và dev tools đã pin.
- Typed config fail-fast cho test/local/demo; secret không có default thật.
- API và worker entrypoint dùng cùng package/image.
- Structured logging có request/correlation/job ID và redaction cơ bản.

Exit gate:

- Một lệnh cài/chạy test trên môi trường sạch.
- formatter, lint, type check và unit test pass.
- API/worker start và health check không cần provider thật.

## S3 - PostgreSQL + migration 0001

Đầu ra:

- Alembic migration 0001 được tạo từ baseline đã review, không copy mù `initial-schema.sql`.
- SQLAlchemy mappings/repositories cho vertical slice đầu: documents, versions, extraction, chats, jobs.
- Trigger/FK/check/index được kiểm tra bằng test thực trên PostgreSQL 16+.
- Adapter contract suite chạy cho PostgreSQL.

Exit gate:

- Migration up/down trên DB rỗng; upgrade từ snapshot có seed data.
- Race test sequence/revision/job claim pass.
- Không có query nghiệp vụ thiếu owner predicate.

## S4 - Upload và extraction vertical slice

Đầu ra:

- API upload envelope + staged object storage + idempotency.
- Worker claim/lease/retry/reclaim.
- Fake extractor adapter, provider JSON Schema validation, atomic complete/fail.
- Region/evidence query có provenance.

Exit gate:

- Upload retry không tạo version/job trùng.
- Invalid provider payload không tạo partial evidence.
- Completed run immutable ở app + DB.
- Object staging cleanup/reconciliation test pass.

## S5 - Question và deterministic answer vertical slice

Đầu ra:

- Submit question transaction, context schema, retrieval port và fake adapter.
- Calculator đủ operation MVP và unit compatibility.
- Answer publish transaction với inputs/scopes/current pointer.
- Clarification, insufficient-data, source-conflict và processing-error states.

Exit gate:

- Oracle/reference cases pass qua application + PostgreSQL.
- Stale lease/fence không thể publish.
- Answer revision tái tạo được từ persisted inputs/scopes/config version.

## S6 - Evidence correction và recalculation

Đầu ra:

- Verify/edit/mark-error/restore API với optimistic concurrency.
- Direct + scope dependency matcher.
- Recalculation job dedup, retry và pin/history behavior.
- Source replacement chỉ ảnh hưởng logical source mục tiêu.

Exit gate:

- Concurrent edit trả conflict ổn định.
- Edit chat A không thay chat B.
- Ranking/group comparison được tính lại từ toàn scope.
- Old revision/pin/source history vẫn mở và tái tạo được.

## S7 - API/web integration và hardening

Đầu ra:

- REST error/idempotency/pagination contract; SSE hoặc polling theo quyết định.
- Web client sinh/kiểm từ contract; golden journeys E2E.
- Auth/upload hardening, audit, retention/purge, backup/restore, observability.
- Provider thật chạy qua profile riêng với privacy/cost telemetry.

Exit gate:

- Contract, integration, E2E, security và recovery gates trong `04-test-plan.md` pass.
- Demo chạy lại được trên máy sạch bằng tài liệu.

## Dependency graph

| Stage | Phụ thuộc | Có thể song song |
|---|---|---|
| S0 | Baseline docs/code | Fixture/license/provider spikes |
| S1 | S0 vocabulary | JSON contract negative fixtures |
| S2 | S0 | Frontend shell không gọi API thật |
| S3 | S1 + S2 | Object-storage fake adapter |
| S4 | S3 | Viewer mock UI |
| S5 | S3 + contract freeze | Calculator/unit tests |
| S6 | S4 + S5 | Correction UI bằng fake API |
| S7 | S4-S6 | Evaluation/benchmark tooling |

