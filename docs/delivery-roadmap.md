# Lo trinh trien khai de xuat

Day la lo trinh theo moc ket qua, khong gan ngay lich. Moi moc chi ket thuc khi dat exit gate, khong chi khi "da code xong".

## M0 - Chot quyet dinh va fixture

**Dau ra:** requirement/traceability duoc review; executable spec pass; ADR duoc chap nhan; schema JSON cho semantic/question/provider; prototype Docling va chart adapter tren fixture.

**Exit:** `scripts/run_flow_tests.py` pass; tra loi cac P0 trong `open-questions.md`; co bang so sanh accuracy/latency/cost; pham vi chart/table duoc chot.

## M1 - Foundation

**Dau ra:** monorepo scaffold, Docker Compose, CI, auth skeleton, migration 0001, object storage adapter, fake AI adapters.

**Exit:** one-command local setup; migration/test deterministic; ownership test co ban.

## M2 - Library va ingestion

**Dau ra:** project/document/version, upload validation, job/progress, extraction run, region/evidence viewer.

**Exit:** fixture text/table/chart region duoc luu va mo dung tren PDF; failed extraction retry duoc.

## M3 - Hoi dap co cau truc

**Dau ra:** message lifecycle, question context, retrieve evidence, calculator, answer revision/input/scope, clarify/missing/conflict states.

**Exit:** user journeys tra cuu, tinh va thieu du lieu qua voi oracle + extracted input; answer cu tai tao duoc tu DB.

## M4 - Chart on demand

**Dau ra:** chon chart sau question parse, crop/provider adapter, direct-label vs axis-estimation, validation va cost/latency telemetry.

**Exit:** dev slice dat threshold da chot; invalid provider output khong the thanh `answered`.

## M5 - Sua va tinh lai

**Dau ra:** evidence history, verify/edit/restore, dependency matcher, recalc job, stale-result fence, pin/history UI.

**Exit:** mutation suite va race suite qua; sua chat A khong thay chat B; ranking cap nhat dung.

## M6 - UI va hardening

**Dau ra:** keyboard cho luong chinh, focus va trang thai UI ro rang, auth/upload hardening, retention/purge, observability va runbook.

**Exit:** UI/security checklist; 5 golden E2E; backup/restore va failure recovery smoke.

## M7 - Benchmark va nghien cuu

**Dau ra:** 120 dev + 60 final questions, baseline, oracle/end-to-end runs, error analysis; pilot va user study protocol.

**Exit:** config freeze truoc final; dataset/license/consent/retention hop le; ket qua co manifest tai tao.

## M8 - Demo/report

**Dau ra:** demo script co fallback, release tag, known limitations, video/screenshot neu can, bao cao metric va user-study trend.

**Exit:** khong P0/P1; mot thanh vien khac chay lai demo tu huong dan tren may sach.

## Workstreams co the chay song song

- Document intelligence: fixtures, extractor, chart adapter, provenance metric.
- Question/calculation: structured context, action selection, deterministic math.
- Data/backend: schema, API, jobs, revision/dependency/concurrency.
- Web: viewer, evidence panel, correction va keyboard cho luong chinh.
- Evaluation: annotation tooling, validation, baseline, user study.

Integration theo vertical slice tu M2; khong doi den cuoi moi ghep thanh phan.

## Critical path

`fixture + schema -> extraction provenance -> structured answer -> revision/dependency -> correction flow -> frozen evaluation`

Rui ro lon nhat la bbox/chart extraction khong du tin cay. Neu spike M0 that bai, giam pham vi attribution xuong whole-chart + table hoa du lieu, khong che giau do chi tiet.
