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
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
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


__all__ = ["OcrEngine", "OcrPage", "TesseractPdfOcr"]
