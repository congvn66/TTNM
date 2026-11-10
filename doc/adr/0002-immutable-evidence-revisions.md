# ADR-0002: Can cu va cau tra loi dung revision bat bien

- Status: Accepted (design); PostgreSQL enforcement tracked in P0
- Date: 2026-11-02

## Context

Nguoi dung can xem gia tri goc, sua trong mot chat, mo lai cau tra loi cu va biet ket qua nao bi anh huong. Update in-place hoac mot JSON chat lon khong the bao dam truy vet va concurrency.

## Decision

- Extraction completed bat bien.
- Moi chat co `chat_evidences`; moi trang thai hieu luc la mot `evidence_revision` day du.
- Moi ket qua la `answer_revision`; `answer_inputs` chup input revision, `answer_scopes` chup pham vi.
- Parent giu current pointer. Edit/verify/restore va publish answer la transaction.
- `chat.data_revision` + job lease token la fence chong stale publish.

## Consequences

Tich cuc: audit/replay ro, isolation giua chat, correction va ranking update dung, race co the test. Tieu cuc: nhieu row, query current/history phuc tap, can purge policy va composite constraints.

## Guardrails

- Khong update/delete revision trong luong thuong.
- Khong dung current evidence khi hien thi answer cu; phai theo `answer_inputs`.
- Recalculation tai lai whole scope; khong patch result cu.
- Pin answer revision cu van hop le va phai thong bao neu co ban moi.

## Alternatives

- Event sourcing day du: linh hoat nhung qua phuc tap cho MVP va can projection.
- Update-in-place + audit log: de lech giua current row va log, kho FK input exact.
- Copy toan bo chat JSON: de lam prototype nhung query/dependency/concurrency yeu.
