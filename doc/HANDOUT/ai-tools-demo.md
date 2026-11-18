# Document assistant (`REPORT_QA_ASSISTANT_MODE=tools`)

Replaces the regex/QuestionPlan resolver for a question with an AI that reads
the whole document and chooses tools. The legacy route stays the default
(`REPORT_QA_ASSISTANT_MODE=legacy`); regression tests select it explicitly.
The assistant uses the configured planner client (Gemini/OpenRouter/SambaNova).

## What the AI can access

- `pages`: full extracted text of every page.
- `data`: the same rows as the **Dữ liệu** drawer: key, page, label
  (row · column for tables, category · series for charts), current value
  (after user corrections), raw PDF text, unit and status.
- `chart_regions`: detected figures; `read=false` means their numbers are not
  in `data` yet.
- Recent conversation on the same document.

## Tools

- `read_chart(chart_region_key)`: crops the region, runs `google/deplot`, then
  asks the visual model whether each value matches a printed label or a linear
  axis. Values are never rewritten by the visual checker; unconfirmed values
  stay `ambiguous` and are flagged. Each read is saved as a separate
  `document.chart_extractions` batch, merged into **Dữ liệu**, and can be
  corrected with the existing append-only revision flow. DePlot output is
  cached by image hash plus model revision.
- `answer`: must cite `evidence_keys` from `data` (server maps page + bbox) or
  existing `pages`, unless `not_found=true`. Invented keys/pages are rejected
  and the model must retry.
- `clarify`: only for genuinely ambiguous questions.

## Run locally

```bash
source ../.venv/bin/activate
PERSISTENCE_BACKEND=json REPORT_QA_ASSISTANT_MODE=tools \
REPORT_QA_PLANNER_MODE=gemini PDF_EXTRACTION_BACKEND=docling \
PDF_NUMBER_LOCALE=en OMP_NUM_THREADS=4 \
python -m uvicorn report_qa.api.main:app --app-dir services/backend/src --port 8001
```

Put the provider key in the ignored `.env`. Try `synthetic_line.pdf`:

- “Theo biểu đồ đường, doanh thu vùng B là bao nhiêu?” → reads the chart (26).
- “Doanh thu Q1 là bao nhiêu?” → cites the table cell.
- “Lợi nhuận vùng A là bao nhiêu?” → the document has revenue, not profit.

The first chart read is slow on CPU; the UI waits up to three minutes and the
assistant has a seven-step limit. Provider/tool errors are returned as errors,
never replaced by a rule-based answer. Documents larger than the full-context
budget are rejected rather than silently truncated.

Tests: `PYTHONPATH=services/backend/src python -m pytest -q`.
