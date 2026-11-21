# Cau hoi mo va ke hoach chot

## P0 - Phai chot truoc scaffold/du lieu final

| Cau hoi | Cach chot | Tieu chi |
|---|---|---|
| Docling/OCR nao cho PDF tieng Viet? | Spike tren 3-5 PDF dai dien | text/table/bbox accuracy, latency, license, cai dat |
| Chart provider/DePlot/VLM nao? | Cung 20 chart crop va schema | value/unit/series accuracy, direct vs estimated, cost |
| Du lieu co duoc gui ra provider ngoai? | Quyet dinh privacy + consent | deployment/demo/user-study policy ro rang |
| Max file size va timeout? | Do worst-case 10 trang | khong page bomb; demo latency chap nhan |
| Semantic/question JSON Schema v1? | Review bang 5 user journeys | du bieu dien missing/period/unit/scope |
| License bao cao cong khai? | License inventory | duoc phep tai xuong, xu ly, cong bo artifact can thiet |

## P1 - Chot truoc correction/UI complete

- Scope matcher la rule exact hay semantic match? Bat dau exact structured filter; chi mo rong khi benchmark chung minh can.
- Claim mapping luu JSON trong answer revision hay table rieng? MVP JSON; tach table neu can query/annotation doc lap.
- SSE hay polling? Uu tien SSE co polling fallback sau spike proxy/deploy.
- Retention cho PDF, auth session, request key, audit va user-study event.
- Khi source table/chart conflict, UI cho chon mot lan hay luu preference theo chat/scope?
- Muc do citation chart: whole chart, series/point bbox, hay chi bang du lieu de doi chieu?

## P2 - Co the de sau MVP

- Vector index co tang retrieval tren report 2-10 trang khong?
- Redis/broker co can khi PostgreSQL job queue da do?
- Collaboration/multi-user/project sharing.
- Them DOCX/Markdown va mapping citation.
- Pixel-level chart attribution va nhieu loai chart.

## Decision log rule

Moi cau tra loi lam thay doi kien truc, data contract, privacy hoac pham vi phai thanh ADR. Ket qua spike gom fixture version, lenh/config, metric va han che; khong chap nhan quyet dinh chi dua tren demo thu cong.
