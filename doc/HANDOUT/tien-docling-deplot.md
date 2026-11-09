# Tiền: Docling and DePlot integration

Branch: `tien`, based on `qanh`. The producer boundary remains the team's
[document-evidence-v2](../../contracts/document-evidence-v2.schema.json).
No incompatible contract fields were added.

## Run the implemented handoff

From the repository root, Python 3.12+:

```bash
python3 -m venv .venv
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -e '.[docling-deplot,dev,postgres]'

# Upload-time extraction: never calls DePlot.
PDF_NUMBER_LOCALE=en .venv/bin/python scripts/extract_document.py \
  examples/tien-extraction/report.pdf \
  --document-version-id example-report-v1 --locale en \
  --output /tmp/report-extraction

# A ready question explicitly requests region A from the selected chart.
.venv/bin/python scripts/extract_document.py \
  examples/tien-extraction/report.pdf \
  --document-version-id example-report-v1 --locale en \
  --chart-request examples/tien-extraction/chart-request.json \
  --output /tmp/report-extraction
```

Models are downloaded on first use and reused from the local cache. Both run
locally. No hosted model API key is needed. The CLI's base extraction runs on
each invocation; the API stores base extraction at upload and reuses it.

## Delivered files and data

- `application/docling_extraction.py`: Docling layout/table extraction; native
  PDF word geometry for numbers in text. No estimated character widths.
- `application/deplot_reading.py`: lazily loaded `google/deplot`; only selected
  chart regions and requested facts are processed. Original model text is
  returned in `provider_outputs` outside the strict evidence batch.
- `application/numeric_extraction.py`: decimal strings, locale, negative values,
  parentheses, zero and percentages. Unknown three-digit separator conventions
  are ambiguous rather than guessed. `-`/`—` means missing, not zero.
- `application/extraction_contract.py`: full JSON Schema plus domain validation
  before publication. A packaged copy of the immutable schema supports wheels;
  a test checks it against the team's original contract.
- `scripts/extract_document.py`: PDF-to-contract CLI.
- `examples/tien-extraction/`: runnable PDF, scoped chart request and actual
  model-generated output, including base evidence, chart evidence and raw
  DePlot response. The PDF is synthetic, not a financial report.

`document.json` contains `pages`, `evidence_batch`, `evidence_contexts`,
`chart_regions` and `extraction_provider`. `base-evidence.json` is the strict
contract alone. Each numeric item includes a 1-based page and a normalized
`[left, top, right, bottom]` bbox using the top-left origin. Table values have
physical row/column locators and resolved header paths; a merged physical cell
is emitted once. Missing cell geometry produces a warning and no operand.
Multiple numbers in a cell produce ambiguous/null evidence, not the first
number guessed as a value. Printed currency text is preserved in `raw_text`.

Periods/units without source support remain null. Table values are not given
the upload year. The resolver now refuses required units, subjects, dimensions
and known measures that are absent or do not match the evidence.

## API integration

The existing session upload calls `extract_pdf_artifact`, now selecting Docling
by default. Legacy extraction is still explicitly selectable for compatibility:

```bash
PDF_EXTRACTION_BACKEND=docling PDF_NUMBER_LOCALE=vi \
CHART_READER_BACKEND=deplot uvicorn report_qa.api.main:app --reload
```

Use `PDF_EXTRACTION_BACKEND=legacy` only to select the older extractor. Invalid
PDF backend names fail explicitly; model errors do not silently fall back.

The existing evidence-list endpoint now includes data status, method, source
region, table/chart locator and confidence as well as value/revision fields.
The question route reads charts only when:

1. The question plan is ready (clarification already returns earlier).
2. Required facts remain unresolved after text/table resolution.
3. The plan allows those facts to use a chart.
4. A unique source chart can be selected from the relevant pages/caption.

Only missing allowed fact keys, selected region keys and requirements cross the
reader boundary. No selected chart means no model call. Multiple indistinguishable
images are not all digitized: the system defers source selection instead.
Numeric lookup with a known measure and period also uses the evidence path;
non-numeric text lookup keeps the existing text-response flow.

## What “đọc từ nhãn” and “ước lượng theo trục” mean here

DePlot returns a table, **not verified extraction-method provenance**. We do not
claim that its table alone proves where a number came from.

- **đọc từ nhãn**: an exact native PDF number aligned above the category label,
  or a reviewed `verified_labels` entry matching category, series and exact
  value. The evidence bbox is the label's source bbox. Reviewed label coordinates
  must be inside the selected chart.
- **ước lượng theo trục**: requires reviewed `axis` metadata (`verified=true`,
  `scale=linear`, explicit unit, lower/upper tick), confirmation
  `value_labels_absent=true`, and a prediction inside that range. Evidence keeps
  the chart region bbox, as exact per-point localization is outside scope.
- Otherwise the value is **ambiguous**, `numeric_value=null`, with
  `CHART_READ_AMBIGUOUS`. The prediction stays in the raw provider response for
  review; it cannot enter the calculator. An ambiguous item's method label is
  provisional, with `unverified_method_do_not_calculate` in assumptions.

The example request contains reviewed label metadata for A=50. These annotations
are explicit source verification, not information automatically produced by
DePlot. The currently generated upload artifact has no reviewed axis/label
annotations. Consequently raster charts without native text generally require
review before they can supply valid operands. Building the review UI or a
separate visual label/tick verifier is still needed for fully automatic raster
chart provenance. No unsupported automatic provenance claim is made.

For a confirmed unlabelled chart, a region annotation can include:

```json
{
  "value_labels_absent": true,
  "axis": {
    "verified": true,
    "scale": "linear",
    "label": "Revenue",
    "unit": "VND_MILLION",
    "lower_tick": "0",
    "upper_tick": "100"
  }
}
```

Facts match returned category/series labels, never positional row order.
For grouped charts, specify `dimensions.category` and `dimensions.series`.
Ambiguous multi-series matches are rejected. The adapter does no arithmetic.
Confidence values are conservative adapter heuristics, not calibrated model
probabilities. DePlot output is never rounded or corrected using expected data.

## Validation and limitations

```bash
.venv/bin/python -m pytest -q
```

Tests use a recorded Docling structure and injected DePlot output; no network or
model downloads. Older API regression tests explicitly inject the legacy
extractor; the new tests cover the real adapter mapping, strict contract, native
number geometry, merged headers, locale, missing values, invalid geometry,
request scope, category matching, printed labels, axis checks and ambiguity.
Real model output is recorded separately in the example directory.

Known boundaries:

- Tested on digital PDFs. Scanned pages produce `OCR_REQUIRED`; this adapter
  does not claim complete scanned-table extraction. The existing Tesseract
  adapter remains in the legacy path.
- Docling picture detection gives chart candidates, not proof every picture is
  a chart. Source selection needs a unique relevant region.
- Base extraction records chart regions but reads no chart values.
- DePlot is CPU-heavy. Loading is cached, generation is bounded to 512 tokens
  and inference serialized. Production job-level timeout/retry scheduling is
  not added by this change; do not deploy this synchronous prototype as a
  concurrent production inference service.
- Existing qanh code still uses chart batches only for the current calculation;
  persisting chart revisions/corrections needs the evidence-store integration.
- No correction UI, new planner model or automatic per-point chart grounding was
  added. Those belong to the team's other components.
