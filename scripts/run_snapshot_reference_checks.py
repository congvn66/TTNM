"""Check the supplied Q1-2026 reference PDF against retrieval-critical facts.

This is intentionally a read-only smoke check. It does not put the user's PDF
in the repository and exits with a clear skip when the local reference is absent.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "tests" / "fixtures" / "snapshot_q1_26_expected.json"
DEFAULT_PDF = Path(r"C:\Users\Admin\Downloads\Snapshot Q1-26 VI.pdf")


def compact(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", "", value)


def main() -> int:
    pdf_path = Path(os.getenv("REPORT_QA_REFERENCE_PDF", str(DEFAULT_PDF)))
    if not pdf_path.is_file():
        print(f"Snapshot reference check: skipped (missing {pdf_path})")
        return 0
    try:
        from pypdf import PdfReader
    except ImportError:
        print("Snapshot reference check: skipped (pypdf is unavailable; use the project .venv)")
        return 0

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) != expected["expected_page_count"]:
        raise AssertionError(f"expected {expected['expected_page_count']} pages, got {len(reader.pages)}")
    for page_number, needles in expected["pages"].items():
        text = compact(reader.pages[int(page_number) - 1].extract_text() or "")
        for needle in needles:
            if compact(needle) not in text:
                raise AssertionError(f"page {page_number} is missing reference marker {needle!r}")
    print(f"Snapshot reference check: pass ({pdf_path.name}, {len(reader.pages)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
