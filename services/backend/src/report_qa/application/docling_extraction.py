"""Docling -> document-evidence-v2, preserving physical cell and number locations.

Heavy imports/model loading occur only during extraction. Picture regions are
indexed during upload but never passed to DePlot here.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from report_qa.application.chart_regions import chart_candidates
from report_qa.application.extraction_contract import validate_extraction_batch
from report_qa.application.numeric_extraction import (
    HEADER_JOIN,
    NUMBER,
    REFERENCE,
    decimal_text,
    detected_locale,
    fold,
    is_note_ref,
    is_value_text,
    joined_number,
    quantities,
    single_year,
)

# The reading's rules: an artifact records the version that made it. 2: scanned pages decided per page,
# codes and numbered labels are not values, OCR misreads are unsure, tables continued across pages.
EXTRACTOR_VERSION = "docling-2"
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


# A page is a scan when one image covers at least this share of it and its text, if any, fits in a
# box under TEXT_BOX_SHARE of it: the stamp "Digitally signed by…" that signing tools add to a scan.
SCAN_IMAGE_SHARE = 0.5
TEXT_BOX_SHARE = 0.15


def scan_pages(pdf) -> set[int]:
    """Numbers of the pages that are a scanned image: no text layer, or a page-size image with only a stamp of text."""
    import pymupdf

    found = set()
    for number, page in enumerate(pdf, 1):
        words = page.get_text("words")
        if not words:
            found.add(number)
            continue
        # Image and word boxes are in the unrotated page space, as is the crop box.
        area = page.cropbox.get_area() or 1.0
        image = max((pymupdf.Rect(i["bbox"]).intersect(page.cropbox).get_area() for i in page.get_image_info()), default=0.0)
        text = pymupdf.Rect(words[0][:4])
        for word in words[1:]:
            text |= word[:4]
        if image >= SCAN_IMAGE_SHARE * area and text.get_area() < TEXT_BOX_SHARE * area:
            found.add(number)
    return found


def _merge_scanned(digital: dict, scanned: dict, numbers: list[int]) -> dict:
    """Docling's reading of a PDF whose pages `numbers` are replaced by the OCR reading of a copy holding only them.

    Page i of the copy is page numbers[i - 1] of the PDF. Text references ("#/texts/3")
    are renumbered so picture captions still point at their text.
    """
    merged: dict[str, list] = {"texts": [], "tables": [], "pictures": []}
    for source, page_of in ((digital, lambda n: None if n in numbers else n), (scanned, lambda n: numbers[n - 1])):
        refs, first_picture = {}, len(merged["pictures"])
        for kind in merged:
            for i, item in enumerate(source.get(kind, [])):
                provs = [{**prov, "page_no": page_of(prov["page_no"])} for prov in item.get("prov", [])]
                if not provs or any(prov["page_no"] is None for prov in provs):
                    continue
                refs[f"#/{kind}/{i}"] = f"#/{kind}/{len(merged[kind])}"
                merged[kind].append({**item, "prov": provs})
        for picture in merged["pictures"][first_picture:]:
            picture["captions"] = [{"$ref": refs[c.get("$ref")]} for c in picture.get("captions", []) if c.get("$ref") in refs]
    merged["tables"].sort(key=lambda table: table["prov"][0]["page_no"])
    return merged


def _code_text(text: str) -> str:
    """A cell's text without the marks OCR adds around a short code: ":310", "| 70", "1\"", "i 440"."""
    text = re.sub(r"^[^\w(]+|[^\w)]+$", "", text.strip())
    return re.sub(r"^[il|]\s+(?=\d)", "", text).strip("()")


_CODE_HEADER = re.compile(r"\b(?:ma so|thuyet minh|tm|stt|so tt)\b")


def _code_columns(cells) -> set[int]:
    """Columns of codes, not values: "Mã số" (100, 110, 111…), "Thuyết minh" (V.01) and "STT".

    Known by the header, or, when OCR garbled it ("Ma sé", "Lrg"), by the cells: three or
    more short codes, mostly rising, left of a column that holds real amounts.
    """
    body, header = defaultdict(list), defaultdict(str)
    for cell in sorted(cells, key=lambda c: c["start_row_offset_idx"]):
        if cell.get("column_header"):
            for col in range(cell["start_col_offset_idx"], cell["end_col_offset_idx"]):
                header[col] += " " + cell.get("text", "")
        elif cell.get("text", "").strip() and cell["end_col_offset_idx"] - cell["start_col_offset_idx"] == 1:
            body[cell["start_col_offset_idx"]].append(_code_text(cell["text"]))
    amounts = {col for col, texts in body.items() if any(len(re.sub(r"\D", "", t)) >= 4 for t in texts)}
    codes = {col for col in header if _CODE_HEADER.search(fold(header[col]).casefold())}
    for col, texts in body.items():
        numbers = [int(t) for t in texts if re.fullmatch(r"\d{1,3}", t)]
        short = len(numbers) + sum(1 for t in texts if is_note_ref(t))
        rising = sum(b > a for a, b in zip(numbers, numbers[1:]))
        if (len(texts) >= 3 and short >= 0.8 * len(texts) and len(numbers) >= 2 and rising >= 0.75 * (len(numbers) - 1)
                and any(other > col for other in amounts)):
            codes.add(col)
    return codes


