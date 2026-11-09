"""Docling -> document-evidence-v2, preserving physical cell and number locations.

Heavy imports/model loading occur only during extraction. Picture regions are
indexed during upload but never passed to DePlot here.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from report_qa.application.extraction_contract import validate_extraction_batch
from report_qa.application.numeric_extraction import NUMBER, decimal_text


@lru_cache(maxsize=1)
def _converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def normalized_box(box, width, height):
    if not box:
        raise ValueError("Missing source bounding box")
    left, top, right, bottom = box["l"], box["t"], box["r"], box["b"]
    if box.get("coord_origin") == "BOTTOMLEFT":
        top, bottom = height - top, height - bottom
    result = [
        round(max(0.0, min(1.0, value)), 6)
        for value in (left / width, top / height, right / width, bottom / height)
    ]
    if result[0] >= result[2] or result[1] >= result[3]:
        raise ValueError("Invalid source bounding box")
    return result


def _inside(inner, outer):
    return (
        outer[0] <= (inner[0] + inner[2]) / 2 <= outer[2]
        and outer[1] <= (inner[1] + inner[3]) / 2 <= outer[3]
    )


def extract_docling_artifact(
    path: Path, document_version_id: str, *, locale: str | None = None, converter=None
) -> dict[str, Any]:
    import pymupdf

    # Reuse semantic helpers, without invoking the legacy extractor.
    from report_qa.application.evidence_extraction import (
        _measure,
        _period_near,
        _unit_near,
    )

    result = (converter or _converter()).convert(path)
    status = str(result.status).split(".")[-1].lower()
    if status != "success":
        raise RuntimeError(f"Docling conversion failed: {result.status}")
    data = result.document.export_to_dict()
    evidence, warnings, contexts, charts, pages = [], [], {}, [], []
    with pymupdf.open(path) as pdf:

        def warn(code, message, key=None):
            warnings.append({"code": code, "message": message, "evidence_key": key})

        def region(prov):
            page = pdf[prov["page_no"] - 1]
            return prov["page_no"], normalized_box(
                prov["bbox"], page.rect.width, page.rect.height
            )

        text_by_ref = {
            item.get("self_ref"): item.get("text", "") for item in data.get("texts", [])
        }
        picture_boxes = []
        for i, picture in enumerate(data.get("pictures", [])):
            for prov in picture.get("prov", []):
                number, box = region(prov)
                key = f"page-{number}-picture-{i}"
                picture_boxes.append((number, box))
                charts.append(
                    {
                        "chart_region_key": key,
                        "page_number": number,
                        "bbox": box,
                        "text": " ".join(
                            text_by_ref.get(c.get("$ref"), "")
                            for c in picture.get("captions", [])
                        ),
                        "kind": "picture_candidate",
                    }
                )
        table_boxes = [
            region(p) for t in data.get("tables", []) for p in t.get("prov", [])
        ]
        for number, page in enumerate(pdf, 1):
            pages.append({"page": number, "text": page.get_text()})
            if not page.get_text().strip():
                warn(
                    "OCR_REQUIRED",
                    f"Trang {number} không có lớp chữ; chưa trích xuất số từ trang này.",
                )

        def emit(raw, context, number, box, key, source, locator=None, original=None):
            try:
                value = decimal_text(raw, locale)
                state = "valid"
            except ValueError:
                value, state = None, "ambiguous"
                warn(
                    "NUMBER_FORMAT_AMBIGUOUS",
                    "Cần xác nhận quy ước dấu phân cách số.",
                    key,
                )
            method = "table_cell" if source == "table" else "text"
            item = {
                "evidence_key": key,
                "source_region_key": key + "-region",
                "source_type": source,
                "page_number": number,
                "bbox": box,
                "raw_text": original if original is not None else raw,
                "numeric_value": value,
                "data_status": state,
                "extraction_method": method,
                "method_label": "đọc từ ô bảng"
                if source == "table"
                else "đọc từ văn bản",
                "semantic": {
                    "measure": _measure(context),
                    "subject": locator.get("row_header") if locator else None,
                    "period": _period_near(context, max(0, context.rfind(raw))),
                    "unit": _unit_near(context, raw),
                    "dimensions": {},
                },
                "table_locator": locator,
                "chart_read": None,
                "confidence": 0.85,
            }
            evidence.append(item)
            contexts[key] = context

        for ti, table in enumerate(data.get("tables", [])):
            provs = table.get("prov", [])
            cells = table["data"]["table_cells"]
            seen = set()
            for ci, cell in enumerate(cells):
                if (
                    cell.get("column_header")
                    or cell.get("row_section")
                    or cell.get("row_header")
                ):
                    continue
                text = cell.get("text", "").strip()
                # One value per physical cell. Footnotes/dates/text containing
                # multiple numbers cannot silently become a numeric operand.
                matches = list(NUMBER.finditer(text))
                if not matches and text in {"-", "—", "–"}:
                    matches = [None]
                if not matches:
                    continue
                row, col = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
                if (row, col) in seen:
                    continue
                seen.add((row, col))
                if len(provs) != 1 or not cell.get("bbox"):
                    warn(
                        "CELL_LOCATION_UNAVAILABLE",
                        "Không xác định được trang/ô số; không đưa vào phép tính.",
                    )
                    continue
                number, table_box = region(provs[0])
                page = pdf[number - 1]
                box = normalized_box(cell["bbox"], page.rect.width, page.rect.height)
                if not _inside(box, table_box):
                    warn("CELL_OUTSIDE_TABLE", "Vị trí ô nằm ngoài vùng bảng.")
                    continue
                headers = [
                    c["text"]
                    for c in cells
                    if c.get("column_header")
                    and c["start_col_offset_idx"] <= col < c["end_col_offset_idx"]
                ]
                row_headers = [
                    c["text"]
                    for c in cells
                    if c["start_row_offset_idx"] <= row < c["end_row_offset_idx"]
                    and c["end_col_offset_idx"] <= col
                    and not NUMBER.search(c["text"])
                ]
                locator = {
                    "table_region_key": f"page-{number}-table-{ti}",
                    "row_index": row,
                    "column_index": col,
                    "row_header": " / ".join(row_headers) or None,
                    "column_header": " / ".join(headers) or None,
                }
                # Only nearby caption/unit notes, never arbitrary page prose.
                nearby = " ".join(
                    t.get("text", "")
                    for t in data.get("texts", [])
                    for p in t.get("prov", [])
                    if p["page_no"] == number
                    and abs(region(p)[1][3] - table_box[1]) < 0.08
                )
                context = " ".join(
                    [
                        nearby,
                        locator["row_header"] or "",
                        locator["column_header"] or "",
                        text,
                    ]
                )
                key = f"ev-table-{number}-{ti}-{row}-{col}"
                if len(matches) != 1 or matches[0] is None:
                    raw = text
                else:
                    raw = matches[0].group()
                emit(raw, context, number, box, key, "table", locator, original=text)
                if matches[0] is None:
                    evidence[-1].update(numeric_value=None, data_status="missing")
                elif len(matches) > 1:
                    evidence[-1].update(numeric_value=None, data_status="ambiguous")
                    warn(
                        "CELL_MULTIPLE_NUMBERS",
                        "Ô chứa nhiều số; cần kiểm tra tiêu đề hoặc chú thích.",
                        key,
                    )

        # Exact native word boxes avoid guessed character widths. Docling
        # decides the text regions; native words supply glyph geometry.
        for ti, text in enumerate(data.get("texts", [])):
            if text.get("label") in {"page_header", "page_footer", "caption"}:
                continue
            for pi, prov in enumerate(text.get("prov", [])):
                number, text_box = region(prov)
                if any(
                    n == number and _inside(text_box, box)
                    for n, box in table_boxes + picture_boxes
                ):
                    continue
                page = pdf[number - 1]
                rect = pymupdf.Rect(
                    text_box[0] * page.rect.width,
                    text_box[1] * page.rect.height,
                    text_box[2] * page.rect.width,
                    text_box[3] * page.rect.height,
                )
                for wi, word in enumerate(
                    page.get_text("words", clip=rect + (-1, -1, 1, 1))
                ):
                    token = word[4]
                    for mi, match in enumerate(NUMBER.finditer(token)):
                        raw = match.group()
                        if re.fullmatch(r"(?:19|20)\d{2}", raw.rstrip(".,")):
                            continue
                        box = [
                            word[0] / page.rect.width,
                            word[1] / page.rect.height,
                            word[2] / page.rect.width,
                            word[3] / page.rect.height,
                        ]
                        if any(
                            n == number and _inside(box, b)
                            for n, b in table_boxes + picture_boxes
                        ):
                            continue
                        key = (
                            "ev-text-"
                            + hashlib.sha256(
                                f"{number}:{word[:5]}:{mi}".encode()
                            ).hexdigest()[:16]
                        )
                        if any(e["evidence_key"] == key for e in evidence):
                            continue
                        emit(raw, text.get("text", ""), number, box, key, "text")
        batch = {
            "schema_version": 2,
            "document_version_id": document_version_id,
            "extraction_run_id": str(uuid4()),
            "scope": "base_document",
            "trigger": None,
            "evidences": evidence,
            "warnings": warnings,
        }
        validate_extraction_batch(batch)
        return {
            "pages": pages,
            "evidence_batch": batch,
            "evidence_contexts": contexts,
            "chart_regions": charts,
            "extraction_provider": "docling",
        }
