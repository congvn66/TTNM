# Mock data

Thu muc nay la du lieu sinh deterministic boi `scripts/generate_mock_data.py`. Khong sua truc tiep file JSON/JSONL/PDF da sinh; sua generator va chay lai:

```powershell
python scripts/run_flow_tests.py
```

## Noi dung

- `domain_seed.json`: seed cho du 23 bang logic, gom hai owner, ba chat va lich su answer/can cu.
- `reports.jsonl`: 20 report synthetic, chia 14 dev va 6 final qua question mapping.
- `evaluation_questions.jsonl`: 180 cau dung phan bo 120 dev/60 final.
- `mutation_scenarios.jsonl`: 12 kich ban verify/edit/missing/zero.
- `pdfs/`: 20 PDF nho hop le de smoke test upload/page count. Noi dung PDF la ASCII co chu dich; khong dung de danh gia OCR tieng Viet.
- `manifest.json`: so luong va SHA-256 cua moi artifact.

`scripts/validate_mock_data.py` kiem FK logic, owner/chat/run isolation, current pointer, value/status invariant, split leakage, phan bo 180 cau, PDF envelope/page count va checksum.

Du lieu nay chi la executable fixture cho domain/flow. Benchmark chat luong tieng Viet that van phai duoc gan nhan theo `doc/evaluation-dataset.md`.
