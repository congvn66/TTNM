# Phần hiểu câu hỏi (Nhóm 7)

Chương trình này đổi một câu hỏi về báo cáo thành yêu cầu rõ ràng: cần số nào, kỳ nào, phép tính gì. Chương trình tự làm phép tính, AI không tính. Khi không đủ căn cứ, chương trình từ chối hoặc hỏi lại và không đưa ra con số.

## Chạy thử (không cần API key)

Cần Python 3.11 trở lên. Chương trình không cần cài thêm thư viện.

```bash
python3 -m qunderstand ask --store datasets/S1.json "Doanh thu thuần của kênh xuất khẩu trong quý 2 tăng bao nhiêu phần trăm so với quý 1?"
```

```bash
python3 -m qunderstand chat --store datasets/S1.json
```

Thêm `--json` để in bản ghi đầy đủ theo `data_design.pdf` mục 4.2.

## Dùng AI thật

Đặt key rồi chọn `--parser`. Key được đọc từ biến môi trường `GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` hoặc `ANTHROPIC_API_KEY`.

```bash
GEMINI_API_KEY=... python3 -m qunderstand chat --store datasets/S1.json --parser gemini
```

Giá trị khác của `--parser`: `openai[:model]`, `deepseek[:model]`, `anthropic[:model]`, `rules` (không dùng AI), `recorded:<file>` (phát lại câu trả lời đã ghi).

## Luồng xử lý

```
câu hỏi -> bộ phân tích (AI hoặc luật) -> yêu cầu JSON -> kiểm tra hai cách hiểu -> tìm số trong kho
        -> máy tính (không AI) -> câu trả lời theo mẫu + bản ghi tương tác
```

AI chỉ thấy tên chỉ tiêu, kỳ và đơn vị. AI không thấy giá trị số, nên AI không thể tự tính hoặc chép số.

| File | Việc |
|---|---|
| `qunderstand/parsers/llm.py` | Prompt và phần gọi AI |
| `qunderstand/parsers/rules.py` | Bộ phân tích không dùng AI, để chạy khi không có key |
| `qunderstand/request.py` | Dạng yêu cầu JSON và phần kiểm tra yêu cầu |
| `qunderstand/resolver.py` | Tìm số trong kho, phát hiện nguồn mâu thuẫn và năm không rõ |
| `qunderstand/guards.py` | Luật hỏi lại, áp dụng dù AI trả lời thế nào |
| `qunderstand/calculator.py` | Mọi phép tính |
| `qunderstand/pipeline.py` | Ghép các bước, tạo bản ghi tương tác |
| `qunderstand/recompute.py` | Tính lại câu trả lời khi người dùng sửa số, không gọi AI |
| `qunderstand/adapters/docling_csv.py` | Đổi CSV của Docling thành dữ liệu vào |

## Dữ liệu vào

Kho số liệu là file JSON theo bảng EVIDENCES trong `data_design.pdf`. Xem mẫu ở `datasets/`.

Lệnh này kiểm tra một file và liệt kê mọi lỗi:

```bash
python3 -m qunderstand check --store datasets/S1.json
```

## Kiểm thử

```bash
uv run --with pytest --with hypothesis --no-project python -m pytest -q
```

```bash
python3 -m qunderstand.evaluate --parser rules -v
```

```bash
python3 -m qunderstand.evaluate --parser recorded:eval/recorded/sonnet.jsonl -v
```

Lệnh này chấm mọi bộ câu hỏi với mọi bộ phân tích và ghi `eval/results.json`:

```bash
python3 scripts/scoreboard.py
```

Thước đo chính là `silent_wrong`: hệ thống trả lời chắc chắn nhưng sai. Thước đo này phải bằng 0. Từ chối hoặc hỏi lại không tính là `silent_wrong`.

Câu trả lời của AI trong `eval/recorded/` do subagent Claude viết theo đúng prompt của chương trình. Các lần gọi API thật đến Gemini, OpenAI và Anthropic chưa được chạy.

Các bộ câu hỏi: `eval/cases.jsonl` do người viết hệ thống soạn. `eval/holdout/` và `eval/holdout2/` do agent độc lập soạn, agent đó không đọc code. `eval/first_run/` giữ nguyên câu trả lời và điểm của lần chạy đầu.

## Tạo lại dữ liệu

```bash
python3 scripts/build_datasets.py
```

```bash
python3 scripts/build_cases.py
```

```bash
python3 scripts/export_llm_batches.py
```

## Đổi CSV của Docling thành dữ liệu vào

```bash
python3 -m qunderstand from-docling --csv bang.csv --out kho.json --document MA_TAI_LIEU --units '{"Doanh thu": "triệu đồng"}'
```

CSV của Docling chưa có đơn vị và chưa có vị trí của từng số, nên người chạy phải nhập đơn vị. Phải nêu đúng `--locale`, vì `1,250` là 1250 theo kiểu `en` và là 1,25 theo kiểu `vi`.
