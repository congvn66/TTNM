"""Optional layout-table adapter with merged-header aware locators.

``pdfplumber`` is used only when available.  The adapter publishes one number
per physical cell and builds a header path from all rows above the first data
row, so a merged parent header is not lost.  It does not fabricate a value for
an empty merged cell.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from report_qa.application.numeric_extraction import canonical_decimal


NUMBER_RE = re.compile(r"(?<![\w/])[-+]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?%?")


def _decimal(raw: str) -> str:
    value = raw.removesuffix("%").replace(" ", "")
    if "," in value and "." in value:
        separator = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if separator == "," else ",", "").replace(separator, ".")
    elif "," in value or "." in value:
        separator = "," if "," in value else "."
        parts = value.split(separator)
        value = "".join(parts) if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3) else ".".join(parts)
    # lstrip("0") turned "0.5" into ".5", which the evidence contract rejects
    # and fails the whole document.
    return canonical_decimal(value)


# A box this far outside the page is a clipped background, not a table cell.
OFF_PAGE_TOLERANCE = 0.01


def _page_bbox(box: Any, width: float, height: float) -> list[float] | None:
    """Page-relative box, or None when the box does not lie on the page.

    Border and background paths overshoot the page by a rounding error
    (-2e-16, 1.0000004). The evidence contract rejects those, and one such
    cell failed the whole document.
    """

    x0, top, x1, bottom = box
    values = [x0 / width, top / height, x1 / width, bottom / height]
    if min(values) < -OFF_PAGE_TOLERANCE or max(values) > 1 + OFF_PAGE_TOLERANCE:
        return None
    values = [round(max(0.0, min(1.0, value)), 6) for value in values]
    if values[2] <= values[0] or values[3] <= values[1]:
        return None
    return values


def _header_count(values: list[list[str | None]]) -> int:
    first_data = next(
        (index for index, row in enumerate(values) if any(cell and NUMBER_RE.search(str(cell)) for cell in row)),
        len(values),
    )
    count = max(1, first_data)
    if first_data == 0:
        # "4 Units" or "Q1/2024" in the top row does not make it data. The
        # rows below it that hold only text still belong to the header.
        while (
            count < len(values) - 1
            and sum(1 for cell in values[count] if cell) >= 2
            and not any(cell and NUMBER_RE.search(str(cell)) for cell in values[count])
        ):
            count += 1
    return count


def _row_header(cells: list[str | None]) -> str | None:
    """First label to the left; an index column (STT, shirt number) is not one.

    Only the first column may be a bare number (a year or an index). A number
    from any other column is a value, and using it as a name mislabels the row.
    """

    labels = [" ".join(str(cell).split()) if cell else "" for cell in cells]
    named = next((label for label in labels if any(char.isalpha() for char in label)), None)
    return named or (labels[0] if labels and labels[0] else None)


def _rows_from_words(table: Any, words: list[tuple[Any, ...]]) -> list[list[str | None]]:
    """Cell text from whole words: PyMuPDF's own cell text drops the decimal
    points of Type 3 fonts onto a separate line ("82874\\n.")."""

    rows: list[list[str | None]] = []
    for row in table.rows:
        cells: list[str | None] = []
        for box in row.cells:
            if box is None:
                cells.append(None)
                continue
            inside = [
                word
                for word in words
                if box[0] <= (word[0] + word[2]) / 2 <= box[2] and box[1] <= (word[1] + word[3]) / 2 <= box[3]
            ]
            inside.sort(key=lambda word: (word[5], word[6], word[7]))
            cells.append(" ".join(str(word[4]) for word in inside) or None)
        rows.append(cells)
    return rows


@dataclass(frozen=True, slots=True)
class ComplexTableResult:
    evidences: tuple[dict[str, Any], ...]
    contexts: dict[str, str]
    regions: tuple[tuple[int, list[float]], ...]
    warnings: tuple[dict[str, Any], ...]


class PdfPlumberTableExtractor:
    def available(self) -> bool:
        try:
            import pdfplumber  # noqa: F401
        except ModuleNotFoundError:
            return False
        return True

    def extract(self, path: Path) -> ComplexTableResult:
        if not self.available():
            return ComplexTableResult((), {}, (), ())
        import pdfplumber
        evidences: list[dict[str, Any]] = []
        contexts: dict[str, str] = {}
        regions: list[tuple[int, list[float]]] = []
        warnings: list[dict[str, Any]] = []

        def publish(page_number: int, table_index: int, values: list[list[str | None]], rows: list[Any], width: float, height: float) -> int:
            published = 0
            header_count = _header_count(values)
            for row_index, (row_values, row) in enumerate(zip(values, rows)):
                for column_index, (cell_text, cell_box) in enumerate(zip(row_values, row.cells)):
                    if row_index < header_count or not cell_text or cell_box is None:
                        continue
                    match = NUMBER_RE.search(str(cell_text))
                    if match is None:
                        continue
                    bbox = _page_bbox(cell_box, width, height)
                    if bbox is None:
                        continue
                    header_parts = [str(values[header_row][column_index]).strip() for header_row in range(header_count) if column_index < len(values[header_row]) and values[header_row][column_index]]
                    row_header = _row_header(row_values[:column_index])
                    raw = match.group(0)
                    digest = hashlib.sha256(f"complex:{page_number}:{table_index}:{row_index}:{column_index}:{raw}".encode()).hexdigest()[:16]
                    key = f"ev-{digest}"
                    locator = {"table_region_key": f"page-{page_number}-complex-table-{table_index}", "row_index": row_index, "column_index": column_index, "row_header": row_header, "column_header": " / ".join(header_parts) or None}
                    context = " ".join(item for item in (row_header, locator["column_header"], str(cell_text)) if item)
                    evidences.append({"evidence_key": key, "source_region_key": f"page-{page_number}-complex-table-{table_index}-cell-{row_index}-{column_index}", "source_type": "table", "page_number": page_number, "bbox": bbox, "raw_text": raw, "numeric_value": _decimal(raw), "value_kind": "number", "data_status": "valid", "extraction_method": "table_cell", "method_label": "đọc từ ô bảng", "semantic": {"measure": "unknown", "subject": None, "period": None, "unit": "PERCENT" if raw.endswith("%") else None, "dimensions": {}}, "table_locator": locator, "chart_read": None, "confidence": 0.93})
                    contexts[key] = context
                    published += 1
            return published

        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                header_only: list[tuple[int, list[float], int]] = []
                for table_index, table in enumerate(page.find_tables()):
                    # One column means a frame around text or the page
                    # background. Treating it as a table hid every number
                    # inside it except the first of each box.
                    if max((len(row.cells) for row in table.rows), default=0) < 2:
                        continue
                    region = _page_bbox(table.bbox, page.width, page.height)
                    if region is None:
                        continue
                    values = table.extract() or []
                    rows = list(table.rows)
                    published = publish(page_number, table_index, values, rows, page.width, page.height)
                    if published or len(rows) > 2 or len(rows[0].cells) < 3:
                        regions.append((page_number, region))
                    else:
                        header_only.append((table_index, region, len(rows[0].cells)))
                if header_only:
                    regions.extend(self._borderless_rows(path, page_number, header_only, publish))
        return ComplexTableResult(tuple(evidences), contexts, tuple(regions), tuple(warnings))

    @staticmethod
    def _borderless_rows(path: Path, page_number: int, headers: list[tuple[int, list[float], int]], publish: Any) -> list[tuple[int, list[float]]]:
        """Data rows under a header bar whose body has no vertical borders.

        pdfplumber sees only the header cells there. PyMuPDF follows the
        columns of the header down the page.
        """

        import pymupdf

        found: list[tuple[int, list[float]]] = []
        with pymupdf.open(path) as pdf:
            page = pdf[page_number - 1]
            words = page.get_text("words")
            width, height = page.rect.width, page.rect.height
            tables = list(page.find_tables().tables)
            for table_index, header, column_count in headers:
                for table in tables:
                    region = _page_bbox(table.bbox, width, height)
                    if region is None or table.row_count < 3:
                        continue
                    same_header = (
                        region[0] >= header[0] - 0.02
                        and region[2] <= header[2] + 0.02
                        # A header with grouped titles splits into more columns
                        # below; a wide last column is trimmed to its text.
                        and (table.col_count == column_count or region[2] - region[0] >= 0.8 * (header[2] - header[0]))
                        and abs(region[1] - header[1]) <= 0.02
                    )
                    if same_header and publish(page_number, table_index, _rows_from_words(table, words), list(table.rows), width, height):
                        found.append((page_number, region))
                        break
                else:
                    found.append((page_number, header))
        return found


__all__ = ["ComplexTableResult", "PdfPlumberTableExtractor"]
