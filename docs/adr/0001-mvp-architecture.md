# ADR-0001: Modular monolith cho MVP

- Status: Accepted (design); runtime cutover tracked in P0
- Date: 2026-11-02

## Context

MVP co nhieu buoc (upload, extraction, question parse, chart read, calculation, correction/recalculation) nhung quy mo nhom nho va can thay doi schema nhanh. Tach microservice som lam tang hop dong, deploy va debug trong khi chua co du lieu ve tai.

## Decision

- Mot React/TypeScript web app.
- Mot FastAPI codebase co module domain va hai process: API + worker.
- Mot PostgreSQL la source of truth va hang doi co lease.
- Mot S3-compatible object storage.
- Provider document/LLM/VLM qua adapter co typed schema.
- Docker Compose cho local/CI; OpenAPI la contract web-backend.

## Consequences

Tich cuc: transaction versioning/dependency de lam dung; setup va observability don gian; fake provider de test. Tieu cuc: API va worker share deploy artifact; PostgreSQL queue co tran throughput; Python/TypeScript can sinh/kiem contract.

## Guardrails

- Module khong import repository noi bo cua module khac; giao tiep qua service/domain interface.
- Job payload chua ID/snapshot, khong chua PDF/base64 lon.
- Khong them Redis/vector DB neu chua co metric va ADR.
- Co the tach extraction/answering sau ma khong doi domain schema/API cong khai.

## Alternatives

- Microservices: tu choi cho MVP vi chi phi van hanh/giao dich.
- Serverless provider chain: tu choi vi kho kiem soat history, stale result va local reproducibility.
- JSON files/SQLite: du cho prototype don, nhung yeu voi concurrency, FK va job; khong chon lam baseline.
