"""Convert a Docling table CSV (the current output of the PDF step) into evidence records.

Docling CSV has no unit and no position per number. The caller supplies them, and each
number keeps the table-level position until the PDF step can give a position per cell.
"""

import csv
import io
import re

from ..numbers import AmbiguousNumber, parse_number
from ..text import deaccent

MISSING_MARKS = {"", "-", "—", "–", "n/a", "na", "null", "none"}


def _code(*parts) -> str:
    text = deaccent("_".join(str(p) for p in parts)).upper()
    return "EVD_" + re.sub(r"[^A-Z0-9]+", "_", text).strip("_")


def table_to_evidences(csv_text: str, *, page: int, bbox: list[float] | None = None, units: dict[str, str] | None = None, locale: str = "en",
                       period_column: bool = True, table_id: str = "T1", entity: str | None = None) -> list[dict]:
    """period_column=True means the first column holds periods and other columns hold metrics.

    locale must be stated because the same text means different numbers: 1,250 is 1250 in en and 1.25 in vi.
    """
    units = units or {}
    rows = list(csv.reader(io.StringIO(csv_text.strip())))
    if len(rows) < 2:
        return []
    header, records = rows[0], []
    for row_index, row in enumerate(rows[1:]):
        for col_index, cell in enumerate(row[1:], 1):
            if col_index >= len(header):
                continue
            metric = header[col_index].strip()
            series, period = (metric, row[0].strip()) if period_column else (row[0].strip(), metric)
            if entity:
                series = f"{series} - {entity}"
            text = cell.strip()
            unit = units.get(metric if period_column else row[0].strip())
            if text.endswith("%") and not unit:
                unit = "%"
            value, status, method = None, "valid", "direct_label"
            if text.lower() in MISSING_MARKS:
                status, method = "missing", "none"
            else:
                try:
                    value = float(parse_number(text, locale=locale))
                except (ValueError, AmbiguousNumber):
                    status, method = "error", "none"
            records.append({"evidence_code": _code(table_id, series, period), "source_type": "table_cell", "extraction_method": method,
                            "location": {"page": page, "bbox": bbox or [], "meta": {"table_id": table_id, "row_index": row_index, "col_index": col_index, "raw_text": text}},
                            "series_name": series, "time_period": period, "unit": unit, "raw_value": value, "current_value": value, "text_content": None,
                            "data_status": status, "verification_status": "unverified"})
    return records
