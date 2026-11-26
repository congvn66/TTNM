from report_qa.infrastructure.integrations import readiness, runtime_capabilities


def test_extraction_selector_uses_docling_when_configured(monkeypatch, tmp_path):
    from report_qa.application import docling_extraction
    from report_qa.application.evidence_extraction import extract_pdf_artifact

    expected = {"extraction_provider": "docling", "pages": [], "evidence_batch": {"evidences": []}}
    called = {}

    def fake(path, document_version_id, *, locale=None):
        called.update(path=path, document_version_id=document_version_id, locale=locale)
        return expected

    monkeypatch.setenv("PDF_EXTRACTION_BACKEND", "docling")
    monkeypatch.setenv("PDF_NUMBER_LOCALE", "vi")
    monkeypatch.setattr(docling_extraction, "extract_docling_artifact", fake, raising=False)
    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF-test")

    assert extract_pdf_artifact(path, "version-1") is expected
    assert called["document_version_id"] == "version-1"
    assert called["locale"] == "vi"


def test_runtime_capabilities_reports_optional_backend_without_loading_models(monkeypatch):
    monkeypatch.setenv("PDF_EXTRACTION_BACKEND", "docling")
    monkeypatch.setenv("CHART_READER_BACKEND", "deplot")
    monkeypatch.setenv("REPORT_QA_AI_MODE", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")

    result = runtime_capabilities(
        database={"backend": "postgres", "status": "ok"},
        storage={"backend": "r2", "status": "ok"},
    )

    assert result["ai"] == {
        "selected": "openrouter",
        "model": "openai/gpt-6-luna",
        "status": "configured",
        "network_probe": "not_run",
    }
    assert result["pdf_extraction"]["selected"] == "docling"
    assert result["chart_reader"]["selected"] == "deplot"
    assert result["chart_reader"]["weights"].startswith("lazy")


def test_readiness_keeps_text_ready_when_on_demand_chart_dependency_is_missing():
    capabilities = {
        "ai": {"status": "available"},
        "pdf_extraction": {"status": "available"},
        "chart_reader": {"status": "missing_dependency"},
        "database": {"status": "disabled"},
        "storage": {"backend": "local", "status": "ok"},
    }

    assert readiness(capabilities) == ("ready", [])


def test_readiness_exposes_selected_external_adapter_blockers():
    capabilities = {
        "ai": {"status": "configured"},
        "pdf_extraction": {"status": "missing_dependency"},
        "chart_reader": {"status": "available"},
        "database": {"status": "unavailable"},
        "storage": {"status": "unavailable"},
    }

    state, blockers = readiness(capabilities)
    assert state == "degraded"
    assert blockers == ["pdf_extraction:missing_dependency", "database:unavailable", "storage:unavailable"]


def test_health_capabilities_say_whether_reextraction_is_available(monkeypatch):
    from dataclasses import replace

    from report_qa.infrastructure import integrations

    assert runtime_capabilities()["reextraction"] == {"status": "available"}
    monkeypatch.setattr(integrations, "settings", replace(integrations.settings, persistence_backend="postgres"))
    assert runtime_capabilities()["reextraction"] == {"status": "unsupported", "error_code": "REEXTRACTION_NOT_SUPPORTED"}