def _column_number_rows(cells) -> set[int]:
    """Rows that number the columns, "1 2 3 4 5" or "(1) (2) (3)": no values in them."""
    rows = defaultdict(list)
    for cell in cells:
        if cell.get("text", "").strip():
            rows[cell["start_row_offset_idx"]].append((cell["start_col_offset_idx"], _code_text(cell["text"])))
    found = set()
    for row, texts in rows.items():
        numbers = [int(t) for _, t in sorted(texts) if re.fullmatch(r"\d{1,2}", t)]
        if len(numbers) >= 3 and len(numbers) == len(texts) and numbers == list(range(numbers[0], numbers[0] + len(numbers))):
            found.add(row)
    return found


def _demote_value_headers(cells) -> None:
    """A header row that holds values is a data row: a table continued from the previous page starts with one."""
    rows = defaultdict(list)
    for cell in cells:
        if cell.get("column_header") and cell.get("text", "").strip():
            rows[cell["start_row_offset_idx"]].append(is_value_text(joined_number(cell["text"])))
    data_rows = {row for row, values in rows.items() if sum(values) * 2 >= len(values)}
    for cell in cells:
        if cell.get("column_header") and cell["start_row_offset_idx"] in data_rows:
            cell["column_header"] = False


_TOTAL_WORDS = re.compile(r"(?i)^(t[oe]ng)(\s+cong)?\b|^(cong)$")


def _clean_ocr_label(text: str) -> str:
    """An OCR'd label without stray marks, with the total words fixed: "‘Téng" -> "Tổng", "TONG CONG" -> "TỔNG CỘNG"."""
    text = re.sub(r"^[^\w(\-+–—]+|[\s|]+$", "", text)
    match = _TOTAL_WORDS.match(fold(text))
    if not match:
        return text
    upper = text[:4].isupper()
    total, together = ("TỔNG", "TỔNG CỘNG") if upper else ("Tổng", "Tổng cộng")
    if match[3]:
        return "CỘNG" if upper else "Cộng"
    return (together if match[2] else total) + text[match.end():]


def _fraction_digits(raw: str) -> int:
    """Digits after the last separator of a printed number when it looks like a decimal part: "412.6" -> 1, "1.234" -> 3."""
    match = re.search(r"[.,](\d+)\)?\s*%?$", raw.strip())
    return len(match[1]) if match else 0


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


