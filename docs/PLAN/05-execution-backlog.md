# Execution backlog

## Current session/document vertical slice (2026-11-03)

Đã triển khai một slice có thể chạy được nhưng chưa phải production persistence:

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| `FND-201` FastAPI/pytest manifest | Done (local) | `pyproject.toml`, cài editable thành công |
| `API-401` Session HTTP/OpenAPI | In progress | `services/backend/src/report_qa/api`, Swagger `/docs`, integration tests |
| `WEB-403` UI gọi API và trace | In progress | session/document/chat UI và persisted message trace |
| PostgreSQL/object storage | Foundation đã có, cutover chưa hoàn tất | Compose 16, psycopg/Alembic/config đã có; session/message adapter vẫn là JSON |

Không được đánh dấu `API-401` hoặc `WEB-403` Done cho đến khi có auth/ownership thật, idempotency contract, PostgreSQL adapter và E2E browser test.

Trạng thái dùng: `Ready`, `In progress`, `Blocked`, `Done`. Mặc định các task dưới đây là `Ready`, trừ task phụ thuộc quyết định P0.

## Status sau Wave 1

| ID | Status | Ghi chú |
|---|---|---|
| `ARCH-101` | In progress | Typed facade đã có; cần tách repository theo aggregate và thêm PostgreSQL implementation |
| `ARCH-102` | In progress | UoW wrapper đã bao phủ core flows; cần fault-injection matrix đầy đủ |
| `PLAN-002` | In progress | `replaced_chat_source_id` đã có; cần multi-source integration test |
| `PLAN-003` | In progress | Expiry/attempt/reclaim đã có; cần DB lease race và timestamps |
| `TEST-106` | In progress | Contract test in-memory đã có; chưa chạy cùng PostgreSQL adapter |
| `PLAN-001` | Ready | Cần hoàn thiện mapping 23 bảng/field trước ORM |
| `DATA-203` | Blocked | Chờ `PLAN-001`, package/runtime decision và repository boundary ổn định |

## Wave 0 - Stabilize contracts và architecture

| ID | Task | Phụ thuộc | Definition of Done |
|---|---|---|---|
| PLAN-001 | Chốt model-to-DDL mapping 23 bảng | Review hiện tại | Mapping được review; mọi drift có decision |
| PLAN-002 | Chốt source replacement semantics | User journey + ADR | Multi-source test scenario và API intent rõ |
| PLAN-003 | Chốt job lease/retry policy | DDL + ops target | Expiry, heartbeat, reclaim, attempts, terminal states rõ |
| PLAN-004 | Chọn package/runtime versions | Open questions P0 | ADR/manifest proposal, compatibility matrix |
| PLAN-005 | Canonical JSON Schema validation | 4 contracts | Positive/negative fixtures và một validation path |

## Wave 1 - Refactor boundary

| ID | Task | Phụ thuộc | Definition of Done |
|---|---|---|---|
| ARCH-101 | Tạo module repository ports | PLAN-001 | Không dùng `state: Any`; ports typed theo aggregate |
| ARCH-102 | Tạo UnitOfWork | ARCH-101 | commit/rollback + fake fault injection |
| ARCH-103 | Refactor upload/question flows | ARCH-102 | Atomic, owner checked, idempotency hash checked |
| ARCH-104 | Refactor evidence/answer flows | ARCH-102 | Atomic revision graph/pointer/fence/jobs |
| ARCH-105 | Refactor job worker port | PLAN-003 + ARCH-101 | Lease expiry/reclaim/finalize contract |
| TEST-106 | Adapter contract suite | ARCH-101 | In-memory adapter pass cùng suite dùng cho Postgres |

## Wave 2 - Runtime và PostgreSQL

| ID | Task | Phụ thuộc | Definition of Done |
|---|---|---|---|
| FND-201 | Tạo `pyproject.toml` và dev tooling | PLAN-004 | Clean install; lint/type/unit commands pass |
| FND-202 | Typed config + logging | FND-201 | Fail-fast; no secret defaults; redaction test |
| DATA-203 | Alembic scaffold + migration 0001 | PLAN-001 + FND-201 | Up/down/seed upgrade pass |
| DATA-204 | PostgreSQL repositories phase 1 | ARCH-101 + DATA-203 | Documents/chats/jobs adapter suite pass |
| DATA-205 | PostgreSQL repositories phase 2 | DATA-204 | Extraction/evidence/answer suite pass |
| DATA-206 | Lock/race/trigger tests | DATA-204/205 | P0 concurrency matrix pass |

## Wave 3 - Vertical slices

| ID | Task | Phụ thuộc | Definition of Done |
|---|---|---|---|
| FLOW-301 | Upload/storage/idempotency | DATA-204 | Retry-safe staged upload flow pass |
| FLOW-302 | Extraction/fake provider | FLOW-301 + PLAN-005 | Atomic complete/fail + provenance query |
| FLOW-303 | Question/context/retrieval fake | DATA-205 | Submit + context states persisted |
| FLOW-304 | Deterministic calculator MVP | PLAN-005 | Operation matrix unit/property tests pass |
| FLOW-305 | Answer publish | FLOW-303/304 | Input/scope snapshot + stale fence pass |
| FLOW-306 | Evidence correction/recalc | FLOW-305 | Mutation/race suite pass |
| FLOW-307 | Source replacement | PLAN-002 + FLOW-302 | Multi-source isolation/history pass |

## Wave 4 - Interfaces và hardening

| ID | Task | Phụ thuộc | Definition of Done |
|---|---|---|---|
| API-401 | FastAPI endpoints/error envelope | Wave 3 slices | OpenAPI + ownership/idempotency contract tests |
| WRK-402 | Worker entrypoint/recovery | DATA-206 | Crash/reclaim/retry smoke pass |
| WEB-403 | Web integration golden journeys | API-401 | 5 E2E journeys pass |
| OPS-404 | Observability/retention/purge | API-401/WRK-402 | Runbook + purge/recovery tests |
| SEC-405 | Auth/upload/privacy hardening | API-401 | Security checklist + scans pass |
| REL-406 | Clean-machine demo release | All gates | Reproducible setup, release manifest, known limits |

## Immediate next sprint candidate

Chỉ lấy các task sau vào lượt triển khai kế tiếp:

1. `PLAN-001` model-to-DDL mapping.
2. `PLAN-002` source replacement semantics.
3. `PLAN-003` job lease policy.
4. `ARCH-101` typed repository ports.
5. `ARCH-102` UnitOfWork + fault injection.
6. `TEST-106` adapter contract suite nền.

Không bắt đầu `DATA-203` cho đến khi `PLAN-001` và `ARCH-101/102` Done.
