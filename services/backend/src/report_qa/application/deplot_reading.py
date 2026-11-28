"""Question-scoped DePlot adapter with explicit source/provenance verification.

DePlot does not say whether a number came from a printed label or the axis.
A printed label must be verified against native PDF words (spatially aligned
with the category), or a reviewed region annotation. Axis estimates require
reviewed linear-axis metadata; absent proof is an ambiguous, null value.
"""

from __future__ import annotations

import hashlib
import re
import threading
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any
from uuid import uuid4

from report_qa.application.chart_reading import ChartReadRequest
from report_qa.application.extraction_contract import validate_extraction_batch

MODEL_ID = "google/deplot"
REVISION = "6e76d62430da16986be3426bae32301fb9115397"
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _model():
    from transformers import Pix2StructForConditionalGeneration, Pix2StructProcessor

    return (
        Pix2StructProcessor.from_pretrained(MODEL_ID, revision=REVISION),
        Pix2StructForConditionalGeneration.from_pretrained(
            MODEL_ID, revision=REVISION
        ).eval(),
    )


def predict_chart(image):
    import torch

    torch.set_num_threads(4)
    # Shared model is loaded lazily and reused; serialize CPU inference.
    with _LOCK:
        processor, model = _model()
        inputs = processor(
            images=image,
            text="Generate underlying data table of the figure below:",
            return_tensors="pt",
        )
        with torch.inference_mode():
            tokens = model.generate(
                **inputs, max_new_tokens=512, do_sample=False, num_beams=1
            )
        return processor.decode(tokens[0], skip_special_tokens=True)


_BYTE_TOKENS = re.compile(r"(?:<0x[0-9A-Fa-f]{2}>)+")


def _decoded(raw: str) -> str:
    """DePlot spells newlines and characters outside its vocabulary as UTF-8
    byte tokens: "<0x0A>" is a newline, "Bi<0xE1><0xBB><0x83>u" is "Biểu"."""
    return _BYTE_TOKENS.sub(
        lambda run: bytes.fromhex(run.group(0).replace("<0x", "").replace(">", "")).decode("utf-8", errors="replace"),
        raw,
    )


def parse_table(raw: str):
    """Parse actual column names and category labels; never zip rows to facts.

    The header is the first line with cells. Lines without cells before it
    belong to the title: DePlot writes a chart's subtitle (e.g. its unit
    line "Đơn vị: nghìn đơn") on its own line after the TITLE line.

    Two DePlot slips are repaired because no value is lost or guessed:
    - the series names on the TITLE line ("TITLE | Doanh thu | KHCN | KHTC"),
      with the first data row taken for the header;
    - a one-series chart whose header is its first data row ("Nước mắm | 70.0%"):
      the series is named after the chart title;
    - a category name broken over lines ("Bắc Trung Bộ và" / "Duyên hải" / "Trung | 2.0").
    """
    lines = [[s.strip() for s in line.split("|")] for line in _decoded(raw).split("\n") if line.strip()]
    title = []
    title_cells = []
    header = None
    table = []
    wrapped = []
    for parts in lines:
        if header is None and parts[0].casefold() == "title":
            title_cells = parts[1:]
            title += parts[1:]
            continue
        if header is None and len(parts) == 1:
            title += parts
            continue
        if header is None:
            header = parts
            continue
        if len(parts) == 1 and len(header) > 1:
            wrapped.append(parts[0])  # a long category name broken over lines: it goes on in the next line
            continue
        if wrapped:
            parts = [" ".join(wrapped + [parts[0]])] + parts[1:]
            wrapped = []
        table.append(parts)
    if wrapped:
        raise ValueError("Inconsistent DePlot row width")
    if header and all(_is_number(cell) for cell in header[1:]):
        if len(title_cells) == len(header) >= 3 and not any(_is_number(cell) for cell in title_cells[1:]):
            # The series names went onto the TITLE line: its first cell is the title, the rest name the columns.
            table.insert(0, header)
            header = [""] + title_cells[1:]
            title = [title_cells[0]] + title[len(title_cells):]
        elif len(header) == 2:
            table.insert(0, header)
            header = ["", " ".join(title).strip()]
    rows = []
    for parts in table:
        if len(parts) != len(header):
            raise ValueError("Inconsistent DePlot row width")
        for index, token in enumerate(parts[1:], 1):
            number = _number(token)
            rows.append((parts[0], header[index], token, None if number is None else format(number, "f")))
    title = " ".join(title)
    if not header or not rows:
        raise ValueError("DePlot did not return a data table")
    # A header made of numbers is a data row: the series names are missing, and the row would
    # be read as names. A header whose first cell looks like a row label ("T1" before "T2")
    # is that row fused with the header: its values are gone. Both fail instead of dropping a row.
    if all(_is_number(cell) for cell in header[1:]):
        raise ValueError("DePlot returned no series names")
    if _row_label_like(header[0], rows[0][0]):
        raise ValueError("DePlot fused the header with the first row")
    return title, rows


