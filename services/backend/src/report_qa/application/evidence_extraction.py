"""Configured PDF extraction entry point and explicit legacy compatibility adapter.

Docling is the default. No chart values are read during upload; the question
pipeline invokes the separate DePlot reader only with a scoped trigger.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from report_qa.domain.contracts import validate_document_evidence_v2
from report_qa.application.ocr_extraction import TesseractPdfOcr
from report_qa.application.table_extraction import PdfPlumberTableExtractor


NUMBER_RE = re.compile(r"(?<![\w/])[-+]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?%?")
QUARTER_RE = re.compile(r"(?i)\b(?:q|quý\s*)([1-4])\s*[/\- ]\s*((?:19|20)\d{2})\b")
YEAR_RE = re.compile(r"(?<![/\d])((?:19|20)\d{2})(?!\d)")


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
    value = value.lstrip("0") or "0"
    if value.startswith("."):
        value = f"0{value}"
    return f"{sign}{value}" if value != "0" else "0"


def _period_near(text: str, number_start: int) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for match in QUARTER_RE.finditer(text):
        quarter, year = int(match.group(1)), int(match.group(2))
        candidates.append(
            (
                abs(match.start() - number_start),
                {
                    "label": f"Q{quarter}/{year}",
                    "start": f"{year}-{(quarter - 1) * 3 + 1:02d}-01",
                    "end": None,
                    "granularity": "quarter",
                },
            )
        )
    if not candidates:
        for match in YEAR_RE.finditer(text):
            year = match.group(1)
            candidates.append(
                (
                    abs(match.start() - number_start),
                    {"label": year, "start": f"{year}-01-01", "end": f"{year}-12-31", "granularity": "year"},
                )
            )
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _unit_near(text: str, raw: str) -> str | None:
    lowered = text.casefold()
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


def _measure(text: str) -> str:
    lowered = text.casefold()
    aliases = (
        (("doanh thu", "revenue"), "doanh_thu"),
        (("lợi nhuận", "profit"), "loi_nhuan"),
        (("bookings",), "bookings"),
        (("wer",), "wer"),
        (("cer",), "cer"),
    )
    for names, key in aliases:
        if any(name in lowered for name in names):
            return key
    return "unknown"


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

        def visitor(text: str, _cm: Any, tm: Any, _font: Any, font_size: float) -> None:
            if not text or not text.strip():
                return
            spans.append({"text": text, "x": float(tm[4]), "y": float(tm[5]), "font_size": float(font_size or 10.0)})

        page_text = page.extract_text(visitor_text=visitor) or ""
        pages.append({"page": page_number, "text": page_text})

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
                                "page_number": page_number, "bbox": token["bbox"], "raw_text": raw, "numeric_value": _decimal_text(raw),
                                "data_status": "valid", "extraction_method": "ocr", "method_label": "đọc bằng OCR",
                                "semantic": {"measure": _measure(str(token["text"])), "subject": None, "period": _period_near(str(token["text"]), match.start()), "unit": _unit_near(str(token["text"]), raw), "dimensions": {}},
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
                evidences.append(
                    {
                        "evidence_key": evidence_key,
                        "source_region_key": region_key,
                        "source_type": "table" if is_table_cell else "text",
                        "page_number": page_number,
                        "bbox": bbox,
                        "raw_text": raw,
                        "numeric_value": numeric_value,
                        "data_status": "valid",
                        "extraction_method": "table_cell" if is_table_cell else "text",
                        "method_label": "đọc từ ô bảng" if is_table_cell else "đọc từ văn bản",
                        "semantic": {
                            "measure": _measure(semantic_context),
                            "subject": None,
                            "period": _period_near(semantic_context, semantic_context.rfind(raw)),
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
        evidences.extend(complex_tables.evidences)
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