def _docling_data(path: Path, pdf, scanned: set[int], converter, ocr_ready: bool) -> dict:
    """Docling's reading of the PDF; scanned pages are read by Docling's OCR on a copy without table lines.

    The copy has the same page sizes, so every box still points at the original page
    (see ocr_extraction.clean_scan).
    """

    def convert(conversion, source):
        result = conversion.convert(source)
        status = str(result.status).split(".")[-1].lower()
        if status != "success":
            raise RuntimeError(f"Docling conversion failed: {result.status}")
        return result.document.export_to_dict()

    if not ocr_ready or not scanned:
        return convert(converter or _converter(), path)
    import tempfile

    from report_qa.application.ocr_extraction import clean_scan

    numbers = sorted(scanned)
    with tempfile.TemporaryDirectory() as folder:
        if len(numbers) == pdf.page_count:
            data = convert(_ocr_converter(), clean_scan(path, Path(folder) / "clean.pdf"))
        else:
            data = _merge_scanned(convert(_converter(), path),
                                  convert(_ocr_converter(), clean_scan(path, Path(folder) / "clean.pdf", numbers)), numbers)
    # OCR writes "Quý 1/2026" with a fraction slash (U+2044), which no period rule reads.
    for item in data.get("texts", []):
        item["text"] = item.get("text", "").replace("⁄", "/")
    for table in data.get("tables", []):
        for cell in table.get("data", {}).get("table_cells", []):
            cell["text"] = cell.get("text", "").replace("⁄", "/")
    return data


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
        label_unit,
        sentence_semantics,
        unit_note,
    )
    from report_qa.application.ocr_extraction import TesseractPdfOcr

    evidence, warnings, contexts, charts, pages, page_years = [], [], {}, [], [], {}
    paragraphs: list[dict] = []
    ocr_pages = {}
    with pymupdf.open(path) as pdf:
        # A page that is a scan (no text layer, or only a signature stamp on a page-size image) is read by OCR.
        scanned = scan_pages(pdf)
        ocr = ocr_engine or TesseractPdfOcr()
        ocr_ready = converter is None and bool(scanned) and ocr.available()[0]
        data = _docling_data(path, pdf, scanned, converter, ocr_ready)
        # Pages whose tables and headings Docling read from the page image by OCR.
        ocr_layout = scanned if ocr_ready else set()

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
        charts[:] = chart_candidates(pdf, charts)
        table_boxes = [
            region(p) for t in data.get("tables", []) for p in t.get("prov", [])
        ]
        # Headings, captions and running heads of OCR pages: their numbers are not values
        # ("BÁO CÁO HOẠT ĐỘNG 9 THÁNG", "Bảng 3. Doanh thu từ 5 khách hàng…").
        heading_boxes = [
            region(p) for t in data.get("texts", []) for p in t.get("prov", [])
            if p["page_no"] in ocr_layout
            and (t.get("label") in _NOT_VALUE_TEXT or (REFERENCE.match(t.get("text", "").strip()) and len(t.get("text", "")) < 200))
        ]
        for number, page in enumerate(pdf, 1):
            page_text = page.get_text()
            if number in scanned:
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
            exact=False,
        ):
            try:
                value = decimal_text(raw, locale, exact=exact)
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
                "table_cell": "đọc từ ô bảng",
                "text": "đọc từ văn bản",
                "ocr": "đọc bằng OCR",
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

        def unsure(item, raw, key):
            """OCR swaps "," and "." and drops them: a number it may have misread is shown as unsure, never as sure."""
            if item["data_status"] == "valid":
                item.update(numeric_value=None, data_status="ambiguous")
                warn("OCR_NUMBER_UNSURE", f"Số «{raw}» đọc từ ảnh quét có thể sai dấu phân cách; cần kiểm tra.", key)

        def misread(raw, value):
            """A number OCR likely misread: a 3-digit decimal part ("19,774" for "19.774") or a leading zero ("073" for "0,73")."""
            return (value is not None and "." in value and _fraction_digits(raw) == 3) or bool(re.fullmatch(r"\(?0\d+\)?", raw))

        def table_page(table):
            provs = table.get("prov", [])
            return provs[0]["page_no"] if len(provs) == 1 else None

        tables = data.get("tables", [])
        table_pages = [table_page(t) for t in tables]
        previous = None  # the last table read: its page, column count, column headers and unit note
        for ti, table in enumerate(tables):
            provs = table.get("prov", [])
            cells = table["data"]["table_cells"]
            page_no = table_pages[ti]
            ocr_table = page_no in ocr_layout
            if ocr_table:
                for cell in cells:
                    if not is_value_text(cell.get("text", "")):
                        cell["text"] = _clean_ocr_label(cell.get("text", ""))
            _demote_value_headers(cells)
            code_columns = _code_columns(cells)
            number_rows = _column_number_rows(cells)
            columns = table["data"].get("num_cols") or max((c["end_col_offset_idx"] for c in cells), default=0)
            # A table that starts a page with no header of its own, right after a table that ended the
            # previous page with as many columns, is that table continued: it takes its headers and unit.
            follows = (
                previous is not None
                and page_no is not None
                and previous["page"] == page_no - 1
                and previous["columns"] == columns
                and page_no not in table_pages[:ti]
                and previous["page"] not in table_pages[ti + 1:]
            )
            continued = follows and not any(c.get("column_header") for c in cells)
            # Only nearby caption/unit notes, never arbitrary page prose.
            nearby = ""
            if page_no is not None:
                table_top = region(provs[0])[1][1]
                nearby = " ".join(
                    t.get("text", "")
                    for t in data.get("texts", [])
                    for p in t.get("prov", [])
                    if p["page_no"] == page_no and abs(region(p)[1][3] - table_top) < 0.08
                )
            # A continued table keeps the unit note of its first part, even when it repeats the header row.
            if follows and not unit_note(nearby):
                nearby = previous["nearby"] + " " + nearby
            column_headers = defaultdict(list)
            for c in sorted(cells, key=lambda c: c["start_row_offset_idx"]):
                if c.get("column_header"):
                    for col in range(c["start_col_offset_idx"], c["end_col_offset_idx"]):
                        column_headers[col].append(c["text"])
            if continued:
                column_headers = previous["headers"]
            seen = set()
            read = []  # (evidence item, raw number, column) of this table
            for ci, cell in enumerate(cells):
                if (
                    cell.get("column_header")
                    or cell.get("row_section")
                    or cell.get("row_header")
                ):
                    continue
                row, col = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
                if col in code_columns or row in number_rows:
                    continue
                text = joined_number(cell.get("text", "").strip())
                if not is_value_text(text):  # a label such as "Giá mục tiêu 2026:"
                    continue
                # One value per physical cell. Footnotes/dates/text containing
                # multiple numbers cannot silently become a numeric operand.
                matches = list(NUMBER.finditer(text))
                if not matches and text in {"-", "—", "–"}:
                    matches = [None]
                if not matches:
                    continue
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
                # inner, and the labels left of it in its row (never a value,
                # a note reference, a code or a "-" placeholder of a neighbouring cell).
                headers = list(column_headers.get(col, []))
                row_headers = [
                    c["text"]
                    for c in cells
                    if c["start_row_offset_idx"] <= row < c["end_row_offset_idx"]
                    and c["end_col_offset_idx"] <= col
                    and not c.get("column_header")
                    and c["start_col_offset_idx"] not in code_columns
                    and not is_value_text(c["text"])
                    and not is_note_ref(c["text"])
                    and c["text"].strip()
                ]
                locator = {
                    "table_region_key": f"page-{number}-table-{ti}",
                    "row_index": row,
                    "column_index": col,
                    "row_header": HEADER_JOIN.join(row_headers) or None,
                    "column_header": HEADER_JOIN.join(headers) or None,
                }
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
                emit(raw, context, number, box, key, "table", locator, original=cell.get("text", "").strip(),
                     headers=row_headers + headers, exact=ocr_table)
                # A cell's unit is its own "%", else what its headers state, else the table's unit note;
                # prose near the table ("tỷ lệ phần trăm khách hàng...") is not the cell's unit.
                labels = HEADER_JOIN.join(row_headers + headers)
                evidence[-1]["semantic"]["unit"] = (
                    "PERCENT" if text.endswith("%") else label_unit(labels) or _unit_near(labels, "")
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
                else:
                    read.append((evidence[-1], raw, col))
            if ocr_table:
                # A column of decimals ("312,4", "72.6") does not hold a whole number like "512": OCR lost
                # its comma. Unsure cells count, since their shape is still seen. A column of amounts
                # grouped in thousands ("2.105", "785") may have a ratio row with decimals under them,
                # so there only the cells next to a decimal are in doubt.
                by_column = defaultdict(list)
                for item, raw, col in read:
                    by_column[col].append((item, raw))
                for column in by_column.values():
                    decimal = [1 <= _fraction_digits(raw) <= 2 for _, raw in column]
                    amounts = any(re.search(r"\d[.,]\d{3}$", raw.strip("()%")) for _, raw in column)
                    for i, (item, raw) in enumerate(column):
                        near = decimal[max(0, i - 1):i] + decimal[i + 1:i + 2]
                        lost = not _fraction_digits(raw) and item["numeric_value"] not in {None, "0"} and (
                            any(near) or (any(decimal) and not amounts))
                        if lost or misread(raw, item["numeric_value"]):
                            unsure(item, raw, item["evidence_key"])
            if page_no is not None:
                previous = {"page": page_no, "columns": columns, "headers": column_headers, "nearby": nearby}

        # Scanned pages: numbers outside tables and charts come from Tesseract's words.
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
                if any(n == number and _inside(list(token["bbox"]), box) for n, box in table_boxes + picture_boxes + heading_boxes):
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
                # A one- or two-digit word alone ("7,", a speck read as "1") counts nothing unless
                # a word follows it, as in "6 lô hàng".
                if re.fullmatch(r"\d{1,2}", match.group()) and (text != match.group() or not following[:1].islower()):
                    continue
                # Read the number's own sentence, as for native text: "220 tỷ đồng" is billions even
                # on a page whose table says "(đơn vị: triệu đồng)". A number with no unit written
                # after it (a scanned table cell) takes the page's unit note.
                semantic = sentence_semantics(page_context, start + match.start(), match.group(), page_years.get(number))
                semantic["unit"] = semantic["unit"] or unit_note(page_context)
                key = f"ev-ocr-{number}-{oi}"
                emit(
                    match.group(),
                    page_context,
                    number,
                    list(token["bbox"]),
                    key,
                    "text",
                    original=text,
                    extraction_method="ocr",
                    confidence=float(token.get("confidence", 0.0)),
                    semantic=semantic,
                    exact=True,
                )
                if misread(match.group(), evidence[-1]["numeric_value"]):
                    unsure(evidence[-1], match.group(), key)

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
                # A scanned page's numbers are its OCR words; its only native words are a stamp.
                if number in ocr_pages:
                    continue
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
            "extractor_version": EXTRACTOR_VERSION,
        }
