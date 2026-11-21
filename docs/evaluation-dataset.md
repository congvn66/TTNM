# Thiet ke bo du lieu ban dau

## 1. Muc dich

Bo du lieu phuc vu ba viec rieng biet:

1. Phat trien va kiem thu trich xuat/hoi dap.
2. Danh gia final khong ro ri.
3. Thu nghiem kha nang nguoi dung kiem tra va sua ket qua.

Khong dung du lieu final de chon prompt, model, threshold hoac sua rule.

## 2. Quy mo va phan bo 180 cau

| Nhom nhiem vu chinh | Tong | Dev | Final |
|---|---:|---:|---:|
| Tra cuu | 45 | 30 | 15 |
| So sanh/tinh toan | 45 | 30 | 15 |
| Ket hop van ban + so lieu | 30 | 20 | 10 |
| Hoi noi tiep | 30 | 20 | 10 |
| Thieu/mo ho/mau thuan | 30 | 20 | 10 |
| **Tong** | **180** | **120** | **60** |

Moi cau co mot `primary_task` de thong ke va nhieu secondary tags: `paragraph|table|bar_chart|line_chart`, `direct_label|axis_estimation`, `missing|ambiguous|conflict`, operation va unit/period condition.

## 3. Tai lieu

- 15-20 bao cao tu xay dung: PDF 2-10 trang, tieng Viet, co du ground truth va bien the layout/chat luong anh.
- 5-10 bao cao cong khai: chi dua vao dataset sau khi luu URL, tac gia, license/terms snapshot va pham vi su dung.
- Moi bao cao co `report_id`, `version`, SHA-256, generator/source metadata va manifest.
- Dev/final chia theo report/chart/conversation, khong chia ngau nhien tung cau. Mot conversation khong duoc tach tap.

## 4. Cau truc repository du kien

```text
datasets/
  manifests/reports.jsonl
  annotations/questions.jsonl
  annotations/evidences.jsonl
  annotations/mutations.jsonl
  splits/dev-report-ids.txt
  splits/final-report-ids.txt
  schemas/*.schema.json
  README.md
tests/fixtures/                 # tap nho synthetic duoc phep commit
private-data/                   # gitignored; PDF/licensed/user-study data
```

Khong commit bao cao cong khai neu license khong cho phep phan phoi lai; chi giu downloader/manifest checksum neu hop le.

## 5. Record schema

### Report manifest

```json
{
  "report_id": "syn-sales-001",
  "version": 1,
  "sha256": "...",
  "language": "vi",
  "page_count": 4,
  "source_kind": "synthetic",
  "license": "project-owned",
  "features": ["paragraph", "table", "grouped_bar"],
  "generator_commit": "..."
}
```

### Question/gold answer

```json
{
  "question_id": "q-0001",
  "report_id": "syn-sales-001",
  "conversation_id": "conv-001",
  "turn_no": 1,
  "question_vi": "...",
  "primary_task": "calculation",
  "tags": ["bar_chart", "growth_rate", "direct_label"],
  "expected_action": "clarify",
  "clarification": {"reason_code": "ambiguous_growth_basis", "accepted_options": ["absolute", "percent"]},
  "oracle_answer": null,
  "required_evidence_ids": [],
  "scope": {},
  "scoring_notes": ""
}
```

Voi `expected_action=answer`, `oracle_answer` gom structured operation, exact decimal result, accepted display rounding, unit, period, subjects/ties va claim-to-evidence mapping. Voi `insufficient_data|clarify|select_source`, khong tao mot cau tra loi so gia.

### Gold evidence

- Source: report/version/page/bbox/region type.
- Value: exact decimal hoac text, status, extraction method.
- Semantic: measure, subject, unit, period, dimensions, operator.
- Attribution level: paragraph, table cell, whole chart, chart element neu co.
- `bbox=null` duoc phep neu chi co page-level gold, nhung phai gan nhan do chi tiet.

### Mutation scenario

```json
{
  "mutation_id": "m-001",
  "conversation_id": "conv-001",
  "target_evidence_id": "ev-001",
  "from": "38",
  "to": "58",
  "reason": "simulated extraction error",
  "affected_question_ids": ["q-0010", "q-0011"],
  "unaffected_question_ids": ["q-0009"],
  "expected_new_results": {"q-0010": {"winner": "Mien Nam", "value": "80"}}
}
```

## 6. Tao du lieu synthetic

Moi report nen co source machine-readable (YAML/JSON/CSV) va generator deterministic. Tao bien the co chu dich:

- Nhap nhang 0/missing; dau phay/dau cham; don vi nghin/trieu/ty.
- Ky known/partial/unspecified; tieu de trang khong phai ky cua moi so.
- Direct label va axis estimation.
- Bang thieu cell, OCR nham chu so, mismatch table-chart.
- Division by zero, incompatible unit, ties, cumulative vs period value.
- Cau hoi "tang nhieu nhat" can clarify absolute vs percent.
- Hoi noi tiep doi ky nhung giu measure/scope.

Khong chen loi bang cach sua annotation sau cung. Generator phai luu ca intended source truth va corruption profile de tai tao.

## 7. Quy trinh gan nhan

1. Annotator A tao question/action/answer/evidence.
2. Annotator B review doc lap value, unit, period, bbox va scope.
3. Disagreement duoc adjudicate va ghi `review_notes`, khong ghi de im lang.
4. Validator tu dong kiem decimal, ID/FK, bbox, split leakage, input completeness va calculation.
5. Dong bang final manifest checksum truoc evaluation.

## 8. Hai che do danh gia

- End-to-end: he thong tu trich xuat va tra loi.
- Oracle evidence: cung evidence/value dung de do question understanding, scope va calculation doc lap khoi extraction.

So sanh baseline VLM truc tiep va pipeline de xuat tren cung report/question/allowed source. Luu provider/model/version/config, thoi gian, token/chi phi va retry.

## 9. Metrics

- Extraction: exact value/unit/period/series accuracy; error cho axis estimation tach rieng.
- Answer: exact structured result va display tolerance; dung scope/tie/rounding.
- Evidence: source-link precision/recall va claim support rate.
- Action: macro-F1/confusion matrix cho answer/clarify/insufficient/select-source.
- Recalculation: affected-set precision/recall va new-result correctness.
- Operation: median/p95 latency, cost, retry/failure rate.

Threshold va tolerance phai chot tren dev truoc final. Bao cao sample size va confidence interval khi phu hop; khong tong hop mot diem che mat tung loai loi.

## 10. User study data

- 5-10 nguoi tren 18 tuoi thuoc nhom muc tieu; informed consent va quyen dung.
- Thu thap toi thieu: condition order, task outcome, time, navigation count, correction accuracy, SUS va interview note.
- Pseudonymous participant ID; form consent tach khoi event log.
- Chot retention/xoa, compensation va deception/debrief neu co cau tra loi co y sai truoc recruitment.

## 11. Mock dataset da co trong repository

`scripts/generate_mock_data.py` sinh `tests/mock_data/` de test cau truc va luong:

- 20 report manifest + 20 PDF smoke fixture.
- 180 question dung phan bo 120 dev/60 final va report-level split.
- 12 mutation scenario.
- SHA-256 manifest va validator chong sua tay/split leakage.

Day chua phai final research dataset: PDF chi la ASCII structure fixture, oracle chua human double-review, bbox/value khong danh gia OCR/VLM tieng Viet. Khi tao dataset that, giu cung record contract va versioning nhung thay manifest/artifact bang du lieu da review/licensed.

Lenh tai tao/kiem:

```powershell
python scripts/run_flow_tests.py
```