_GROUPED = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d+)?")


def _number(token):
    """DePlot's value as a number: "70.0%" is 70.0 (the % stays in the raw text), "1,234.5" is 1234.5."""
    text = token.strip().removesuffix("%").strip()
    if _GROUPED.fullmatch(text):
        text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _is_number(token):
    return _number(token) is not None


def _row_label_like(cell, first_label):
    """'T1' beside a first row 'T2', 'Năm 2024' beside 'Năm 2025': same words, a number in both."""
    words = lambda text: re.sub(r"\d+", "#", text.casefold()).strip()
    return bool(cell) and bool(re.search(r"\d", cell)) and bool(re.search(r"\d", first_label)) and words(cell) == words(first_label) and cell != first_label


def _box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("Missing bbox")
    if (
        not all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in value)
        or value[0] >= value[2]
        or value[1] >= value[3]
    ):
        raise ValueError("Invalid bbox")
    return list(value)


def _native_label(page, region, category, value):
    words = page.get_text("words")
    width, height = page.rect.width, page.rect.height

    def inside(w):
        return (
            region[0] <= w[0] / width
            and w[2] / width <= region[2]
            and region[1] <= w[1] / height
            and w[3] / height <= region[3]
        )

    words = [w for w in words if inside(w)]
    categories = [w for w in words if w[4].casefold() == category.casefold()]
    if len(categories) != 1:
        return None
    cat = categories[0]
    candidates = []
    for w in words:
        try:
            number = Decimal(w[4].removesuffix("%"))
        except InvalidOperation:
            continue
        if number != Decimal(value):
            continue
        # Must be above the x-axis category and aligned with it, not a y tick.
        if w[3] < cat[1] and abs((w[0] + w[2] - cat[0] - cat[2]) / 2) < max(
            8, (cat[2] - cat[0]) / 2
        ):
            candidates.append(w)
    if len(candidates) != 1:
        return None
    w = candidates[0]
    return [w[0] / width, w[1] / height, w[2] / width, w[3] / height]


