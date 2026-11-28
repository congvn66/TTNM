"""Optional OCR boundary for scanned PDF pages.

OCR is not a silent fallback.  A page without a text layer is either processed
through this adapter (with per-token normalized bounding boxes and confidence)
or recorded as unreadable with an actionable capability warning.  That keeps
an empty OCR installation from masquerading as missing data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class OcrPage:
    page_number: int
    width: int
    height: int
    tokens: tuple[dict[str, Any], ...]


class OcrEngine(Protocol):
    def available(self) -> tuple[bool, str | None]: ...
    def read_page(self, path: Path, page_number: int) -> OcrPage: ...


class TesseractPdfOcr:
    """Tesseract + PyMuPDF implementation, loaded only when OCR is needed."""

    # Reports are Vietnamese: read without "vie", "220 tỷ đồng" comes out as
    # "220 ty dong", so numbers lose their unit and quotes never match the page.
    LANGUAGES = ("vie", "eng")

    def available(self) -> tuple[bool, str | None]:
        try:
            import pymupdf  # noqa: F401
            import pytesseract
            installed = set(pytesseract.get_languages(config=""))
        except ModuleNotFoundError:
            return False, "OCR_PYTHON_DEPENDENCY_MISSING"
        except Exception:
            return False, "TESSERACT_ENGINE_UNAVAILABLE"
        if not set(self.LANGUAGES) <= installed:
            return False, "TESSERACT_VIETNAMESE_MISSING"
        return True, None

    def read_page(self, path: Path, page_number: int) -> OcrPage:
        available, code = self.available()
        if not available:
            raise RuntimeError(code or "OCR_UNAVAILABLE")
        import pymupdf
        import pytesseract
        from PIL import Image

        document = pymupdf.open(path)
        page = document.load_page(page_number - 1)
        pixmap, gray = _clean_page(page)
        image = Image.fromarray(gray)
        data = pytesseract.image_to_data(image, lang="+".join(self.LANGUAGES), output_type=pytesseract.Output.DICT, config="--oem 1 --psm 6")
        tokens: list[dict[str, Any]] = []
        for index, raw in enumerate(data["text"]):
            text = str(raw).strip()
            confidence = float(data["conf"][index]) if str(data["conf"][index]) not in {"", "-1"} else -1
            if not text or confidence < 0:
                continue
            x, y, width, height = (int(data[key][index]) for key in ("left", "top", "width", "height"))
            if width <= 0 or height <= 0:
                continue
            tokens.append({"text": text, "bbox": [x / pixmap.width, y / pixmap.height, (x + width) / pixmap.width, (y + height) / pixmap.height], "confidence": round(confidence / 100, 4)})
        return OcrPage(page_number, pixmap.width, pixmap.height, tuple(tokens))


# Scans are read at 4x: at 2x a ~290 dpi page loses detail; 4x keeps the source's own resolution.
SCAN_SCALE = 4


def remove_ruling_lines(gray):
    """The page with table and box lines painted white.

    Tesseract cannot read digits that sit between grid lines: on a scanned
    table it returns tokens like "2248|" for "273.458". A line is a run of
    dark pixels at least 1/30 of the page wide (or tall); text strokes are
    much shorter, so they stay.
    """
    import cv2
    import numpy as np

    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    length = max(10, gray.shape[1] // 30)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)))
    lines = cv2.dilate(horizontal | vertical, np.ones((3, 3), np.uint8))
    cleaned = gray.copy()
    cleaned[lines > 0] = 255
    return cleaned


def _clean_page(page):
    """(pixmap, grayscale image without ruling lines) of one page at SCAN_SCALE."""
    import cv2
    import numpy as np
    import pymupdf

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(SCAN_SCALE, SCAN_SCALE), alpha=False)
    rgb = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return pixmap, remove_ruling_lines(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))


def clean_scan(path: Path, target: Path, pages: list[int] | None = None) -> Path:
    """A copy of a scanned PDF (or of its pages `pages`, numbered from 1) with ruling lines removed.

    Pages keep their sizes, so boxes stay in page coordinates.
    """
    import cv2
    import pymupdf

    with pymupdf.open(path) as source, pymupdf.open() as copy:
        for number in pages or range(1, source.page_count + 1):
            page = source[number - 1]
            _, gray = _clean_page(page)
            ok, png = cv2.imencode(".png", gray)
            if not ok:
                raise RuntimeError("Could not encode a cleaned scan page")
            new_page = copy.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=png.tobytes())
        copy.save(target)
    return target


__all__ = ["OcrEngine", "OcrPage", "SCAN_SCALE", "TesseractPdfOcr", "clean_scan", "remove_ruling_lines"]
