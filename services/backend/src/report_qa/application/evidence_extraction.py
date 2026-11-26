"""Configured PDF extraction entry point and explicit legacy compatibility adapter.

Docling is the default. No chart values are read during upload; the question
pipeline invokes the separate DePlot reader only with a scoped trigger.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import uuid4

from report_qa.domain.contracts import validate_document_evidence_v2
from report_qa.application.numeric_extraction import (
    HEADER_JOIN,
    PERIOD,
    _period,
    canonical_decimal,
    header_period,
    period_near,
    quantities,
    single_year,
)
from report_qa.application.ocr_extraction import TesseractPdfOcr
from report_qa.application.table_extraction import PdfPlumberTableExtractor


NUMBER_RE = re.compile(r"(?<![\w/])[-+]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?%?")


def _matrix_product(m: Any, n: Any) -> list[float]:
    """Affine product m x n for PDF matrices [a, b, c, d, e, f]."""
    return [
        m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5],
    ]


def _keyword_text(text: str) -> str:
    """Casefolded text for keyword checks.

    PDFs often separate words with U+00A0 (non-breaking space) and may store
    Vietnamese diacritics decomposed; both made "doanh thu" never match.
    """
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


def _bbox_for_match(
    *,
    text: str,
    start: int,
    end: int,
    x: float,
    y: float,
    font_size: float,
    page_width: float,
    page_height: float,
) -> list[float]:
    char_width = max(font_size * 0.48, 1.0)
    x0 = x + start * char_width
    x1 = x + end * char_width
    # PDF coordinates start at the bottom-left; the product contract starts at
    # the top-left. Keep a small vertical margin around the glyph box.
    y0 = page_height - y - font_size * 1.05
    y1 = page_height - y + font_size * 0.15
    bbox = [_clamp(x0 / page_width), _clamp(y0 / page_height), _clamp(x1 / page_width), _clamp(y1 / page_height)]
    if bbox[2] <= bbox[0]:
        bbox[2] = _clamp(bbox[0] + max(1.0 / page_width, 0.001))
    if bbox[3] <= bbox[1]:
        bbox[3] = _clamp(bbox[1] + max(1.0 / page_height, 0.001))
    return bbox


def _decimal_text(raw: str) -> str:
    value = raw.strip().replace(" ", "").removesuffix("%")
    sign = ""
    if value[:1] in {"+", "-"}:
        sign, value = value[0], value[1:]
    if "," in value and "." in value:
        decimal_separator = "," if value.rfind(",") > value.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        value = value.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in value or "." in value:
        separator = "," if "," in value else "."
        pieces = value.split(separator)
        if len(pieces) > 2 or (len(pieces) == 2 and len(pieces[1]) == 3 and len(pieces[0]) >= 1):
            value = "".join(pieces)
        else:
            value = ".".join(pieces)
    # Canonical form drops a leading "+" ("+12" was passed through and failed
    # contract validation for the whole document) and raises ValueError for
    # text that is not a number, which the caller records as a warning.
    return canonical_decimal(f"{sign}{value}")


def cell_semantics(headers: list[str | None], context: str, raw: str, page_year: str | None) -> tuple[str, dict[str, Any] | None]:
    """(measure, period) of a number from its own table header path.

    headers is the path outer to inner: row header, then each column header
    level. Only a number with no header at all takes them from nearby text.
    """
    named = [header for header in headers if header]
    if named:
        return _measure(" ".join(named)), header_period(named, page_year)
    return _measure(context), period_near(context, max(0, context.rfind(raw)))


_SENTENCE_END = re.compile(r"[.!?;](?=\s)|\n")
_CLAUSE_END = re.compile(r"[,:;–—()]")
# What is written right after a number: "6,5%", "220 tỷ đồng", "33 nghìn đơn", "26.900 VND".
_UNIT_AFTER = re.compile(r"\s*(?:(?P<scale>nghìn|ngàn|triệu|tỷ|tỉ|thousand|million|billion)\b\s*(?P<money>đồng|vnd)?|(?P<plain>đồng|vnd|usd)\b)", re.IGNORECASE)
_SCALE_UNITS = {"nghìn": "THOUSAND", "ngàn": "THOUSAND", "triệu": "MILLION", "tỷ": "BILLION", "tỉ": "BILLION",
                "thousand": "THOUSAND", "million": "MILLION", "billion": "BILLION"}
_UNIT_NOTE = re.compile(r"đơn vị\s*:?\s*([^)\n;]+)", re.IGNORECASE)
SUBJECT_WORDS = 12  # a label, not the sentence


def unit_after(text: str, end: int, raw: str) -> str | None:
    """Unit written right after a number in text; None when nothing is written."""
    if raw.endswith("%"):
        return "PERCENT"
    match = _UNIT_AFTER.match(text, end)
    if not match:
        return None
    if match["plain"]:
        return "USD" if match["plain"].casefold() == "usd" else "VND"
    scale = _SCALE_UNITS[match["scale"].casefold()]
    return f"VND_{scale}" if match["money"] else scale


def unit_note(text: str) -> str | None:
    """Unit an explicit note states: "(đơn vị: triệu đồng)"."""
    match = _UNIT_NOTE.search(_keyword_text(text))
    return _unit_near(match.group(1), "") if match else None


def sentence_semantics(text: str, position: int, raw: str, page_year: str | None) -> dict[str, Any]:
    """Measure, subject, period and unit that a text number's own sentence states for it.

    Only the sentence part before the number is read: its nearest measure word, its
    nearest period (a bare quarter or month takes the page's year) and, as
    subject, the opening words of the number's own phrase: from the clause
    start or the previous number and its unit, whichever is later ("số đơn
    hàng tháng 6 đạt" for 33). The unit is what is written right after the
    number. Nothing is borrowed from other sentences of the paragraph.
    """
    start = max((m.end() for m in _SENTENCE_END.finditer(text, 0, position)), default=0)
    before = text[start:position]
    phrase_start = max((m.end() for m in _CLAUSE_END.finditer(before)), default=0)
    for match in quantities(before):
        phrase_start = max(phrase_start, (_UNIT_AFTER.match(before, match.end()) or match).end())
    phrase = " ".join(before[phrase_start:].split()[:SUBJECT_WORDS])
    periods = [period for match in PERIOD.finditer(before) if (period := _period(match, page_year))]
    return {
        "measure": _last_measure(before),
        "subject": phrase if any(c.isalpha() for c in phrase) else None,
        "period": periods[-1] if periods else None,
        "unit": unit_after(text, position + len(raw), raw),
        "dimensions": {},
    }


def _unit_near(text: str, raw: str) -> str | None:
    lowered = _keyword_text(text)
    if raw.endswith("%") or "phần trăm" in lowered or "percent" in lowered:
        return "PERCENT"
    if ("million" in lowered or "triệu" in lowered) and ("vnd" in lowered or "đồng" in lowered):
        return "VND_MILLION"
    if ("billion" in lowered or "tỷ" in lowered) and ("vnd" in lowered or "đồng" in lowered):
        return "VND_BILLION"
    if ("nghìn" in lowered or "ngàn" in lowered or "thousand" in lowered) and ("vnd" in lowered or "đồng" in lowered):
        return "VND_THOUSAND"
    if "$" in text or "usd" in lowered:
        return "USD"
    if "tỷ" in lowered and ("đồng" in lowered or "vnd" in lowered):
        return "VND_BILLION"
    if "triệu" in lowered and ("đồng" in lowered or "vnd" in lowered):
        return "VND_MILLION"
    if "đồng" in lowered or "vnd" in lowered:
        return "VND"
    return None


_MEASURE_ALIASES = (
    (("doanh thu", "revenue", "dtt"), "doanh_thu"),
    (("lợi nhuận", "profit", "lnst"), "loi_nhuan"),
    (("bookings",), "bookings"),
    (("wer",), "wer"),
    (("cer",), "cer"),
)


def _measure(text: str) -> str:
    lowered = _keyword_text(text)
    for names, key in _MEASURE_ALIASES:
        if any(name in lowered for name in names):
            return key
    return "unknown"


def _last_measure(text: str) -> str:
    """The measure word written last in text: the one nearest a number that follows it."""
    lowered = _keyword_text(text)
    found = [(lowered.rfind(name), key) for names, key in _MEASURE_ALIASES for name in names if name in lowered]
    return max(found)[1] if found else "unknown"


def _bbox_in_box(box: list[float], length: int, start: int, end: int, page_width: float, page_height: float) -> list[float]:
    """The part of a known text box that holds characters start..end."""

    left, top, right, bottom = box
    step = (right - left) / max(1, length)
    bbox = [
        _clamp((left + start * step) / page_width),
        _clamp(top / page_height),
        _clamp((left + end * step) / page_width),
        _clamp(bottom / page_height),
    ]
    if bbox[2] <= bbox[0]:
        bbox[2] = _clamp(bbox[0] + 0.001)
    if bbox[3] <= bbox[1]:
        bbox[3] = _clamp(bbox[1] + 0.001)
    return bbox


def _private_use_share(text: str) -> float:
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    return sum(1 for char in visible if "\ue000" <= char <= "\uf8ff") / len(visible)


# Word bullets and icons are private-use characters too, so a few are normal.
UNREADABLE_TEXT_SHARE = 0.05


def _readable_page(path: Path, page_number: int) -> tuple[str, list[dict[str, Any]], float, float] | None:
    """Page text and spans from PyMuPDF, or None when it reads no better.

    Some fonts (Type 3, as Chrome prints them) give pypdf private-use glyph
    codes instead of digits, so the page had no numbers at all.
    """

    import pymupdf

    with pymupdf.open(path) as pdf:
        page = pdf[page_number - 1]
        text = page.get_text(sort=True)
        if not text.strip() or _private_use_share(text) >= UNREADABLE_TEXT_SHARE:
            return None
        # Layout padding is up to 200 spaces a line here and would only spend
        # the AI's page budget.
        text = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]{2,}", "  ", text)).strip()
        width, height = float(page.rect.width) or 1.0, float(page.rect.height) or 1.0
        spans: list[dict[str, Any]] = []
        for x0, top, x1, bottom, word, *_ in sorted(page.get_text("words"), key=lambda item: (round(item[3]), item[0])):
            size = bottom - top
            previous = spans[-1] if spans else None
            # Words closer than a wide space belong to one run ("Kylian
            # MBAPPE"); a wider gap is the next table cell.
            if previous and abs(previous["box"][3] - bottom) <= size * 0.35 and 0 <= x0 - previous["box"][2] <= size * 0.6:
                previous["text"] += f" {word}"
                previous["box"][2] = x1
                previous["box"][1] = min(previous["box"][1], top)
                continue
            spans.append({"text": word, "x": x0, "y": height - bottom, "font_size": size, "box": [x0, top, x1, bottom]})
        return text, spans, width, height


def extract_legacy_pdf_artifact(path: Path, document_version_id: str) -> dict[str, Any]:
    """Return page text plus a strict v2 evidence batch and local contexts."""

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    contexts: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    ocr = TesseractPdfOcr()

    for page_number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width) or 1.0
        height = float(page.mediabox.height) or 1.0
        spans: list[dict[str, Any]] = []
        last_span: dict[str, Any] | None = None

        def visitor(text: str, cm: Any, tm: Any, _font: Any, font_size: float) -> None:
            nonlocal last_span
            if not text or not text.strip():
                return
            # The text matrix is relative to the current transformation
            # matrix. Using tm alone put text drawn under a "cm" translation
            # (e.g. a table block) at the wrong place: wrong bbox, rows merged
            # across blocks, and table cells never matched to the pdfplumber
            # region, so every cell was published twice.
            matrix = _matrix_product(tm, cm)
            scale = (matrix[2] ** 2 + matrix[3] ** 2) ** 0.5 or 1.0
            size = float(font_size or 10.0) * scale
            x, y = float(matrix[4]), float(matrix[5])
            # Some valid PDFs reset pypdf's text matrix to (0, 0) for a
            # continuation run after a separate BT/ET block. A leading space
            # means that run belongs to the previous visual line; carry the
            # previous baseline forward so table row/column inference remains
            # stable instead of creating a phantom row at the page origin.
            if (
                last_span is not None
                and text[:1].isspace()
                and abs(x) < 1e-6
                and abs(y) < 1e-6
            ):
                previous_text = last_span["text"].strip()
                x = last_span["x"] + max(size, len(previous_text) * size * 0.48)
                y = last_span["y"]
            last_span = {"text": text, "x": x, "y": y, "font_size": size}
            spans.append(last_span)

        page_text = page.extract_text(visitor_text=visitor) or ""
        if _private_use_share(page_text) >= UNREADABLE_TEXT_SHARE:
            readable = _readable_page(path, page_number)
            if readable is not None:
                page_text, spans, width, height = readable
        pages.append({"page": page_number, "text": page_text})
        page_year = single_year(page_text)

        # OCR is intentionally page-scoped and only used when the PDF has no
        # usable text layer.  A missing engine becomes an explicit warning;
        # it never silently turns a scanned page into "no evidence".
        if not page_text.strip():
            available, reason = ocr.available()
            if not available:
                warnings.append({"code": reason or "OCR_UNAVAILABLE", "message": "Trang ảnh cần OCR nhưng OCR engine chưa sẵn sàng.", "page_number": page_number})
            else:
                try:
                    ocr_page = ocr.read_page(path, page_number)
                except Exception as exc:
                    warnings.append({"code": "OCR_PAGE_FAILED", "message": "Không đọc được trang ảnh bằng OCR.", "page_number": page_number, "error_type": type(exc).__name__})
                else:
                    for token_index, token in enumerate(ocr_page.tokens):
                        for number_index, match in enumerate(NUMBER_RE.finditer(str(token["text"]))):
                            raw = match.group(0)
                            if re.fullmatch(r"(?:19|20)\d{2}", raw):
                                continue
                            digest = hashlib.sha256(f"ocr:{page_number}:{token_index}:{number_index}:{raw}".encode("utf-8")).hexdigest()[:16]
                            evidence_key = f"ev-{digest}"
                            evidences.append({
                                "evidence_key": evidence_key, "source_region_key": f"page-{page_number}-ocr-token-{token_index}", "source_type": "text",
                                "page_number": page_number, "bbox": token["bbox"], "raw_text": raw, "numeric_value": _decimal_text(raw), "value_kind": "number",
                                "data_status": "valid", "extraction_method": "ocr", "method_label": "đọc bằng OCR",
                                "semantic": {"measure": _measure(str(token["text"])), "subject": None, "period": period_near(str(token["text"]), match.start()), "unit": _unit_near(str(token["text"]), raw), "dimensions": {}},
                                "table_locator": None, "chart_read": None, "confidence": float(token["confidence"]),
                            })
                            contexts[evidence_key] = str(token["text"])
                    pages[-1]["text"] = " ".join(token["text"] for token in ocr_page.tokens)

        # A lightweight table detector for digitally generated PDFs: text runs
        # sharing a baseline are cells in the same visual row. It intentionally
        # does not claim scanned/merged/complex tables; those remain provider
        # work and are never fabricated here.
        rows: list[list[dict[str, Any]]] = []
        for span in sorted(spans, key=lambda item: (-item["y"], item["x"])):
            row = next(
                (
                    candidate
                    for candidate in rows
                    if abs(candidate[0]["y"] - span["y"]) <= max(2.0, span["font_size"] * 0.35)
                ),
                None,
            )
            if row is None:
                row = []
                rows.append(row)
            row.append(span)
        for row_index, row in enumerate(rows):
            row.sort(key=lambda item: item["x"])
            for column_index, span in enumerate(row):
                span["row_index"] = row_index
                span["column_index"] = column_index
                span["row_size"] = len(row)
        header_row = rows[0] if rows else []

        for span_index, span in enumerate(spans):
            text = span["text"]
            for number_index, match in enumerate(NUMBER_RE.finditer(text)):
                raw = match.group(0)
                # Years and quarter tokens are semantic locators, not numeric
                # facts. The negative look-behind removes most of them; this
                # guard covers a standalone year nearest to a Q marker.
                if re.fullmatch(r"(?:19|20)\d{2}", raw):
                    continue
                try:
                    numeric_value = _decimal_text(raw)
                except ValueError:
                    warnings.append({"code": "NUMBER_NORMALIZATION_FAILED", "message": "Không chuẩn hóa được số.", "evidence_key": None})
                    continue
                bbox = _bbox_for_match(
                    text=text,
                    start=match.start(),
                    end=match.end(),
                    x=span["x"],
                    y=span["y"],
                    font_size=span["font_size"],
                    page_width=width,
                    page_height=height,
                )
                if "box" in span:
                    bbox = _bbox_in_box(span["box"], len(text), match.start(), match.end(), width, height)
                digest = hashlib.sha256(f"{page_number}:{span_index}:{number_index}:{raw}".encode("utf-8")).hexdigest()[:16]
                evidence_key = f"ev-{digest}"
                region_key = f"page-{page_number}-span-{span_index}"
                is_table_cell = span.get("row_size", 1) >= 2
                row_index = int(span.get("row_index", 0))
                column_index = int(span.get("column_index", 0))
                row = rows[row_index] if row_index < len(rows) else [span]
                column_header = header_row[column_index]["text"].strip() if row_index > 0 and column_index < len(header_row) else None
                row_header = row[0]["text"].strip() if column_index > 0 and row else None
                semantic_context = " ".join(
                    item
                    for item in (row_header, column_header, text)
                    if item
                ) if is_table_cell else text
                headers = [row_header, column_header] if is_table_cell else []
                measure, period = cell_semantics(headers, text, raw, page_year)
                evidences.append(
                    {
                        "evidence_key": evidence_key,
                        "source_region_key": region_key,
                        "source_type": "table" if is_table_cell else "text",
                        "page_number": page_number,
                        "bbox": bbox,
                        "raw_text": raw,
                        "numeric_value": numeric_value,
                        "value_kind": "number",
                        "data_status": "valid",
                        "extraction_method": "table_cell" if is_table_cell else "text",
                        "method_label": "đọc từ ô bảng" if is_table_cell else "đọc từ văn bản",
                        "semantic": {
                            "measure": measure,
                            "subject": row_header if is_table_cell else None,
                            "period": period,
                            "unit": _unit_near(semantic_context, raw),
                            "dimensions": {},
                        },
                        "table_locator": (
                            {
                                "table_region_key": f"page-{page_number}-layout-table",
                                "row_index": row_index,
                                "column_index": column_index,
                                "row_header": row_header,
                                "column_header": column_header,
                            }
                            if is_table_cell
                            else None
                        ),
                        "chart_read": None,
                        "confidence": 0.9 if is_table_cell else 0.85,
                    }
                )
                contexts[evidence_key] = " ".join(semantic_context.split())

    # Text-run grouping remains a useful no-dependency fallback.  When the
    # optional layout adapter is installed it replaces only the overlapping
    # table cells, retaining text evidence outside a table and preserving the
    # immutable output shape.
    complex_tables = PdfPlumberTableExtractor().extract(path)
    if complex_tables.evidences:
        def inside_complex_region(item: dict[str, Any]) -> bool:
            if item.get("source_type") != "table":
                return False
            x0, y0, x1, y1 = item["bbox"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            return any(number == item["page_number"] and left <= cx <= right and top <= cy <= bottom for number, (left, top, right, bottom) in complex_tables.regions)
        evidences = [item for item in evidences if not inside_complex_region(item)]
        # pdfplumber cells arrive untagged (measure "unknown", no period);
        # tag them from their row/column headers like every other number.
        page_years = {page["page"]: single_year(page["text"]) for page in pages}
        for item in complex_tables.evidences:
            context = complex_tables.contexts.get(item["evidence_key"], item["raw_text"])
            locator = item["table_locator"]
            headers = [locator["row_header"], *(locator["column_header"] or "").split(HEADER_JOIN)]
            measure, period = cell_semantics(headers, context, item["raw_text"], page_years.get(item["page_number"]))
            evidences.append({
                **item,
                "semantic": {
                    **item["semantic"],
                    "measure": measure,
                    "subject": locator["row_header"],
                    "period": period,
                    "unit": _unit_near(context, item["raw_text"]),
                },
            })
        contexts.update(complex_tables.contexts)
    warnings.extend(complex_tables.warnings)

    batch = {
        "schema_version": 2,
        "document_version_id": document_version_id,
        "extraction_run_id": str(uuid4()),
        "scope": "base_document",
        "trigger": None,
        "evidences": evidences,
        "warnings": warnings,
    }
    validate_document_evidence_v2(batch)
    return {"pages": pages, "evidence_batch": batch, "evidence_contexts": contexts}


def extract_pdf_artifact(path: Path, document_version_id: str) -> dict[str, Any]:
    """Select a configured backend; never silently fall back after model failure."""
    import os
    backend = os.getenv("PDF_EXTRACTION_BACKEND", "docling")
    if backend == "legacy":
        return extract_legacy_pdf_artifact(path, document_version_id)
    if backend != "docling":
        raise ValueError("PDF_EXTRACTION_BACKEND must be docling or legacy")
    from report_qa.application.docling_extraction import extract_docling_artifact
    return extract_docling_artifact(path, document_version_id, locale=os.getenv("PDF_NUMBER_LOCALE") or None)


__all__ = ["extract_pdf_artifact", "extract_legacy_pdf_artifact"]
