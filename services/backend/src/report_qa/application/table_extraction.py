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
    return value.lstrip("0") or "0"


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
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for table_index, table in enumerate(page.find_tables()):
                    x0, top, x1, bottom = table.bbox
                    region = [x0 / page.width, top / page.height, x1 / page.width, bottom / page.height]
                    regions.append((page_number, region))
                    values = table.extract() or []
                    rows = list(table.rows)
                    first_data = next((index for index, row in enumerate(values) if any(cell and NUMBER_RE.search(str(cell)) for cell in row)), len(values))
                    header_count = max(1, first_data)
                    for row_index, (row_values, row) in enumerate(zip(values, rows)):
                        for column_index, (cell_text, cell_box) in enumerate(zip(row_values, row.cells)):
                            if row_index < header_count or not cell_text or cell_box is None:
                                continue
                            match = NUMBER_RE.search(str(cell_text))
                            if match is None:
                                continue
                            left, cell_top, right, cell_bottom = cell_box
                            bbox = [left / page.width, cell_top / page.height, right / page.width, cell_bottom / page.height]
                            header_parts = [str(values[header_row][column_index]).strip() for header_row in range(header_count) if column_index < len(values[header_row]) and values[header_row][column_index]]
                            row_header = next((str(value).strip() for value in row_values[:column_index] if value), None)
                            raw = match.group(0)
                            digest = hashlib.sha256(f"complex:{page_number}:{table_index}:{row_index}:{column_index}:{raw}".encode()).hexdigest()[:16]
                            key = f"ev-{digest}"
                            locator = {"table_region_key": f"page-{page_number}-complex-table-{table_index}", "row_index": row_index, "column_index": column_index, "row_header": row_header, "column_header": " / ".join(header_parts) or None}
                            context = " ".join(item for item in (row_header, locator["column_header"], str(cell_text)) if item)
                            evidences.append({"evidence_key": key, "source_region_key": f"page-{page_number}-complex-table-{table_index}-cell-{row_index}-{column_index}", "source_type": "table", "page_number": page_number, "bbox": bbox, "raw_text": raw, "numeric_value": _decimal(raw), "data_status": "valid", "extraction_method": "table_cell", "method_label": "đọc từ ô bảng", "semantic": {"measure": "unknown", "subject": None, "period": None, "unit": "PERCENT" if raw.endswith("%") else None, "dimensions": {}}, "table_locator": locator, "chart_read": None, "confidence": 0.93})
                            contexts[key] = context
        return ComplexTableResult(tuple(evidences), contexts, tuple(regions), tuple(warnings))


__all__ = ["ComplexTableResult", "PdfPlumberTableExtractor"]
