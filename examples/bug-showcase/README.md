# Bug showcase PDFs

One small PDF per backend bug fixed on `tien-fork`. Upload them into one
session (the bug-3 pair must be in the **same** session) and ask the questions
below. Run the backend with `PDF_EXTRACTION_BACKEND=legacy` (no AI key needed).

| PDF | Ask | You'll see before the fix → after | Reason for bug |
|---|---|---|---|
| `bug2-bao-cao-mau-cua-repo.pdf` (copy of `examples/tien-extraction/report.pdf`) | "Doanh thu Q1/2024 là bao nhiêu?" | Upload fails ("Trích text thất bại"), no question possible → 1250.5 | Table cell `0.0%` became `.0` (`lstrip("0")`), invalid decimal, whole document rejected |
| `bug2-so-co-dau-cong.pdf` | "Doanh thu Q1/2024 là bao nhiêu?" | Upload fails → 1250 tỷ đồng | `+0.5` kept its `+`, invalid decimal, whole document rejected |
| `bug3-A-cong-ty-A.pdf` | 1. "Doanh thu Q2/2024 tăng bao nhiêu so với Q1/2024?" 3. "Tỷ lệ phần trăm" | Clarification, then only a text excerpt (clarification lost) → 10.4% | The pending clarification was looked up across the whole session, so B's message used it |
| `bug3-B-cong-ty-B.pdf` | 2. "Tỷ lệ phần trăm" (between A's two questions) | "60%", A's question computed with B's numbers → treated as a new question | Same: last assistant message of the session, from any document |
| `bug4-khoang-trang-dac-biet.pdf` | "Doanh thu Q1/2024 là bao nhiêu?" | "Không đủ dữ liệu…" → 1250 tỷ đồng | Words are separated by U+00A0; `"doanh thu"` (normal space) never matched, measure stayed `unknown` |
| `bug-moi-o-bang-chua-gan-nhan.pdf` | "Doanh thu Q1/2024 là bao nhiêu?" | "Không đủ dữ liệu…" → 1250 | pdfplumber table cells were published with `measure: unknown` and no period |

The PDFs were generated with PyMuPDF; `bug4` uses a TrueType font whose
spaces extract as U+00A0, the others use a font that extracts normal spaces.
