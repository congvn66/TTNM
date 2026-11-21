# Versioned JSON contracts

Day la hop dong may-doc-duoc cho cac JSONB/domain payload co shape thay doi theo loai. PostgreSQL bao ve quan he/state; application validate cac file nay truoc khi ghi.

- `semantic-v1.schema.json`: y nghia cua mot evidence revision.
- `question-context-v1.schema.json`: cau hoi da parse.
- `answer-scope-v1.schema.json`: pham vi dependency.
- `provider-extraction-v1.schema.json`: output adapter trich xuat/VLM duoc phep.
- `document-evidence-v2.schema.json`: output canonical cua doc text/bang va chart on-demand; moi so co trang/bbox/phuong phap doc.
- `question-plan-v2.schema.json`: yeu cau fact/ky/unit/phep tinh va clarification da parse.
- `calculation-result-v1.schema.json`: ket qua calculator deterministic va cac trang thai missing/zero/unit/ambiguous.

Quy tac:

- File schema da phat hanh khong sua meaning; thay doi incompatible tao version moi.
- `additionalProperties=false` o boundary provider/domain de bat typo va output tu do.
- Decimal la string theo regex, khong dung JSON float.
- Code production can compile/validate schema va contract test; mock validator chi kiem cac invariant cot loi bang stdlib.

Payload mẫu đầy đủ nằm trong `contracts/examples/`; đây là fixture giao tiếp, không phải dữ liệu người dùng.