class DeplotChartReader:
    def __init__(self, predictor=None):
        self.predictor = predictor or predict_chart

    def read(self, request: ChartReadRequest) -> dict[str, Any]:
        def result(status, code, batch=None):
            return {
                "status": status,
                "code": code,
                "question_plan_id": request.question_plan_id,
                "fact_keys": list(request.fact_keys),
                "evidence_batch": batch,
            }

        # Validate the trigger before loading model weights or touching the PDF.
        if (
            not request.question_plan_id
            or not request.fact_keys
            or not request.chart_region_keys
        ):
            return result("not_available", "CHART_TRIGGER_REQUIRED")
        if request.source_pdf_path is None or not request.source_pdf_path.exists():
            return result("not_available", "CHART_SOURCE_UNAVAILABLE")
        regions = [
            r
            for r in request.chart_regions
            if r["chart_region_key"] in request.chart_region_keys
            and (not request.page_numbers or r["page_number"] in request.page_numbers)
        ]
        if not regions:
            return result("not_found", "CHART_REGION_NOT_FOUND")
        import pymupdf
        from PIL import Image

        from report_qa.application.evidence_extraction import (
            _measure,
            _unit_near,
        )
        from report_qa.application.numeric_extraction import period_near

        evidence, warnings, outputs = [], [], []
        provider_failure = False
        requirements = {
            f["fact_key"]: f
            for f in request.fact_requirements
            if f["fact_key"] in request.fact_keys
        }

        def warn(code, message, key=None):
            warnings.append({"code": code, "message": message, "evidence_key": key})

        with pymupdf.open(request.source_pdf_path) as pdf:
            for region in regions:
                box = _box(region["bbox"])
                page = pdf[region["page_number"] - 1]
                rect = pymupdf.Rect(
                    box[0] * page.rect.width,
                    box[1] * page.rect.height,
                    box[2] * page.rect.width,
                    box[3] * page.rect.height,
                )
                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2), clip=rect, alpha=False
                )
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                try:
                    raw = self.predictor(image)
                except Exception as exc:
                    provider_failure = True
                    warnings.append(
                        {
                            "code": "CHART_PROVIDER_UNAVAILABLE",
                            "message": "DePlot không sẵn sàng; không publish giá trị chart chưa kiểm chứng.",
                            "evidence_key": None,
                        }
                    )
                    outputs.append(
                        {
                            "chart_region_key": region["chart_region_key"],
                            "model": MODEL_ID,
                            "revision": REVISION,
                            "error_code": type(exc).__name__,
                        }
                    )
                    continue
                outputs.append(
                    {
                        "chart_region_key": region["chart_region_key"],
                        "raw_output": raw,
                        "model": MODEL_ID,
                        "revision": REVISION,
                    }
                )
                try:
                    title, rows = parse_table(raw)
                except ValueError:
                    warn(
                        "CHART_OUTPUT_INVALID",
                        "Không đọc được bảng số liệu nhất quán từ biểu đồ.",
                    )
                    continue
                selected = set()
                for fact_key, fact in requirements.items():
                    # Match semantic labels, not row order. Multi-series charts
                    # require an explicit series to avoid arbitrary selection.
                    category = (
                        fact.get("dimensions", {}).get("category")
                        or fact.get("period")
                        or fact.get("subject")
                    )
                    series = fact.get("dimensions", {}).get("series")
                    if isinstance(category, dict):
                        category = category.get("label")
                    matches = [
                        r
                        for r in rows
                        if category
                        and r[0].casefold() == category.casefold()
                        and (not series or r[1].casefold() == series.casefold())
                    ]
                    if len(matches) != 1:
                        warn(
                            "CHART_FACT_AMBIGUOUS",
                            f"Không ghép duy nhất được nhãn biểu đồ cho fact {fact_key}.",
                        )
                        continue
                    category, series, raw_value, value = matches[0]
                    identity = (category, series)
                    if identity in selected:
                        continue
                    selected.add(identity)
                    key = (
                        "chart-"
                        + hashlib.sha256(
                            f"{request.document_version_id}:{region['chart_region_key']}:{category}:{series}".encode()
                        ).hexdigest()[:20]
                    )
                    axis = region.get("axis") or {}
                    direct_box = (
                        _native_label(page, box, category, value)
                        if value is not None
                        else None
                    )
                    # Raster charts can be reviewed/annotated by a user. The
                    # proof must match the category, series AND exact value.
                    for label in region.get("verified_labels", []):
                        if (
                            label.get("category") == category
                            and label.get("series") == series
                            and label.get("value") == value
                        ):
                            candidate_box = _box(label["bbox"])
                            if not (
                                box[0] <= candidate_box[0] < candidate_box[2] <= box[2]
                                and box[1]
                                <= candidate_box[1]
                                < candidate_box[3]
                                <= box[3]
                            ):
                                raise ValueError(
                                    "Verified label bbox must be inside selected chart"
                                )
                            direct_box = candidate_box
                    method = "direct_label" if direct_box else "axis_estimation"
                    valid_axis = (
                        region.get("value_labels_absent") is True
                        and axis.get("verified") is True
                        and axis.get("scale") == "linear"
                        and axis.get("lower_tick") is not None
                        and axis.get("upper_tick") is not None
                        and axis.get("unit")
                    )
                    if valid_axis:
                        try:
                            lo, hi = (
                                Decimal(str(axis["lower_tick"])),
                                Decimal(str(axis["upper_tick"])),
                            )
                            valid_axis = lo.is_finite() and hi.is_finite() and lo < hi
                        except InvalidOperation:
                            valid_axis = False
                    if valid_axis and value is not None and not direct_box:
                        valid_axis = lo <= Decimal(value) <= hi
                    state = (
                        "valid"
                        if value is not None and (direct_box or valid_axis)
                        else "ambiguous"
                    )
                    if state != "valid":
                        value = None
                        warn(
                            "CHART_READ_AMBIGUOUS",
                            "Chưa xác minh được nhãn số hoặc trục tuyến tính; không sử dụng giá trị dự đoán.",
                            key,
                        )
                    read = {
                        "chart_region_key": region["chart_region_key"],
                        "series_label": series,
                        "category_label": category,
                        "axis_label": axis.get("label"),
                        "axis_unit": axis.get("unit"),
                        "lower_tick": str(axis["lower_tick"]) if valid_axis else None,
                        "upper_tick": str(axis["upper_tick"]) if valid_axis else None,
                        "assumptions": [
                            "deplot_chart_to_table",
                            "chart_region_bbox_for_estimates",
                        ]
                        + (
                            ["printed_label_verified"]
                            if direct_box
                            else ["reviewed_linear_axis"]
                            if valid_axis
                            else ["unverified_method_do_not_calculate"]
                        )
                        # Where the value's box is: its printed label, or the whole chart.
                        + (["box_printed_label"] if direct_box else ["box_whole_chart"]),
                    }
                    context = f"{title} {category} {series}"
                    evidence.append(
                        {
                            "evidence_key": key,
                            "source_region_key": region["chart_region_key"],
                            "source_type": "chart",
                            "page_number": region["page_number"],
                            "bbox": direct_box or box,
                            "raw_text": raw_value,
                            "numeric_value": value,
                            "value_kind": "number",
                            "data_status": state,
                            "extraction_method": method,
                            "method_label": "đọc từ nhãn"
                            if direct_box
                            else "ước lượng theo trục",
                            "semantic": {
                                "measure": _measure(context),
                                "subject": category,
                                "period": period_near(context, 0),
                                "unit": axis.get("unit")
                                or _unit_near(series, raw_value),
                                "dimensions": {"category": category, "series": series},
                            },
                            "table_locator": None,
                            "chart_read": read,
                            "confidence": 0.9
                            if direct_box
                            else 0.6
                            if state == "valid"
                            else 0.0,
                        }
                    )
        batch = {
            "schema_version": 2,
            "document_version_id": request.document_version_id,
            "extraction_run_id": str(uuid4()),
            "scope": "on_demand_chart",
            "trigger": {
                "question_plan_id": request.question_plan_id,
                "fact_keys": list(request.fact_keys),
                "chart_region_keys": list(request.chart_region_keys),
            },
            "evidences": evidence,
            "warnings": warnings,
        }
        validate_extraction_batch(batch)
        has_valid = any(e["data_status"] == "valid" for e in evidence)
        answer = result(
            "completed" if has_valid else "not_available" if provider_failure else "not_found",
            None if has_valid else "CHART_PROVIDER_UNAVAILABLE" if provider_failure else "CHART_READ_AMBIGUOUS",
            batch,
        )
        answer["provider_outputs"] = outputs
        return answer
