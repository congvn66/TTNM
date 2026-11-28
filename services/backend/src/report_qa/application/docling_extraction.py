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
from report_qa.application.numeric_extraction import (
    HEADER_JOIN,
    NUMBER,
    decimal_text,
    detected_locale,
    is_value_text,
    period_near,
    quantities,
    single_year,
)

# Headings and running text around the page are not values: "1. Phạm vi", "BÁO CÁO 6 THÁNG".
_NOT_VALUE_TEXT = {"page_header", "page_footer", "caption", "section_header", "title"}


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


@lru_cache(maxsize=1)
def _ocr_converter():
    """Docling with Tesseract OCR, for PDFs that are scans only: it finds tables and their cells
    in the page image, so a scanned table gets rows and columns like a digital one."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from report_qa.application.ocr_extraction import SCAN_SCALE, TesseractPdfOcr

    options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=TesseractCliOcrOptions(lang=list(TesseractPdfOcr.LANGUAGES), scale=SCAN_SCALE, force_full_page_ocr=True),
    )
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def _is_scan(path) -> bool:
    """No page has a text layer."""
    import pymupdf

    with pymupdf.open(path) as pdf:
        return all(not page.get_text().strip() for page in pdf)


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
    path: Path,
    document_version_id: str,
    *,
    locale: str | None = None,
    converter=None,
    ocr_engine=None,
) -> dict[str, Any]:
    import pymupdf

    # Reuse semantic helpers, without invoking the legacy extractor.
    from report_qa.application.evidence_extraction import (
        _unit_near,
        cell_semantics,
        sentence_semantics,
        unit_note,
    )
    from report_qa.application.ocr_extraction import TesseractPdfOcr

    # A scan-only PDF is read by Docling's OCR on a copy without table lines (see ocr_extraction.clean_scan).
    # The copy has the same page sizes, so every box still points at the original page.
    scan = converter is None and _is_scan(path) and TesseractPdfOcr().available()[0]
    if scan:
        import tempfile

        from report_qa.application.ocr_extraction import clean_scan

        with tempfile.TemporaryDirectory() as folder:
            result = _ocr_converter().convert(clean_scan(path, Path(folder) / "clean.pdf"))
    else:
        result = (converter or _converter()).convert(path)
    status = str(result.status).split(".")[-1].lower()
    if status != "success":
        raise RuntimeError(f"Docling conversion failed: {result.status}")
    data = result.document.export_to_dict()
    if scan:
        # OCR writes "Quý 1/2026" with a fraction slash (U+2044), which no period rule reads.
        for item in data.get("texts", []):
            item["text"] = item.get("text", "").replace("\u2044", "/")
        for table in data.get("tables", []):
            for cell in table.get("data", {}).get("table_cells", []):
                cell["text"] = cell.get("text", "").replace("\u2044", "/")
    evidence, warnings, contexts, charts, pages, page_years = [], [], {}, [], [], {}
    paragraphs: list[dict] = []
    ocr_pages = {}
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
        ocr = ocr_engine or TesseractPdfOcr()
        for number, page in enumerate(pdf, 1):
            page_text = page.get_text()
            if not page_text.strip():
                available, code = ocr.available()
                if available:
                    try:
                        ocr_page = ocr.read_page(path, number)
                        ocr_pages[number] = ocr_page
                        page_text = " ".join(
                            str(token.get("text", "")).strip()
                            for token in ocr_page.tokens
                            if str(token.get("text", "")).strip()
                        )
                    except Exception as exc:
                        warn(
                            type(exc).__name__ or "OCR_FAILED",
                            f"Không đọc được trang {number} bằng OCR.",
                        )
                else:
                    warn(
                        code or "OCR_UNAVAILABLE",
                        f"Trang {number} không có lớp chữ; chưa trích xuất số từ trang này.",
                    )
            pages.append({"page": number, "text": page_text})
            page_years[number] = single_year(page_text)
            if not page_text.strip():
                warn(
                    "OCR_REQUIRED",
                    f"Trang {number} không có lớp chữ; chưa trích xuất số từ trang này.",
                )
        # Unconfigured, numbers are read in the format the page text proves (as the API reads typed numbers).
        # OCR misreads ("1.25" for "1,25") look like proof of English number format, so a document read
        # only by OCR takes the format of the OCR language: Vietnamese.
        if locale is None and ocr_pages and len(ocr_pages) == len(pages):
            locale = "vi"
        locale = locale or detected_locale(page["text"] for page in pages)

        def emit(
            raw,
            context,
            number,
            box,
            key,
            source,
            locator=None,
            original=None,
            extraction_method=None,
            confidence=0.85,
            headers=(),
            semantic=None,
            paragraph=None,
        ):
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
            measure, period = cell_semantics(list(headers), context, raw, page_years.get(number))
            method = extraction_method or ("table_cell" if source == "table" else "text")
            method_labels = {
                "table_cell": "\u0111\u1ecdc t\u1eeb \u00f4 b\u1ea3ng",
                "text": "\u0111\u1ecdc t\u1eeb v\u0103n b\u1ea3n",
                "ocr": "\u0111\u1ecdc b\u1eb1ng OCR",
            }
            item = {
                "evidence_key": key,
                "source_region_key": key + "-region",
                "source_type": source,
                "page_number": number,
                "bbox": box,
                "raw_text": original if original is not None else raw,
                "numeric_value": value,
                "value_kind": "number",
                "data_status": state,
                "extraction_method": method,
                "method_label": "đọc từ ô bảng"
                if source == "table"
                else "đọc từ văn bản",
                "semantic": semantic or {
                    "measure": measure,
                    "subject": locator.get("row_header") if locator else None,
                    "period": period,
                    "unit": _unit_near(context, raw),
                    "dimensions": {},
                },
                "table_locator": locator,
                # Where a text number sits in its paragraph: {paragraph_key, start, end} in its text.
                "paragraph_locator": paragraph,
                "chart_read": None,
                "method_label": method_labels[method],
                "confidence": confidence,
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
                if not is_value_text(text):  # a label such as "Giá mục tiêu 2026:"
                    continue
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
                # The cell's own header path: column header levels outer to
                # inner, and the labels left of it in its row (never a value
                # or a "-" placeholder of a neighbouring cell).
                headers = [
                    c["text"]
                    for c in sorted(cells, key=lambda c: c["start_row_offset_idx"])
                    if c.get("column_header")
                    and c["start_col_offset_idx"] <= col < c["end_col_offset_idx"]
                ]
                row_headers = [
                    c["text"]
                    for c in cells
                    if c["start_row_offset_idx"] <= row < c["end_row_offset_idx"]
                    and c["end_col_offset_idx"] <= col
                    and not c.get("column_header")
                    and not is_value_text(c["text"])
                ]
                locator = {
                    "table_region_key": f"page-{number}-table-{ti}",
                    "row_index": row,
                    "column_index": col,
                    "row_header": HEADER_JOIN.join(row_headers) or None,
                    "column_header": HEADER_JOIN.join(headers) or None,
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
                emit(raw, context, number, box, key, "table", locator, original=text, headers=row_headers + headers)
                # A cell's unit is its own "%", else what its headers state, else the table's unit note;
                # prose near the table ("tỷ lệ phần trăm khách hàng...") is not the cell's unit.
                evidence[-1]["semantic"]["unit"] = (
                    "PERCENT" if text.endswith("%") else _unit_near(HEADER_JOIN.join(row_headers + headers), "")
                    or unit_note(nearby)
                )
                if matches[0] is None:
                    evidence[-1].update(numeric_value=None, data_status="missing")
                elif len(matches) > 1:
                    evidence[-1].update(numeric_value=None, data_status="ambiguous")
                    warn(
                        "CELL_MULTIPLE_NUMBERS",
                        "Ô chứa nhiều số; cần kiểm tra tiêu đề hoặc chú thích.",
                        key,
                    )

        # Scanned pages use OCR only when no native text layer was available.
        # Every numeric OCR token keeps its normalized bbox and confidence;
        # without that proof it never becomes a calculator operand.
        for number, ocr_page in ocr_pages.items():
            page_context = next(
                (item["text"] for item in pages if item["page"] == number), ""
            )
            # The same rule as printed text: headings ("1."), years and list markers are not values.
            # Titles are often upper case ("6 THÁNG ĐẦU NĂM"): read the text in lower case too, same positions.
            quantity_starts = {m.start() for m in quantities(page_context)} & {m.start() for m in quantities(page_context.lower())}
            texts = [str(token.get("text", "")).strip() for token in ocr_page.tokens]
            # page_context is the tokens joined by one space, so a token starts where the previous one ended + 1.
            offset = -1
            for oi, token in enumerate(ocr_page.tokens):
                text = str(token.get("text", "")).strip()
                if not text:
                    continue
                offset += 1
                start, offset = offset, offset + len(text)
                # A number in a table or chart comes from that table's cells or that chart's read.
                if any(n == number and _inside(list(token["bbox"]), box) for n, box in table_boxes + picture_boxes):
                    continue
                matches = list(NUMBER.finditer(text))
                if len(matches) == 1 and start + matches[0].start() not in quantity_starts:
                    continue
                # A section number: "1." followed by a capitalised heading word ("1. Định nghĩa").
                following = next((later for later in texts[oi + 1:] if later), "")
                if re.fullmatch(r"\d{1,2}\.", text) and following[:1].isupper():
                    continue
                if len(matches) != 1:
                    if matches:
                        warn(
                            "OCR_MULTIPLE_NUMBERS",
                            "OCR token chứa nhiều số; không đưa vào phép tính.",
                        )
                    continue
                match = matches[0]
                # Read the number's own sentence, as for native text: "220 tỷ đồng" is billions even
                # on a page whose table says "(đơn vị: triệu đồng)". A number with no unit written
                # after it (a scanned table cell) takes the page's unit note.
                semantic = sentence_semantics(page_context, start + match.start(), match.group(), page_years.get(number))
                semantic["unit"] = semantic["unit"] or unit_note(page_context)
                emit(
                    match.group(),
                    page_context,
                    number,
                    list(token["bbox"]),
                    f"ev-ocr-{number}-{oi}",
                    "text",
                    original=text,
                    extraction_method="ocr",
                    confidence=float(token.get("confidence", 0.0)),
                    semantic=semantic,
                )

        # Exact native word boxes avoid guessed character widths. Docling
        # decides the text regions; native words supply glyph geometry.
        for ti, text in enumerate(data.get("texts", [])):
            if text.get("label") in _NOT_VALUE_TEXT:
                continue
            item_text = text.get("text", "")
            # Only quantities are values: not "quý 2", "tháng 6/2026", "6 tháng", "31/12/2023".
            values = [m.span() for m in quantities(item_text)]
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
                paragraph_key = f"para-{number}-{ti}-{pi}"
                paragraphs.append({"paragraph_key": paragraph_key, "page_number": number, "bbox": text_box,
                                   "text": item_text, "label": text.get("label")})
                cursor = 0
                for wi, word in enumerate(
                    page.get_text("words", clip=rect + (-1, -1, 1, 1))
                ):
                    token = word[4]
                    at = item_text.find(token, cursor)
                    cursor = at + len(token) if at >= 0 else cursor
                    for mi, match in enumerate(NUMBER.finditer(token)):
                        raw = match.group()
                        if re.fullmatch(r"(?:19|20)\d{2}", raw.rstrip(".,")):
                            continue
                        # A word the Docling text does not hold is from a neighbouring region
                        # (a header line, a side box): its number belongs to that region, not here.
                        if at < 0:
                            continue
                        position = at + match.start()
                        if not any(a <= position < b for a, b in values):
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
                        # Overlapping Docling regions hold the same word twice: one number, one evidence.
                        if any(e["evidence_key"] == key or (e["page_number"] == number and e["raw_text"] == raw and _inside(box, e["bbox"]))
                               for e in evidence):
                            continue
                        semantic = sentence_semantics(item_text, position, raw.rstrip(".,"), page_years.get(number))
                        emit(raw, item_text, number, box, key, "text", semantic=semantic,
                             paragraph={"paragraph_key": paragraph_key, "start": position, "end": position + len(raw)})
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
            "paragraphs": paragraphs,
            "evidence_batch": batch,
            "evidence_contexts": contexts,
            "chart_regions": charts,
            "extraction_provider": "docling",
        }
