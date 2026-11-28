import sys
import types

from report_qa.application.ocr_extraction import TesseractPdfOcr


def _fake_tesseract(monkeypatch, languages):
    module = types.SimpleNamespace(get_languages=lambda config="": list(languages))
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    monkeypatch.setitem(sys.modules, "pymupdf", types.ModuleType("pymupdf"))


def test_ocr_is_unavailable_without_vietnamese(monkeypatch):
    _fake_tesseract(monkeypatch, ["eng", "osd"])
    assert TesseractPdfOcr().available() == (False, "TESSERACT_VIETNAMESE_MISSING")


def test_ocr_is_available_with_vietnamese(monkeypatch):
    _fake_tesseract(monkeypatch, ["eng", "osd", "vie"])
    assert TesseractPdfOcr().available() == (True, None)
