# Quy tac domain va phep tinh

## 1. Tu vung chuan

| Thuat ngu | Dinh nghia |
|---|---|
| Document | Danh tinh logic qua nhieu file version |
| Document version | Mot file PDF bat bien |
| Extraction run | Mot attempt trich xuat voi provider/config cu the |
| Source region | Vung co the mo tren PDF: page + bbox + type |
| Extracted evidence | Fact/text goc tu completed run, bat bien |
| Chat evidence | Working reference cua mot chat den extracted evidence |
| Evidence revision | Snapshot gia tri/semantic hieu luc trong chat |
| Answer revision | Snapshot ket qua cua mot assistant message |
| Input dependency | Exact evidence revisions da dung |
| Scope dependency | Toan bo tap du lieu co the anh huong ket qua |
| Data revision | Fence monotonic cua chat khi du lieu/source thay doi |

## 2. Trang thai du lieu

### `data_status`

- `valid`: co noi dung dung duoc theo value kind.
- `missing`: nguon khong co noi dung can tim; khong dong nghia 0.
- `error`: co loi extraction/validation, chua the dung.

### `verification_status`

- `unverified`: he thong tao, nguoi dung chua xac nhan.
- `verified`: nguoi dung xac nhan snapshot hien tai; tao revision moi.
- `edited`: nguoi dung thay content/semantic/status; tao revision moi.

Confidence provider khong duoc tu dong chuyen `unverified -> verified`.

## 3. Chon action cho cau hoi

Thu tu quyet dinh:

1. Khong xac dinh duoc measure/operation bat buoc -> `needs_clarification`.
2. Co nhieu cach hieu lam doi ket qua -> `needs_clarification` voi options.
3. Cac source hop le mau thuan -> `source_conflict` va yeu cau chon source.
4. Required evidence missing/error/unit/period khong du -> `insufficient_data`.
5. Du input va calculation defined -> `answered`.
6. Loi provider/he thong sau retry -> `processing_error`, khong bien thanh insufficient.

## 4. Gia tri, don vi va thoi gian

- Internal numeric la decimal exact.
- Unit co `code`, `label`, `multiplier`; chi convert neu cung dimension.
- Gia tri so sanh sau convert, truoc rounding.
- `period.status`: known, partial, unspecified, not_applicable.
- `period.basis`: explicit/context/user; explicit/context co source regions, user co reason/revision.
- Upload/publication year chi la metadata, khong tu dong thanh data period.

## 5. Phep tinh v1

| Operation | Cong thuc/ket qua | Dieu kien |
|---|---|---|
| lookup | exact value/text | evidence valid, semantic match |
| sum | `sum(x_i)` | unit compatible, khong double-count cumulative |
| difference | `target - base` | unit/measure compatible |
| absolute_change | `target - base` | ky ro neu time_required |
| growth_rate | `(target-base)/base*100` | base != 0 |
| percentage_point | `target_percent-base_percent` | input la percent points |
| compare | relation va delta | cung measure/dimension |
| ranking | max/min tren group | tat ca required members complete; ties tra tat ca |

Neu group incomplete, co the tra `partial_rates` de giai thich nhung `winner_subjects=[]` va answer khong `answered`.

## 6. Rounding

- Luu exact result, calculator version va display rule rieng.
- Ranking/compare tren exact value.
- Default presentation co the 2 decimal, nhung contract phai chi ro rounding mode.
- Khong dung rounded display lam input cho phep tinh sau.

## 7. Match evidence

V1 exact match tren normalized keys:

- measure code;
- subject selector;
- period key/status;
- dimensions;
- active chat source/region restriction;
- value/operator/unit compatibility.

Khong dung embedding/LLM de quyet dinh dependency. AI co the de xuat candidate, rule/validator quyet dinh ghi va tinh.

## 8. Correction va dependency

- Direct dependency: answer input tro old evidence revision.
- Scope dependency: changed semantic cu hoac moi match canonical scope.
- Tap anh huong la union; deduplicate theo current assistant message.
- Verify cung gia tri co the khong can recalc neu policy xac dinh result khong doi; edit/status/semantic/source change phai evaluate dependency.
- Recalc tai lai whole scope, tao answer revision moi va publish bang fence.

## 9. Isolation

- Raw extraction chia se duoc giua chat cua cung owner.
- Working revision khong chia se; chat A/B co current pointer rieng.
- Khong cho attach source cua owner khac.
- Khong mang edit sang document version moi neu chua co mapping/xac nhan ro.

## 10. Error reason codes on dinh

Toi thieu: `missing_measure`, `missing_period`, `ambiguous_growth_basis`, `source_conflict`, `unit_incompatible`, `zero_denominator`, `incomplete_comparison_group`, `extraction_error`, `provider_invalid_output`, `stale_data_revision`, `revision_conflict`.

UI message co the thay doi/dich; reason code khong doi ngu nghia trong cung API major version.

