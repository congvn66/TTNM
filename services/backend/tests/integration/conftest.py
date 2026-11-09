"""Legacy API regression tests stay offline; real adapters have injected tests."""

import pytest


@pytest.fixture(autouse=True)
def offline_extraction(monkeypatch):
    from report_qa.api import main
    from report_qa.application.evidence_extraction import extract_legacy_pdf_artifact

    monkeypatch.setattr(main, "extract_pdf_artifact", extract_legacy_pdf_artifact)
